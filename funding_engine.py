"""
funding_engine.py — Funding Rate Engine
Fetches perpetual futures funding rates from Binance Futures API.
Funding rates indicate market sentiment extremes and leverage buildup.

Positive funding = longs paying shorts = overbought / bearish signal
Negative funding = shorts paying longs = oversold / bullish signal
"""

import asyncio
import logging
import time
from collections import deque
from typing import Dict, List, Optional

import aiohttp

from config import Settings

logger = logging.getLogger("smft.funding")


class FundingEngine:
    """
    Periodically fetches perpetual futures funding rates for all tracked symbols.
    Stores history to detect trend changes and extremes.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session: Optional[aiohttp.ClientSession] = None

        # Latest funding rates: symbol -> rate (float, e.g. 0.0001 = 0.01%)
        self._rates: Dict[str, dict] = {}

        # History for trend analysis
        self._rate_history: Dict[str, deque] = {
            sym: deque(maxlen=24) for sym in settings.FUTURES_SYMBOLS
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.settings.REQUEST_TIMEOUT)
            )
        return self.session

    async def run(self):
        """Main funding rate fetch loop."""
        logger.info("FundingEngine starting…")
        await self._fetch_all_rates()  # immediate first fetch

        while True:
            try:
                await asyncio.sleep(self.settings.FUNDING_INTERVAL)
                await self._fetch_all_rates()
            except asyncio.CancelledError:
                logger.info("FundingEngine cancelled")
                break
            except Exception as e:
                logger.warning(f"FundingEngine error: {e}")
                await asyncio.sleep(10)

    async def _fetch_all_rates(self):
        """Fetch funding rates for all futures symbols in one batch request."""
        session = await self._get_session()
        try:
            # Binance provides all funding rates in one call
            url = f"{self.settings.BINANCE_FUTURES_URL}/fapi/v1/premiumIndex"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data:
                        sym = item.get("symbol", "")
                        if sym not in self.settings.FUTURES_SYMBOLS:
                            continue

                        rate     = float(item.get("lastFundingRate", 0))
                        mark_px  = float(item.get("markPrice", 0))
                        index_px = float(item.get("indexPrice", 0))

                        # Annualized rate (3 funding periods per day, 365 days)
                        annualized = rate * 3 * 365 * 100

                        # Track history
                        self._rate_history[sym].append(rate)

                        # Compute 24h average from history
                        hist = list(self._rate_history[sym])
                        avg_rate = sum(hist) / len(hist) if hist else rate

                        self._rates[sym] = {
                            "symbol":     sym,
                            "rate":       rate,
                            "annualized": round(annualized, 2),
                            "avg24h":     round(avg_rate, 6),
                            "markPrice":  mark_px,
                            "indexPrice": index_px,
                            "bias":       self._rate_bias(rate),
                            "timestamp":  int(time.time() * 1000),
                        }
                else:
                    logger.warning(f"Funding rate fetch returned status {resp.status}")
        except Exception as e:
            logger.warning(f"Failed to fetch funding rates: {e}")
            # Fall back to per-symbol fetch
            await self._fetch_rates_individually()

    async def _fetch_rates_individually(self):
        """Fallback: fetch each symbol's funding rate individually."""
        session = await self._get_session()
        tasks = [self._fetch_single_rate(session, sym) for sym in self.settings.FUTURES_SYMBOLS]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_single_rate(self, session: aiohttp.ClientSession, symbol: str):
        """Fetch funding rate for a single symbol."""
        try:
            url = f"{self.settings.BINANCE_FUTURES_URL}/fapi/v1/fundingRate"
            params = {"symbol": symbol, "limit": 1}
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        rate = float(data[0].get("fundingRate", 0))
                        annualized = rate * 3 * 365 * 100
                        self._rate_history[symbol].append(rate)
                        hist = list(self._rate_history[symbol])
                        avg_rate = sum(hist) / len(hist) if hist else rate

                        self._rates[symbol] = {
                            "symbol":     symbol,
                            "rate":       rate,
                            "annualized": round(annualized, 2),
                            "avg24h":     round(avg_rate, 6),
                            "bias":       self._rate_bias(rate),
                            "timestamp":  int(time.time() * 1000),
                        }
        except Exception as e:
            logger.debug(f"Single funding fetch failed for {symbol}: {e}")

    def _rate_bias(self, rate: float) -> str:
        """Classify funding rate as sentiment signal."""
        if rate >= 0.001:
            return "EXTREME_LONG"
        elif rate >= 0.0003:
            return "LONG_HEAVY"
        elif rate > 0.00005:
            return "SLIGHT_LONG"
        elif rate >= -0.00005:
            return "NEUTRAL"
        elif rate >= -0.0003:
            return "SLIGHT_SHORT"
        elif rate >= -0.001:
            return "SHORT_HEAVY"
        else:
            return "EXTREME_SHORT"

    def get_latest(self) -> List[dict]:
        """Return sorted list of funding rates (most extreme first)."""
        rates = list(self._rates.values())
        if not rates:
            # Return zero-filled placeholders until data arrives
            return [
                {
                    "symbol": sym,
                    "rate": 0.0,
                    "annualized": 0.0,
                    "avg24h": 0.0,
                    "bias": "NEUTRAL",
                    "timestamp": int(time.time() * 1000),
                }
                for sym in self.settings.FUTURES_SYMBOLS
            ]
        return sorted(rates, key=lambda x: abs(x.get("rate", 0)), reverse=True)

    def get_rate(self, symbol: str) -> float:
        """Return the current funding rate for a specific symbol."""
        return self._rates.get(symbol, {}).get("rate", 0.0)

    def get_average_rate(self) -> float:
        """Return the market-wide average funding rate."""
        rates = [v.get("rate", 0) for v in self._rates.values()]
        return sum(rates) / max(len(rates), 1)

    def get_sentiment_summary(self) -> dict:
        """
        Summarise overall market sentiment from funding rates.
        Returns dict with avg, max, min, bias counts.
        """
        rates = [v.get("rate", 0) for v in self._rates.values()]
        if not rates:
            return {"avg": 0.0, "max": 0.0, "min": 0.0, "long_count": 0, "short_count": 0}

        return {
            "avg":         round(sum(rates) / len(rates), 6),
            "max":         round(max(rates), 6),
            "min":         round(min(rates), 6),
            "long_count":  sum(1 for r in rates if r > 0.0001),
            "short_count": sum(1 for r in rates if r < -0.0001),
        }
