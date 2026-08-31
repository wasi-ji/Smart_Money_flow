"""
dominance_engine.py — Market Dominance Engine
Estimates BTC, ETH, USDT, and Altcoin dominance from live volume/price data.
Tracks dominance shifts to detect capital rotation signals.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Optional

import aiohttp

from market_scanner import MarketScanner
from config import Settings

logger = logging.getLogger("smft.dominance")

# Approximate stablecoin symbols to detect USDT dominance shift
STABLECOINS = {"USDCUSDT", "BUSDUSDT", "DAIUSDT", "TUSDUSDT", "FRAXUSDT"}

# Approximate total market cap weights used for dominance estimation
# (Updated periodically; these are fallback weights)
APPROX_WEIGHTS = {
    "BTCUSDT":  0.52,
    "ETHUSDT":  0.17,
    "STABLECOINS": 0.07,
    "ALTS":     0.24,
}


class DominanceEngine:
    """
    Estimates market dominance distribution.
    Uses CoinGecko global API as primary source, falls back to volume estimation.
    """

    def __init__(self, market_scanner: MarketScanner, settings: Settings):
        self.scanner = market_scanner
        self.settings = settings
        self.session: Optional[aiohttp.ClientSession] = None

        # History deques for change detection
        self._btc_history  = deque(maxlen=10)
        self._eth_history  = deque(maxlen=10)
        self._usdt_history = deque(maxlen=10)

        self._latest: dict = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self.session

    async def run(self):
        """Periodically fetch dominance data."""
        logger.info("DominanceEngine starting…")
        while True:
            try:
                await self._fetch_dominance()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Dominance fetch error: {e}")
            await asyncio.sleep(self.settings.DOMINANCE_INTERVAL)

    async def _fetch_dominance(self):
        """
        Fetch global market dominance from CoinGecko.
        Falls back to volume-weighted estimation if API unavailable.
        """
        session = await self._get_session()
        try:
            url = "https://api.coingecko.com/api/v3/global"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    market_cap_pct = data["data"]["market_cap_percentage"]
                    btc  = market_cap_pct.get("btc", 0)
                    eth  = market_cap_pct.get("eth", 0)
                    usdt = market_cap_pct.get("usdt", 0)
                    alts = max(0, 100 - btc - eth - usdt)
                    self._update(btc, eth, usdt, alts)
                    return
        except Exception:
            pass

        # Fallback: estimate from tracked volumes
        self._estimate_from_volumes()

    def _estimate_from_volumes(self):
        """Estimate dominance from tracked asset volumes as a fallback."""
        prices = self.scanner.get_latest_prices()
        btc_vol  = prices.get("BTCUSDT", {}).get("volume", 0)
        eth_vol  = prices.get("ETHUSDT", {}).get("volume", 0)
        other    = sum(v.get("volume", 0) for k, v in prices.items()
                       if k not in ("BTCUSDT", "ETHUSDT"))
        total = max(btc_vol + eth_vol + other, 1)

        btc  = (btc_vol / total) * 100
        eth  = (eth_vol / total) * 100
        usdt = 6.5   # approximate stablecoin dominance
        alts = max(0, 100 - btc - eth - usdt)

        self._update(btc, eth, usdt, alts)

    def _update(self, btc: float, eth: float, usdt: float, alts: float):
        """Store latest dominance values and detect changes."""
        self._btc_history.append(btc)
        self._eth_history.append(eth)
        self._usdt_history.append(usdt)

        # Compute recent changes
        btc_chg  = self._calc_change(self._btc_history)
        eth_chg  = self._calc_change(self._eth_history)
        usdt_chg = self._calc_change(self._usdt_history)
        alts_chg = -(btc_chg + eth_chg + usdt_chg)

        # Determine rotation signal
        signal = self._detect_signal(btc, btc_chg, usdt, usdt_chg, alts, alts_chg)

        self._latest = {
            "btc":      round(btc, 2),
            "eth":      round(eth, 2),
            "usdt":     round(usdt, 2),
            "alts":     round(alts, 2),
            "btcChg":   round(btc_chg, 3),
            "ethChg":   round(eth_chg, 3),
            "usdtChg":  round(usdt_chg, 3),
            "altsChg":  round(alts_chg, 3),
            "signal":   signal,
            "timestamp": int(time.time() * 1000),
        }

    def _calc_change(self, history: deque) -> float:
        """Calculate change from oldest to newest value in deque."""
        if len(history) < 2:
            return 0.0
        return history[-1] - history[0]

    def _detect_signal(
        self, btc: float, btc_chg: float,
        usdt: float, usdt_chg: float,
        alts: float, alts_chg: float
    ) -> str:
        """Generate a human-readable rotation signal."""
        if usdt_chg > 0.3:
            return "🔴 Capital fleeing to Stablecoins — Risk-Off signal"
        elif btc_chg > 0.5 and alts_chg < -0.3:
            return "🔵 Capital rotating into BTC — Altcoins under pressure"
        elif alts_chg > 0.5 and btc_chg < -0.2:
            return "🟢 Capital dispersing into Altcoins — Risk-On rotation"
        elif btc > 55:
            return "⚪ BTC dominance elevated — defensive positioning"
        elif alts > 30:
            return "🟡 Altcoin season conditions present"
        else:
            return "⚫ Capital flow balanced — monitoring for breakout"

    def get_latest(self) -> dict:
        """Return latest dominance snapshot."""
        if not self._latest:
            # Return approximate defaults before first fetch
            return {
                "btc": 52.0, "eth": 17.0, "usdt": 6.5, "alts": 24.5,
                "btcChg": 0.0, "ethChg": 0.0, "usdtChg": 0.0, "altsChg": 0.0,
                "signal": "Awaiting dominance data…",
            }
        return self._latest
