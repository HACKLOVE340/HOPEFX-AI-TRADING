# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/live_trading_gate.py
=========================
Production live trading gate — single authoritative check before any live order.

Gate checks (all must pass)
---------------------------
1. Kill-switch       — KillSwitch.is_active() must be False
2. Paper clock       — 30-day OANDA paper run must be complete
3. OOS accuracy      — advanced_oos_meta.json accuracy >= 0.60, p-value < 0.05
4. Sharpe SE         — N >= 600 trades OR multi_symbol_report.json gate_passed
5. Feature flag      — FEATURE_LIVE_TRADING=true must be set

Any failing check blocks the order and fires a Sentry alert.
All checks degrade gracefully — if a component is unavailable the gate
defaults to BLOCKED (fail-safe).

Usage
-----
    from core.live_trading_gate import LiveTradingGate, get_gate

    gate = get_gate()
    result = gate.check()
    if not result.allowed:
        raise OrderBlockedError(result.reason)

    # Or as a decorator:
    @gate.require_open
    def place_live_order(symbol, units):
        ...

Environment variables
---------------------
FEATURE_LIVE_TRADING=true   — master switch (default: false)
LIVE_GATE_OOS_MIN_ACC=0.60  — minimum OOS accuracy (default: 0.60)
LIVE_GATE_OOS_MAX_PVAL=0.05 — maximum OOS p-value (default: 0.05)
LIVE_GATE_MIN_TRADES=600    — minimum pooled trades for Sharpe gate (default: 600)
LIVE_GATE_PAPER_DAYS=30     — minimum paper trading days (default: 30)
"""

from __future__ import annotations

import functools
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent

# ── Gate thresholds (overridable via env) ─────────────────────────────────────
_LIVE_TRADING_ENABLED = os.getenv("FEATURE_LIVE_TRADING", "false").lower() == "true"
_OOS_MIN_ACC = float(os.getenv("LIVE_GATE_OOS_MIN_ACC", "0.60"))
_OOS_MAX_PVAL = float(os.getenv("LIVE_GATE_OOS_MAX_PVAL", "0.05"))
_MIN_TRADES = int(os.getenv("LIVE_GATE_MIN_TRADES", "600"))
_PAPER_DAYS = int(os.getenv("LIVE_GATE_PAPER_DAYS", "30"))


@dataclass
class GateResult:
    """Result of a live trading gate check."""

    allowed: bool
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    reason: str = ""
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "checked_at": self.checked_at,
            "checks": self.checks,
        }


class LiveTradingGate:
    """
    Single authoritative gate for live order placement.

    All five checks must pass. Any failure blocks the order and
    fires the appropriate Sentry alert.
    """

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_kill_switch(self) -> tuple[bool, str]:
        """Check 1: Kill-switch must be inactive."""
        try:
            from kill_switch import KillSwitch

            ks = KillSwitch()
            if ks.is_active():
                return False, f"Kill-switch is ACTIVE: {ks.reason}"
            return True, "Kill-switch inactive"
        except Exception as exc:
            logger.debug("Kill-switch check failed: %s", exc)
            return False, f"Kill-switch check unavailable: {exc}"

    def _check_paper_clock(self) -> tuple[bool, str]:
        """Check 2: 30-day paper trading clock must be complete."""
        try:
            from brokers.oanda_paper_clock import get_clock

            clock = get_clock()
            status = clock.status()
            elapsed = status.get("elapsed_days", 0.0)
            complete = status.get("complete", False)
            if not complete:
                remaining = status.get("remaining_days", _PAPER_DAYS)
                # Fire Sentry alert
                try:
                    from monitoring.sentry_config import capture_paper_clock_alert

                    capture_paper_clock_alert(
                        elapsed_days=elapsed,
                        remaining_days=remaining,
                        environment=status.get("environment", "practice"),
                    )
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
                return False, (
                    f"Paper clock incomplete: {elapsed:.1f}/{_PAPER_DAYS} days elapsed. {remaining:.1f} days remaining."
                )
            return True, f"Paper clock complete: {elapsed:.1f} days elapsed"
        except Exception as exc:
            logger.debug("Paper clock check failed: %s", exc)
            return False, f"Paper clock unavailable: {exc}"

    def _check_oos_accuracy(self) -> tuple[bool, str]:
        """Check 3: OOS accuracy >= threshold and p-value < threshold."""
        meta_paths = [
            ROOT / "ml" / "saved_models" / "advanced_oos_meta.json",
            ROOT / "ml" / "saved_models" / "advanced_training_report.json",
        ]
        for path in meta_paths:
            if not path.exists():
                continue
            try:
                meta = json.loads(path.read_text())
                # Handle nested structure from training report
                oos = meta.get("oos", meta)
                acc = float(oos.get("oos_accuracy", oos.get("accuracy", 0.0)))
                pval = float(oos.get("oos_p_value", oos.get("p_value_binomial", 1.0)))
                n_oos = int(oos.get("oos_n", oos.get("oos_size", 0)))

                if acc < _OOS_MIN_ACC:
                    return False, (
                        f"OOS accuracy {acc:.3f} < threshold {_OOS_MIN_ACC:.3f} "
                        f"(n={n_oos}). Retrain: python ml/train_advanced.py --years 50 --oos-years 3"
                    )
                if pval >= _OOS_MAX_PVAL:
                    return False, (
                        f"OOS p-value {pval:.4f} >= threshold {_OOS_MAX_PVAL:.4f} "
                        f"(not statistically significant). n={n_oos}"
                    )
                return (
                    True,
                    f"OOS accuracy {acc:.3f} (p={pval:.4f}, n={n_oos}) — gate passed",
                )
            except Exception as exc:
                logger.debug("OOS meta read failed for %s: %s", path, exc)
                continue

        return False, ("OOS metadata not found. Run: python ml/train_advanced.py --years 50 --oos-years 3")

    def _check_sharpe_gate(self) -> tuple[bool, str]:
        """Check 4: N >= 600 pooled trades with SE <= 0.10 (Sharpe SE gate).

        Resolution order:
          1. backtest/results/multi_symbol_report.json  (live backtest output)
          2. advanced_oos_meta.json sharpe_gate_authoritative  (pre-computed, authoritative)
          3. advanced_oos_meta.json multi_symbol_backtest_extended  (7-symbol extended run)
          4. advanced_oos_meta.json sharpe_gate  (OOS bar count, last resort)

        The 3-symbol multi_symbol_backtest block (N=628, SE=0.121) is intentionally
        NOT used — it did not satisfy the SE<=0.10 requirement and its
        sharpe_gate_passed flag was historically incorrect.
        """
        # ── 1. Live backtest report ───────────────────────────────────────────
        report_path = ROOT / "backtest" / "results" / "multi_symbol_report.json"
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text())
                pooled = report.get("pooled")
                if not pooled or not isinstance(pooled, dict):
                    logger.warning(
                        "Sharpe gate: multi_symbol_report.json has no 'pooled' "
                        "metrics section — treating as gate-blocked"
                    )
                    try:
                        from monitoring.sentry_config import capture_sharpe_gate_alert

                        capture_sharpe_gate_alert(n_trades=0, sharpe=0.0, se=999.0)
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)
                    return False, (
                        "Sharpe gate BLOCKED: multi_symbol_report.json exists but "
                        "contains no 'pooled' metrics. "
                        "Re-run: python backtest/multi_symbol_backtest.py --years 10"
                    )
                n_total = int(pooled.get("n_total_trades", 0))
                gate_passed = bool(pooled.get("sharpe_gate_passed", False))
                se = float(pooled.get("pooled_sharpe_se", 999.0))
                sharpe = float(pooled.get("pooled_sharpe", 0.0))
                if not gate_passed:
                    try:
                        from monitoring.sentry_config import capture_sharpe_gate_alert

                        capture_sharpe_gate_alert(n_trades=n_total, sharpe=sharpe, se=se)
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)
                    return False, (
                        f"Sharpe gate BLOCKED: N={n_total} trades, SE={se:.3f}. "
                        f"Need N>={_MIN_TRADES}. "
                        "Run: python backtest/multi_symbol_backtest.py --years 10"
                    )
                return True, f"Sharpe gate passed: N={n_total} trades, SE={se:.3f}"
            except Exception as exc:
                logger.debug("Sharpe gate report read failed: %s", exc)

        # ── 2–4. OOS meta fallback ────────────────────────────────────────────
        meta_path = ROOT / "ml" / "saved_models" / "advanced_oos_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())

                # 2. Top-level authoritative field (set by fix script / training)
                auth = meta.get("sharpe_gate_authoritative")
                if auth and isinstance(auth, dict):
                    gate_passed = bool(auth.get("gate_passed", False))
                    n = int(auth.get("pooled_n_trades", 0))
                    se = float(auth.get("pooled_sharpe_se", 999.0))
                    msg = auth.get("message", "")
                    if gate_passed:
                        return True, f"Sharpe gate passed (authoritative): N={n}, SE={se:.3f}. {msg}"
                    return False, f"Sharpe gate BLOCKED (authoritative): {msg}"

                # 3. Extended 7-symbol backtest block
                mse = meta.get("multi_symbol_backtest_extended", {})
                if mse and isinstance(mse, dict):
                    gate_passed = bool(mse.get("sharpe_gate_passed", False))
                    n = int(mse.get("pooled_n_trades", 0))
                    se = float(mse.get("pooled_sharpe_se", 999.0))
                    if gate_passed and se <= 0.10:
                        return True, (f"Sharpe gate passed (extended backtest): N={n}, SE={se:.3f}")
                    return False, (f"Sharpe gate BLOCKED (extended backtest): N={n}, SE={se:.3f}. Need SE<=0.10.")

                # 4. OOS bar count from primary sharpe_gate block
                sg = meta.get("sharpe_gate", {})
                n = int(sg.get("n_trades", meta.get("oos_n", 0)))
                gate_passed = bool(sg.get("gate_passed", False))
                se = float(sg.get("se", 999.0))
                if not gate_passed:
                    return False, (
                        f"Sharpe gate BLOCKED: N={n} OOS bars, SE={se:.3f}. "
                        f"Need N>={_MIN_TRADES} trades. Run multi-symbol backtest."
                    )
                return True, f"Sharpe gate passed via OOS meta: N={n}, SE={se:.3f}"
            except Exception as exc:
                logger.debug("OOS meta sharpe gate read failed: %s", exc)

        return False, (
            "Sharpe gate: no backtest report found. Run: python backtest/multi_symbol_backtest.py --years 10"
        )

    def _check_feature_flag(self) -> tuple[bool, str]:
        """Check 5: FEATURE_LIVE_TRADING=true must be set."""
        # Re-read env at check time (allows runtime toggle)
        enabled = os.getenv("FEATURE_LIVE_TRADING", "false").lower() == "true"
        if not enabled:
            return False, (
                "FEATURE_LIVE_TRADING is not set to 'true'. Set this env var only after all other gates pass."
            )
        return True, "FEATURE_LIVE_TRADING=true"

    # ── Master check ──────────────────────────────────────────────────────────

    def check(self) -> GateResult:
        """
        Run all five gate checks. Returns GateResult with allowed=True only
        when every check passes.

        Checks run in order — first failure short-circuits the reason string
        but all checks are still evaluated for the status dict.
        """
        check_fns = [
            ("kill_switch", self._check_kill_switch),
            ("paper_clock", self._check_paper_clock),
            ("oos_accuracy", self._check_oos_accuracy),
            ("sharpe_gate", self._check_sharpe_gate),
            ("feature_flag", self._check_feature_flag),
        ]

        checks: dict[str, dict[str, Any]] = {}
        all_passed = True
        first_failure = ""

        for name, fn in check_fns:
            try:
                passed, msg = fn()
            except Exception as exc:
                passed, msg = False, f"Check error: {exc}"
            checks[name] = {"passed": passed, "message": msg}
            if not passed:
                all_passed = False
                if not first_failure:
                    first_failure = f"[{name}] {msg}"

        return GateResult(
            allowed=all_passed,
            checks=checks,
            reason="" if all_passed else first_failure,
        )

    def require_open(self, fn: Callable) -> Callable:
        """Decorator: raise RuntimeError if gate is not open."""

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = self.check()
            if not result.allowed:
                raise RuntimeError(f"Live trading gate BLOCKED: {result.reason}")
            return fn(*args, **kwargs)

        return wrapper

    def status_dict(self) -> dict[str, Any]:
        """Return gate status as a dict for the /api/status endpoint."""
        result = self.check()
        return result.to_dict()


# ── Module-level singleton ────────────────────────────────────────────────────

_gate: LiveTradingGate | None = None


def get_gate() -> LiveTradingGate:
    """Return the module-level LiveTradingGate singleton."""
    global _gate
    if _gate is None:
        _gate = LiveTradingGate()
    return _gate
