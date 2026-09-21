# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Research & Intelligence — the first department, and the read-only one.

Spec §4 Cluster A. Implemented before the other three because all four of its
actions move no money: a backtest, a regime read, a news fetch and a
walk-forward validation are all questions, not instructions. That makes it the
safe way to prove the whole path — permission tier, scope gate, handler, audit —
before Markets & Execution, whose `place_order` is the one action in Cluster A
that can lose money.

**Every handler delegates to code that already exists.** A handler that computes
a plausible-looking number itself would be the defect this audit keeps finding:
an answer nobody measured. Where the underlying call is unavailable — a missing
dependency, an unconfigured feed, a symbol nothing knows — the handler returns
`available: False` and the reason. It never returns a number it did not get.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    """The honest answer when the real call could not be made.

    Deliberately shaped so a caller cannot mistake it for a result: there is no
    score, no equity curve and no headline in it. `available` is the first thing
    a reader sees, and every consumer has to pass it before reaching anything.
    """
    return {"available": False, "reason": reason, **extra}


def score_regime(*, symbol: str = "XAUUSD", **_: Any) -> dict[str, Any]:
    """The current market regime for `symbol`, as the router already computes it."""
    try:
        from core.regime_router import get_current_regime
    except Exception as exc:
        return _unavailable(f"regime_router_unavailable: {exc}", symbol=symbol)

    try:
        regime = get_current_regime(symbol)
    except Exception as exc:
        logger.warning("research.score_regime: %s failed (%s)", symbol, exc)
        return _unavailable(f"regime_lookup_failed: {exc}", symbol=symbol)

    if not regime:
        # No regime for this symbol is a real answer, and a different one from
        # "the lookup broke". Kept distinct so an operator can tell them apart.
        return _unavailable("no_regime_for_symbol", symbol=symbol)
    return {"available": True, "symbol": symbol, "regime": regime}


def fetch_market_news(*, days_ahead: int = 7, **_: Any) -> dict[str, Any]:
    """Upcoming economic events, from the calendar the platform already builds."""
    try:
        from news.economic_calendar import fetch_live_calendar
    except Exception as exc:
        return _unavailable(f"calendar_unavailable: {exc}")

    try:
        calendar = fetch_live_calendar(days_ahead=days_ahead)
    except Exception as exc:
        logger.warning("research.fetch_market_news: calendar fetch failed (%s)", exc)
        return _unavailable(f"calendar_fetch_failed: {exc}", days_ahead=days_ahead)

    events = list(getattr(calendar, "events", []) or [])
    return {
        "available": True,
        "days_ahead": days_ahead,
        "event_count": len(events),
        # Titles only. A tool answer is fed to a model, and the whole calendar
        # object is both larger than the question and full of fields the model
        # has no use for.
        "events": [str(getattr(e, "title", "") or "") for e in events[:25]],
    }


def run_backtest(*, strategy: str = "", symbol: str = "XAUUSD", **kwargs: Any) -> dict[str, Any]:
    """Run a backtest through `backtesting/`, the canonical package.

    Refuses without a strategy name rather than picking one: a backtest of
    something the caller did not ask for is a result they will read as theirs.
    """
    if not strategy.strip():
        return _unavailable("strategy_required", symbol=symbol)

    try:
        from backtesting.cli_runner import run_backtest as _run
    except Exception as exc:
        return _unavailable(f"backtesting_unavailable: {exc}", strategy=strategy)

    try:
        report = _run(strategy=strategy, symbol=symbol, **kwargs)
    except TypeError as exc:
        # A signature this handler does not match is a wiring fault, not a
        # backtest result. Saying so beats passing whatever it accepted.
        return _unavailable(f"backtest_signature_mismatch: {exc}", strategy=strategy)
    except Exception as exc:
        logger.warning("research.run_backtest: %s on %s failed (%s)", strategy, symbol, exc)
        return _unavailable(f"backtest_failed: {exc}", strategy=strategy, symbol=symbol)

    return {"available": True, "strategy": strategy, "symbol": symbol, "report": report}


def walk_forward_validate(*, symbol: str = "XAUUSD", **_: Any) -> dict[str, Any]:
    """Out-of-sample validation, from the ML package that owns it.

    Reports `available: False` when the walk-forward tooling is not installed in
    this deployment, which is the common case for an API-only container.
    """
    try:
        from ml.walk_forward import run_walk_forward  # type: ignore[attr-defined]
    except Exception as exc:
        return _unavailable(f"walk_forward_unavailable: {exc}", symbol=symbol)

    try:
        result = run_walk_forward(symbol=symbol)
    except Exception as exc:
        logger.warning("research.walk_forward_validate: %s failed (%s)", symbol, exc)
        return _unavailable(f"walk_forward_failed: {exc}", symbol=symbol)
    return {"available": True, "symbol": symbol, "result": result}


__all__ = ["fetch_market_news", "run_backtest", "score_regime", "walk_forward_validate"]
