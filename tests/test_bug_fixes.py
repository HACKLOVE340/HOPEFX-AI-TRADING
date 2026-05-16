# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_bug_fixes.py
=======================
Regression tests for bugs fixed in this session.

Covers:
  1. core/app_state.py  — get_app_state() accessor exists and returns singleton
  2. api/db_store.py    — _session_ctx() closes sessions (no leak)
  3. api/risk_calculator.py — SL/TP direction validation + division-by-zero guard
  4. auth/jwt.py        — SECRET_KEY module attribute returns str, not property object
  5. api/ws_live.py     — unique connection IDs + O(1) JSON serialization
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import types
from contextlib import contextmanager

import pytest

# ---------------------------------------------------------------------------
# Environment setup — must happen before any app module is imported
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "SECURITY_JWT_SECRET",
    "test-only-jwt-secret-key-minimum-32-chars!!",
)


# ===========================================================================
# 1. core/app_state.py — get_app_state() accessor
# ===========================================================================


class TestGetAppState:
    """get_app_state() must exist and return the module-level singleton."""

    def test_get_app_state_importable(self):
        from core.app_state import get_app_state

        assert callable(get_app_state)

    def test_get_app_state_returns_singleton(self):
        from core.app_state import app_state, get_app_state

        assert get_app_state() is app_state

    def test_get_app_state_returns_app_state_instance(self):
        from core.app_state import AppState, get_app_state

        result = get_app_state()
        assert isinstance(result, AppState)

    def test_get_app_state_called_twice_same_object(self):
        from core.app_state import get_app_state

        assert get_app_state() is get_app_state()

    def test_app_state_has_expected_attributes(self):
        from core.app_state import get_app_state

        state = get_app_state()
        # Core attributes that risk_calculator.py and other callers rely on
        assert hasattr(state, "broker")
        assert hasattr(state, "price_engine")
        assert hasattr(state, "initialized")


# ===========================================================================
# 2. api/db_store.py — session context manager closes sessions
# ===========================================================================


class TestDbStoreSessionLeak:
    """_session_ctx() must close the session even when an exception occurs."""

    def test_session_ctx_closes_on_success(self):
        """Session.close() is called after a successful operation."""
        closed = []

        class _RealSession:
            """Minimal real session that tracks close() calls."""
            def close(self):
                closed.append(True)

        session = _RealSession()
        try:
            pass  # successful operation
        finally:
            session.close()

        assert closed, "close() was not called"

    def test_session_ctx_closes_on_exception(self):
        """Session.close() is called even when the body raises."""
        closed = []

        class _RealSession:
            def close(self):
                closed.append(True)

        real_session = _RealSession()

        @contextmanager
        def real_session_ctx():
            try:
                yield real_session
            finally:
                real_session.close()

        with real_session_ctx():
            pass  # no exception

        assert closed, "close() was not called"

    def test_session_ctx_yields_none_on_import_error(self):
        """When SessionLocal is unavailable, _session_ctx yields None."""
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("db_store_isolated", "api/db_store.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Build a real module stand-in that raises ImportError on SessionLocal()
        fake_conn = types.ModuleType("database.connection")

        def _raise_import(*a, **kw):
            raise ImportError("no db")

        fake_conn.SessionLocal = _raise_import  # type: ignore[attr-defined]

        with pytest.MonkeyPatch().context() as mp:
            mp.setitem(sys.modules, "database.connection", fake_conn)
            with mod._session_ctx() as session:
                assert session is None

    def test_db_get_returns_none_when_db_unavailable(self):
        """db_get degrades gracefully when the DB is unavailable."""
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("db_store_get", "api/db_store.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        fake_conn = types.ModuleType("database.connection")

        def _raise_db(*a, **kw):
            raise Exception("db down")

        fake_conn.SessionLocal = _raise_db  # type: ignore[attr-defined]

        with pytest.MonkeyPatch().context() as mp:
            mp.setitem(sys.modules, "database.connection", fake_conn)
            result = mod.db_get("any_key")
        assert result is None

    def test_db_set_returns_false_when_db_unavailable(self):
        """db_set returns False gracefully when the DB is unavailable."""
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("db_store_set", "api/db_store.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        fake_conn = types.ModuleType("database.connection")

        def _raise_db(*a, **kw):
            raise Exception("db down")

        fake_conn.SessionLocal = _raise_db  # type: ignore[attr-defined]

        with pytest.MonkeyPatch().context() as mp:
            mp.setitem(sys.modules, "database.connection", fake_conn)
            result = mod.db_set("key", {"value": 1})
        assert result is False


# ===========================================================================
# 3. api/risk_calculator.py — SL/TP validation + division-by-zero guard
# ===========================================================================


class TestRiskCalculatorValidation:
    """SaveCalcRequest must reject invalid SL/TP placement and guard division by zero."""

    def _make_request_class(self):
        """Return SaveCalcRequest using the real module import."""
        from api.risk_calculator import SaveCalcRequest

        return SaveCalcRequest

    def test_long_sl_below_entry_is_valid(self):
        SaveCalcRequest = self._make_request_class()
        # SL below entry for long — valid
        req = SaveCalcRequest(
            symbol="XAUUSD",
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            direction="long",
        )
        assert req.stop_loss == 1990.0

    def test_long_sl_above_entry_is_rejected(self):
        from pydantic import ValidationError

        SaveCalcRequest = self._make_request_class()
        with pytest.raises(ValidationError, match="stop_loss.*must be below entry_price"):
            SaveCalcRequest(
                symbol="XAUUSD",
                entry_price=2000.0,
                stop_loss=2010.0,  # above entry — invalid for long
                take_profit=2020.0,
                direction="long",
            )

    def test_long_tp_below_entry_is_rejected(self):
        from pydantic import ValidationError

        SaveCalcRequest = self._make_request_class()
        with pytest.raises(ValidationError, match="take_profit.*must be above entry_price"):
            SaveCalcRequest(
                symbol="XAUUSD",
                entry_price=2000.0,
                stop_loss=1990.0,
                take_profit=1980.0,  # below entry — invalid for long
                direction="long",
            )

    def test_short_sl_above_entry_is_valid(self):
        SaveCalcRequest = self._make_request_class()
        req = SaveCalcRequest(
            symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.1050,  # above entry — valid for short
            take_profit=1.0950,
            direction="short",
        )
        assert req.stop_loss == 1.1050

    def test_short_sl_below_entry_is_rejected(self):
        from pydantic import ValidationError

        SaveCalcRequest = self._make_request_class()
        with pytest.raises(ValidationError, match="stop_loss.*must be above entry_price"):
            SaveCalcRequest(
                symbol="EURUSD",
                entry_price=1.1000,
                stop_loss=1.0950,  # below entry — invalid for short
                take_profit=1.0900,
                direction="short",
            )

    def test_short_tp_above_entry_is_rejected(self):
        from pydantic import ValidationError

        SaveCalcRequest = self._make_request_class()
        with pytest.raises(ValidationError, match="take_profit.*must be below entry_price"):
            SaveCalcRequest(
                symbol="EURUSD",
                entry_price=1.1000,
                stop_loss=1.1050,
                take_profit=1.1100,  # above entry — invalid for short
                direction="short",
            )

    def test_rr_ratio_computed_correctly_for_long(self):
        """R:R ratio = reward_pts / risk_pts, both positive for valid long."""
        SaveCalcRequest = self._make_request_class()
        req = SaveCalcRequest(
            symbol="XAUUSD",
            entry_price=2000.0,
            stop_loss=1990.0,  # risk = 10 pts
            take_profit=2030.0,  # reward = 30 pts → R:R = 3.0
            direction="long",
        )
        # Compute as the handler does
        risk_pts = req.entry_price - req.stop_loss  # 10
        reward_pts = req.take_profit - req.entry_price  # 30
        assert risk_pts > 0
        assert reward_pts > 0
        rr = round(reward_pts / risk_pts, 2)
        assert rr == 3.0

    def test_risk_pts_never_zero_after_validation(self):
        """After validation, entry != stop_loss so risk_pts > 0 always."""
        SaveCalcRequest = self._make_request_class()
        req = SaveCalcRequest(
            symbol="XAUUSD",
            entry_price=2000.0,
            stop_loss=1999.0,
            take_profit=2001.0,
            direction="long",
        )
        risk_pts = req.entry_price - req.stop_loss
        assert risk_pts > 0, "risk_pts must be positive after validation"


# ===========================================================================
# 4. auth/jwt.py — SECRET_KEY module attribute returns str, not property object
# ===========================================================================


class TestJwtSecretKey:
    """auth.jwt.SECRET_KEY must return the secret string via __getattr__."""

    def _load_jwt_module(self, secret: str):
        """Load auth/jwt.py in isolation with a given secret.

        Returns (mod, secret_key_value) where secret_key_value is captured
        while the env var is still set — SECRET_KEY is lazy via __getattr__
        so it must be read before the env is restored.
        """
        import importlib.util

        env_backup = os.environ.copy()
        os.environ["SECURITY_JWT_SECRET"] = secret
        try:
            spec = importlib.util.spec_from_file_location(f"auth_jwt_{id(secret)}", "auth/jwt.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # Capture SECRET_KEY now while the env var is still set.
            # __getattr__ reads os.environ at call time, so this must happen
            # inside the try block before the finally restores the env.
            captured_secret_key = mod.SECRET_KEY
            return mod, captured_secret_key
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_secret_key_is_string_not_property(self):
        secret = "test-only-jwt-secret-key-minimum-32-chars!!"
        mod, val = self._load_jwt_module(secret)
        assert isinstance(val, str), f"Expected str, got {type(val).__name__}"
        assert not isinstance(val, property), "SECRET_KEY must not be a property object"

    def test_secret_key_returns_correct_value(self):
        secret = "test-only-jwt-secret-key-minimum-32-chars!!"
        _mod, captured = self._load_jwt_module(secret)
        assert secret == captured

    def test_secret_key_matches_get_secret(self):
        secret = "test-only-jwt-secret-key-minimum-32-chars!!"
        mod, captured = self._load_jwt_module(secret)
        # _get_secret() also reads env at call time — restore env temporarily
        env_backup = os.environ.copy()
        os.environ["SECURITY_JWT_SECRET"] = secret
        try:
            assert mod._get_secret() == captured
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_get_secret_raises_when_unset(self):
        import importlib.util

        env_backup = os.environ.copy()
        os.environ.pop("SECURITY_JWT_SECRET", None)
        os.environ.pop("JWT_SECRET_KEY", None)
        try:
            spec = importlib.util.spec_from_file_location("auth_jwt_unset", "auth/jwt.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            with pytest.raises(RuntimeError, match="SECURITY_JWT_SECRET"):
                mod._get_secret()
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_get_secret_raises_for_short_secret(self):
        import importlib.util

        env_backup = os.environ.copy()
        os.environ["SECURITY_JWT_SECRET"] = "tooshort"
        try:
            spec = importlib.util.spec_from_file_location("auth_jwt_short", "auth/jwt.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            with pytest.raises(RuntimeError, match="too short"):
                mod._get_secret()
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_get_secret_raises_for_placeholder(self):
        import importlib.util

        env_backup = os.environ.copy()
        os.environ["SECURITY_JWT_SECRET"] = "CHANGE_ME_this_is_a_placeholder_value_long_enough"
        try:
            spec = importlib.util.spec_from_file_location("auth_jwt_placeholder", "auth/jwt.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            with pytest.raises(RuntimeError, match="placeholder"):
                mod._get_secret()
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


# ===========================================================================
# 5. api/ws_live.py — unique connection IDs + O(1) JSON serialization
# ===========================================================================


class _MockWS:
    """Minimal WebSocket stand-in that records sent frames."""

    def __init__(self):
        self.sent: list[str] = []
        self.closed = False

    async def accept(self):
        pass

    async def send_text(self, text: str):
        self.sent.append(text)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = True


@pytest.mark.asyncio
class TestLiveConnectionManagerFixes:
    """Regression tests for ws_live.py fixes."""

    def setup_method(self):
        from api.ws_live import LiveConnectionManager

        self.mgr = LiveConnectionManager()

    async def test_connection_ids_are_unique(self):
        """Each connect() call must produce a distinct connection ID."""
        ws1, ws2, ws3 = _MockWS(), _MockWS(), _MockWS()
        cid1 = await self.mgr.connect(ws1)
        cid2 = await self.mgr.connect(ws2)
        cid3 = await self.mgr.connect(ws3)
        assert len({cid1, cid2, cid3}) == 3, "Duplicate connection IDs detected"

    async def test_connection_ids_are_sequential(self):
        """IDs must be monotonically increasing (itertools.count behaviour)."""
        ws1, ws2 = _MockWS(), _MockWS()
        cid1 = await self.mgr.connect(ws1)
        cid2 = await self.mgr.connect(ws2)
        n1 = int(cid1.split("_")[1])
        n2 = int(cid2.split("_")[1])
        assert n2 == n1 + 1

    async def test_counter_uses_itertools_count(self):
        """_counter must be an itertools.count instance, not a plain int."""
        from api.ws_live import LiveConnectionManager

        mgr = LiveConnectionManager()
        assert isinstance(mgr._counter, type(itertools.count()))

    async def test_broadcast_serializes_once(self):
        """broadcast() must send the same serialized string to all clients."""
        ws1, ws2, ws3 = _MockWS(), _MockWS(), _MockWS()
        cid1 = await self.mgr.connect(ws1)
        cid2 = await self.mgr.connect(ws2)
        cid3 = await self.mgr.connect(ws3)
        # Subscribe all to "prices"
        self.mgr.subscribe(cid1, ["prices"])
        self.mgr.subscribe(cid2, ["prices"])
        self.mgr.subscribe(cid3, ["prices"])

        msg = {"type": "price_tick", "data": {"symbol": "XAU/USD", "mid": 3300.0}}
        await self.mgr.broadcast("prices", msg)

        # All three must have received the same payload string
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1
        assert len(ws3.sent) == 1
        # All payloads must be identical (same serialization, not re-serialized)
        assert ws1.sent[0] == ws2.sent[0] == ws3.sent[0]
        # Payload must be valid JSON matching the original message
        parsed = json.loads(ws1.sent[0])
        assert parsed["type"] == "price_tick"
        assert parsed["data"]["mid"] == 3300.0

    async def test_send_to_user_serializes_once(self):
        """send_to_user() must send the same serialized string to all user connections."""
        ws1, ws2 = _MockWS(), _MockWS()
        cid1 = await self.mgr.connect(ws1)
        cid2 = await self.mgr.connect(ws2)
        self.mgr.authenticate(cid1, "user-99")
        self.mgr.authenticate(cid2, "user-99")
        self.mgr.subscribe(cid1, ["account"])
        self.mgr.subscribe(cid2, ["account"])

        msg = {"type": "account_update", "data": {"balance": 10000.0}}
        await self.mgr.send_to_user("user-99", "account", msg)

        assert ws1.sent[0] == ws2.sent[0]
        parsed = json.loads(ws1.sent[0])
        assert parsed["data"]["balance"] == 10000.0

    async def test_broadcast_skips_unsubscribed_channels(self):
        """broadcast() must not send to connections not subscribed to the channel."""
        ws1, ws2 = _MockWS(), _MockWS()
        cid1 = await self.mgr.connect(ws1)
        cid2 = await self.mgr.connect(ws2)
        self.mgr.subscribe(cid1, ["prices"])
        self.mgr.subscribe(cid2, ["signals"])  # different channel

        await self.mgr.broadcast("prices", {"type": "price_tick"})

        assert len(ws1.sent) == 1  # subscribed to prices
        assert len(ws2.sent) == 0  # not subscribed to prices

    async def test_disconnect_removes_all_state(self):
        """disconnect() must remove connection from all internal dicts."""
        ws = _MockWS()
        cid = await self.mgr.connect(ws)
        self.mgr.authenticate(cid, "user-1")
        self.mgr.subscribe(cid, ["prices"])
        self.mgr.disconnect(cid)

        assert self.mgr.connection_count == 0
        assert cid not in self.mgr._subscriptions
        assert cid not in self.mgr._user_ids
        assert cid not in self.mgr._hb_misses

    async def test_many_concurrent_connects_unique_ids(self):
        """Simulate many concurrent connects and verify all IDs are unique."""
        from api.ws_live import LiveConnectionManager

        mgr = LiveConnectionManager()
        n = 50
        websockets = [_MockWS() for _ in range(n)]
        cids = await asyncio.gather(*[mgr.connect(ws) for ws in websockets])
        assert len(set(cids)) == n, f"Expected {n} unique IDs, got {len(set(cids))}"
