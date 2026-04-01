# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk/margin_stress.py
======================
Cross-broker margin stress simulation.

Simulates margin calls across multiple broker accounts simultaneously
under adverse market scenarios. Tests systemic resilience when positions
span multiple brokers with different margin regimes.

Scenarios:
  - Simultaneous gold flash crash (-5%, -10%, -20%)
  - Cross-broker contagion (forced liquidation cascade)
  - Margin regime changes (broker increases requirement mid-position)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BrokerAccount:
    """Represents a single broker account."""
    name: str
    equity: float
    """Available equity in USD."""
    positions: dict[str, float]
    """Symbol → notional position value in USD."""
    initial_margin_pct: float = 0.02
    """Initial margin requirement as fraction (e.g. 0.02 = 2%)."""
    maintenance_margin_pct: float = 0.01
    """Maintenance margin (below which margin call triggers)."""
    max_leverage: float = 50.0
    """Maximum allowed leverage."""


@dataclass
class MarginStressResult:
    """Result for a single stress scenario."""
    scenario_name: str
    shock_pct: float
    broker_results: list[dict[str, Any]]
    """Per-broker result dicts."""
    total_equity_before: float
    total_equity_after: float
    equity_loss_pct: float
    n_margin_calls: int
    n_forced_liquidations: int
    systemic_failure: bool
    """True if >50% of accounts receive margin calls."""


class MarginStressSimulator:
    """
    Simulates cross-broker margin stress for gold/FX positions.

    Models simultaneous adverse price moves across all broker accounts
    and identifies which accounts face margin calls or forced liquidation.
    """

    SCENARIOS: list[dict[str, Any]] = [
        {"name": "gold_flash_-5pct",  "gold_shock": -0.05,  "dxy_shock": +0.01},
        {"name": "gold_flash_-10pct", "gold_shock": -0.10,  "dxy_shock": +0.02},
        {"name": "gold_crash_-20pct", "gold_shock": -0.20,  "dxy_shock": +0.04},
        {"name": "gold_spike_+5pct",  "gold_shock": +0.05,  "dxy_shock": -0.01},
        {"name": "margin_hike_x2",    "gold_shock": -0.03,  "dxy_shock": +0.01,
         "margin_multiplier": 2.0},
        {"name": "liquidity_crunch",  "gold_shock": -0.08,  "dxy_shock": +0.03,
         "spread_multiplier": 5.0},
    ]

    def run_scenario(
        self,
        accounts: list[BrokerAccount],
        scenario: dict[str, Any],
    ) -> MarginStressResult:
        """
        Apply a single stress scenario to all broker accounts.

        Returns MarginStressResult with per-account outcomes.
        """
        gold_shock = float(scenario.get("gold_shock", 0.0))
        dxy_shock = float(scenario.get("dxy_shock", 0.0))
        margin_mult = float(scenario.get("margin_multiplier", 1.0))
        spread_mult = float(scenario.get("spread_multiplier", 1.0))

        total_before = sum(a.equity for a in accounts)
        broker_results = []
        n_calls = 0
        n_liq = 0

        for account in accounts:
            pos_total = sum(account.positions.values())
            # Gold positions lose (gold_shock) on notional
            pnl = pos_total * gold_shock

            equity_after = account.equity + pnl

            # Adjusted margin requirements
            eff_maint_pct = account.maintenance_margin_pct * margin_mult
            eff_init_pct = account.initial_margin_pct * margin_mult

            # Spread cost on forced liquidation
            spread_cost = pos_total * 0.0005 * spread_mult  # base spread 5bp

            margin_required = pos_total * eff_maint_pct
            margin_call = equity_after < margin_required

            if margin_call:
                n_calls += 1
                # Forced liquidation: sell all positions at wider spread
                liquidation_pnl = -(spread_cost + abs(pnl * 0.1))  # slippage
                equity_after = max(0.0, equity_after - spread_cost + liquidation_pnl)
                n_liq += 1

            broker_results.append({
                "broker": account.name,
                "equity_before": account.equity,
                "equity_after": equity_after,
                "pnl": pnl,
                "margin_call": margin_call,
                "forced_liquidation": margin_call,
                "margin_required": margin_required,
                "positions_notional": pos_total,
            })

        total_after = sum(r["equity_after"] for r in broker_results)
        equity_loss_pct = (
            (total_before - total_after) / total_before
            if total_before > 0
            else 0.0
        )

        return MarginStressResult(
            scenario_name=str(scenario.get("name", "unknown")),
            shock_pct=gold_shock,
            broker_results=broker_results,
            total_equity_before=total_before,
            total_equity_after=total_after,
            equity_loss_pct=equity_loss_pct,
            n_margin_calls=n_calls,
            n_forced_liquidations=n_liq,
            systemic_failure=n_calls > len(accounts) / 2,
        )

    def run_all(
        self,
        accounts: list[BrokerAccount],
    ) -> list[MarginStressResult]:
        """Run all predefined scenarios. Returns sorted by equity loss (worst first)."""
        results = [self.run_scenario(accounts, s) for s in self.SCENARIOS]
        return sorted(results, key=lambda r: r.equity_loss_pct, reverse=True)

    def worst_case(self, accounts: list[BrokerAccount]) -> MarginStressResult:
        """Return the worst-case scenario result."""
        results = self.run_all(accounts)
        return results[0] if results else self.run_scenario(
            accounts, self.SCENARIOS[0]
        )

    def summary(self, results: list[MarginStressResult]) -> dict[str, Any]:
        """Serialisable summary for API response."""
        return {
            "scenarios_run": len(results),
            "worst_equity_loss_pct": results[0].equity_loss_pct if results else 0.0,
            "systemic_failures": sum(1 for r in results if r.systemic_failure),
            "scenarios": [
                {
                    "name": r.scenario_name,
                    "equity_loss_pct": r.equity_loss_pct,
                    "n_margin_calls": r.n_margin_calls,
                    "systemic_failure": r.systemic_failure,
                }
                for r in results
            ],
        }


margin_stress_simulator = MarginStressSimulator()
