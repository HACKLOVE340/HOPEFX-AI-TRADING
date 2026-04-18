# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
visualization/charts.py
=======================
Chart generation utilities for equity curves, drawdown, trade distribution,
and regime heatmaps using Plotly and Matplotlib.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class ChartGenerator:
    """
    Generates Plotly/Matplotlib charts from trade and portfolio data.

    All methods return a dict with keys:
        "type"   — "plotly" | "matplotlib"
        "figure" — the figure object (Plotly Figure or Matplotlib Figure)
        "html"   — HTML string (Plotly only, else None)
    """

    # ── Equity curve ─────────────────────────────────────────────────────────

    def equity_curve(
        self,
        equity: pd.Series,
        benchmark: pd.Series | None = None,
        title: str = "Equity Curve",
    ) -> dict[str, Any]:
        """
        Plot portfolio equity over time, optionally overlaid with a benchmark.

        Parameters
        ----------
        equity:    DatetimeIndex Series of portfolio value.
        benchmark: Optional DatetimeIndex Series of benchmark value.
        title:     Chart title.
        """
        try:
            import plotly.graph_objects as go

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=equity.index,
                    y=equity.values,
                    mode="lines",
                    name="Portfolio",
                    line=dict(color="#00ff88", width=2),
                )
            )
            if benchmark is not None:
                fig.add_trace(
                    go.Scatter(
                        x=benchmark.index,
                        y=benchmark.values,
                        mode="lines",
                        name="Benchmark",
                        line=dict(color="#888888", width=1, dash="dash"),
                    )
                )
            fig.update_layout(
                title=title,
                xaxis_title="Date",
                yaxis_title="Value",
                template="plotly_dark",
                hovermode="x unified",
            )
            return {"type": "plotly", "figure": fig, "html": fig.to_html(full_html=False)}
        except ImportError:
            logger.warning("plotly not installed — falling back to matplotlib")
            return self._equity_curve_mpl(equity, benchmark, title)

    def _equity_curve_mpl(
        self,
        equity: pd.Series,
        benchmark: pd.Series | None,
        title: str,
    ) -> dict[str, Any]:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(equity.index, equity.values, label="Portfolio", color="#00aa55")
        if benchmark is not None:
            ax.plot(benchmark.index, benchmark.values, label="Benchmark", color="#888888", linestyle="--")
        ax.set_title(title)
        ax.set_xlabel("Date")
        ax.set_ylabel("Value")
        ax.legend()
        fig.tight_layout()
        return {"type": "matplotlib", "figure": fig, "html": None}

    # ── Drawdown ──────────────────────────────────────────────────────────────

    def drawdown(self, equity: pd.Series, title: str = "Drawdown") -> dict[str, Any]:
        """
        Plot the rolling drawdown from peak for the given equity series.
        """
        rolling_max = equity.cummax()
        dd = (equity - rolling_max) / rolling_max * 100

        try:
            import plotly.graph_objects as go

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=dd.index,
                    y=dd.values,
                    mode="lines",
                    fill="tozeroy",
                    name="Drawdown %",
                    line=dict(color="#ff4444", width=1),
                    fillcolor="rgba(255,68,68,0.2)",
                )
            )
            fig.update_layout(
                title=title,
                xaxis_title="Date",
                yaxis_title="Drawdown (%)",
                template="plotly_dark",
            )
            return {"type": "plotly", "figure": fig, "html": fig.to_html(full_html=False)}
        except ImportError:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(12, 3))
            ax.fill_between(dd.index, dd.values, 0, color="#ff4444", alpha=0.4, label="Drawdown %")
            ax.set_title(title)
            ax.set_xlabel("Date")
            ax.set_ylabel("Drawdown (%)")
            fig.tight_layout()
            return {"type": "matplotlib", "figure": fig, "html": None}

    # ── Trade distribution ────────────────────────────────────────────────────

    def trade_distribution(
        self,
        pnl: pd.Series,
        bins: int = 50,
        title: str = "Trade P&L Distribution",
    ) -> dict[str, Any]:
        """
        Histogram of per-trade P&L values.

        Parameters
        ----------
        pnl:  Series of per-trade P&L values.
        bins: Number of histogram bins.
        """
        try:
            import plotly.graph_objects as go

            fig = go.Figure()
            fig.add_trace(
                go.Histogram(
                    x=pnl.values,
                    nbinsx=bins,
                    name="P&L",
                    marker_color="#4488ff",
                    opacity=0.75,
                )
            )
            fig.update_layout(
                title=title,
                xaxis_title="P&L",
                yaxis_title="Count",
                template="plotly_dark",
                bargap=0.05,
            )
            return {"type": "plotly", "figure": fig, "html": fig.to_html(full_html=False)}
        except ImportError:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.hist(pnl.values, bins=bins, color="#4488ff", alpha=0.75, edgecolor="white")
            ax.set_title(title)
            ax.set_xlabel("P&L")
            ax.set_ylabel("Count")
            fig.tight_layout()
            return {"type": "matplotlib", "figure": fig, "html": None}

    # ── Regime heatmap ────────────────────────────────────────────────────────

    def regime_heatmap(
        self,
        regime_data: dict[str, Any],
        title: str = "Strategy Regime Heatmap",
    ) -> dict[str, Any]:
        """
        Render a heatmap of strategy allocations across market regimes.

        Parameters
        ----------
        regime_data: Dict mapping strategy_id → {"win_rate", "sharpe", "allocation"}.
        """
        if not regime_data:
            logger.warning("regime_heatmap: empty regime_data — returning empty chart")
            return {"type": "plotly", "figure": None, "html": "<p>No regime data</p>"}

        strategies = list(regime_data.keys())
        metrics = ["win_rate", "sharpe", "allocation"]
        z = [
            [regime_data[s].get(m, 0.0) for m in metrics]
            for s in strategies
        ]

        try:
            import plotly.graph_objects as go

            fig = go.Figure(
                data=go.Heatmap(
                    z=z,
                    x=metrics,
                    y=strategies,
                    colorscale="RdYlGn",
                    showscale=True,
                )
            )
            fig.update_layout(title=title, template="plotly_dark")
            return {"type": "plotly", "figure": fig, "html": fig.to_html(full_html=False)}
        except ImportError:
            import matplotlib.pyplot as plt
            import numpy as np

            fig, ax = plt.subplots(figsize=(8, max(4, len(strategies) * 0.5)))
            im = ax.imshow(z, aspect="auto", cmap="RdYlGn")
            ax.set_xticks(range(len(metrics)))
            ax.set_xticklabels(metrics)
            ax.set_yticks(range(len(strategies)))
            ax.set_yticklabels(strategies)
            ax.set_title(title)
            plt.colorbar(im, ax=ax)
            fig.tight_layout()
            return {"type": "matplotlib", "figure": fig, "html": None}
