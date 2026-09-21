# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/safety_config_report.py
============================
One place that answers: **which safety gates is this process actually running
with?**

The codebase reads ~1,078 distinct environment variables. 255 are read but
undocumented and 134 are documented but read nowhere, so no operator — and no
log line — could previously answer that question. Several Round 3 audit
findings were invisible in production for exactly this reason: a gate wired to
state nothing writes, or a blocking mode left at its warn-only default, looks
identical in the logs to a gate that is passing legitimately.

This module resolves the ~20 flags that decide whether the system will refuse a
trade, and emits them once at startup and via ``/api/health/detailed``.

See docs/HARDENING_BACKLOG.md S11-03.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SafetyFlag:
    """One safety-critical setting and how to read it."""

    name: str
    env_var: str
    default: str
    #: Value(s) that mean "this gate is NOT protecting you".
    unsafe_when: tuple[str, ...] = ()
    note: str = ""

    def resolved(self) -> str:
        return os.getenv(self.env_var, self.default)

    @property
    def is_unsafe(self) -> bool:
        return self.resolved().strip().lower() in {v.lower() for v in self.unsafe_when}


# Ordered roughly by blast radius: what stops a bad trade, then what stops a
# bad model, then what stops bad data.
SAFETY_FLAGS: tuple[SafetyFlag, ...] = (
    SafetyFlag(
        "kill switch (env override)",
        "HOPEFX_KILL_SWITCH",
        "0",
        note="1 = all trading halted at startup",
    ),
    SafetyFlag(
        "live trading",
        "LIVE_TRADING_ENABLED",
        "false",
        note="false = paper only",
    ),
    SafetyFlag(
        "paper trading",
        "PAPER_TRADING",
        "true",
        unsafe_when=("false", "0"),
        note="false = real orders reach the broker",
    ),
    SafetyFlag(
        "broker",
        "BROKER_TYPE",
        "paper",
        note="paper | oanda | mt5 | …",
    ),
    SafetyFlag(
        "paper fallback",
        "FALLBACK_TO_PAPER",
        "false",
        unsafe_when=("true", "1", "yes"),
        note="true = silently trades on paper if the real broker is down",
    ),
    SafetyFlag(
        "invariant mode",
        "HOPEFX_INVARIANT_MODE",
        "monitor",
        unsafe_when=("off",),
        note="monitor = log only; enforce = block",
    ),
    SafetyFlag(
        "stale-model block",
        "STALE_MODEL_BLOCK",
        "true",
        unsafe_when=("false", "0"),
        note="false = trade on a stale model",
    ),
    SafetyFlag(
        "drift block",
        "DRIFT_BLOCK",
        "false",
        unsafe_when=("false", "0"),
        note="false = warn on feature drift but keep trading",
    ),
    SafetyFlag("max drawdown pct", "RISK_MAX_DRAWDOWN_PCT", "0.10"),
    SafetyFlag("max daily loss pct", "RISK_MAX_DAILY_LOSS_PCT", "0.05"),
    SafetyFlag("max open positions", "RISK_MAX_OPEN_POSITIONS", "3"),
    SafetyFlag("max position pct", "RISK_MAX_POSITION_PCT", "0.05"),
    SafetyFlag("max risk per trade", "MAX_RISK_PCT_PER_TRADE", "0.01"),
    SafetyFlag("drawdown halt pct", "DRAWDOWN_HALT_PCT", "0.05"),
    SafetyFlag("max tick staleness (s)", "RISK_MAX_TICK_STALENESS_S", "5.0"),
    SafetyFlag("tick stale threshold (s)", "DQE_STALE_THRESHOLD_S", "30.0"),
    SafetyFlag("SL/TP max tick age (s)", "SLTP_MAX_TICK_AGE_S", "5"),
    SafetyFlag("min data quality", "RISK_MIN_DATA_QUALITY", "0.40"),
    SafetyFlag("max spread (USD)", "GATEKEEPER_MAX_SPREAD_USD", "2.00"),
    SafetyFlag(
        "WS auth required",
        "WS_AUTH_REQUIRED",
        "true",
        unsafe_when=("false", "0"),
        note="false = unauthenticated WebSocket clients",
    ),
    SafetyFlag("WS send timeout (s)", "WS_SEND_TIMEOUT_S", "2.0"),
)


def resolve_safety_config() -> dict[str, Any]:
    """Return every safety flag with its resolved value and safety verdict."""
    flags = [
        {
            "name": f.name,
            "env_var": f.env_var,
            "value": f.resolved(),
            "is_default": os.getenv(f.env_var) is None,
            "unsafe": f.is_unsafe,
            "note": f.note,
        }
        for f in SAFETY_FLAGS
    ]
    return {
        "flags": flags,
        "unsafe_count": sum(1 for f in flags if f["unsafe"]),
        "explicit_count": sum(1 for f in flags if not f["is_default"]),
        "total": len(flags),
    }


def log_safety_config() -> dict[str, Any]:
    """Log the resolved safety configuration once, at startup.

    Anything marked unsafe is logged at WARNING so it is visible without
    grepping — the point is that "which gates are live?" should never again
    require reading the source.
    """
    report = resolve_safety_config()

    logger.info(
        "── SAFETY CONFIG ── %d flags (%d set explicitly, %d not protecting)",
        report["total"],
        report["explicit_count"],
        report["unsafe_count"],
    )
    for f in report["flags"]:
        origin = "env" if not f["is_default"] else "default"
        note = f"  — {f['note']}" if f["note"] else ""
        line = f"  {f['name']:<26} {f['value']:<12} ({origin}){note}"
        if f["unsafe"]:
            logger.warning("%s  ** NOT PROTECTING **", line)
        else:
            logger.info(line)

    if report["unsafe_count"]:
        logger.warning(
            "SAFETY CONFIG: %d gate(s) are configured NOT to protect. Confirm this is deliberate before trading live.",
            report["unsafe_count"],
        )
    return report
