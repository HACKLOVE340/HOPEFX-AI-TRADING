# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The brute-force throttle on /api/auth/change-password.

`current_password` makes this a credential-guessing surface: a stolen access
token is a session, but the password is the account, so an attacker holding a
token guesses the password to take the account permanently. The throttle is
what stands between those two states.

The existing suite for this route asserts **source text** — that the module
does not name a column, that it imports the right helper. None of it runs the
throttle, so nothing here has ever shown that a second attempt is counted, let
alone a hundredth (F176: a control that exists and never runs).

Two properties, and the second is the one that was wrong:

* **Attempts are counted and refused.** Proven by making them.
* **A throttle that could not run says so where someone will see it.** The
  route wraps the limiter in `except Exception` and continues — deliberately,
  because failing closed would lock every user out of their own password reset
  whenever the limiter hiccups. That trade is defensible. Logging it at DEBUG
  is not: DEBUG is off in production, so the one moment this endpoint is
  unprotected is the one moment nobody is told (F248).
"""

from __future__ import annotations

import logging
import types

import pytest

pytestmark = [pytest.mark.unit]


class _Req:
    def __init__(self, ip: str = "198.51.100.7"):
        self.client = types.SimpleNamespace(host=ip)
        self.headers: dict[str, str] = {}


def _user(uid: str = "user-1"):
    return types.SimpleNamespace(sub=uid)


def _body(current: str = "wrong-guess", new: str = "a-long-enough-password"):
    from api.settings_extended import ChangePasswordBody

    return ChangePasswordBody(current_password=current, new_password=new)


class _Session:
    """The three operations the route performs on a session."""

    def __init__(self, row):
        self._row = row
        self.committed = False

    def query(self, _model):
        return self

    def filter_by(self, **_k):
        return self

    def first(self):
        return self._row

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture
def working_db(monkeypatch):
    """Make the DB path succeed, so a request that is NOT throttled really does
    reach the password comparison.

    Without this the route dies at the circuit breaker and `verify_password` is
    never called on any path — which makes "the throttle prevented the compare"
    true for the wrong reason, whether or not a throttle exists (F255).
    """
    import database.connection as dbc

    row = types.SimpleNamespace(id="user-1", hashed_password="stored-hash")
    session = _Session(row)
    mgr = types.SimpleNamespace(session=lambda: session)
    monkeypatch.setattr(dbc, "get_db_manager", lambda: mgr)
    return session


@pytest.fixture
def limiter(monkeypatch):
    """A clean in-memory limiter with a small, explicit budget."""
    from auth import router as ar

    monkeypatch.setenv("AUTH_RATE_LIMIT_REQUESTS", "3")
    monkeypatch.setenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(ar, "_rl_redis", None)
    monkeypatch.setattr(ar, "_rl_redis_probed", True)
    ar._ip_windows.clear()
    yield ar
    ar._ip_windows.clear()


class TestTheThrottleActuallyCounts:
    @pytest.mark.asyncio
    async def test_a_burst_of_guesses_from_one_ip_is_refused(self, limiter):
        from fastapi import HTTPException

        from api.settings_extended import change_password

        req = _Req()
        refusals = 0
        for _ in range(6):
            try:
                await change_password(_body(), req, _user())
            except HTTPException as exc:
                if exc.status_code == 429:
                    refusals += 1

        assert refusals >= 2, "an unlimited number of password guesses were accepted"

    @pytest.mark.asyncio
    async def test_a_different_ip_has_its_own_budget(self, limiter):
        from fastapi import HTTPException

        from api.settings_extended import change_password

        exhausted = False
        for _ in range(6):
            try:
                await change_password(_body(), _Req("198.51.100.7"), _user())
            except HTTPException as exc:
                exhausted = exhausted or exc.status_code == 429

        # Liveness: the negative below means nothing unless the first address
        # really was locked out.
        assert exhausted, "the first address was never throttled, so this proves nothing"

        try:
            await change_password(_body(), _Req("203.0.113.4"), _user())
            refused = False
        except HTTPException as exc:
            refused = exc.status_code == 429

        assert not refused, "one IP's burst locked out an unrelated address"

    @pytest.mark.asyncio
    async def test_a_refused_attempt_never_reaches_the_hash_compare(self, limiter, working_db, monkeypatch):
        """Otherwise the 429 costs a bcrypt verify each time, and the throttle
        becomes an amplifier rather than a brake.

        `working_db` is load-bearing: without it the route dies before the
        compare on every path, and this assertion holds against a route with no
        throttle at all.
        """
        import auth.jwt as ajwt
        from fastapi import HTTPException

        from api.settings_extended import change_password

        verifies = {"n": 0}

        def _counting_verify(*_a, **_k):
            verifies["n"] += 1
            return False

        monkeypatch.setattr(ajwt, "verify_password", _counting_verify)

        req = _Req()
        refusals = 0
        for _ in range(8):
            try:
                await change_password(_body(), req, _user())
            except HTTPException as exc:
                refusals += exc.status_code == 429

        # Liveness first: the compare must be reachable at all.
        assert verifies["n"] >= 1, "the harness never reached the compare — the count below means nothing"
        assert refusals >= 1, "nothing was refused, so there is no short-circuit to observe"
        assert verifies["n"] + refusals == 8, (
            f"{8 - verifies['n'] - refusals} attempts neither compared nor were refused"
        )
        assert verifies["n"] <= 4, f"the refused attempts still ran {verifies['n']} password verifications"


class TestAThrottleThatCouldNotRunSaysSo:
    """F248. The handler is the only thing that knows the endpoint just served
    an unthrottled credential guess. At DEBUG it tells nobody."""

    @pytest.fixture
    def broken_limiter(self, monkeypatch):
        from auth import router as ar

        def _boom(_ip):
            raise RuntimeError("limiter backend exploded")

        monkeypatch.setattr(ar, "_check_ip_rate_limit", _boom)

    @pytest.mark.asyncio
    async def test_the_request_is_still_served(self, broken_limiter):
        """The deliberate half of the trade: a broken limiter must not lock a
        user out of changing their own password."""
        from fastapi import HTTPException

        from api.settings_extended import change_password

        try:
            await change_password(_body(), _Req(), _user())
            status = 200
        except HTTPException as exc:
            status = exc.status_code

        assert status != 429, "a limiter fault was reported to the user as rate limiting"

    @pytest.mark.asyncio
    async def test_the_failure_is_logged_at_error_not_debug(self, broken_limiter, caplog):
        from api.settings_extended import change_password
        from fastapi import HTTPException

        caplog.set_level(logging.INFO, logger="api.settings_extended")
        try:
            await change_password(_body(), _Req(), _user())
        except HTTPException:
            pass

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "the endpoint served an unthrottled password guess and logged nothing above DEBUG"

    @pytest.mark.asyncio
    async def test_the_message_says_what_did_not_happen(self, broken_limiter, caplog):
        """'rate limit unavailable' describes the tool. The operator needs to
        know the consequence: this request was not throttled."""
        from api.settings_extended import change_password
        from fastapi import HTTPException

        caplog.set_level(logging.INFO, logger="api.settings_extended")
        try:
            await change_password(_body(), _Req(), _user())
        except HTTPException:
            pass

        text = " ".join(r.getMessage().lower() for r in caplog.records if r.levelno >= logging.ERROR)
        assert "unthrottled" in text or "not throttled" in text, (
            f"the log names the fault but not its consequence: {text!r}"
        )
