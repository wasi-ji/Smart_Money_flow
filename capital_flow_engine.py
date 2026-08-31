"""
capital_flow_engine.py — Capital Flow Score Engine
Computes a composite 0-100 flow score for each asset.

Formula:
  FlowScore = 0.20*Price + 0.20*Volume + 0.20*RelVol
            + 0.15*Momentum + 0.15*OI_Change + 0.10*Funding
            + 0.05*Trend (bonus component)
Normalized to 0-100.
"""

import logging
import time
from typing import Dict, List, Optional

from market_scanner import MarketScanner

logger = logging.getLogger("smft.capital_flow")

# Flow signal thresholds
STRONG_INFLOW_THRESHOLD  = 68.0
INFLOW_THRESHOLD         = 55.0
OUTFLOW_THRESHOLD        = 45.0
STRONG_OUTFLOW_THRESHOLD = 32.0


def normalize(value: float, min_val: float, max_val: float, invert: bool = False) -> float:
    """Normalize a value to 0-100 range. Optionally invert (higher raw = lower score)."""
    if max_val == min_val:
        return 50.0
    n = (value - min_val) / (max_val - min_val) * 100.0
    n = max(0.0, min(100.0, n))
    return 100.0 - n if invert else n


def score_to_signal(score: float) -> str:
    """Convert a numeric flow score to a human-readable signal."""
    if score >= STRONG_INFLOW_THRESHOLD:
        return "STRONG_INFLOW"
    elif score >= INFLOW_THRESHOLD:
        return "INFLOW"
    elif score <= STRONG_OUTFLOW_THRESHOLD:
        return "STRONG_OUTFLOW"
    elif score <= OUTFLOW_THRESHOLD:
        return "OUTFLOW"
    else:
        return "NEUTRAL"


class CapitalFlowEngine:
    """
    Computes multi-factor capital flow scores for each tracked asset.
    Scores are updated every time the market scanner refreshes.
    """

    def __init__(self, market_scanner: MarketScanner):
        self.scanner = market_scanner
        self._flow_scores: Dict[str, dict] = {}
        self._funding_rates: Dict[str, float] = {}

    def update_funding(self, funding_data: List[dict]):
        """Accept funding rate updates from FundingEngine."""
        for item in funding_data:
            self._funding_rates[item["symbol"]] = item.get("rate", 0.0)

    def compute_scores(self, symbols: List[str]) -> List[dict]:
        """
        Compute capital flow scores for all provided symbols.
        Returns a list of score dicts sorted by score descending.
        """
        raw_scores = []

        for sym in symbols:
            try:
                score_dict = self._compute_symbol_score(sym)
                raw_scores.append(score_dict)
            except Exception as e:
                logger.debug(f"Score computation failed for {sym}: {e}")

        # Cross-normalize: find global min/max for relative ranking
        if raw_scores:
            all_raw = [s["_raw"] for s in raw_scores]
            min_raw = min(all_raw)
            max_raw = max(all_raw)

            for s in raw_scores:
                s["score"] = round(normalize(s["_raw"], min_raw, max_raw), 2)
                s["signal"] = score_to_signal(s["score"])
                del s["_raw"]
                self._flow_scores[s["symbol"]] = s

        return sorted(raw_scores, key=lambda x: x.get("score", 0), reverse=True)

    def _compute_symbol_score(self, symbol: str) -> dict:
        """Compute the flow score components for a single symbol."""
        prices = self.scanner.get_latest_prices()
        data = prices.get(symbol, {})

        if not data:
            return {"symbol": symbol, "_raw": 50.0, "components": {}}

        price     = data.get("price", 0)
        change24h = data.get("change24h", 0)   # %
        volume    = data.get("volume", 0)       # USDT
        high24h   = data.get("high24h", price)
        low24h    = data.get("low24h", price)
        open24h   = data.get("open24h", price)

        # ── Component 1: Price Strength (0-100) ──
        # Based on 24h % change; scaled so ±10% maps to 0-100
        price_score = normalize(change24h, -10.0, 10.0)

        # ── Component 2: Volume Score ──
        # Relative to all tracked assets — computed globally later
        # For now: log-scale 0-100 using rough USDT volume ranges
        import math
        vol_score = min(100.0, max(0.0, (math.log10(max(volume, 1)) - 6) * 20))

        # ── Component 3: Relative Volume Score ──
        rel_vol = self.scanner.get_relative_volume(symbol)
        rel_vol_score = normalize(rel_vol, 0.5, 3.0)

        # ── Component 4: Momentum ──
        momentum = self.scanner.compute_momentum(symbol, periods=12)
        momentum_score = normalize(momentum, -8.0, 8.0)

        # ── Component 5: Trend Strength ──
        trend = self.scanner.compute_trend_strength(symbol)
        trend_score = normalize(trend, -5.0, 5.0)

        # ── Component 6: OI Change ──
        oi_change = self.scanner.get_oi_change(symbol)
        oi_score = normalize(oi_change, -10.0, 10.0)

        # ── Component 7: Funding Rate ──
        # Negative funding = bullish (shorts paying longs) → high score
        # Positive funding = bearish (longs paying shorts) → low score
        funding = self._funding_rates.get(symbol, 0.0)
        funding_score = normalize(-funding, -0.001, 0.001)  # inverted

        # ── Weighted Composite ──
        w = {
            "price":    0.20,
            "volume":   0.20,
            "rel_vol":  0.20,
            "momentum": 0.15,
            "oi_chg":   0.15,
            "funding":  0.10,
        }

        raw = (
            w["price"]    * price_score    +
            w["volume"]   * vol_score      +
            w["rel_vol"]  * rel_vol_score  +
            w["momentum"] * momentum_score +
            w["oi_chg"]   * oi_score       +
            w["funding"]  * funding_score
        )

        return {
            "symbol": symbol,
            "_raw":   round(raw, 4),
            "components": {
                "price":    round(price_score, 1),
                "volume":   round(vol_score, 1),
                "rel_vol":  round(rel_vol_score, 1),
                "momentum": round(momentum_score, 1),
                "trend":    round(trend_score, 1),
                "oi_chg":   round(oi_score, 1),
                "funding":  round(funding_score, 1),
            },
            "price":    price,
            "change24h": change24h,
            "volume":   volume,
            "timestamp": int(time.time() * 1000),
        }

    def get_flow_score(self, symbol: str) -> Optional[dict]:
        """Return the latest flow score for a symbol."""
        return self._flow_scores.get(symbol)

    def get_all_scores(self) -> Dict[str, dict]:
        """Return all cached flow scores."""
        return dict(self._flow_scores)

    def get_risk_regime(self) -> dict:
        """
        Derive market risk regime from aggregate flow scores.
        Returns regime info for the Risk Gauge panel.
        """
        if not self._flow_scores:
            return {"regime": "NEUTRAL", "score": 50, "riskScore": 50}

        scores = [v.get("score", 50) for v in self._flow_scores.values()]
        avg_score = sum(scores) / len(scores) if scores else 50

        # BTC vs. Altcoin divergence
        btc_score  = self._flow_scores.get("BTCUSDT", {}).get("score", 50)
        eth_score  = self._flow_scores.get("ETHUSDT", {}).get("score", 50)
        avg_alt    = avg_score

        # Sentiment distribution
        bull = len([s for s in scores if s >= 60])
        bear = len([s for s in scores if s <= 40])
        neut = len(scores) - bull - bear
        total = max(len(scores), 1)

        bull_pct = (bull / total) * 100
        bear_pct = (bear / total) * 100
        neut_pct = (neut / total) * 100

        # Determine regime
        if bull_pct >= 60 and btc_score >= 55:
            regime = "RISK-ON"
        elif bear_pct >= 60 or btc_score <= 35:
            regime = "RISK-OFF"
        else:
            regime = "NEUTRAL"

        return {
            "regime":     regime,
            "score":      round(avg_score, 1),
            "riskScore":  round((btc_score + avg_alt) / 2, 1),
            "btcScore":   round(btc_score, 1),
            "ethScore":   round(eth_score, 1),
            "bullPct":    round(bull_pct, 1),
            "neutPct":    round(neut_pct, 1),
            "bearPct":    round(bear_pct, 1),
            "fear":       str(int(100 - avg_score)),
            "avgFunding": 0.0,  # populated by FundingEngine
        }
