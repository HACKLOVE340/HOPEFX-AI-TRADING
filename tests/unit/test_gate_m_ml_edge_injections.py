# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate M — the guard that notices when the ML edge disappears.

It runs an A/B against a rule baseline on a leakage-safe out-of-sample split and
fails when the model stops winning. It had no test.

## A skip is not a pass — the defect this file exists for

The gate exited **0** when its dataset was missing:

    $ AB_CSV=data/does_not_exist.csv python scripts/ci/gate_m_ml_edge.py
    Gate M SKIPPED — dataset not found: data/does_not_exist.csv
    $ echo $?
    0

That was deliberate, to avoid flakiness, and it was the wrong trade. The dataset
is **committed to this repository** — 478 KB, tracked — so it is present in every
checkout, and its absence means a rename, a deletion or a mis-set `AB_CSV`, not
an environmental quirk. A gate that measures nothing and reports success is the
exact shape of control this codebase has now found eight times.

It fails closed now, with `AB_ALLOW_SKIP=1` as an explicit local opt-out. Rule 2:
an unmeasured value is absent, never zero — and "the ML edge is intact" must not
look identical to "nobody checked".

## Thresholds are proven live, not assumed

Setting an impossible floor must fail. Otherwise the comparison is decorative and
a real regression would pass just as quietly.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_m_ml_edge.py"
DATASET = REPO / "data" / "XAUUSD_40Y.csv"


def _run(**env: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(env)
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(GATE)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


class TestTheDatasetIsCommittedSoAbsenceIsADefect:
    """The premise the fail-closed decision rests on. If the dataset stops being
    tracked, that decision needs revisiting and this test is the trigger."""

    def test_the_dataset_is_present(self) -> None:
        assert DATASET.exists(), f"{DATASET.relative_to(REPO)} is missing"

    def test_the_dataset_is_tracked_by_git(self) -> None:
        result = subprocess.run(  # nosec B603 — fixed argument list, no shell
            ["git", "ls-files", "--error-unmatch", str(DATASET.relative_to(REPO))],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            "the A/B dataset is no longer tracked by git. Gate M fails closed on a missing "
            "dataset because it is committed; if that changed, revisit AB_ALLOW_SKIP."
        )


class TestAnUnmeasuredRunIsNotAPass:
    def test_a_missing_dataset_fails_the_gate(self) -> None:
        result = _run(AB_CSV="data/does_not_exist.csv", AB_ALLOW_SKIP="")
        assert result.returncode != 0, "a missing dataset exited 0 — the ML edge guard is off and CI is green"
        assert "could not measure" in result.stdout

    def test_the_documented_opt_out_still_skips(self) -> None:
        # The other half: the escape hatch has to work, or people delete the
        # check instead of setting the variable.
        result = _run(AB_CSV="data/does_not_exist.csv", AB_ALLOW_SKIP="1")
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
    def test_the_opt_out_accepts_the_obvious_spellings(self, value: str) -> None:
        assert _run(AB_CSV="data/nope.csv", AB_ALLOW_SKIP=value).returncode == 0

    @pytest.mark.parametrize("value", ["0", "false", "no", ""])
    def test_anything_else_does_not_open_the_hatch(self, value: str) -> None:
        assert _run(AB_CSV="data/nope.csv", AB_ALLOW_SKIP=value).returncode != 0


class TestMalformedThresholdsAreRefused:
    @pytest.mark.parametrize(
        ("env", "value"),
        [("AB_MIN_ML_ACC", "not-a-number"), ("AB_MIN_LIFT", "nan"), ("AB_MIN_ML_ACC", "1.5")],
    )
    def test_a_threshold_that_cannot_be_honoured_fails_fast(self, env: str, value: str) -> None:
        result = _run(**{env: value})
        assert result.returncode != 0, f"{env}={value} was accepted"


@pytest.mark.slow
class TestTheThresholdComparisonIsLive:
    """Runs the real A/B, so it is marked slow. Without this the fast tests above
    prove only that the gate refuses bad input — not that it ever compares
    anything, which is the thing it exists to do."""

    def test_an_unreachable_accuracy_floor_fails(self) -> None:
        result = _run(AB_MIN_ML_ACC="0.99")
        assert result.returncode != 0, "an impossible accuracy floor passed — the threshold is decorative"

    def test_an_unreachable_lift_floor_fails(self) -> None:
        assert _run(AB_MIN_LIFT="0.99").returncode != 0

    def test_the_real_thresholds_pass(self) -> None:
        # The positive control. Both tests above pass against a gate wired to
        # fail unconditionally.
        result = _run()
        assert result.returncode == 0, result.stdout[-800:]
        assert "PASSED" in result.stdout
