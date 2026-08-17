# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_default_rate_limit_and_ai_quota.py
===================================================
Regression tests for the two spend/abuse gaps found in the pre-launch pass.

Pre-launch checklist findings P-03 and P-04 (docs/HARDENING_BACKLOG.md).

P-03 — rate limiting was configured but not applied. `GLOBAL_DEFAULT_RATE` in
`rate_limiting_configuration.py` documents itself as "applied to every endpoint
that has no explicit decorator", and `api/platform.py::setup_rate_limiting()`
builds a slowapi `Limiter` and stores it on `app.state`. Neither was ever
consumed: there is not one `@limiter.limit()` decorator in the repository, so
the Limiter only installed its 429 handler. The endpoints that *were* limited
each brought their own mechanism — `auth/router.py` (per-IP on
login/register/reset), `api/payments.py` (`WITHDRAWAL_RATE`), the WS handshakes
— which is exactly why the absence was invisible: spot-checking any of those
showed a working limiter. Everything else, including ML inference and backtest
submission, was unmetered. `core/middleware.DefaultRateLimitMiddleware` now
supplies the documented default so routes opt out rather than opt in.

P-04 — no per-user LLM cap. Every LLM route required a token, and
`api/chat.py`'s docstring already reasoned about the cost risk ("any bot that
discovers the URL can run up OpenAI charges indefinitely") — but auth answers
*who*, not *how much*. One registered account could loop `/api/brain/complete`
and drain the provider budget, and the per-IP limiter does not help: a caller
staying under the rate limit still runs unbounded over a day. `core/ai_quota.py`
adds the missing cumulative dimension.

The two mechanisms are deliberately separate — a rate limit bounds burst, a
quota bounds total spend, and neither substitutes for the other.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_limiter_state():
    """Clear the shared in-process window between tests.

    The fallback limiter in rate_limiting/advanced.py is a module-level
    singleton, so counts leak across tests without this and the assertions
    become order-dependent.
    """
    from rate_limiting.advanced import _fallback_limiter

    _fallback_limiter._windows.clear()
    yield
    _fallback_limiter._windows.clear()


# ── P-03: default rate limit ──────────────────────────────────────────────────


def _rate_limited_app(rate: str = "5 per minute") -> FastAPI:
    from core.middleware import DefaultRateLimitMiddleware

    app = FastAPI()
    app.add_middleware(DefaultRateLimitMiddleware, rate=rate)

    @app.get("/api/thing")
    async def thing():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/api/billing/webhook/stripe")
    async def webhook():
        return {"received": True}

    return app


@pytest.mark.unit
class TestDefaultRateLimit:
    def test_requests_over_the_limit_get_429(self):
        client = TestClient(_rate_limited_app())
        codes = [client.get("/api/thing").status_code for _ in range(8)]
        assert codes[:5] == [200] * 5, f"first 5 should pass, got {codes}"
        assert codes[5:] == [429] * 3, f"remainder should be throttled, got {codes}"

    def test_429_carries_retry_after(self):
        client = TestClient(_rate_limited_app())
        for _ in range(5):
            client.get("/api/thing")
        response = client.get("/api/thing")
        assert response.status_code == 429
        assert response.headers.get("Retry-After") == "60", (
            "A 429 without Retry-After leaves a well-behaved client guessing when to retry."
        )

    def test_health_probes_are_never_throttled(self):
        """A 429 to a k8s probe reads as an unhealthy pod and gets it restarted."""
        client = TestClient(_rate_limited_app())
        codes = {client.get("/health").status_code for _ in range(30)}
        assert codes == {200}, f"health probes must stay exempt, saw {codes}"

    def test_provider_webhooks_are_never_throttled(self):
        """Providers retry in bursts after an outage; HMAC is what guards these."""
        client = TestClient(_rate_limited_app())
        codes = {client.post("/api/billing/webhook/stripe").status_code for _ in range(30)}
        assert codes == {200}, f"webhooks must stay exempt, saw {codes}"

    def test_separate_bearer_tokens_get_separate_buckets(self):
        """Otherwise one office behind a NAT shares a single allowance."""
        client = TestClient(_rate_limited_app())
        a = [client.get("/api/thing", headers={"Authorization": "Bearer tok-A"}).status_code for _ in range(5)]
        b = [client.get("/api/thing", headers={"Authorization": "Bearer tok-B"}).status_code for _ in range(5)]
        assert a == [200] * 5 and b == [200] * 5, f"buckets bled together: A={a} B={b}"

    def test_raw_token_is_not_used_as_the_storage_key(self):
        """The key reaches Redis, so it must not be a credential at rest."""
        from starlette.requests import Request

        from core.middleware import DefaultRateLimitMiddleware

        mw = DefaultRateLimitMiddleware(_rate_limited_app(), rate="5 per minute")
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/thing",
            "headers": [(b"authorization", b"Bearer super-secret-jwt")],
            "client": ("1.2.3.4", 1234),
        }
        key = mw._key(Request(scope))
        assert "super-secret-jwt" not in key, f"raw token leaked into the rate-limit key: {key}"

    def test_middleware_is_registered_by_register_all(self):
        """The middleware existing is not the same as it being installed."""
        import core.middleware as cm

        app = FastAPI()
        cm.register_all(app)
        classes = {m.cls for m in app.user_middleware}
        assert cm.DefaultRateLimitMiddleware in classes, (
            "DefaultRateLimitMiddleware is not in register_all() — the default "
            "limit would exist but never run, which is the P-03 failure itself."
        )

    def test_disable_switch_is_honoured(self, monkeypatch):
        import core.middleware as cm

        monkeypatch.setenv("RATE_LIMIT_DEFAULT_ENABLED", "false")
        app = FastAPI()
        cm.setup_default_rate_limit(app)
        classes = {m.cls for m in app.user_middleware}
        assert cm.DefaultRateLimitMiddleware not in classes


# ── P-04: per-user AI quota ───────────────────────────────────────────────────


def _quota_app():
    from api.auth import TokenPayload, get_current_user
    from core.ai_quota import ai_quota

    app = FastAPI()

    @app.post("/spend")
    async def spend(user: TokenPayload = Depends(ai_quota(feature="test"))):
        return {"ok": True}

    return app, get_current_user, TokenPayload


def _as(app, get_current_user, TokenPayload, sub: str, role: str = "trader"):
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub=sub, role=role, email=f"{sub}@example.com")


@pytest.mark.unit
class TestAIQuota:
    def test_user_is_cut_off_at_the_daily_limit(self, monkeypatch):
        monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "3")
        app, dep, payload = _quota_app()
        _as(app, dep, payload, "user-1")
        client = TestClient(app)
        codes = [client.post("/spend").status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429], f"quota not enforced: {codes}"

    def test_quota_is_per_user_not_global(self, monkeypatch):
        """A shared counter would let one user lock everyone else out."""
        monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "2")
        app, dep, payload = _quota_app()
        client = TestClient(app)

        _as(app, dep, payload, "heavy-user")
        assert [client.post("/spend").status_code for _ in range(3)] == [200, 200, 429]

        _as(app, dep, payload, "fresh-user")
        assert client.post("/spend").status_code == 200, "one user's overuse denied service to another"

    def test_operators_are_exempt(self, monkeypatch):
        """Admins run the system; they are not the abuse case being guarded."""
        monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "1")
        app, dep, payload = _quota_app()
        _as(app, dep, payload, "boss", role="admin")
        client = TestClient(app)
        assert {client.post("/spend").status_code for _ in range(6)} == {200}

    def test_rejection_explains_itself(self, monkeypatch):
        monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "1")
        app, dep, payload = _quota_app()
        _as(app, dep, payload, "user-2")
        client = TestClient(app)
        client.post("/spend")
        response = client.post("/spend")
        assert response.status_code == 429
        assert "limit" in response.json()["detail"].lower()
        assert response.headers.get("Retry-After")

    def test_zero_limit_is_treated_as_misconfiguration(self, monkeypatch):
        """A stray AI_DAILY_LIMIT_PER_USER=0 must not silently kill the feature."""
        monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "0")
        from core.ai_quota import _daily_limit

        assert _daily_limit() == 200

    def test_non_numeric_limit_falls_back(self, monkeypatch):
        monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "lots")
        from core.ai_quota import _daily_limit

        assert _daily_limit() == 200

    @pytest.mark.parametrize(
        ("module_name", "handler"),
        [
            ("api.chat", "ai_chat"),
            ("api.brain", "brain_complete"),
            ("api.brain", "brain_embed"),
            ("api.voice", "tts"),
            ("api.voice", "stt"),
        ],
    )
    def test_paid_llm_routes_carry_the_quota(self, module_name: str, handler: str):
        """Pin the wiring: the quota only helps on routes that actually use it."""
        import importlib
        import inspect

        mod = importlib.import_module(module_name)
        src = inspect.getsource(getattr(mod, handler))
        assert "ai_quota" in src, (
            f"{module_name}.{handler} spends money at an LLM provider but does not "
            "depend on ai_quota() — auth alone bounds who calls it, not how much (P-04)."
        )
