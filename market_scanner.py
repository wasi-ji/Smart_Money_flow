"""
market_scanner.py — Live Market Data Scanner
Connects to Binance REST & WebSocket APIs to fetch:
- Real-time prices and 24h stats
- Order book snapshots
- Kline (candlestick) data for momentum calculations
- Open Interest from Binance Futures
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional

import aiohttp

from config import Settings

logger = logging.getLogger("smft.market_scanner")


class MarketScanner:
    """
    Fetches and caches live market data from Binance.
    Provides price, volume, OI, and historical data to other engines.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session: Optional[aiohttp.ClientSession] = None

        # Latest market data cache: symbol -> MarketData dict
        self._prices: Dict[str, dict] = {}
        self._oi_data: Dict[str, dict] = {}
        self._klines: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        self._volume_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=30))

        # Running flag
        self._running = False

    # ── Lifecycle ──

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.REQUEST_TIMEOUT)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ── Main Run Loop ──

    async def run(self):
        """Main scanning loop — fetches all data on each tick."""
        self._running = True
        logger.info("MarketScanner starting…")

        # Initial full fetch
        await self._fetch_all()

        while self._running:
            try:
                await asyncio.sleep(self.settings.MARKET_SCAN_INTERVAL)
                await self._fetch_ticker_prices()
                await self._fetch_oi_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MarketScanner loop error: {e}", exc_info=True)
                await asyncio.sleep(2)

        logger.info("MarketScanner stopped")

    async def _fetch_all(self):
        """Fetch all data sources simultaneously."""
        await asyncio.gather(
            self._fetch_ticker_prices(),
            self._fetch_klines(),
            self._fetch_oi_data(),
            return_exceptions=True,
        )

    # ── Ticker / 24h Stats ──

    async def _fetch_ticker_prices(self):
        """Fetch 24h ticker stats for all tracked symbols."""
        session = await self._get_session()
        try:
            url = f"{self.settings.BINANCE_BASE_URL}/api/v3/ticker/24hr"
            params = {"symbols": str([s for s in self.settings.SYMBOLS]).replace("'", '"')}
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for ticker in data:
                        sym = ticker["symbol"]
                        if sym in self.settings.SYMBOLS:
                            price = float(ticker["lastPrice"])
                            vol   = float(ticker["quoteVolume"])  # in USDT
                            chg   = float(ticker["priceChangePercent"])

                            # Track volume history for relative volume
                            self._volume_history[sym].append(vol / 24)  # hourly approx

                            self._prices[sym] = {
                                "symbol":    sym,
                                "price":     price,
                                "change24h": chg,
                                "volume":    vol,
                                "high24h":   float(ticker["highPrice"]),
                                "low24h":    float(ticker["lowPrice"]),
                                "open24h":   float(ticker["openPrice"]),
                                "count":     int(ticker.get("count", 0)),
                                "timestamp": int(time.time() * 1000),
                            }
        except Exception as e:
            logger.warning(f"Ticker fetch failed: {e}")

    # ── Klines for Momentum ──

    async def _fetch_klines(self):
        """Fetch 1h kline data for all symbols to compute momentum/trend."""
        session = await self._get_session()
        tasks = [self._fetch_symbol_klines(session, sym) for sym in self.settings.SYMBOLS]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_symbol_klines(self, session: aiohttp.ClientSession, symbol: str):
        """Fetch klines for a single symbol."""
        try:
            url = f"{self.settings.BINANCE_BASE_URL}/api/v3/klines"
            params = {"symbol": symbol, "interval": "1h", "limit": 24}
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    closes = [float(k[4]) for k in data]
                    self._klines[symbol] = deque(closes, maxlen=50)
        except Exception as e:
            logger.debug(f"Kline fetch failed for {symbol}: {e}")

    # ── Open Interest ──

    async def _fetch_oi_data(self):
        """Fetch open interest data from Binance Futures."""
        session = await self._get_session()
        tasks = [self._fetch_symbol_oi(session, sym) for sym in self.settings.FUTURES_SYMBOLS]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_symbol_oi(self, session: aiohttp.ClientSession, symbol: str):
        """Fetch OI for a single futures symbol."""
        try:
            url = f"{self.settings.BINANCE_FUTURES_URL}/fapi/v1/openInterest"
            params = {"symbol": symbol}
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    oi_qty = float(data["openInterest"])
                    price = self._prices.get(symbol, {}).get("price", 1)
                    oi_usd = oi_qty * price

                    # Compute change from previous snapshot
                    prev_oi = self._oi_data.get(symbol, {}).get("oi", oi_usd)
                    change_pct = ((oi_usd - prev_oi) / max(prev_oi, 1)) * 100

                    self._oi_data[symbol] = {
                        "symbol":  symbol,
                        "oi":      oi_usd,
                        "oi_qty":  oi_qty,
                        "change":  change_pct,
                        "timestamp": int(time.time() * 1000),
                    }
        except Exception as e:
            logger.debug(f"OI fetch failed for {symbol}: {e}")

    # ── Public Accessors ──

    def get_latest_prices(self) -> Dict[str, dict]:
        """Return copy of latest price/ticker data."""
        return dict(self._prices)

    def get_oi_data(self) -> List[dict]:
        """Return OI data as sorted list."""
        return sorted(self._oi_data.values(), key=lambda x: x.get("oi", 0), reverse=True)

    def get_price(self, symbol: str) -> Optional[float]:
        """Return current price for a symbol."""
        return self._prices.get(symbol, {}).get("price")

    def get_volume(self, symbol: str) -> Optional[float]:
        """Return 24h volume for a symbol."""
        return self._prices.get(symbol, {}).get("volume")

    def get_klines(self, symbol: str) -> List[float]:
        """Return recent kline closes for a symbol."""
        return list(self._klines.get(symbol, []))

    def get_relative_volume(self, symbol: str) -> float:
        """
        Return relative volume: current hourly vol vs avg hourly vol.
        > 1.0 means above average volume.
        """
        history = list(self._volume_history.get(symbol, []))
        if len(history) < 2:
            return 1.0
        avg = sum(history[:-1]) / max(len(history) - 1, 1)
        current = history[-1] if history else avg
        return current / max(avg, 1.0)

    def get_oi_change(self, symbol: str) -> float:
        """Return OI change percentage for a symbol."""
        return self._oi_data.get(symbol, {}).get("change", 0.0)

    def compute_momentum(self, symbol: str, periods: int = 12) -> float:
        """
        Compute price momentum: (close_now / close_N_periods_ago - 1) * 100
        Returns percentage momentum.
        """
        closes = self.get_klines(symbol)
        if len(closes) < periods + 1:
            return 0.0
        old = closes[-periods - 1]
        current = closes[-1]
        return ((current / max(old, 1e-10)) - 1) * 100

    def compute_trend_strength(self, symbol: str) -> float:
        """
        Simple trend strength using price vs 20-period SMA.
        Returns % distance from SMA (-100 to +100 range).
        """
        closes = self.get_klines(symbol)
        if len(closes) < 5:
            return 0.0
        sma = sum(closes[-20:]) / min(len(closes), 20)
        current = closes[-1]
        return ((current / max(sma, 1e-10)) - 1) * 100
