"""
ranking_engine.py — Asset Ranking Engine
Coordinates with CapitalFlowEngine to produce top-10 inflow/outflow rankings.
Updates every second via the broadcast loop.
"""

import logging
import time
from typing import List

from capital_flow_engine import CapitalFlowEngine

logger = logging.getLogger("smft.ranking")


class RankingEngine:
    """
    Maintains sorted rankings of all tracked assets by capital flow score.
    Provides both inflow (highest score) and outflow (lowest score) views.
    """

    def __init__(self, flow_engine: CapitalFlowEngine):
        self.flow_engine = flow_engine
        self._last_rankings: List[dict] = []

    def get_rankings(self, top_n: int = 10) -> List[dict]:
        """
        Compute and return top_n inflow + top_n outflow rankings.
        Triggers a fresh score computation from the flow engine.
        """
        from config import settings

        # Compute scores for all symbols
        scores = self.flow_engine.compute_scores(settings.SYMBOLS)

        if not scores:
            return self._last_rankings

        self._last_rankings = scores
        return scores

    def get_top_inflows(self, n: int = 10) -> List[dict]:
        """Return top N assets by flow score (highest = most inflow)."""
        scores = self.get_rankings()
        return sorted(scores, key=lambda x: x.get("score", 0), reverse=True)[:n]

    def get_top_outflows(self, n: int = 10) -> List[dict]:
        """Return top N assets by lowest flow score (most outflow pressure)."""
        scores = self.get_rankings()
        return sorted(scores, key=lambda x: x.get("score", 0))[:n]
