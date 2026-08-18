# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_graphql_auth_and_reachability.py
=================================================
Regression tests for findings S-13 through S-16.

**S-13 — GraphQL reported every rejected token as a server fault.**
``_get_current_user`` documents "returns user dict … or None if
unauthenticated" and guards its body with::

    except (RuntimeError, ValueError, OSError, AttributeError)

``decode_access_token`` signals every rejection with a ``jwt.PyJWTError``
subclass — ``ExpiredSignatureError``, ``InvalidSignatureError``,
``DecodeError``, and the explicit ``InvalidTokenError("Not an access token")``
it raises for a refresh token. None of those inherit from ``ValueError`` or
``RuntimeError`` (checked, not assumed — see
``test_pyjwt_errors_are_not_value_errors``), so all four escaped the handler,
escaped ``_require_auth``, and reached ``_format_error``, which labels anything
that is not ``PermissionError``/``ValueError`` as ``INTERNAL_ERROR`` with the
message "An internal error occurred".

It failed closed, so this was never an authentication bypass. But an expired
session was indistinguishable from a server fault, so no client could know to
refresh; and the three subscriptions catch only ``PermissionError``, so they
raised out of the async generator instead of closing cleanly.

**S-14 — unreachable code.**
``Query.trades`` ended with ``return await loader.load(...)`` followed by 44
lines of DB fallback that could never run. ``_batch_load_trades`` returns ``[]``
when ``app_state.broker`` is None and never consults the database, so with no
broker attached the query answered "no trades" while closed trades sat in the
``Trade`` table. ``api/gateway.py`` had a duplicated ``return`` block. Ruff has
no unreachable-code rule enabled here, so nothing flagged either.

**S-15 — every GraphQL request was rejected, valid token included.**
``_get_context()`` returns a **dict**, and strawberry's FastAPI integration
injects ``request`` / ``ws`` into it as dict *keys* (verified against
strawberry 0.324, not assumed). The auth helper read them with
``getattr(info.context, "request", None)``, which on a dict is always ``None``,
so no Authorization header was ever found. The whole API answered
"Authentication required" to everything while ``FEATURE_GRAPHQL_API`` defaults
to ``"true"``. Fail-closed, so not a bypass — but the feature was inert. The
resolvers use ``info.context.get(...)``, i.e. the dict API, so the mismatch
lived only in this one helper, and only a request through ``GraphQLRouter``
exposes it.

**S-16 — ``_format_error`` was wired to nothing.**
Neither ``strawberry.Schema`` nor ``GraphQLRouter`` accepts an error-formatter
argument, so the function was never called: no ``error_code`` extension reached
any client, and the "replace internal messages unless DEBUG=true" branch never
ran. ``process_result`` is the hook that exists for it.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

import jwt as pyjwt
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECRET = "graphql-regression-secret-key-min-32-chars"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", _SECRET)


def _info(token: str):
    """Minimal stand-in for strawberry's Info with an HTTP request context."""
    request = type("R", (), {"headers": {"authorization": f"Bearer {token}"}})()
    context = type("C", (), {"request": request})()
    return type("I", (), {"context": context})()


def _token(**claims) -> str:
    from auth.jwt import ALGORITHM, _get_secret

    payload = {"sub": "u1", "type": "access", "exp": int(time.time()) + 600}
    payload.update(claims)
    secret = claims.pop("_secret", None) or _get_secret()
    return pyjwt.encode(payload, secret, algorithm=ALGORITHM)


@pytest.mark.unit
class TestPyJWTErrorsWereNeverCaught:
    def test_pyjwt_errors_are_not_value_errors(self):
        """The premise of the bug, pinned so the fix is not later 'simplified'."""
        for error in (
            pyjwt.InvalidTokenError,
            pyjwt.ExpiredSignatureError,
            pyjwt.DecodeError,
            pyjwt.InvalidSignatureError,
        ):
            assert not issubclass(error, (RuntimeError, ValueError, OSError, AttributeError)), (
                f"{error.__name__} would be caught by the old handler, which would "
                "make this whole test file pointless — recheck the finding."
            )


@pytest.mark.unit
class TestRejectedTokensAreUnauthenticated:
    def _cases(self) -> dict[str, str]:
        from auth.jwt import ALGORITHM, _get_secret

        now = int(time.time())
        return {
            "expired": pyjwt.encode(
                {"sub": "u1", "type": "access", "exp": now - 60}, _get_secret(), algorithm=ALGORITHM
            ),
            "wrong signature": pyjwt.encode(
                {"sub": "u1", "type": "access", "exp": now + 600},
                "an-entirely-different-secret-value-32ch",  # pragma: allowlist secret
                algorithm=ALGORITHM,
            ),
            "refresh token": pyjwt.encode(
                {"sub": "u1", "type": "refresh", "exp": now + 600}, _get_secret(), algorithm=ALGORITHM
            ),
            "malformed": "not.a.jwt",
        }

    def test_get_current_user_returns_none_for_every_rejection(self):
        from api.graphql_schema import _get_current_user

        for name, token in self._cases().items():
            assert _get_current_user(_info(token)) is None, (
                f"a {name} token did not resolve to None — it raised out of "
                "_get_current_user, which contradicts the function's own "
                "documented contract (S-13)."
            )

    def test_require_auth_raises_permission_error_for_every_rejection(self):
        from api.graphql_schema import _require_auth

        for name, token in self._cases().items():
            with pytest.raises(PermissionError, match="Authentication required"):
                _require_auth(_info(token)), f"a {name} token must be unauthenticated"

    def test_a_valid_token_still_authenticates(self):
        from api.graphql_schema import _get_current_user

        user = _get_current_user(_info(_token()))
        assert user is not None and user["sub"] == "u1"

    def test_missing_header_is_still_unauthenticated(self):
        from api.graphql_schema import _get_current_user

        request = type("R", (), {"headers": {}})()
        info = type("I", (), {"context": type("C", (), {"request": request})()})()
        assert _get_current_user(info) is None


@pytest.mark.unit
class TestErrorCodeIsUnauthorizedNotInternal:
    """What the client actually sees — the reason this mattered."""

    def test_permission_error_maps_to_unauthorized(self):
        from api.graphql_schema import _format_error

        class _Err:
            original_error = PermissionError("Authentication required")

        formatted = _format_error(_Err(), lambda _e: {"message": "Authentication required"})
        assert formatted["extensions"]["error_code"] == "UNAUTHORIZED"

    def test_a_raw_jwt_error_would_have_been_internal(self):
        """Shows the old outcome, so the fix's value is legible."""
        from api.graphql_schema import _format_error

        class _Err:
            original_error = pyjwt.ExpiredSignatureError("Signature has expired")

        formatted = _format_error(_Err(), lambda _e: {"message": "Signature has expired"})
        assert formatted["extensions"]["error_code"] == "INTERNAL_ERROR", (
            "An expired token reaching the formatter is reported as a server "
            "fault. _get_current_user must convert it to None before it gets "
            "here (S-13)."
        )


@pytest.mark.unit
class TestTheApiActuallyAnswers:
    """S-15: over the real router, which is the only check that would have caught it.

    ``_get_context()`` returns a **dict**, and strawberry's FastAPI integration
    injects ``request`` / ``ws`` into it as dict *keys*. ``_get_current_user``
    read them with ``getattr(info.context, "request", None)``, which on a dict
    is always ``None`` — so no Authorization header was ever seen and **every**
    GraphQL request was rejected, valid token or not. The whole API was inert
    while ``FEATURE_GRAPHQL_API`` defaults to ``"true"``.

    Every unit-level check of the helper passed, because they all built an
    object-style context. Only a request through ``GraphQLRouter`` shows it.
    """

    @staticmethod
    def _client():
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.graphql_schema import graphql_router

        app = FastAPI()
        app.include_router(graphql_router, prefix="/graphql")
        return TestClient(app, raise_server_exceptions=False)

    _QUERY = "{ signals(limit: 1) { signalId symbol } }"

    def test_a_valid_token_is_accepted_over_http(self):
        body = (
            self._client()
            .post(
                "/graphql",
                json={"query": self._QUERY},
                headers={"Authorization": f"Bearer {_token()}"},
            )
            .json()
        )

        assert body.get("errors") is None, (
            f"a valid access token was rejected: {body.get('errors')}. The "
            "context is a dict; the auth helper must read request/ws as keys "
            "rather than attributes (S-15)."
        )
        assert body["data"]["signals"] == []

    def test_an_unauthenticated_request_is_still_refused(self):
        body = self._client().post("/graphql", json={"query": self._QUERY}).json()

        assert body["data"] is None
        assert body["errors"][0]["message"] == "Authentication required"

    def test_the_context_really_is_a_dict_with_request_as_a_key(self):
        """Pins the premise, so the fix is not 'simplified' back to getattr."""
        import asyncio

        from api.graphql_schema import _get_context

        context = asyncio.run(_get_context())
        assert isinstance(context, dict)
        assert getattr(context, "request", None) is None, (
            "attribute access on the context returns nothing — that is the bug"
        )


@pytest.mark.unit
class TestErrorsReachTheClientFormatted:
    """S-16: ``_format_error`` was defined but wired to nothing.

    Neither ``strawberry.Schema`` nor ``GraphQLRouter`` accepts an
    error-formatter argument, so the function was never called: no
    ``error_code`` extension reached any client, and the "hide internal
    messages unless DEBUG=true" branch never ran. The router now applies it in
    ``process_result``.
    """

    def test_unauthorized_error_code_reaches_the_client(self):
        body = (
            TestTheApiActuallyAnswers._client()
            .post("/graphql", json={"query": TestTheApiActuallyAnswers._QUERY})
            .json()
        )

        extensions = body["errors"][0].get("extensions") or {}
        assert extensions.get("error_code") == "UNAUTHORIZED", (
            f"no error_code in {extensions} — _format_error is not wired into the response path (S-16)."
        )

    def test_the_router_subclass_is_the_one_mounted(self):
        from api.graphql_schema import _FormattingGraphQLRouter, graphql_router

        assert isinstance(graphql_router, _FormattingGraphQLRouter)

    def test_internal_errors_are_masked_outside_debug(self, monkeypatch):
        monkeypatch.setenv("DEBUG", "false")
        from api.graphql_schema import _format_error

        class _Err:
            original_error = KeyError("secret_internal_detail")

        formatted = _format_error(_Err(), lambda _e: {"message": "secret_internal_detail"})
        assert formatted["message"] == "An internal error occurred"
        assert formatted["extensions"]["error_code"] == "INTERNAL_ERROR"

    def test_graphiql_is_disabled_in_production(self, monkeypatch):
        import importlib

        monkeypatch.setenv("APP_ENV", "production")
        import api.graphql_schema as module

        module = importlib.reload(module)
        assert module._graphql_ide is None, "the GraphiQL IDE exposes the full schema without authentication"
        monkeypatch.setenv("APP_ENV", "test")
        importlib.reload(module)


# ── S-14: unreachable code ───────────────────────────────────────────────────

# Scanned packages. The repo root's own *.py entry points are included; the
# virtualenv, node_modules and generated trees are not.
_PACKAGES = (
    "api",
    "auth",
    "core",
    "risk",
    "execution",
    "ml",
    "strategies",
    "data_layer",
    "brokers",
    "market_data",
    "mobile",
    "social",
    "compliance",
    "database",
    "infrastructure",
    "backtesting",
    "monitoring",
)

# `raise` immediately followed by `yield` is the documented idiom for making a
# stub an (async) generator so FastAPI treats it as a yield-dependency. The
# yield is genuinely unreachable and genuinely required.
_ALLOWED = {("database/connection.py", "generator stub: raise then yield")}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for package in _PACKAGES:
        directory = _REPO_ROOT / package
        if directory.is_dir():
            files.extend(directory.rglob("*.py"))
    files.extend(_REPO_ROOT.glob("*.py"))
    return files


def _unreachable_sites(path: Path) -> list[tuple[int, int]]:
    """(line of the terminating statement, dead line count) for one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []

    sites: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for index, statement in enumerate(block[:-1]):
                if not isinstance(statement, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                    continue
                dead = block[index + 1 :]
                if all(isinstance(d, ast.Pass) for d in dead):
                    continue
                # The generator-stub idiom: a lone `yield` after a `raise`.
                if (
                    isinstance(statement, ast.Raise)
                    and len(dead) == 1
                    and isinstance(dead[0], ast.Expr)
                    and isinstance(dead[0].value, ast.Yield)
                ):
                    continue
                lines = sum(getattr(d, "end_lineno", d.lineno) - d.lineno + 1 for d in dead)
                sites.append((statement.lineno, lines))
                break
    return sites


@pytest.mark.unit
class TestNoUnreachableCode:
    def test_the_scan_covers_a_meaningful_number_of_files(self):
        files = _python_files()
        assert len(files) > 300, (
            f"only {len(files)} files scanned — the package list is stale and "
            "this test is checking far less than it appears to."
        )

    def test_the_detector_finds_a_known_pattern(self):
        """Guard against a scanner that silently matches nothing."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "sample.py"
            sample.write_text("def f():\n    return 1\n    return 2\n", encoding="utf-8")
            assert _unreachable_sites(sample), "the detector does not detect anything"

    def test_no_statement_follows_a_return_or_raise(self):
        offenders = []
        for path in _python_files():
            for lineno, dead_lines in _unreachable_sites(path):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno} ({dead_lines} dead lines)")

        assert not offenders, (
            "unreachable code found: "
            + ", ".join(sorted(offenders))
            + ". Ruff has no rule for this here, so it goes unnoticed — "
            "`Query.trades` hid a 44-line database fallback behind a `return` "
            "for long enough that the query answered 'no trades' whenever the "
            "broker was not attached (S-14)."
        )
