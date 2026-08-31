"""
sector_rotation.py — Sector Rotation Engine
Groups assets into crypto sectors and tracks relative performance.
Identifies the strongest and weakest sectors to detect capital rotation.

Sectors:
  Layer 1  — BTC, ETH, BNB, SOL, AVAX, ADA, TRX
  DeFi     — LINK, AAVE, UNI, SUSHI
  AI       — FET, AGIX, RENDER, WLD
  Gaming   — AXS, SAND, MANA, ENJ
  Meme     — DOGE, SHIB, PEPE, FLOKI
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional

from market_scanner import MarketScanner
from config import Settings

logger = logging.getLogger("smft.sector_rotation")


class SectorRotationEngine:
    """
    Computes sector-level performance metrics by aggregating
    individual asset data within each sector.
    """

    def __init__(self, market_scanner: MarketScanner):
        self.scanner = market_scanner
        self._latest: Optional[dict] = None

    async def run(self):
        """Periodically compute sector performance."""
        logger.info("SectorRotationEngine starting…")
        from config import settings  # local import to avoid circular

        while True:
            try:
                self._compute()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"SectorRotationEngine error: {e}")
            await asyncio.sleep(settings.SECTOR_INTERVAL)

    def _compute(self):
        """Compute weighted average performance for each sector."""
        from config import settings
        prices = self.scanner.get_latest_prices()
        sectors = []

        for sector_name, symbols in settings.SECTORS.items():
            changes = []
            volumes = []

            for sym in symbols:
                data = prices.get(sym)
                if not data:
                    continue
                chg = data.get("change24h", 0)
                vol = data.get("volume", 0)
                if vol > 0:
                    changes.append(chg)
                    volumes.append(vol)

            if not changes:
                # No live data for this sector — use placeholder
                sectors.append({
                    "name":   sector_name,
                    "change": 0.0,
                    "volume": 0.0,
                    "assets": len(symbols),
                    "heat":   3,  # neutral
                })
                continue

            # Volume-weighted average change
            total_vol = sum(volumes) or 1
            weighted_change = sum(
                c * v / total_vol for c, v in zip(changes, volumes)
            )
            total_volume = sum(volumes)

            # Heat level: 1 (coldest) to 5 (hottest)
            heat = self._change_to_heat(weighted_change)

            sectors.append({
                "name":   sector_name,
                "change": round(weighted_change, 2),
                "volume": total_volume,
                "assets": len([s for s in symbols if s in prices]),
                "heat":   heat,
            })

        # Determine hot/cold sectors
        if sectors:
            sorted_sectors = sorted(sectors, key=lambda x: x["change"], reverse=True)
            hot  = sorted_sectors[0]["name"]  if sorted_sectors else "—"
            cold = sorted_sectors[-1]["name"] if sorted_sectors else "—"
        else:
            hot = cold = "—"

        self._latest = {
            "sectors":   sectors,
            "hot":       hot,
            "cold":      cold,
            "timestamp": int(time.time() * 1000),
        }

    def _change_to_heat(self, change: float) -> int:
        """Convert percent change to a 1-5 heat score."""
        if change >= 3.0:   return 5
        if change >= 1.0:   return 4
        if change >= -1.0:  return 3
        if change >= -3.0:  return 2
        return 1

    def get_latest(self) -> Optional[dict]:
        """Return the latest sector rotation snapshot."""
        if not self._latest:
            # Compute synchronously for immediate availability
            try:
                self._compute()
            except Exception:
                pass
        return self._latest

    def get_strongest_sector(self) -> Optional[str]:
        """Return the name of the currently strongest sector."""
        data = self.get_latest()
        return data.get("hot") if data else None

    def get_weakest_sector(self) -> Optional[str]:
        """Return the name of the currently weakest sector."""
        data = self.get_latest()
        return data.get("cold") if data else None

    def get_sector_scores(self) -> Dict[str, float]:
        """Return a dict of sector_name -> weighted_change."""
        data = self.get_latest()
        if not data:
            return {}
        return {s["name"]: s["change"] for s in data.get("sectors", [])}
