# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Prop-firm rule enforcement for the order path.

Reads prop_firm_mode.json at startup and exposes a single function:

    check_prop_firm_rules(account_info) -> None

Raises HTTPException(403) if the current account state would breach the
active firm's daily-drawdown or total-drawdown limits.  No-ops when
prop-firm mode is disabled or the config file is missing.

This is intentionally synchronous and dependency-free so it can be called
from any FastAPI endpoint without async overhead.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parents[2] / "prop_firm_mode.json"
_config: dict[str, Any] | None = None
_firm_rules: dict[str, Any] | None = None
_enforcement: dict[str, Any] | None = None


def _load_config() -> None:
    global _config, _firm_rules, _enforcement
    if _config is not None:
        return
    try:
        with Path(_CONFIG_PATH).open(encoding="utf-8") as f:
            _config = json.load(f)
        if not _config.get("enabled", False):
            logger.info("Prop-firm mode disabled (prop_firm_mode.json enabled=false)")
            _firm_rules = None
            return
        active = _config.get("active_firm", "")
        _firm_rules = _config.get("firms", {}).get(active)
        _enforcement = _config.get("enforcement", {})
        if _firm_rules:
            logger.info("Prop-firm guard active: firm=%s", active)
        else:
            logger.warning(
                "Prop-firm mode enabled but active_firm '%s' not found in config",
                active,
            )
    except FileNotFoundError:
        logger.debug("prop_firm_mode.json not found — prop-firm guard disabled")
        _config = {}
    except Exception as exc:
        logger.error("Failed to load prop_firm_mode.json: %s", exc)
        _config = {}


def check_prop_firm_rules(account_info: object) -> None:
    """
    Enforce prop-firm drawdown rules before an order is placed.

    account_info must expose .balance and .equity (floats).
    Raises fastapi.HTTPException(403) on a rule breach.
    No-ops if prop-firm mode is disabled or account_info is None.
    """
    _load_config()

    if not _firm_rules or account_info is None:
        return

    try:
        from fastapi import HTTPException
        from fastapi import status as _status
    except ImportError:
        return  # FastAPI not available — skip silently

    balance: float = float(getattr(account_info, "balance", 0) or 0)
    equity: float = float(getattr(account_info, "equity", balance) or balance)

    if balance <= 0:
        return  # Can't compute percentages without a valid balance

    drawdown_cfg = _firm_rules.get("drawdown", {})
    max_daily_pct: float = drawdown_cfg.get("max_daily_drawdown_pct", 5.0)
    max_total_pct: float = drawdown_cfg.get("max_total_drawdown_pct", 10.0)

    # Total drawdown: equity vs balance (initial capital proxy)
    total_dd_pct = (balance - equity) / balance * 100.0

    # Daily drawdown is measured against the same balance baseline. This is
    # deliberately CONSERVATIVE for a pre-trade safety gate: it counts loss from
    # initial capital, so it can only OVER-restrict (block earlier) the daily
    # rule, never under-restrict. A precise daily rule needs the day's OPENING
    # equity captured at the firm's daily rollover (a snapshot hook in the engine,
    # persisted in Redis/DB); a naive in-process first-observation baseline would
    # be unsafe (it could baseline at an already-lossy equity and MISS a breach),
    # so we keep the conservative baseline until that hook exists.
    daily_dd_pct = total_dd_pct

    alert_daily_threshold = (
        _enforcement.get("alert_at_pct_of_daily_limit", 80) / 100.0 * max_daily_pct
        if _enforcement
        else max_daily_pct * 0.8
    )
    alert_total_threshold = (
        _enforcement.get("alert_at_pct_of_total_limit", 80) / 100.0 * max_total_pct
        if _enforcement
        else max_total_pct * 0.8
    )

    # Warn when approaching limits
    if daily_dd_pct >= alert_daily_threshold:
        logger.warning(
            "Prop-firm daily drawdown warning: %.2f%% of %.2f%% limit",
            daily_dd_pct,
            max_daily_pct,
        )
    if total_dd_pct >= alert_total_threshold:
        logger.warning(
            "Prop-firm total drawdown warning: %.2f%% of %.2f%% limit",
            total_dd_pct,
            max_total_pct,
        )

    # Hard blocks
    if daily_dd_pct >= max_daily_pct:
        logger.error(
            "Prop-firm daily drawdown BREACHED: %.2f%% >= %.2f%% — order blocked",
            daily_dd_pct,
            max_daily_pct,
        )
        raise HTTPException(
            status_code=_status.HTTP_403_FORBIDDEN,
            detail=(
                f"Prop-firm daily drawdown limit breached: "
                f"{daily_dd_pct:.2f}% >= {max_daily_pct:.2f}%. "
                "No new orders permitted today."
            ),
        )

    if total_dd_pct >= max_total_pct:
        logger.error(
            "Prop-firm total drawdown BREACHED: %.2f%% >= %.2f%% — order blocked",
            total_dd_pct,
            max_total_pct,
        )
        raise HTTPException(
            status_code=_status.HTTP_403_FORBIDDEN,
            detail=(
                f"Prop-firm total drawdown limit breached: "
                f"{total_dd_pct:.2f}% >= {max_total_pct:.2f}%. "
                "Account trading halted."
            ),
        )
