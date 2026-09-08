# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The caller check — Group 3 Chapters 13 and 14.

`verify()` proves an evidence locator resolves. It has no opinion about whether
anything calls it, and that gap produced a real defect: a worker runtime marked
live while imported by nothing outside its own tests.

## The test that matters most is the one about the sweep itself

The first version of this sweep reported **154 dead capabilities having read no
files at all** — `rg` was given no path from a process whose stdin was a file at
EOF, so it searched stdin, found nothing, and every row looked dead. It was
caught only because a symbol known to be mounted in `App.tsx` came back with
zero references.

So the first assertion here is not about capabilities. It is that a broken sweep
**raises** rather than returning a clean-looking answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.capability_callers import (
    CONTROL_SYMBOL,
    Row,
    SweepBroken,
    assert_sweep_works,
    sweep,
)

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parent.parent.parent


class TestTheSweepProvesItIsReadingTheRepository:
    def test_the_control_symbol_is_found(self) -> None:
        assert assert_sweep_works(REPO) >= 2

    def test_a_sweep_that_finds_nothing_raises_rather_than_reporting_clean(self, tmp_path: Path) -> None:
        # THE test. An empty directory stands in for every way a sweep can end up
        # examining nothing — the wrong path, a swallowed error, ripgrep reading
        # stdin. Each produces the same output: no findings, which reads as good
        # news. Raising is the only safe response.
        with pytest.raises(SweepBroken, match=CONTROL_SYMBOL):
            assert_sweep_works(tmp_path)

    def test_sweep_itself_refuses_on_a_broken_repository(self, tmp_path: Path) -> None:
        # The guard existing is not the guard running. Removing the
        # `assert_sweep_works` call from `sweep()` left every other test in this
        # file passing — a control present and never invoked, which is the exact
        # defect this module was written to detect, committed inside it.
        with pytest.raises(SweepBroken):
            sweep(tmp_path)

    def test_the_refusal_says_why_rather_than_only_that(self, tmp_path: Path) -> None:
        try:
            assert_sweep_works(tmp_path)
        except SweepBroken as exc:
            assert "meaningless" in str(exc)
        else:  # pragma: no cover - the test above already pins this
            pytest.fail("a broken sweep did not raise")


class TestItDistinguishesCalledFromUncalled:
    def test_a_row_with_one_production_file_is_flagged(self) -> None:
        # One file is the definition itself. A capability nothing else names is
        # the shape that let `run_isolated` sit live with no caller.
        assert Row("x", "1", "s", production_files=1, any_files=3).uncalled

    def test_a_row_named_by_two_or_more_production_files_is_not(self) -> None:
        assert not Row("x", "1", "s", production_files=2, any_files=2).uncalled

    def test_zero_production_files_is_flagged(self) -> None:
        assert Row("x", "1", "s", production_files=0, any_files=1).uncalled


class TestTheLiveSweep:
    def test_it_screens_a_substantial_number_of_rows(self) -> None:
        # A sweep that screened three rows would pass every other test here while
        # measuring nothing. The registry carries 230+ live rows and well over a
        # hundred name a symbol.
        rows = sweep(REPO)
        assert len(rows) > 100

    def test_the_known_dead_control_is_no_longer_dead(self) -> None:
        # `run_isolated` was the defect that motivated this whole check. It has a
        # caller now — `JobRunner.submit_isolated` — and this test is the
        # regression guard for that specific row.
        rows = {r.symbol: r for r in sweep(REPO)}
        assert "run_isolated" in rows
        assert not rows["run_isolated"].uncalled, "run_isolated lost its production caller again"

    def test_the_flagged_set_is_a_minority(self) -> None:
        # If most rows were flagged the screen would be measuring something other
        # than what it claims, exactly as the 154-finding version was.
        rows = sweep(REPO)
        flagged = [r for r in rows if r.uncalled]
        assert len(flagged) < len(rows) / 2
