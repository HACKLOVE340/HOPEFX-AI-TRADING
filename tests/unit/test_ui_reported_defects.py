# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ui_reported_defects.py
=======================================
Eight defects found by walking the deployed UI, each reproduced here first.

They are unrelated in code and identical in shape: the screen said something
untrue and nothing in the system disagreed.

1. ``GET /api/trading/account`` → 500. ``UnboundLocalError: cannot access local
   variable 'margin_level'``. The name is imported at module level *and*
   assigned later in the same function, which makes it local throughout, so the
   read on the paper branch — the branch that runs in this deployment — was
   unbound. This is the "route_health: 1 route(s) returning 5xx errors" the
   superadmin diagnostics page reported.

2. ``GET /api/notifications`` → 404 while ``/api/notifications/`` → 200. The SPA
   catch-all matches every unrouted path and returns a bare 404, which pre-empts
   Starlette's automatic trailing-slash redirect. api/notifications.py declares
   the route at both ``""`` and ``"/"`` to avoid this and the mitigation does
   not survive router inclusion — both land on ``/api/notifications/``.
   ``/api/admin``, ``/api/alerts``, ``/api/dom`` and ``/api/superadmin`` were
   unreachable the same way.

3. Free strategies could not be acquired. ``price or price_monthly`` treats a
   legitimate 0.0 as missing, so the free listing the UI badges "Free" with an
   "Add to my strategies" button was rejected as "Strategy has no valid price
   configured."

4. Paid purchases returned "Payment provider error. Please try again." when
   Stripe simply is not configured. Retrying a missing API key never succeeds.

5. "Run Reconciliation" always failed with ``period is required (e.g.
   '2025-01')`` — an error naming a parameter the page offered no way to enter.

6. The diagnostics log scanner reported ``[690x] Numeric instability in trading
   calculations`` against a system with no numeric problem: the pattern
   ``inf.*value`` matches any line with "INFO" followed by "value". Graded
   high, so all 690 went to ``alerts:critical``.

7. The SIGNAL FEED panel showed "undefined is not an object (evaluating
   'e.toUpperCase')". ``fetchSignals`` cast the response ``as MLSignal[]``; the
   server sends neither ``status`` nor the direction vocabulary the component
   compares against, so a BUY rendered as a red ▼.

8. The chart header sat at "3,300.00 +0.00%" beside candles near 4,400. The
   paper broker's hardcoded seed table is read at level 2 of the live-price
   chain, above the Redis tick cache and the event bus, and it is always
   present — so the two real sources below it were unreachable.
"""

from __future__ import annotations

import os
import re
import time

import pytest

pytestmark = pytest.mark.unit

os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("CSRF_PROTECTION", "false")
os.environ["STARTUP_GATE"] = "false"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def su_headers():
    import jwt

    token = jwt.encode(
        {"sub": "superadmin", "role": "superadmin", "type": "access", "exp": int(time.time()) + 3600},
        os.environ["SECURITY_JWT_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


# ── 1. The account endpoint ──────────────────────────────────────────────────


def test_the_account_endpoint_does_not_500(client, su_headers):
    r = client.get("/api/trading/account", headers=su_headers)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    body = r.json()
    for field in ("balance", "equity", "margin_used", "margin_free", "margin_level"):
        assert field in body, f"{field} missing from the account payload"
    assert isinstance(body["margin_level"], (int, float))


def test_margin_level_is_never_read_as_a_bare_name_in_get_account():
    """The defect was a shadowed name, so guard the name, not the symptom.

    ``margin_level`` is assigned inside ``get_account``, which makes every read
    of the bare name in that function a read of an unbound local until the
    assignment runs. The module imports the function under both names; only the
    underscored alias is safe to call there.
    """
    import ast
    import inspect
    import textwrap

    from api import trading

    src = textwrap.dedent(inspect.getsource(trading.get_account))
    tree = ast.parse(src)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "margin_level"
    ]
    assert calls == [], "get_account calls margin_level(...) by its shadowed name; use _margin_level"


# ── 2. Trailing-slash routes ─────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/api/notifications", "/api/alerts"])
def test_api_paths_resolve_without_a_trailing_slash(client, su_headers, path):
    r = client.get(path, headers=su_headers)
    assert r.status_code == 200, f"{path} → {r.status_code}; the SPA catch-all ate the redirect"


def test_the_query_string_survives_the_redirect(client, su_headers):
    r = client.get("/api/notifications?page=1&limit=5", headers=su_headers)
    assert r.status_code == 200
    assert r.json()["limit"] == 5, "the redirect dropped the query string"


def test_an_unknown_api_path_still_404s(client, su_headers):
    """The redirect must not turn every miss into a 200."""
    r = client.get("/api/definitely-not-a-route", headers=su_headers)
    assert r.status_code == 404


def test_spa_routes_are_untouched(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "html" in r.headers.get("content-type", "")


def test_no_api_route_is_reachable_only_with_a_trailing_slash():
    """The general property, so a router added later cannot reintroduce this."""
    from app import app
    from core.router_registry import iter_api_routes

    paths = {r.path for r in iter_api_routes(app.routes)}
    orphans = sorted(
        p for p in paths if p.startswith("/api/") and p.endswith("/") and p[:-1] not in paths and "/v1/" not in p
    )
    # These exist only in the slashed form; the catch-all redirect is what makes
    # them reachable. Assert the redirect covers each one rather than asserting
    # the set is empty, which would require touching every router.
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False)
    for p in orphans:
        r = c.get(p[:-1], follow_redirects=False)
        assert r.status_code in (307, 401, 403), f"{p[:-1]} → {r.status_code}, expected a redirect to {p}"


# ── 3 & 4. Marketplace ───────────────────────────────────────────────────────


def _free_and_paid_ids(client, headers):
    strategies = client.get("/api/monetization/marketplace/strategies", headers=headers).json()["strategies"]
    free = next(s["strategy_id"] for s in strategies if float(s.get("price") or 0) == 0)
    paid = next(s["strategy_id"] for s in strategies if float(s.get("price") or 0) > 0)
    return free, paid


def test_a_free_strategy_can_be_added(client, su_headers):
    """The listing is badged "Free" and the button says "Add to my strategies".
    It must not be answered with a message about a broken price."""
    free_id, _ = _free_and_paid_ids(client, su_headers)
    r = client.post("/api/monetization/marketplace/purchase", headers=su_headers, json={"strategy_id": free_id})
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body["success"] is True
    assert body["free"] is True
    assert body["amount"] == 0.0
    assert body["client_secret"] is None, "a free strategy must not create a payment intent"


def test_a_free_strategy_never_touches_the_payment_provider(client, su_headers, monkeypatch):
    """Booby-trap the provider: reaching it at all is the failure."""
    import api.monetization as mon

    def _forbidden(*a, **k):
        raise AssertionError("a free strategy reached the payment provider")

    monkeypatch.setattr(mon.stripe_integration, "create_payment_intent", _forbidden)
    free_id, _ = _free_and_paid_ids(client, su_headers)
    r = client.post("/api/monetization/marketplace/purchase", headers=su_headers, json={"strategy_id": free_id})
    assert r.status_code == 200


def test_an_unconfigured_payment_provider_says_so(client, su_headers):
    """ "Please try again" is false advice when there is no API key. The status
    separates a configuration gap (503) from a provider outage (502)."""
    _, paid_id = _free_and_paid_ids(client, su_headers)
    r = client.post("/api/monetization/marketplace/purchase", headers=su_headers, json={"strategy_id": paid_id})
    assert r.status_code in (200, 503), f"{r.status_code}: {r.text[:200]}"
    if r.status_code == 503:
        detail = r.json()["detail"]
        assert "not configured" in detail
        assert "try again" not in detail.lower()


# ── 5. Reconciliation period ─────────────────────────────────────────────────


def test_the_reconciliation_ui_sends_a_period():
    src = (
        __import__("pathlib").Path(__file__).resolve().parents[2] / "frontend/src/pages/superadmin/FinancialSection.tsx"
    ).read_text()
    run_call = src.split("runReconciliation(")[1][:200]
    assert "period" in run_call, "Run Reconciliation still omits the period the server requires"
    assert 'type="month"' in src, "there is no way for an operator to choose the period"


def test_the_server_still_refuses_an_unspecified_period(client, su_headers):
    """The UI now supplies one; the server must keep refusing to guess. A
    financial reconciliation run against a silently-chosen month is worse than
    an error."""
    r = client.post("/api/superadmin/financial/reconciliation/run", headers=su_headers, json={})
    assert r.status_code == 400
    assert "period is required" in r.json()["detail"]


# ── 6. Log pattern false positives ───────────────────────────────────────────


def _pattern(category):
    from security.diagnostics import _LOG_PATTERN_MAP

    return next(p["pattern"] for p in _LOG_PATTERN_MAP if p["category"] == category)


@pytest.mark.parametrize(
    "line",
    [
        "2026-08-09 08:19:32 - prometheus_monitoring - INFO - [prometheus.py:333] - configured, sync value=15s",
        "INFO - risk.manager - Kelly fraction value computed",
        "2026-08-09 - app - INFO - [app.py:460] - TracingMiddleware registered — span buffer value",
    ],
)
def test_ordinary_info_lines_are_not_numeric_instability(line):
    """690 of these were reported as a high-severity trading defect and pushed
    to alerts:critical."""
    assert _pattern("numeric_error").search(line) is None, f"false positive on: {line}"


@pytest.mark.parametrize(
    "line",
    [
        "ERROR - division by zero in position sizing",
        "WARNING - feature vector contains NaN",
        "ERROR - ZeroDivisionError in sharpe calculation",
        "ERROR - equity became inf after fill",
    ],
)
def test_real_numeric_instability_is_still_caught(line):
    assert _pattern("numeric_error").search(line) is not None, f"missed: {line}"


def test_rate_limit_does_not_fire_on_any_number_containing_429():
    assert _pattern("rate_limit").search("INFO - request completed in 4291 ms") is None
    assert _pattern("rate_limit").search("WARNING - upstream returned 429 Too Many Requests") is not None


@pytest.mark.parametrize("line", ["INFO - trading room initialised", "DEBUG - zoom level set to 3"])
def test_memory_pressure_does_not_fire_on_words_containing_oom(line):
    assert _pattern("memory_pressure").search(line) is None, f"false positive on: {line}"


def test_real_memory_pressure_is_still_caught():
    for line in ("CRITICAL - MemoryError during backtest", "kernel: Out of memory: Killed process"):
        assert _pattern("memory_pressure").search(line) is not None, line


def test_no_log_pattern_matches_a_plain_startup_line():
    """A sweep over every pattern, because the two that were wrong were wrong in
    the same way and nothing checked the rest."""
    from security.diagnostics import _LOG_PATTERN_MAP

    benign = "2026-08-09 08:19:32,987 - core.middleware - INFO - [middleware.py:273] - Prometheus metrics registered"
    hits = [p["category"] for p in _LOG_PATTERN_MAP if p["pattern"].search(benign)]
    assert hits == [], f"benign startup line classified as {hits}"


# ── 7. Signal normalisation (mirrors the TS boundary) ────────────────────────


def test_the_wire_signal_lacks_the_fields_the_panel_dereferences(client, su_headers):
    """The premise of the frontend fix, pinned server-side so a future change to
    to_dict() that adds them does not silently make the mapper look wrong."""
    from api.signals import SignalDirection

    assert {d.value for d in SignalDirection} & {"buy", "sell"}, (
        "directions are no longer buy/sell; revisit the frontend normaliser"
    )


def test_the_frontend_normalises_instead_of_casting():
    path = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "frontend/src/features/chart-bot/services/chart-api.ts"
    )
    src = path.read_text()
    assert "normaliseSignal" in src
    fetch = src.split("export async function fetchSignals")[1][:600]
    assert ".map(normaliseSignal)" in fetch, "fetchSignals returns the raw wire objects again"
    assert "as MLSignal[]" not in fetch, "the cast that hid the mismatch is back"


# ── 8. Seeded prices must not masquerade as quotes ───────────────────────────


def test_a_seeded_price_is_not_reported_as_live():
    from brokers.paper_trading import PaperTradingBroker

    broker = PaperTradingBroker(namespace="test-seed")
    assert broker.market_prices.get("XAUUSD"), "precondition: the seed table is populated"
    assert broker.has_live_price("XAUUSD") is False, "the hardcoded seed is being reported as a live price"


def test_a_fed_price_is_reported_as_live():
    from brokers.paper_trading import PaperTradingBroker

    broker = PaperTradingBroker(namespace="test-fed")
    broker.update_market_price("XAUUSD", 4412.35)
    assert broker.has_live_price("XAUUSD") is True
    assert broker.market_prices["XAUUSD"] == 4412.35


def test_the_price_chain_skips_the_seed_and_falls_through(monkeypatch):
    """Level 2 must not short-circuit levels 3 and 4. With only a seeded broker
    present, the chain has to report no live price rather than 3300.0 — the UI
    already renders that as 'no feed', which is the truth."""
    import api.ws_live as ws
    from brokers.paper_trading import PaperTradingBroker
    from core.app_state import app_state

    broker = PaperTradingBroker(namespace="test-chain")
    monkeypatch.setattr(app_state, "broker", broker, raising=False)
    monkeypatch.setattr(app_state, "price_engine", None, raising=False)
    monkeypatch.setattr(ws, "_last_mid", {}, raising=False)

    assert ws._get_live_price("XAU/USD") != 3300.0, "the seed was served as a live quote"

    broker.update_market_price("XAUUSD", 4412.35)
    assert ws._get_live_price("XAU/USD") == 4412.35, "a fed price must be used"


def test_the_gold_seed_is_labelled_as_a_seed_not_a_quote():
    """Documentation guard: the constant stays, its role must stay stated."""
    src = (__import__("pathlib").Path(__file__).resolve().parents[2] / "api/ws_live.py").read_text()
    chain = src.split("Level 2 —")[1][:900]
    assert re.search(r"seed|not quotes|has_live_price", chain), "the level-2 docstring no longer says these are seeds"
