# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/cross_asset.py
==================
Cross-asset inter-market signals — gold/silver/oil/SPX ratio analysis.

Computes ratio signals and correlation-based signals across:
  - Gold/Silver ratio (GSR) — regime indicator
  - Gold/Oil ratio — real asset relative value
  - Gold/SPX ratio — safe-haven demand
  - Gold/DXY — USD-adjusted gold performance

These ratios are leading indicators for gold direction. Extreme GSR
historically signals regime inflection points.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CrossAssetSignal:
    """Cross-asset signal snapshot."""
    gold_silver_ratio: float
    """XAU/XAG. High (>80) historically bullish gold setup."""
    gold_oil_ratio: float
    """XAU/WTI. Measures commodity bloc alignment."""
    gold_spx_ratio: float
    """XAU/SPX (normalised). Safe-haven demand proxy."""
    gsr_z20: float
    """GSR 20-day z-score."""
    gsr_z60: float
    """GSR 60-day z-score."""
    gold_momentum_20: float
    """Gold 20-day momentum (return)."""
    silver_momentum_20: float
    """Silver 20-day momentum."""
    oil_momentum_20: float
    """Oil 20-day momentum."""
    spx_momentum_20: float
    """SPX 20-day momentum."""
    risk_on_score: float
    """Composite risk-on score [-1, 1]. >0 = risk-on, <0 = risk-off."""
    intermarket_bullish: bool
    """True if cross-asset configuration is net bullish for gold."""


class CrossAssetEngine:
    """
    Computes cross-asset inter-market signals for gold.

    Uses price series for Gold, Silver, Oil, and SPX to generate
    ratio-based and momentum-based signals.
    """

    def compute(
        self,
        gold: pd.Series,
        silver: pd.Series | None = None,
        oil: pd.Series | None = None,
        spx: pd.Series | None = None,
        dxy: pd.Series | None = None,
    ) -> pd.DataFrame:
        """
        Compute cross-asset signals from price series.

        Parameters
        ----------
        gold : pd.Series
            Gold price (XAU_USD or GC=F).
        silver : pd.Series, optional
        oil : pd.Series, optional
        spx : pd.Series, optional
        dxy : pd.Series, optional

        Returns
        -------
        pd.DataFrame with one row per date and all cross-asset features.
        """
        df = pd.DataFrame({"gold": gold})

        if silver is not None:
            df["silver"] = silver
            df["gsr"] = df["gold"] / df["silver"].replace(0, float("nan"))
        if oil is not None:
            df["oil"] = oil
            df["gold_oil"] = df["gold"] / df["oil"].replace(0, float("nan"))
        if spx is not None:
            df["spx"] = spx
            df["gold_spx"] = df["gold"] / df["spx"].replace(0, float("nan"))
        if dxy is not None:
            df["dxy"] = dxy
            df["gold_dxy"] = df["gold"] / df["dxy"].replace(0, float("nan"))

        # Returns (momentum)
        for col in ["gold", "silver", "oil", "spx"]:
            if col in df.columns:
                df[f"{col}_ret20"] = df[col].pct_change(20)

        # GSR z-scores
        if "gsr" in df.columns:
            gsr_roll20 = df["gsr"].rolling(20)
            gsr_roll60 = df["gsr"].rolling(60)
            df["gsr_z20"] = (df["gsr"] - gsr_roll20.mean()) / gsr_roll20.std().replace(0, float("nan"))
            df["gsr_z60"] = (df["gsr"] - gsr_roll60.mean()) / gsr_roll60.std().replace(0, float("nan"))

        # Risk-on score: SPX rising + oil rising = risk-on (bearish gold)
        # Gold outperforming = risk-off (bullish gold)
        risk_components: list[pd.Series] = []
        if "spx_ret20" in df.columns:
            # SPX rising → risk-on → bearish gold
            spx_signal = -np.sign(df["spx_ret20"])
            risk_components.append(spx_signal)
        if "oil_ret20" in df.columns:
            # Oil falling → risk-off → bullish gold
            oil_signal = -np.sign(df["oil_ret20"])
            risk_components.append(oil_signal)
        if "gsr_z20" in df.columns:
            # High GSR → gold outperforming silver → bullish gold
            gsr_signal = np.sign(df["gsr_z20"])
            risk_components.append(gsr_signal)

        if risk_components:
            df["risk_on_score"] = pd.concat(risk_components, axis=1).mean(axis=1)
        else:
            df["risk_on_score"] = 0.0

        df["intermarket_bullish"] = df["risk_on_score"] < 0  # risk-off = bullish gold

        return df.ffill()

    def latest_signal(
        self,
        gold: pd.Series,
        silver: pd.Series | None = None,
        oil: pd.Series | None = None,
        spx: pd.Series | None = None,
        dxy: pd.Series | None = None,
    ) -> CrossAssetSignal:
        """Return the latest cross-asset signal snapshot."""
        df = self.compute(gold, silver, oil, spx, dxy)
        if df.empty:
            return CrossAssetSignal(
                gold_silver_ratio=80.0, gold_oil_ratio=20.0, gold_spx_ratio=0.5,
                gsr_z20=0.0, gsr_z60=0.0,
                gold_momentum_20=0.0, silver_momentum_20=0.0,
                oil_momentum_20=0.0, spx_momentum_20=0.0,
                risk_on_score=0.0, intermarket_bullish=False,
            )

        row = df.iloc[-1]
        return CrossAssetSignal(
            gold_silver_ratio=float(row.get("gsr", 80.0) or 80.0),
            gold_oil_ratio=float(row.get("gold_oil", 20.0) or 20.0),
            gold_spx_ratio=float(row.get("gold_spx", 0.5) or 0.5),
            gsr_z20=float(row.get("gsr_z20", 0.0) or 0.0),
            gsr_z60=float(row.get("gsr_z60", 0.0) or 0.0),
            gold_momentum_20=float(row.get("gold_ret20", 0.0) or 0.0),
            silver_momentum_20=float(row.get("silver_ret20", 0.0) or 0.0),
            oil_momentum_20=float(row.get("oil_ret20", 0.0) or 0.0),
            spx_momentum_20=float(row.get("spx_ret20", 0.0) or 0.0),
            risk_on_score=float(row.get("risk_on_score", 0.0) or 0.0),
            intermarket_bullish=bool(row.get("intermarket_bullish", False)),
        )

    def ml_features(
        self,
        gold: pd.Series,
        silver: pd.Series | None = None,
        oil: pd.Series | None = None,
        spx: pd.Series | None = None,
        dxy: pd.Series | None = None,
    ) -> dict[str, float]:
        """Return flat dict of cross-asset features for ML pipeline."""
        sig = self.latest_signal(gold, silver, oil, spx, dxy)
        return {
            "ca_gsr": sig.gold_silver_ratio,
            "ca_gold_oil": sig.gold_oil_ratio,
            "ca_gold_spx": sig.gold_spx_ratio,
            "ca_gsr_z20": sig.gsr_z20,
            "ca_gsr_z60": sig.gsr_z60,
            "ca_gold_mom20": sig.gold_momentum_20,
            "ca_silver_mom20": sig.silver_momentum_20,
            "ca_oil_mom20": sig.oil_momentum_20,
            "ca_spx_mom20": sig.spx_momentum_20,
            "ca_risk_on_score": sig.risk_on_score,
            "ca_intermarket_bullish": float(sig.intermarket_bullish),
        }


cross_asset_engine = CrossAssetEngine()
