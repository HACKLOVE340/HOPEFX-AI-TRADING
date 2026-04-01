# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/stress_test.py
===================
Historical and hypothetical stress scenarios for XAUUSD / gold portfolios.

Scenarios are drawn from documented market events and applied as instantaneous
shocks to a position's mark-to-market value.  Results feed into the pre-trade
gate and the /api/risk/stress endpoint.

Usage
-----
    from risk.stress_test import StressTester, run_all_scenarios

    tester = StressTester(position_value=50_000, leverage=1.0)
    results = tester.run_all()
    worst = tester.worst_case(results)
    print(f"Worst scenario: {worst.name} → loss ${worst.pnl_usd:,.0f}")

    # Gate: block trade if any scenario exceeds max_loss_pct of equity
    gate_ok = tester.gate_check(results, equity=100_000, max_loss_pct=0.20)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── Scenario definitions ──────────────────────────────────────────────────────


@dataclass
class StressScenario:
    """A single stress scenario definition."""

    name: str
    description: str
    gold_shock_pct: float  # % change in gold price (negative = drop)
    dxy_shock_pct: float = 0.0  # % change in DXY (informational)
    vix_shock_pct: float = 0.0  # % change in VIX (informational)
    source: str = ""  # historical reference


# Historical and hypothetical scenarios calibrated to XAUUSD
SCENARIOS: list[StressScenario] = [
    StressScenario(
        name="COVID_CRASH_2020",
        description="Gold flash crash March 2020 — forced liquidations, margin calls",
        gold_shock_pct=-12.5,
        dxy_shock_pct=+8.0,
        vix_shock_pct=+300.0,
        source="March 16–18 2020: XAU/USD fell from ~$1,680 to ~$1,470",
    ),
    StressScenario(
        name="RATE_SHOCK_2022",
        description="Fed 75bp hike cycle — gold bear market 2022",
        gold_shock_pct=-20.0,
        dxy_shock_pct=+15.0,
        vix_shock_pct=+60.0,
        source="Mar–Sep 2022: XAU/USD fell from ~$2,050 to ~$1,620",
    ),
    StressScenario(
        name="TAPER_TANTRUM_2013",
        description="Bernanke taper announcement — gold crash",
        gold_shock_pct=-28.0,
        dxy_shock_pct=+5.0,
        vix_shock_pct=+40.0,
        source="Apr–Jun 2013: XAU/USD fell from ~$1,580 to ~$1,180",
    ),
    StressScenario(
        name="FLASH_CRASH_2021",
        description="Gold flash crash August 2021 — thin liquidity Sunday open",
        gold_shock_pct=-4.5,
        dxy_shock_pct=+0.5,
        vix_shock_pct=+10.0,
        source="Aug 9 2021: XAU/USD dropped ~$100 in minutes at Asia open",
    ),
    StressScenario(
        name="GFC_2008",
        description="Global Financial Crisis — gold initially sold for margin",
        gold_shock_pct=-30.0,
        dxy_shock_pct=+20.0,
        vix_shock_pct=+500.0,
        source="Sep–Oct 2008: XAU/USD fell from ~$920 to ~$680",
    ),
    StressScenario(
        name="GEOPOLITICAL_SPIKE",
        description="Hypothetical geopolitical shock — gold spike then reversal",
        gold_shock_pct=+15.0,
        dxy_shock_pct=-5.0,
        vix_shock_pct=+80.0,
        source="Hypothetical: rapid +15% spike followed by mean reversion",
    ),
    StressScenario(
        name="DOLLAR_SURGE",
        description="Hypothetical USD surge — gold drops on DXY strength",
        gold_shock_pct=-8.0,
        dxy_shock_pct=+10.0,
        vix_shock_pct=+20.0,
        source="Hypothetical: DXY +10% in 30 days",
    ),
    StressScenario(
        name="OVERNIGHT_GAP",
        description="Worst-case overnight gap — weekend geopolitical event",
        gold_shock_pct=-6.0,
        dxy_shock_pct=+3.0,
        vix_shock_pct=+50.0,
        source="Hypothetical: Sunday open gap based on 99th percentile gap distribution",
    ),
]


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class StressResult:
    """Result of applying one scenario to a position."""

    scenario: StressScenario
    position_value: float  # USD value before shock
    pnl_usd: float  # USD P&L after shock (negative = loss)
    pnl_pct: float  # P&L as % of position value
    equity_impact_pct: float  # P&L as % of total equity
    breaches_gate: bool  # True if loss exceeds max_loss_pct of equity

    @property
    def name(self) -> str:
        return self.scenario.name

    @property
    def is_loss(self) -> bool:
        return self.pnl_usd < 0


# ── Stress tester ─────────────────────────────────────────────────────────────


class StressTester:
    """
    Apply stress scenarios to a single position.

    Parameters
    ----------
    position_value : Current mark-to-market value of the position in USD.
    leverage       : Leverage multiplier (1.0 = no leverage).
    equity         : Total account equity in USD (used for gate checks).
    max_loss_pct   : Maximum tolerable loss as a fraction of equity (default 0.20).
    """

    def __init__(
        self,
        position_value: float,
        leverage: float = 1.0,
        equity: float | None = None,
        max_loss_pct: float = 0.20,
        scenarios: list[StressScenario] | None = None,
    ) -> None:
        if position_value < 0:
            raise ValueError("position_value must be >= 0")
        if leverage <= 0:
            raise ValueError("leverage must be > 0")
        self.position_value = position_value
        self.leverage = leverage
        self.equity = equity or position_value
        self.max_loss_pct = max_loss_pct
        self.scenarios = scenarios or SCENARIOS

    def _apply(self, scenario: StressScenario) -> StressResult:
        """Apply a single scenario shock and return the result."""
        shock = scenario.gold_shock_pct / 100.0
        pnl_usd = self.position_value * shock * self.leverage
        pnl_pct = shock * self.leverage
        equity_impact_pct = pnl_usd / self.equity if self.equity > 0 else 0.0
        breaches_gate = abs(equity_impact_pct) > self.max_loss_pct and pnl_usd < 0
        return StressResult(
            scenario=scenario,
            position_value=self.position_value,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            equity_impact_pct=equity_impact_pct,
            breaches_gate=breaches_gate,
        )

    def run_all(self) -> list[StressResult]:
        """Run all scenarios and return results sorted by P&L (worst first)."""
        results = [self._apply(s) for s in self.scenarios]
        results.sort(key=lambda r: r.pnl_usd)
        logger.debug(
            "StressTester: ran %d scenarios on position_value=%.0f leverage=%.1fx",
            len(results),
            self.position_value,
            self.leverage,
        )
        return results

    def worst_case(self, results: list[StressResult] | None = None) -> StressResult:
        """Return the scenario with the largest USD loss."""
        r = results or self.run_all()
        return min(r, key=lambda x: x.pnl_usd)

    def gate_check(
        self,
        results: list[StressResult] | None = None,
        equity: float | None = None,
        max_loss_pct: float | None = None,
    ) -> bool:
        """
        Return True if all scenarios pass (no scenario breaches the loss gate).

        Parameters
        ----------
        results      : Pre-computed results (runs all scenarios if None).
        equity       : Override equity for this check.
        max_loss_pct : Override max_loss_pct for this check.
        """
        r = results or self.run_all()
        _equity = equity or self.equity
        _max = max_loss_pct or self.max_loss_pct

        breaching = [res for res in r if res.pnl_usd < 0 and abs(res.pnl_usd / _equity) > _max]
        if breaching:
            logger.warning(
                "StressTester gate FAILED: %d scenario(s) breach %.0f%% equity loss limit: %s",
                len(breaching),
                _max * 100,
                [b.name for b in breaching],
            )
            return False
        return True

    def summary(self, results: list[StressResult] | None = None) -> dict:
        """Return a JSON-serialisable summary of all scenario results."""
        r = results or self.run_all()
        return {
            "position_value": self.position_value,
            "leverage": self.leverage,
            "equity": self.equity,
            "max_loss_pct": self.max_loss_pct,
            "scenarios_run": len(r),
            "gate_passed": self.gate_check(r),
            "worst_case": {
                "name": self.worst_case(r).name,
                "pnl_usd": round(self.worst_case(r).pnl_usd, 2),
                "equity_impact_pct": round(self.worst_case(r).equity_impact_pct * 100, 2),
            },
            "results": [
                {
                    "name": res.name,
                    "description": res.scenario.description,
                    "gold_shock_pct": res.scenario.gold_shock_pct,
                    "pnl_usd": round(res.pnl_usd, 2),
                    "pnl_pct": round(res.pnl_pct * 100, 2),
                    "equity_impact_pct": round(res.equity_impact_pct * 100, 2),
                    "breaches_gate": res.breaches_gate,
                }
                for res in r
            ],
        }


# ── Convenience function ──────────────────────────────────────────────────────


def run_all_scenarios(
    position_value: float,
    equity: float,
    leverage: float = 1.0,
    max_loss_pct: float = 0.20,
) -> dict:
    """
    Run all stress scenarios and return a summary dict.

    Convenience wrapper for the /api/risk/stress endpoint.
    """
    tester = StressTester(
        position_value=position_value,
        leverage=leverage,
        equity=equity,
        max_loss_pct=max_loss_pct,
    )
    return tester.summary()
