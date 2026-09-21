# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_kill_switch_broadcast_visibility.py
====================================================
Regression tests for finding R-05: a kill switch that halts one pod and never
tells the others, quietly.

``_write_redis_latch`` writes the key every other pod reads to halt itself. It
had two failure paths and neither was visible:

  * ``_get_latch_redis()`` swallows every exception and returns ``None``. The
    write was guarded by ``if r is not None:`` with no ``else``, so a Redis that
    could not be reached produced **no write and no log line at all** — the
    quietest possible failure for the loudest possible control.
  * The exception path logged at ``warning`` and described itself as
    "(non-fatal)". It is not. This pod has stopped trading and the others have
    not been told; they keep trading against a book the operator believes is
    flat.

That outcome already has a name in this repo's history: S2-01, "Split-brain kill
switch", rated CRITICAL. It was reached then by having two KillSwitch instances;
an unwritable latch reaches the same place by a different route.

Neither path may raise — the local halt has already succeeded, and throwing
would unwind the one stop that did work. So the requirement is visibility:
CRITICAL in the log, and a flag on ``status()`` because an operator checking
kill-switch state must be able to see the halt was local-only.
"""

from __future__ import annotations

import logging

import pytest

from kill_switch import KillSwitch


@pytest.fixture
def switch(tmp_path):
    # state_file is derived from flag_file, not passed separately.
    return KillSwitch(flag_file=tmp_path / "kill.flag")


@pytest.mark.unit
class TestBroadcastFailureIsVisible:
    def test_status_exposes_the_broadcast_flag(self, switch):
        assert "latch_broadcast_ok" in switch.status(), (
            "An operator reading kill-switch status must be able to tell whether the halt reached other pods (R-05)."
        )

    def test_untouched_switch_reports_none_not_false(self, switch):
        """None means 'not attempted' — distinct from 'attempted and failed'."""
        assert switch.status()["latch_broadcast_ok"] is None

    def test_no_redis_client_is_critical_not_silent(self, switch, monkeypatch, caplog):
        """The `r is None` path previously wrote nothing and logged nothing."""
        monkeypatch.setattr(switch, "_get_latch_redis", lambda: None)
        with caplog.at_level(logging.CRITICAL, logger="kill_switch"):
            switch._write_redis_latch("test reason")

        assert switch.status()["latch_broadcast_ok"] is False
        assert any(r.levelno >= logging.CRITICAL for r in caplog.records), (
            "An unreachable Redis must be CRITICAL — other pods are still trading (R-05)."
        )

    def test_write_failure_is_critical(self, switch, monkeypatch, caplog):
        class _Boom:
            def set(self, *a, **k):
                raise ConnectionError("redis is down")

        monkeypatch.setattr(switch, "_get_latch_redis", lambda: _Boom())
        with caplog.at_level(logging.CRITICAL, logger="kill_switch"):
            switch._write_redis_latch("test reason")

        assert switch.status()["latch_broadcast_ok"] is False
        assert any(r.levelno >= logging.CRITICAL for r in caplog.records)

    def test_failure_does_not_raise(self, switch, monkeypatch):
        """The local halt already succeeded; throwing would unwind it."""
        monkeypatch.setattr(switch, "_get_latch_redis", lambda: None)
        switch._write_redis_latch("test reason")  # must not raise

    def test_successful_write_sets_the_flag_true(self, switch, monkeypatch):
        written: dict = {}

        class _OK:
            def set(self, key, value, ex=None):
                written[key] = value

        monkeypatch.setattr(switch, "_get_latch_redis", lambda: _OK())
        switch._write_redis_latch("halt: drawdown breach")

        assert switch.status()["latch_broadcast_ok"] is True
        assert written, "the latch keys must actually be written on the success path"

    def test_the_word_non_fatal_is_gone_from_the_write_path(self):
        """Naming a split-brain 'non-fatal' is how it got ignored."""
        import ast
        import inspect
        import textwrap

        # Parse rather than string-split: the docstring quotes the old wording to
        # explain it, so any naive slice still matches it.
        tree = ast.parse(textwrap.dedent(inspect.getsource(KillSwitch._write_redis_latch)))
        node = tree.body[0]
        stmts = node.body
        if (
            stmts
            and isinstance(stmts[0], ast.Expr)
            and isinstance(stmts[0].value, ast.Constant)
            and isinstance(stmts[0].value.value, str)
        ):
            stmts = stmts[1:]
        body = "\n".join(ast.unparse(st) for st in stmts)
        assert "non-fatal" not in body, "A failure to broadcast the kill switch is not non-fatal (R-05)."
