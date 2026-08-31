"""
whale_detector.py — Whale Activity Detector
Monitors for abnormal market behavior indicating large institutional activity:
- Volume spikes (>3x average)
- Abnormal OI changes (>5% in short period)
- Extreme funding rates
- Large liquidations
"""

import asyncio
import logging
import time
from collections import deque
from typing import List, Optional

import aiohttp

from market_scanner import MarketScanner
from websocket_manager import WebSocketManager
from config import Settings

logger = logging.getLogger("smft.whale_detector")


class WhaleDetector:
    """
    Detects unusual market activity that may indicate whale/institutional moves.
    Generates structured alerts and broadcasts them via WebSocketManager.
    """

    def __init__(
        self,
        market_scanner: MarketScanner,
        ws_manager: WebSocketManager,
        settings: Settings,
    ):
        self.scanner = market_scanner
        self.ws_manager = ws_manager
        self.settings = settings
        self.session: Optional[aiohttp.ClientSession] = None

        # Per-symbol baselines
        self._vol_baselines: dict = {}   # symbol -> avg hourly volume
        self._oi_snapshots:  dict = {}   # symbol -> last oi value
        self._fund_snapshots:dict = {}   # symbol -> last funding rate

        # Alert history (deque capped at settings.ALERT_HISTORY_LENGTH)
        self._alerts: deque = deque(maxlen=settings.ALERT_HISTORY_LENGTH)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self.session

    async def run(self):
        """Periodically check for whale activity."""
        logger.info("WhaleDetector starting…")
        while True:
            try:
                await self._check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"WhaleDetector error: {e}")
            await asyncio.sleep(self.settings.WHALE_CHECK_INTERVAL)

    async def _check_all(self):
        """Run all whale detection checks."""
        tasks = [
            self._check_volume_spikes(),
            self._check_oi_changes(),
            self._check_funding_extremes(),
            self._check_liquidations(),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    # ── Volume Spike Detection ──

    async def _check_volume_spikes(self):
        """Detect symbols with volume significantly above their baseline."""
        prices = self.scanner.get_latest_prices()

        for sym, data in prices.items():
            current_vol = data.get("volume", 0)
            baseline = self._vol_baselines.get(sym, 0)

            if baseline == 0:
                # Establish baseline on first observation
                self._vol_baselines[sym] = current_vol
                continue

            ratio = current_vol / max(baseline, 1)

            if ratio >= self.settings.WHALE_VOLUME_MULTIPLIER:
                severity = "critical" if ratio >= 5.0 else "high" if ratio >= 4.0 else "medium"
                await self._emit_alert({
                    "symbol":   sym.replace("USDT", ""),
                    "type":     "volume_spike",
                    "severity": severity,
                    "title":    f"Volume Spike {ratio:.1f}x",
                    "message":  (
                        f"24h volume {ratio:.1f}x above baseline. "
                        f"Current: ${current_vol/1e9:.2f}B. "
                        "Possible institutional accumulation or distribution."
                    ),
                    "timestamp": int(time.time() * 1000),
                    "data": {"ratio": ratio, "volume": current_vol},
                })

            # Update baseline with exponential moving average
            alpha = 0.05
            self._vol_baselines[sym] = (1 - alpha) * baseline + alpha * current_vol

    # ── OI Change Detection ──

    async def _check_oi_changes(self):
        """Detect sudden large changes in open interest."""
        oi_data = self.scanner.get_oi_data()

        for item in oi_data:
            sym    = item["symbol"]
            oi     = item.get("oi", 0)
            change = abs(item.get("change", 0))

            if change >= self.settings.WHALE_OI_CHANGE_PCT:
                direction = "increased" if item.get("change", 0) > 0 else "decreased"
                severity  = "critical" if change >= 15 else "high" if change >= 10 else "medium"
                await self._emit_alert({
                    "symbol":   sym.replace("USDT", ""),
                    "type":     "oi_change",
                    "severity": severity,
                    "title":    f"OI {direction.title()} {change:.1f}%",
                    "message":  (
                        f"Open Interest {direction} by {change:.1f}% "
                        f"(${oi/1e9:.2f}B). "
                        "Large leveraged position building detected."
                    ),
                    "timestamp": int(time.time() * 1000),
                    "data": {"change_pct": change, "oi_usd": oi},
                })

    # ── Funding Rate Extremes ──

    async def _check_funding_extremes(self):
        """Detect extreme funding rates indicating over-leveraged positions."""
        session = await self._get_session()

        for sym in self.settings.FUTURES_SYMBOLS:
            try:
                url = f"{self.settings.BINANCE_FUTURES_URL}/fapi/v1/fundingRate"
                params = {"symbol": sym, "limit": 1}
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    if not data:
                        continue
                    rate = float(data[0].get("fundingRate", 0))
                    abs_rate = abs(rate)

                    if abs_rate >= self.settings.WHALE_FUNDING_THRESHOLD:
                        direction = "LONG" if rate > 0 else "SHORT"
                        severity  = "critical" if abs_rate >= 0.001 else "high" if abs_rate >= 0.0007 else "medium"
                        await self._emit_alert({
                            "symbol":   sym.replace("USDT", ""),
                            "type":     "funding_extreme",
                            "severity": severity,
                            "title":    f"Extreme {direction}s ({rate*100:+.4f}%)",
                            "message":  (
                                f"Funding rate {rate*100:+.4f}% — {direction}s dominating. "
                                "High risk of {'short squeeze' if rate < 0 else 'long liquidation cascade'}."
                            ),
                            "timestamp": int(time.time() * 1000),
                            "data": {"rate": rate, "direction": direction},
                        })
            except Exception as e:
                logger.debug(f"Funding extreme check failed for {sym}: {e}")

    # ── Liquidation Detection ──

    async def _check_liquidations(self):
        """Check recent liquidation data from Binance Futures."""
        session = await self._get_session()

        for sym in self.settings.FUTURES_SYMBOLS[:5]:  # Check top 5 to avoid rate limits
            try:
                url = f"{self.settings.BINANCE_FUTURES_URL}/fapi/v1/allForceOrders"
                params = {"symbol": sym, "limit": 5}
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    if not data:
                        continue

                    # Sum recent liquidations
                    total_usd = sum(
                        float(liq.get("origQty", 0)) * float(liq.get("price", 0))
                        for liq in data
                    )

                    if total_usd >= 1_000_000:  # > $1M liquidations
                        severity = "critical" if total_usd >= 10e6 else "high" if total_usd >= 5e6 else "medium"
                        side     = data[0].get("side", "UNKNOWN")
                        await self._emit_alert({
                            "symbol":   sym.replace("USDT", ""),
                            "type":     "liquidation",
                            "severity": severity,
                            "title":    f"${total_usd/1e6:.1f}M Liquidated",
                            "message":  (
                                f"${total_usd/1e6:.1f}M in {side} positions liquidated recently. "
                                "Forced selling pressure detected."
                            ),
                            "timestamp": int(time.time() * 1000),
                            "data": {"total_usd": total_usd, "side": side},
                        })
            except Exception as e:
                logger.debug(f"Liquidation check failed for {sym}: {e}")

    # ── Alert Emission ──

    async def _emit_alert(self, alert: dict):
        """Broadcast alert and store in history."""
        # Deduplicate: don't emit same symbol+type combo within 60s
        key = f"{alert['symbol']}_{alert['type']}"
        now = int(time.time() * 1000)

        for existing in list(self._alerts):
            if (
                existing.get("symbol") == alert["symbol"]
                and existing.get("type") == alert["type"]
                and (now - existing.get("timestamp", 0)) < 60_000
            ):
                return  # Duplicate, skip

        self._alerts.appendleft(alert)
        await self.ws_manager.broadcast_alert(alert)
        logger.info(f"Whale alert: {alert['symbol']} — {alert['title']}")

    def get_recent_alerts(self, limit: int = 20) -> List[dict]:
        """Return recent whale alerts."""
        return list(self._alerts)[:limit]
