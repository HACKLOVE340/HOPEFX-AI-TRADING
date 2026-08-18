# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_user_resources_are_owner_scoped.py
===================================================
Regression tests for findings S-24, S-25 and S-26 — one bug shape in three
modules, found by generalising S-23.

The scan that produced them: every ``@router`` handler that binds a parameter
to an auth dependency and then never references it, narrowed to those also
taking a resource-id parameter. 36 candidates; most were legitimately global
(market data, model explanations, the security dashboard). These three were
per-user resources with no ownership check at all.

**S-24 — no-code strategies (`nocode/router.py`).** `GET /strategies` took no
user parameter and returned every strategy in the shared `builder.strategies`
dict. `POST /strategies` bound `user` and recorded no owner —
`builder.create_strategy(name, description, symbol, timeframe)` had nowhere to
put one. `PATCH`, `DELETE`, `compile` and `backtest` acted on any id.
`GET /strategies/{id}/export` had **no role gate either** — only the
router-level `Depends(get_current_user)` — and returns the strategy's generated
**Python source**. A strategy is the user's trading logic, and the platform
sells strategies through `/api/monetization/marketplace`.

**S-25 — research notebooks (`research/__init__.py`).** Same shape.
`create_notebook` took `author` from the **request body**, so a caller could
claim any author, and nothing recorded the real owner. `list_notebooks`
returned everyone's. `add_cell`, `execute_cell`, `execute_all`,
`delete_notebook`, `run_notebook` acted on any id; `GET /notebooks/{id}` and
`GET /notebooks/{id}/export` had no user parameter at all and returned full
cell contents — the latter as runnable Python. (Cell execution itself is
sandboxed in a subprocess, so this was disclosure and tampering, not RCE.)

**S-26 — chat message deletion (`api/community_chat.py`).**
`DELETE /rooms/{room_id}/messages/{msg_id}` bound `user` and never looked at
it, so any authenticated account could delete anybody's message in any room —
even though `send_message` already records `user_id` on every message.

Rooms and their message history stay readable by any authenticated user: it is
a community chat, and that is the point.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SECRET = "owner-scope-tests-secret-key-min-32-chars"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", _SECRET)
    monkeypatch.setenv("APP_ENV", "test")


def _headers(sub: str, role: str = "trader", email: str | None = None) -> dict[str, str]:
    from auth.jwt import ALGORITHM, _get_secret

    claims = {"sub": sub, "type": "access", "role": role, "exp": int(time.time()) + 600}
    if email:
        claims["email"] = email
    return {"Authorization": "Bearer " + pyjwt.encode(claims, _get_secret(), algorithm=ALGORITHM)}


@pytest.fixture
def alice():
    return _headers("alice")


@pytest.fixture
def bob():
    return _headers("bob")


# ── S-24: no-code strategies ─────────────────────────────────────────────────


@pytest.fixture
def nocode_client():
    from nocode.builder import NoCodeStrategyBuilder
    from nocode.router import create_nocode_router

    app = FastAPI()
    app.include_router(create_nocode_router(NoCodeStrategyBuilder()))
    return TestClient(app, raise_server_exceptions=False)


def _create_strategy(client, headers, name="Alpha") -> str:
    response = client.post(
        "/api/nocode/strategies",
        json={"name": name, "description": "proprietary edge", "symbol": "XAUUSD", "timeframe": "1h"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["strategy_id"]


@pytest.mark.unit
class TestNoCodeStrategiesAreOwnerScoped:
    def test_the_list_shows_only_the_callers_strategies(self, nocode_client, alice, bob):
        strategy_id = _create_strategy(nocode_client, alice)

        mine = nocode_client.get("/api/nocode/strategies", headers=alice).json()
        theirs = nocode_client.get("/api/nocode/strategies", headers=bob).json()

        assert any(s["strategy_id"] == strategy_id for s in mine)
        assert not any(s["strategy_id"] == strategy_id for s in theirs), (
            "every trader could enumerate every other trader's strategies (S-24)"
        )

    def test_built_in_templates_stay_visible_to_everyone(self, nocode_client, bob):
        """`_create_templates()` puts them in the same dict at builder init."""
        assert nocode_client.get("/api/nocode/strategies", headers=bob).json(), (
            "scoping must not hide the shared built-in templates"
        )

    @pytest.mark.parametrize(
        ("method", "suffix"),
        [
            ("get", "/export"),
            ("post", "/compile"),
            ("post", "/backtest"),
            ("delete", ""),
        ],
    )
    def test_another_user_gets_404(self, nocode_client, alice, bob, method, suffix):
        strategy_id = _create_strategy(nocode_client, alice)

        response = getattr(nocode_client, method)(f"/api/nocode/strategies/{strategy_id}{suffix}", headers=bob)

        assert response.status_code == 404, (
            f"{method.upper()} {suffix or '(delete)'} answered {response.status_code} "
            "for someone else's strategy (S-24)"
        )

    def test_patch_by_another_user_is_refused(self, nocode_client, alice, bob):
        strategy_id = _create_strategy(nocode_client, alice)

        response = nocode_client.patch(
            f"/api/nocode/strategies/{strategy_id}",
            json={"name": "pwned", "description": "", "symbol": "XAUUSD", "timeframe": "1h"},
            headers=bob,
        )
        assert response.status_code == 404

    def test_the_owner_keeps_full_access(self, nocode_client, alice):
        strategy_id = _create_strategy(nocode_client, alice)

        assert nocode_client.get(f"/api/nocode/strategies/{strategy_id}/export", headers=alice).status_code == 200
        assert nocode_client.delete(f"/api/nocode/strategies/{strategy_id}", headers=alice).status_code == 204

    def test_a_failed_delete_leaves_the_strategy_alone(self, nocode_client, alice, bob):
        strategy_id = _create_strategy(nocode_client, alice)

        nocode_client.delete(f"/api/nocode/strategies/{strategy_id}", headers=bob)

        still_there = nocode_client.get("/api/nocode/strategies", headers=alice).json()
        assert any(s["strategy_id"] == strategy_id for s in still_there)

    def test_the_owner_is_recorded_on_the_strategy(self):
        from nocode.models import NoCodeStrategy

        assert "user_id" in NoCodeStrategy.__dataclass_fields__, (
            "without a field on the model there is nowhere to record the owner (S-24)"
        )


# ── S-25: research notebooks ─────────────────────────────────────────────────


@pytest.fixture
def research_client():
    from research import ResearchNotebookEngine, create_research_router

    app = FastAPI()
    app.include_router(create_research_router(ResearchNotebookEngine()))
    return TestClient(app, raise_server_exceptions=False)


def _create_notebook(client, headers, author="whoever") -> str:
    response = client.post(
        "/api/research/notebooks",
        json={"title": "Alpha research", "description": "edge", "author": author},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["notebook_id"]


@pytest.mark.unit
class TestResearchNotebooksAreOwnerScoped:
    def test_the_list_shows_only_the_callers_notebooks(self, research_client, alice, bob):
        notebook_id = _create_notebook(research_client, alice)

        mine = research_client.get("/api/research/notebooks", headers=alice).json()["notebooks"]
        theirs = research_client.get("/api/research/notebooks", headers=bob).json()["notebooks"]

        assert any(n["notebook_id"] == notebook_id for n in mine)
        assert not any(n["notebook_id"] == notebook_id for n in theirs), (
            "every trader could list every other trader's research (S-25)"
        )

    @pytest.mark.parametrize(
        ("method", "suffix"),
        [("get", ""), ("get", "/export"), ("post", "/run"), ("post", "/execute"), ("delete", "")],
    )
    def test_another_user_gets_404(self, research_client, alice, bob, method, suffix):
        notebook_id = _create_notebook(research_client, alice)

        response = getattr(research_client, method)(f"/api/research/notebooks/{notebook_id}{suffix}", headers=bob)

        assert response.status_code == 404, (
            f"{method.upper()} {suffix or '(root)'} answered {response.status_code} for someone else's notebook (S-25)"
        )

    def test_another_user_cannot_add_a_cell(self, research_client, alice, bob):
        notebook_id = _create_notebook(research_client, alice)

        response = research_client.post(
            f"/api/research/notebooks/{notebook_id}/cells",
            json={"cell_type": "code", "content": "print(1)"},
            headers=bob,
        )
        assert response.status_code == 404

    def test_the_owner_keeps_full_access(self, research_client, alice):
        notebook_id = _create_notebook(research_client, alice)

        assert research_client.get(f"/api/research/notebooks/{notebook_id}", headers=alice).status_code == 200
        assert research_client.delete(f"/api/research/notebooks/{notebook_id}", headers=alice).status_code == 204

    def test_a_claimed_author_does_not_grant_access(self, research_client, alice, bob):
        """`author` is a display string the client supplies — not authorisation."""
        notebook_id = _create_notebook(research_client, alice, author="bob")

        assert research_client.get(f"/api/research/notebooks/{notebook_id}", headers=bob).status_code == 404, (
            "passing someone else's name as `author` must not grant them the "
            "notebook, nor take it from its real creator (S-25)"
        )
        assert research_client.get(f"/api/research/notebooks/{notebook_id}", headers=alice).status_code == 200

    def test_the_owner_is_recorded_separately_from_the_author(self):
        from research import ResearchNotebook

        fields = ResearchNotebook.__dataclass_fields__
        assert "user_id" in fields and "author" in fields, (
            "the owner must be a separate field from the client-supplied author (S-25)"
        )


# ── S-26: chat message deletion ──────────────────────────────────────────────


@pytest.fixture
def chat_client():
    from api.community_chat import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _post_message(client, headers, text="hello") -> tuple[str, str]:
    room_id = client.get("/api/chat/rooms", headers=headers).json()["rooms"][0]["id"]
    response = client.post(f"/api/chat/rooms/{room_id}/messages", json={"content": text}, headers=headers)
    assert response.status_code == 200, response.text
    return room_id, response.json()["id"]


@pytest.mark.unit
class TestChatMessagesCanOnlyBeDeletedByTheirAuthor:
    def test_another_user_cannot_delete_it(self, chat_client, alice, bob):
        room_id, message_id = _post_message(chat_client, alice, "alice's message")

        response = chat_client.delete(f"/api/chat/rooms/{room_id}/messages/{message_id}", headers=bob)

        assert response.status_code == 404, "any authenticated account could delete anybody's message (S-26)"
        remaining = chat_client.get(f"/api/chat/rooms/{room_id}/messages", headers=alice).json()["messages"]
        assert any(m["id"] == message_id for m in remaining), "the message was deleted anyway"

    def test_the_author_can_delete_it(self, chat_client, alice):
        room_id, message_id = _post_message(chat_client, alice)

        assert chat_client.delete(f"/api/chat/rooms/{room_id}/messages/{message_id}", headers=alice).status_code == 200

    def test_an_admin_can_moderate(self, chat_client, alice):
        room_id, message_id = _post_message(chat_client, alice)
        admin = _headers("root", role="admin")

        assert chat_client.delete(f"/api/chat/rooms/{room_id}/messages/{message_id}", headers=admin).status_code == 200

    def test_a_refusal_looks_like_a_missing_message(self, chat_client, alice, bob):
        room_id, message_id = _post_message(chat_client, alice)

        refused = chat_client.delete(f"/api/chat/rooms/{room_id}/messages/{message_id}", headers=bob)
        missing = chat_client.delete(f"/api/chat/rooms/{room_id}/messages/does-not-exist", headers=bob)

        assert refused.status_code == missing.status_code == 404
        assert refused.json() == missing.json()

    def test_reading_the_room_is_still_open_to_members(self, chat_client, alice, bob):
        """It is a community chat — history is meant to be shared."""
        room_id, message_id = _post_message(chat_client, alice, "visible to all")

        seen = chat_client.get(f"/api/chat/rooms/{room_id}/messages", headers=bob).json()["messages"]
        assert any(m["id"] == message_id for m in seen)


@pytest.mark.unit
class TestSendingAMessageSurvivesATokenWithoutAnEmail:
    """A 500 uncovered while probing S-26, unrelated to ownership.

    ``"username": getattr(user, "email", user.sub).split("@")[0]`` — but
    ``TokenPayload.email`` is declared ``str | None``, so the attribute always
    exists and the getattr default never fires. A token carrying no ``email``
    claim yielded ``None`` and ``.split`` raised, 500-ing the request.
    """

    def test_a_token_with_no_email_claim_still_posts(self, chat_client):
        headers = _headers("no-email-user")
        room_id = chat_client.get("/api/chat/rooms", headers=headers).json()["rooms"][0]["id"]

        response = chat_client.post(f"/api/chat/rooms/{room_id}/messages", json={"content": "hi"}, headers=headers)

        assert response.status_code == 200, f"send_message 500s without an email claim: {response.text}"
        assert response.json()["username"] == "no-email-user"

    def test_an_email_claim_is_still_used_for_the_display_name(self, chat_client):
        headers = _headers("u1", email="alice@example.com")
        room_id = chat_client.get("/api/chat/rooms", headers=headers).json()["rooms"][0]["id"]

        response = chat_client.post(f"/api/chat/rooms/{room_id}/messages", json={"content": "hi"}, headers=headers)
        assert response.json()["username"] == "alice"


# ── S-28: backtest results ───────────────────────────────────────────────────


@pytest.fixture
def backtest_client(monkeypatch):
    from api import backtesting

    app = FastAPI()
    app.include_router(backtesting.router)

    # Isolate the module-level write-through caches per test.
    monkeypatch.setattr(backtesting, "_results", {}, raising=False)
    monkeypatch.setattr(backtesting, "_wf_results", {}, raising=False)
    monkeypatch.setattr(backtesting, "_results_loaded", True, raising=False)
    monkeypatch.setattr(backtesting, "_wf_results_loaded", True, raising=False)
    monkeypatch.setattr(backtesting, "db_set", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(backtesting, "db_get", lambda *a, **k: None, raising=False)

    return TestClient(app, raise_server_exceptions=False), backtesting


_RUN = {
    "strategy": "S",
    "symbol": "XAUUSD",
    "start_date": "2024-01-01",
    "end_date": "2024-06-01",
    "initial_capital": 10_000.0,
    "final_equity": 11_000.0,
    "total_return_pct": 10.0,
    "max_drawdown_pct": 2.0,
    "sharpe_ratio": 1.5,
    "total_trades": 10,
    "win_rate_pct": 60.0,
    "status": "completed",
    "created_at": "2024-06-01",
}


@pytest.mark.unit
class TestBacktestResultsAreOwnerScoped:
    """S-28: `api/backtesting.py` had no reference to a user anywhere in it."""

    def test_the_list_shows_only_the_callers_runs(self, backtest_client, alice, bob):
        client, backtesting = backtest_client
        backtesting._persist_result("ra", {**_RUN, "run_id": "ra"}, user_id="alice")
        backtesting._persist_result("rb", {**_RUN, "run_id": "rb"}, user_id="bob")

        mine = [r["run_id"] for r in client.get("/api/backtesting/results", headers=alice).json()]
        theirs = [r["run_id"] for r in client.get("/api/backtesting/results", headers=bob).json()]

        assert mine == ["ra"]
        assert theirs == ["rb"], (
            "a backtest result carries the strategy, symbol, return, Sharpe and "
            "drawdown — one user's research, listed to everyone (S-28)"
        )

    @pytest.mark.parametrize("path", ["/api/backtesting/results/ra", "/api/backtesting/ra/report.pdf"])
    def test_another_user_gets_404(self, backtest_client, alice, bob, path):
        client, backtesting = backtest_client
        backtesting._persist_result("ra", {**_RUN, "run_id": "ra"}, user_id="alice")

        assert client.get(path, headers=bob).status_code == 404
        assert client.get(path, headers=alice).status_code == 200

    def test_walk_forward_runs_are_scoped_too(self, backtest_client, alice, bob):
        client, backtesting = backtest_client
        backtesting._persist_wf_result(
            "wf1",
            {"run_id": "wf1", "strategy": "S", "status": "completed", "created_at": "2024-06-01"},
            user_id="alice",
        )

        assert client.get("/api/backtesting/walk-forward/wf1", headers=bob).status_code == 404
        assert client.get("/api/backtesting/walk-forward/wf1", headers=alice).status_code == 200
        # The list endpoint answers {"results": [...], "total": N} — asserted
        # against the endpoint rather than an assumed bare list.
        theirs = client.get("/api/backtesting/walk-forward", headers=bob).json()
        assert theirs == {"results": [], "total": 0}

        mine = client.get("/api/backtesting/walk-forward", headers=alice).json()
        assert [r["run_id"] for r in mine["results"]] == ["wf1"]

    def test_runs_stored_before_the_field_stay_visible(self, backtest_client, bob):
        """Authorisation check, not a data migration."""
        client, backtesting = backtest_client
        backtesting._persist_result("legacy", {**_RUN, "run_id": "legacy"})

        assert [r["run_id"] for r in client.get("/api/backtesting/results", headers=bob).json()] == ["legacy"]

    def test_the_owner_survives_a_sparse_status_update(self, backtest_client):
        """The failure paths persist `{"run_id": ..., "status": "error"}`.

        Without carrying the previous owner forward, a run would become
        unowned — and so visible to everyone — the moment it failed.
        """
        _client, backtesting = backtest_client
        backtesting._persist_result("ra", {**_RUN, "run_id": "ra"}, user_id="alice")

        backtesting._persist_result("ra", {"run_id": "ra", "status": "error", "error": "boom"})

        assert backtesting._results["ra"]["user_id"] == "alice"

    def test_every_persist_call_site_records_an_owner(self):
        """Structural: a new write path cannot quietly create an unowned run."""
        import ast
        from pathlib import Path

        tree = ast.parse((Path(__file__).resolve().parents[2] / "api" / "backtesting.py").read_text())
        missing = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("_persist_result", "_persist_wf_result")
            and "user_id" not in {kw.arg for kw in node.keywords}
        ]
        assert not missing, f"persist calls without an owner at lines {missing} (S-28)"


# ── S-29: the unmounted subscription router factory ──────────────────────────


@pytest.fixture
def billing_client():
    from monetization.subscription import SubscriptionManager, SubscriptionTier, create_subscription_router

    manager = SubscriptionManager()
    manager.create_subscription("alice", SubscriptionTier.FREE)

    app = FastAPI()
    app.include_router(create_subscription_router(manager), prefix="/billing")
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
class TestTheSubscriptionFactoryCannotBeWiredIntoAHole:
    """S-29: an unmounted router with weaker guards than the mounted one.

    `monetization/subscription.py::create_subscription_router()` is called
    nowhere — `api/monetization.py` serves the guarded equivalents. But the
    module docstring tells you to mount it
    (``app.include_router(create_subscription_router(), prefix="/billing")``),
    and doing so published, with **no authentication at all**:

        POST   /subscribe               start a paid subscription for any user_id
        GET    /license/validate        read any user's tier and entitlements
        GET    /subscription/{user_id}  read any user's subscription
        DELETE /subscription/{user_id}  cancel any user's subscription

    Same landmine as the duplicate `/api/alerts` router removed in S-21:
    harmless until somebody follows the instructions written next to it. The
    endpoints are authenticated and self-or-operator scoped now, so wiring it
    up is safe rather than merely unlikely.
    """

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/billing/subscription/alice"),
            ("delete", "/billing/subscription/alice"),
            ("get", "/billing/license/validate?user_id=alice"),
            ("post", "/billing/subscribe"),
        ],
    )
    def test_no_endpoint_answers_without_a_token(self, billing_client, method, path):
        response = getattr(billing_client, method)(path)

        assert response.status_code == 401, (
            f"{method.upper()} {path} answered {response.status_code} unauthenticated (S-29)"
        )

    def test_another_user_cannot_read_a_subscription(self, billing_client, alice, bob):
        assert billing_client.get("/billing/subscription/alice", headers=bob).status_code == 404
        assert billing_client.get("/billing/subscription/alice", headers=alice).status_code == 200

    def test_another_user_cannot_cancel_a_subscription(self, billing_client, alice, bob):
        assert billing_client.delete("/billing/subscription/alice", headers=bob).status_code == 404, (
            "cancelling someone else's paid subscription is the sharpest edge here (S-29)"
        )
        assert billing_client.delete("/billing/subscription/alice", headers=alice).status_code == 200

    def test_another_user_cannot_subscribe_on_your_behalf(self, billing_client, alice, bob):
        assert (
            billing_client.post(
                "/billing/subscribe", json={"user_id": "alice", "tier": "free"}, headers=bob
            ).status_code
            == 404
        )
        assert (
            billing_client.post(
                "/billing/subscribe", json={"user_id": "alice", "tier": "free"}, headers=alice
            ).status_code
            == 200
        )

    def test_another_user_cannot_read_entitlements(self, billing_client, bob):
        assert billing_client.get("/billing/license/validate?user_id=alice", headers=bob).status_code == 404

    def test_staff_may_act_on_behalf_of_a_customer(self, billing_client):
        admin = _headers("root", role="admin")

        assert billing_client.get("/billing/subscription/alice", headers=admin).status_code == 200

    def test_the_stripe_webhook_stays_unauthenticated(self):
        """It is authenticated by signature, not by a bearer token."""
        from monetization.subscription import create_subscription_router

        routes = {r.path: r for r in create_subscription_router().routes}
        webhook = routes["/webhook"]

        assert not webhook.dependant.dependencies, (
            "the Stripe webhook must stay tokenless — Stripe cannot present one; "
            "handle_stripe_webhook verifies the stripe-signature header instead"
        )

    def test_every_other_route_requires_a_token(self):
        from monetization.subscription import create_subscription_router

        for route in create_subscription_router().routes:
            if route.path == "/webhook":
                continue
            names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
            assert "get_current_user" in names, f"{route.path} has no auth dependency (S-29)"
