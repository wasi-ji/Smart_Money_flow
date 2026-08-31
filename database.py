"""
database.py — SQLite Database Layer
Persists market snapshots, flow scores, whale alerts, and dominance history.
Uses aiosqlite for non-blocking async operations.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("smft.database")

# Try to import aiosqlite; fall back to a no-op stub if not installed
try:
    import aiosqlite
    AIOSQLITE_AVAILABLE = True
except ImportError:
    AIOSQLITE_AVAILABLE = False
    logger.warning("aiosqlite not installed — database persistence disabled. Install with: pip install aiosqlite")


# ── SQL Schema ──
SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    score       REAL    NOT NULL,
    signal      TEXT,
    components  TEXT,   -- JSON blob
    price       REAL,
    change24h   REAL,
    volume      REAL,
    timestamp   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dominance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    btc         REAL,
    eth         REAL,
    usdt        REAL,
    alts        REAL,
    btc_chg     REAL,
    signal      TEXT,
    timestamp   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS whale_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT,
    type        TEXT,
    severity    TEXT,
    title       TEXT,
    message     TEXT,
    data        TEXT,   -- JSON blob
    timestamp   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS funding_rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    rate        REAL    NOT NULL,
    annualized  REAL,
    bias        TEXT,
    timestamp   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    price       REAL,
    change24h   REAL,
    volume      REAL,
    timestamp   INTEGER NOT NULL
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_flow_sym_ts  ON flow_scores    (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dom_ts       ON dominance      (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_whale_ts     ON whale_alerts   (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_funding_ts   ON funding_rates  (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_snap_sym_ts  ON market_snapshots (symbol, timestamp DESC);
"""

# How many rows to keep per table (older rows pruned automatically)
MAX_ROWS = {
    "flow_scores":       10_000,
    "dominance":         1_000,
    "whale_alerts":      500,
    "funding_rates":     5_000,
    "market_snapshots":  20_000,
}


class Database:
    """
    Async SQLite database wrapper.
    Provides methods to insert and query historical market data.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Create database file, apply schema, and run initial maintenance."""
        if not AIOSQLITE_AVAILABLE:
            logger.warning("Database disabled (aiosqlite not available)")
            return

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        try:
            self._db = await aiosqlite.connect(self.db_path)
            await self._db.executescript(SCHEMA)
            await self._db.commit()
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")

    async def close(self):
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ── Write Methods ──

    async def save_flow_scores(self, scores: List[dict]):
        """Persist a batch of flow score records."""
        if not self._db:
            return
        async with self._lock:
            try:
                rows = [
                    (
                        s["symbol"],
                        s.get("score", 0),
                        s.get("signal"),
                        json.dumps(s.get("components", {})),
                        s.get("price"),
                        s.get("change24h"),
                        s.get("volume"),
                        s.get("timestamp", int(time.time() * 1000)),
                    )
                    for s in scores
                ]
                await self._db.executemany(
                    """INSERT INTO flow_scores
                       (symbol, score, signal, components, price, change24h, volume, timestamp)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    rows,
                )
                await self._db.commit()
                await self._prune("flow_scores", MAX_ROWS["flow_scores"])
            except Exception as e:
                logger.debug(f"save_flow_scores failed: {e}")

    async def save_dominance(self, data: dict):
        """Persist a dominance snapshot."""
        if not self._db:
            return
        async with self._lock:
            try:
                await self._db.execute(
                    """INSERT INTO dominance (btc, eth, usdt, alts, btc_chg, signal, timestamp)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        data.get("btc"),
                        data.get("eth"),
                        data.get("usdt"),
                        data.get("alts"),
                        data.get("btcChg"),
                        data.get("signal"),
                        data.get("timestamp", int(time.time() * 1000)),
                    ),
                )
                await self._db.commit()
                await self._prune("dominance", MAX_ROWS["dominance"])
            except Exception as e:
                logger.debug(f"save_dominance failed: {e}")

    async def save_whale_alert(self, alert: dict):
        """Persist a whale alert."""
        if not self._db:
            return
        async with self._lock:
            try:
                await self._db.execute(
                    """INSERT INTO whale_alerts (symbol, type, severity, title, message, data, timestamp)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        alert.get("symbol"),
                        alert.get("type"),
                        alert.get("severity"),
                        alert.get("title"),
                        alert.get("message"),
                        json.dumps(alert.get("data", {})),
                        alert.get("timestamp", int(time.time() * 1000)),
                    ),
                )
                await self._db.commit()
                await self._prune("whale_alerts", MAX_ROWS["whale_alerts"])
            except Exception as e:
                logger.debug(f"save_whale_alert failed: {e}")

    async def save_funding_rates(self, rates: List[dict]):
        """Persist a batch of funding rate records."""
        if not self._db:
            return
        async with self._lock:
            try:
                rows = [
                    (
                        r["symbol"],
                        r.get("rate", 0),
                        r.get("annualized"),
                        r.get("bias"),
                        r.get("timestamp", int(time.time() * 1000)),
                    )
                    for r in rates
                ]
                await self._db.executemany(
                    """INSERT INTO funding_rates (symbol, rate, annualized, bias, timestamp)
                       VALUES (?,?,?,?,?)""",
                    rows,
                )
                await self._db.commit()
                await self._prune("funding_rates", MAX_ROWS["funding_rates"])
            except Exception as e:
                logger.debug(f"save_funding_rates failed: {e}")

    async def save_market_snapshot(self, data: Dict[str, dict]):
        """Persist market price snapshots."""
        if not self._db:
            return
        async with self._lock:
            try:
                rows = [
                    (
                        sym,
                        d.get("price"),
                        d.get("change24h"),
                        d.get("volume"),
                        d.get("timestamp", int(time.time() * 1000)),
                    )
                    for sym, d in data.items()
                ]
                await self._db.executemany(
                    """INSERT INTO market_snapshots (symbol, price, change24h, volume, timestamp)
                       VALUES (?,?,?,?,?)""",
                    rows,
                )
                await self._db.commit()
                await self._prune("market_snapshots", MAX_ROWS["market_snapshots"])
            except Exception as e:
                logger.debug(f"save_market_snapshot failed: {e}")

    # ── Read Methods ──

    async def get_flow_history(self, symbol: str, limit: int = 100) -> List[dict]:
        """Retrieve recent flow score history for a symbol."""
        if not self._db:
            return []
        try:
            async with self._db.execute(
                """SELECT score, signal, timestamp FROM flow_scores
                   WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?""",
                (symbol, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [{"score": r[0], "signal": r[1], "timestamp": r[2]} for r in rows]
        except Exception as e:
            logger.debug(f"get_flow_history failed: {e}")
            return []

    async def get_whale_alerts(self, limit: int = 50) -> List[dict]:
        """Retrieve recent whale alerts from the database."""
        if not self._db:
            return []
        try:
            async with self._db.execute(
                """SELECT symbol, type, severity, title, message, data, timestamp
                   FROM whale_alerts ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "symbol": r[0], "type": r[1], "severity": r[2],
                        "title": r[3], "message": r[4],
                        "data": json.loads(r[5] or "{}"),
                        "timestamp": r[6],
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.debug(f"get_whale_alerts failed: {e}")
            return []

    async def get_dominance_history(self, limit: int = 48) -> List[dict]:
        """Retrieve dominance history."""
        if not self._db:
            return []
        try:
            async with self._db.execute(
                """SELECT btc, eth, usdt, alts, timestamp
                   FROM dominance ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    {"btc": r[0], "eth": r[1], "usdt": r[2], "alts": r[3], "timestamp": r[4]}
                    for r in rows
                ]
        except Exception as e:
            logger.debug(f"get_dominance_history failed: {e}")
            return []

    # ── Maintenance ──

    async def _prune(self, table: str, max_rows: int):
        """Remove old rows keeping only the newest max_rows entries."""
        try:
            await self._db.execute(
                f"""DELETE FROM {table} WHERE id NOT IN (
                    SELECT id FROM {table} ORDER BY timestamp DESC LIMIT ?
                )""",
                (max_rows,),
            )
        except Exception:
            pass  # Non-critical; next prune will handle it

    async def get_stats(self) -> Dict[str, Any]:
        """Return row counts for all tables."""
        if not self._db:
            return {"status": "disabled"}
        stats = {}
        for table in MAX_ROWS:
            try:
                async with self._db.execute(f"SELECT COUNT(*) FROM {table}") as cur:
                    row = await cur.fetchone()
                    stats[table] = row[0] if row else 0
            except Exception:
                stats[table] = -1
        return stats
