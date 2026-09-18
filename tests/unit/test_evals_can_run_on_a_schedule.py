# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""An eval suite that can run itself, without becoming a way to spend money.

The gate bounds a report at 24 hours and nothing runs the suite automatically,
so canary promotion is blocked for most of any given day unless somebody
remembers. That is the pressure that gets a staleness bound raised to a month.

But `ai/evals/runner.py` says why it was manual, and it is right: *"Every case
is a paid model call through the gateway... A startup that quietly spends money
is hard to notice and harder to stop."* So the schedule is built to that
constraint rather than around it:

* **Off unless explicitly enabled.** No env var, no schedule. A deployment that
  does nothing spends nothing.
* **It does not run at startup.** The first run is one interval in. Otherwise
  every restart is a purchase, and a crash-looping deployment is a bill.
* **The ceiling is consulted first.** The one path that makes six calls in a
  row must not be the one path that runs past the budget.
* **A failed run does not stop the schedule**, and it logs at ERROR — the gate's
  evidence going stale is not a debug detail.

These tests fail on the pre-fix tree — `ai.evals.schedule` does not exist there.
"""

from __future__ import annotations


import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from ai.gateway import budget

    monkeypatch.delenv("AI_EVAL_SCHEDULE_HOURS", raising=False)
    budget.reset_for_testing()
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)
    yield
    budget.reset_for_testing()


class _Stop(Exception):
    """Ends the loop from inside the injected sleep."""


def _sleeper(times: int):
    """A sleep that lets the loop turn `times` times, then stops it."""
    calls = {"n": 0}

    async def sleep(_seconds):
        calls["n"] += 1
        if calls["n"] > times:
            raise _Stop

    sleep.calls = calls  # type: ignore[attr-defined]
    return sleep


# ── off by default ────────────────────────────────────────────────────────────


def test_the_schedule_is_off_unless_it_is_switched_on():
    from ai.evals import schedule

    assert schedule.interval_s() is None, "an unconfigured deployment would start spending"


@pytest.mark.parametrize("value", ["0", "-4", "", "  ", "soon", "NaN", "inf", "-inf"])
def test_a_value_that_is_not_a_positive_number_leaves_it_off(monkeypatch, value):
    """Not a crash, and above all not a zero-second interval — a tight loop of
    paid model calls is the worst possible reading of a typo."""
    from ai.evals import schedule

    monkeypatch.setenv("AI_EVAL_SCHEDULE_HOURS", value)
    assert schedule.interval_s() is None


def test_a_positive_number_of_hours_is_read_as_seconds(monkeypatch):
    from ai.evals import schedule

    monkeypatch.setenv("AI_EVAL_SCHEDULE_HOURS", "6")
    assert schedule.interval_s() == pytest.approx(6 * 3600)


# ── the loop ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_it_does_not_run_at_startup():
    """Otherwise every restart is a purchase, and a crash-loop is a bill."""
    from ai.evals import schedule

    ran: list[int] = []
    sleep = _sleeper(0)
    with pytest.raises(_Stop):
        await schedule.run_forever(60.0, run=lambda: ran.append(1), sleep=sleep)
    assert ran == [], "the suite ran before the first interval elapsed"


@pytest.mark.asyncio
async def test_it_runs_once_per_interval():
    from ai.evals import schedule

    ran: list[int] = []
    with pytest.raises(_Stop):
        await schedule.run_forever(60.0, run=lambda: ran.append(1), sleep=_sleeper(3))
    assert len(ran) == 3


@pytest.mark.asyncio
async def test_a_failed_run_does_not_stop_the_schedule(caplog):
    """A vendor outage must not silently end automatic evals — the gate would
    then go stale with nothing saying why."""
    import logging

    from ai.evals import schedule

    attempts: list[int] = []

    def explode():
        attempts.append(1)
        raise RuntimeError("every vendor is down")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(_Stop):
            await schedule.run_forever(60.0, run=explode, sleep=_sleeper(3))

    assert len(attempts) == 3, "the loop stopped at the first failure"
    assert any(r.levelno >= logging.ERROR for r in caplog.records), (
        "a failed eval run was not logged loudly enough to notice"
    )


# ── it is a spender, and behaves like one ─────────────────────────────────────


@pytest.mark.asyncio
async def test_a_run_is_skipped_when_the_ceiling_is_already_reached():
    """The one path that makes six calls in a row must not be the one that runs
    past the budget."""
    from ai.evals import budgeted_run, schedule
    from ai.gateway import budget

    budget.set_limits(per_operator_usd=0.0, global_usd=0.0)
    ran: list[int] = []
    assert budgeted_run(run=lambda: ran.append(1)) is False
    assert ran == [], "an eval run started with no budget left"
    assert schedule is not None


@pytest.mark.asyncio
async def test_a_run_proceeds_when_there_is_budget():
    from ai.evals import budgeted_run

    ran: list[int] = []
    assert budgeted_run(run=lambda: ran.append(1)) is True
    assert ran == [1]


# ── wiring ────────────────────────────────────────────────────────────────────


def test_a_startup_factory_exists_and_is_registered():
    import pathlib

    import core.startup_factories as F

    assert hasattr(F, "init_ai_eval_schedule")
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    assert "F.init_ai_eval_schedule" in src, "the factory is defined but never registered"
    assert "F.init_ai_eval_store" in src, "nothing installs the durable report store"


@pytest.mark.asyncio
async def test_the_factory_starts_nothing_when_the_schedule_is_off(monkeypatch):
    from types import SimpleNamespace

    import core.startup_factories as F

    state = SimpleNamespace(background_tasks=[])
    assert await F.init_ai_eval_schedule(state) is None
    assert state.background_tasks == [], "an unconfigured deployment started a paid loop"
