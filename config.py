"""
config.py — Application Configuration
All settings loaded from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Settings:
    # ── Server ──
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # ── Database ──
    DB_PATH: str = os.getenv("DB_PATH", "../data/market.db")

    # ── Binance API ──
    BINANCE_BASE_URL: str = "https://api.binance.com"
    BINANCE_FUTURES_URL: str = "https://fapi.binance.com"
    BINANCE_WS_URL: str = "wss://stream.binance.com:9443/stream"
    BINANCE_FUTURES_WS_URL: str = "wss://fstream.binance.com/stream"

    # Optional API keys (not required for public market data)
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET: str = os.getenv("BINANCE_SECRET", "")

    # ── Tracked Symbols ──
    SYMBOLS: List[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "TRXUSDT",
    ])

    # ── Futures symbols (subset that have active futures) ──
    FUTURES_SYMBOLS: List[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "TRXUSDT",
    ])

    # ── Sector definitions ──
    SECTORS: dict = field(default_factory=lambda: {
        "Layer 1": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT", "ADAUSDT", "TRXUSDT"],
        "DeFi":    ["LINKUSDT", "AAVEUSDT", "UNIUSDT", "SUSHIUSDT"],
        "AI":      ["FETUSDT", "AGIXUSDT", "RENDERUSDT", "WLDUSDT"],
        "Gaming":  ["AXSUSDT", "SANDUSDT", "MANAUSDT", "ENJUSDT"],
        "Meme":    ["DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT"],
    })

    # ── Capital Flow Engine Weights ──
    FLOW_WEIGHTS: dict = field(default_factory=lambda: {
        "price":    0.20,
        "volume":   0.20,
        "rel_vol":  0.20,
        "momentum": 0.15,
        "trend":    0.10,
        "oi_chg":   0.15,
        "funding":  0.10,
    })

    # ── Whale Detection Thresholds ──
    WHALE_VOLUME_MULTIPLIER: float = 3.0    # x above average = whale
    WHALE_OI_CHANGE_PCT: float = 5.0        # % OI change = whale signal
    WHALE_FUNDING_THRESHOLD: float = 0.0005  # 0.05% funding = extreme

    # ── Engine Update Intervals (seconds) ──
    MARKET_SCAN_INTERVAL: float = 1.0
    DOMINANCE_INTERVAL: float = 30.0
    FUNDING_INTERVAL: float = 60.0
    OI_INTERVAL: float = 10.0
    WHALE_CHECK_INTERVAL: float = 5.0
    SECTOR_INTERVAL: float = 30.0

    # ── History ──
    PRICE_HISTORY_LENGTH: int = 200
    ALERT_HISTORY_LENGTH: int = 100

    # ── HTTP Request Settings ──
    REQUEST_TIMEOUT: float = 10.0
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 2.0


# Singleton settings instance
settings = Settings()
