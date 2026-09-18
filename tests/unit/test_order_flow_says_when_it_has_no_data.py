# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Order flow must distinguish "balanced" from "never measured", and have one analyzer.

F147. `analysis/order_flow.py` is 936 lines mounted behind a router at
`/api/orderflow`, and nothing feeds it. Two separate defects follow, both
reproduced before this file was written.

**1. A zero that means "no measurement" is served as a measurement.**
`analyze()` and `get_volume_profile()` already 404 when there is no data — the
honest behaviour, and the convention this router set for itself. The rest do
not:

    GET /{symbol}/delta      -> {"cumulative_delta": 0}
    GET /{symbol}/levels     -> {"support": [], "resistance": [], "poc": None}
    GET /{symbol}/footprint  -> []

A cumulative delta of 0 is what a genuinely balanced tape looks like. So is a
tape nobody is reading. The caller cannot tell, and the audit's own decision
rule is that a zero produced from missing measurement is misleading rather than
neutral.

**2. Two analyzers, and the one that could be fed is the one nobody serves.**
`core/router_registry.py` mounts the module-level `router`, built on
`get_order_flow_analyzer()`'s global. `core/startup_factories.py::init_order_flow`
builds a *second* `OrderFlowAnalyzer()` and mounts its own copy of the same
paths with a plain `include_router` — not the deduped helper. FastAPI resolves
to the first registration, so the startup instance is shadowed. Measured:

    startup instance trades : 2      (after feeding it)
    global  instance trades : 0
    served  /delta          : {"cumulative_delta": 0}
    served  /stats          : {"total_trades": 0, ...}

That is the trap underneath the finding. "Just subscribe it to the tick feed"
looks like a one-line change, and if you wired it to the object
`init_order_flow` returns — the obvious one, since it is the registered startup
service — nothing whatsoever would change, with no error to explain why.
"""

from __future__ import annotations

import inspect  # noqa: F401 — kept for the sibling suite
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analysis.order_flow import (
    OrderFlowAnalyzer,
    create_order_flow_router,
)

pytestmark = pytest.mark.unit

SYMBOL = "XAUUSD"


@pytest.fixture
def analyzer() -> OrderFlowAnalyzer:
    return OrderFlowAnalyzer()


@pytest.fixture
def client(analyzer: OrderFlowAnalyzer) -> TestClient:
    app = FastAPI()
    app.include_router(create_order_flow_router(analyzer))
    return TestClient(app)


def _feed(analyzer: OrderFlowAnalyzer) -> None:
    analyzer.add_trade(SYMBOL, price=2000.0, size=10.0, side="buy")
    analyzer.add_trade(SYMBOL, price=2001.0, size=4.0, side="sell")


# ── An unread tape must not read as a balanced one ────────────────────────────


@pytest.mark.parametrize("endpoint", ["delta", "levels", "footprint"])
def test_an_unfed_symbol_is_reported_as_unmeasured(client: TestClient, endpoint: str):
    """404, the same as /analysis and /profile already do for the same condition.

    Consistency inside one router matters here: two of its six endpoints
    already refuse, so a caller reasonably reads a 200 as "measured".
    """
    r = client.get(f"/api/orderflow/{SYMBOL}/{endpoint}")

    assert r.status_code == 404, (
        f"/{endpoint} returned {r.status_code} with {r.json()!r} for a symbol no tick "
        "has ever been recorded for — indistinguishable from a real, quiet market"
    )


@pytest.mark.parametrize("endpoint", ["analysis", "profile"])
def test_the_endpoints_that_already_refused_still_refuse(client: TestClient, endpoint: str):
    """Regression guard on the behaviour that was already right."""
    assert client.get(f"/api/orderflow/{SYMBOL}/{endpoint}").status_code == 404


@pytest.mark.parametrize("endpoint", ["delta", "levels", "footprint", "analysis", "profile"])
def test_a_fed_symbol_is_served(client: TestClient, analyzer: OrderFlowAnalyzer, endpoint: str):
    """The positive control.

    Without it, every refusal above is satisfied by a router that 404s
    everything — which is exactly as useless as one that returns zeros.
    """
    _feed(analyzer)

    r = client.get(f"/api/orderflow/{SYMBOL}/{endpoint}")
    assert r.status_code == 200, r.text


def test_delta_reports_the_real_imbalance_once_fed(client: TestClient, analyzer: OrderFlowAnalyzer):
    """And the number must be the measured one, not merely non-404."""
    _feed(analyzer)

    body = client.get(f"/api/orderflow/{SYMBOL}/delta").json()
    assert body["cumulative_delta"] == pytest.approx(6.0), body


def test_stats_says_whether_anything_is_feeding_it(client: TestClient, analyzer: OrderFlowAnalyzer):
    """An operator must be able to tell a quiet market from a dead subscription.

    `/stats` is the only non-per-symbol endpoint, and `total_trades: 0` is
    literally true whether the tape is quiet or nothing is subscribed. The
    distinction has to be stated, not inferred.
    """
    before = client.get("/api/orderflow/stats").json()
    assert before["ingesting"] is False, before

    _feed(analyzer)

    after = client.get("/api/orderflow/stats").json()
    assert after["ingesting"] is True, after


# ── One analyzer, not two ─────────────────────────────────────────────────────


def test_the_startup_service_is_the_analyzer_that_serves_requests():
    """Feeding what `init_order_flow` returns must reach the mounted endpoints.

    It did not. `init_order_flow` built its own `OrderFlowAnalyzer()` while the
    router registry mounted one built on the module global, so the startup
    service was shadowed and anything wired to it fed an object no request could
    reach.
    """
    import analysis.order_flow as of
    import core.startup_factories as factories

    app = FastAPI()
    # The registry mounts the module-level router first, as it does in production.
    app.include_router(of.router)

    import asyncio

    service = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(factories.init_order_flow(None, app))

    assert service is of.get_order_flow_analyzer(), (
        "init_order_flow returned an analyzer that is not the one serving "
        "/api/orderflow — feeding it would change nothing, silently"
    )


# ── The dashboard on top of it ────────────────────────────────────────────────
#
# `analysis/order_flow_dashboard.py` reads the same analyzer and has the same
# defect in its worst form. `get_complete_analysis` at least returns nulls, but
# `get_market_bias` synthesises a verdict from nothing:
#
#     {"bias": "neutral", "strength": "weak", "bullish_count": 0, "bearish_count": 0}
#
# "Neutral, weak" is a defensible read of a real tape. It is not the same
# statement as "no tick has ever been ingested", and a trader cannot tell them
# apart.


@pytest.fixture
def dashboard_client():
    from analysis.order_flow import get_order_flow_analyzer
    from analysis.order_flow_dashboard import create_dashboard, create_dashboard_router

    analyzer = get_order_flow_analyzer()
    analyzer.clear_trades(SYMBOL)
    dash = create_dashboard()
    app = FastAPI()
    app.include_router(create_dashboard_router(dash))
    return TestClient(app), analyzer


@pytest.mark.parametrize("endpoint", ["bias", "levels"])
def test_the_dashboard_does_not_invent_a_read_from_no_data(dashboard_client, endpoint):
    """A verdict with no measurement behind it is worse than a zero."""
    client, _analyzer = dashboard_client

    r = client.get(f"/api/dashboard/{SYMBOL}/{endpoint}")

    assert r.status_code == 404, (
        f"/{endpoint} answered {r.status_code} with {r.json()!r} for a symbol with no recorded ticks"
    )


@pytest.mark.parametrize("endpoint", ["bias", "levels"])
def test_the_dashboard_serves_a_fed_symbol(dashboard_client, endpoint):
    """Positive control — the refusal must be about data, not about the route."""
    client, analyzer = dashboard_client
    _feed(analyzer)
    try:
        r = client.get(f"/api/dashboard/{SYMBOL}/{endpoint}")
        assert r.status_code == 200, r.text
    finally:
        analyzer.clear_trades(SYMBOL)


# ── The bias vote ─────────────────────────────────────────────────────────────
#
# `get_summary` and `get_bias` carry 143 of this module's uncovered lines and
# are not routed — nothing serves them over HTTP, and `get_bias` is called only
# from `get_summary`. They are covered here because the coverage gate refuses a
# money-adjacent module below 80% that a commit touches, and because covering
# them is what surfaced the dead voter below.


def _dashboard():
    from analysis.order_flow import get_order_flow_analyzer
    from analysis.order_flow_dashboard import create_dashboard

    get_order_flow_analyzer().clear_trades(SYMBOL)
    return create_dashboard()


def test_the_advanced_bias_voter_can_never_vote():
    """One of three voters calls a method that does not exist.

    `_bias_vote_advanced` calls `self._adv.analyze(symbol)`.
    `AdvancedOrderFlowAnalyzer` has no `analyze` — its surface is
    `get_aggression_metrics`, `get_pressure_gauges`,
    `get_order_flow_oscillator`, `detect_delta_divergence`,
    `get_stacked_imbalances`, `get_volume_clusters` and
    `get_volume_imbalance_by_level`. Every call raises `AttributeError` into a
    handler that logs at WARNING and returns None, so the vote is silently
    absent and the majority is decided by two voters wearing three hats.

    Pinned rather than repaired: choosing which of those methods constitutes a
    bullish or bearish read is a quantitative decision, not a wiring fix, and
    guessing one would be inventing a signal. Tracked as OF-VOTER. When it is
    wired, this test should fail and be rewritten.
    """
    from analysis.advanced_order_flow import get_advanced_order_flow_analyzer

    adv = get_advanced_order_flow_analyzer()
    assert not hasattr(adv, "analyze"), (
        "AdvancedOrderFlowAnalyzer grew an `analyze` method — _bias_vote_advanced may "
        "now work, and this test and OF-VOTER should be revisited"
    )
    assert _dashboard()._bias_vote_advanced(SYMBOL) is None


def test_bias_is_neutral_when_no_voter_can_speak():
    """Documented, not endorsed.

    `get_bias` returns 'neutral' both when the voters disagree and when not one
    of them could form an opinion. Those are different states and the return
    type — a bare string — cannot express the difference. It is unrouted today,
    so this pins the behaviour rather than changing a signal nothing consumes.
    """
    assert _dashboard().get_bias(SYMBOL) == "neutral"


def test_the_summary_reports_nulls_rather_than_zeros_for_unmeasured_fields():
    """The one place in this subsystem that was already honest.

    `get_summary` returns None for every unmeasured field instead of 0.0, which
    is why it is not part of the F147 fix — a null cannot be mistaken for a
    measurement the way `cumulative_delta: 0` could.
    """
    summary = _dashboard().get_summary(SYMBOL)

    assert summary["symbol"] == SYMBOL
    for field in ("dom_imbalance", "buy_pressure", "sell_pressure", "cumulative_delta"):
        assert summary[field] is None, f"{field} was {summary[field]!r}, not None"
    assert summary["signals"] == []


def test_the_summary_reports_measured_values_once_fed():
    """Positive control: the nulls above must be absence, not a broken summary."""
    from analysis.order_flow import get_order_flow_analyzer

    # Build the dashboard BEFORE feeding: `_dashboard()` clears the symbol so
    # each test starts unmeasured, and calling it after the feed wiped the very
    # trades this test is about. The first version of this test did exactly
    # that and read as a defect in `get_summary`.
    dashboard = _dashboard()
    analyzer = get_order_flow_analyzer()
    try:
        _feed(analyzer)
        summary = dashboard.get_summary(SYMBOL)
        assert summary["cumulative_delta"] == pytest.approx(6.0), summary
    finally:
        analyzer.clear_trades(SYMBOL)


def test_the_complete_analysis_runs_end_to_end(dashboard_client):
    """Exercises the four _summary_* branches, each of which swallows its own errors."""
    client, analyzer = dashboard_client
    try:
        _feed(analyzer)
        r = client.get(f"/api/dashboard/{SYMBOL}/complete")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["symbol"] == SYMBOL
        assert "order_flow" in body and "advanced" in body
    finally:
        analyzer.clear_trades(SYMBOL)


# ── The ingest path ───────────────────────────────────────────────────────────
#
# `OrderFlowDashboard.add_trade` fans a tick out to time-and-sales and the
# order-flow analyzer. It is the entry point the remaining half of F147 needs —
# whatever subscribes a tick source will call this — and it was uncovered.


def test_a_trade_reaches_both_downstream_analyzers():
    """The fan-out is the ingest contract; if it drops a leg, half the readouts stay dark."""
    from analysis.order_flow import get_order_flow_analyzer

    dashboard = _dashboard()
    analyzer = get_order_flow_analyzer()
    try:
        dashboard.add_trade(SYMBOL, price=2000.0, volume=3.0, side="buy")

        assert analyzer.has_data(SYMBOL), "the order-flow analyzer received nothing"
        assert analyzer.get_stats()["total_trades"] >= 1
    finally:
        analyzer.clear_trades(SYMBOL)


def test_ingest_survives_one_failing_downstream_analyzer():
    """A broken leg must not take the tick away from the working one.

    Both legs are individually guarded, which is right — but a guard nobody has
    watched hold is not a guard, and these two handlers were uncovered.
    """
    from unittest.mock import MagicMock

    from analysis.order_flow import get_order_flow_analyzer

    dashboard = _dashboard()
    analyzer = get_order_flow_analyzer()
    broken = MagicMock()
    broken.add_trade.side_effect = RuntimeError("time-and-sales is down")
    dashboard._ts = broken

    try:
        dashboard.add_trade(SYMBOL, price=2000.0, volume=3.0, side="buy")

        assert analyzer.has_data(SYMBOL), "a failure in time-and-sales swallowed the tick before order flow saw it"
    finally:
        analyzer.clear_trades(SYMBOL)


def test_the_complete_analysis_survives_a_failing_subsystem():
    """Each section of the report is independently guarded.

    `get_complete_analysis` wraps institutional, advanced, time-and-sales and
    DOM in separate try/excepts so one dead subsystem does not blank the report.
    Every one of those handlers was uncovered.
    """
    from unittest.mock import MagicMock

    from analysis.order_flow import get_order_flow_analyzer

    dashboard = _dashboard()
    analyzer = get_order_flow_analyzer()
    dashboard._dom = MagicMock()
    dashboard._dom.get_order_book_analysis.side_effect = RuntimeError("DOM unavailable")

    try:
        _feed(analyzer)
        result = dashboard.get_complete_analysis(SYMBOL)

        assert result["symbol"] == SYMBOL
        assert result["order_flow"] is not None, (
            "a DOM failure blanked the order-flow section it has nothing to do with"
        )
    finally:
        analyzer.clear_trades(SYMBOL)


# ── OF-VOTER: the vote is absent; the count must say so ───────────────────────


def test_the_dead_voter_no_longer_calls_a_method_that_does_not_exist(caplog):
    """Refusing knowingly is not the same as failing every time.

    Wiring the advanced voter to a real signal stays a quantitative decision and
    is not made here. Raising `AttributeError` into a WARNING handler on every
    single call is not that decision — it is a bug that produces the same answer
    by accident, one exception per invocation, on a hot path.

    The voter now checks for the capability and declines, so the absence is a
    stated condition rather than a swallowed error.
    """
    import analysis.order_flow_dashboard as ofd

    # Asserted behaviourally. Grepping the source for `self._adv.analyze(` was
    # the first attempt and it failed against the FIXED code, because the new
    # docstring quotes the call it replaced — `inspect.getsource` returns the
    # docstring too. A text match tests how code is written; calling it tests
    # what it does.
    dashboard = _dashboard()
    ofd.OrderFlowDashboard._advanced_vote_warned = False

    with caplog.at_level(logging.WARNING, logger=ofd.logger.name):
        first = dashboard._bias_vote_advanced(SYMBOL)
        second = dashboard._bias_vote_advanced(SYMBOL)

    assert first is None and second is None

    # One warning for a structural condition, not one per call on a hot path.
    unwired = [r for r in caplog.records if "advanced voter is not wired" in r.getMessage()]
    assert len(unwired) == 1, f"expected exactly one warning across two calls, got {len(unwired)}"

    # And nothing raised: the old code produced an AttributeError every time.
    assert not [r for r in caplog.records if "Advanced get_bias error" in r.getMessage()], (
        "the voter is still raising into the generic error handler"
    )


def test_get_bias_reports_how_many_voters_actually_voted():
    """A majority of two must not read as a majority of three.

    `get_bias` consults three vote functions and counts only the non-None
    answers, so with the advanced voter permanently silent the result is decided
    by two — and "bullish" from a 2-voter poll is indistinguishable in the
    output from "bullish" from a 3-voter poll. Any consumer weighting this
    signal is weighting a quorum it cannot see.
    """
    dashboard = _dashboard()
    bias, voted, total = dashboard.bias_with_quorum(SYMBOL)

    assert bias in ("bullish", "bearish", "neutral")
    assert total == 3, "the number of declared voters changed — revisit OF-VOTER"
    assert voted < total, (
        "every voter now votes; the advanced voter may have been wired, so this test and OF-VOTER should be revisited"
    )
    assert dashboard.get_bias(SYMBOL) == bias, "get_bias and bias_with_quorum disagree"


def test_the_summary_carries_the_quorum_so_a_consumer_can_see_it():
    """Reporting the number where the bias is reported, not only in a log line.

    `hopefx-dead-controls`: evidence swallowed at DEBUG is evidence nobody has.
    A consumer of `get_summary` must be able to tell a full poll from a partial
    one without reading the source.
    """
    summary = _dashboard().get_summary(SYMBOL)
    assert "bias" in summary
    assert summary.get("bias_voters_total") == 3, "the number of declared voters changed — revisit OF-VOTER"
    # With no ticks ingested every voter declines, which is itself the right
    # answer — and the reason this asserts a bound rather than the 2 a first
    # draft expected. What must hold is that the count is REPORTED and can never
    # reach the declared total while the advanced voter is unwired.
    assert summary.get("bias_voters") is not None, "the quorum is not reported beside the bias"
    assert 0 <= summary["bias_voters"] < 3
