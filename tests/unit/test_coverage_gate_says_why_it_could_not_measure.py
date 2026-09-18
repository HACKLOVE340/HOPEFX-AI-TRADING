"""An unmeasured module is not a module below the floor.

`_run_coverage` returns ``(None, reason)`` and the reason distinguishes two very
different failures:

    "Coverage check timed out for run.py"     the gate ran out of its 600s budget
    <pytest output>                           the run happened and produced no row

`main` printed that reason as raw output but never passed it to `_judge`, so the
VERDICT always read:

    coverage could not be measured (74 test files, ...) —
    the test may not import the module, or may fail to collect

For `run.py` that advice is simply wrong. The module is imported by 74 resolved
test files; nothing is missing. The gate timed out, and a reader following the
message goes looking for an import that is already there.

The summary line then said ``N module(s) below 80% coverage threshold`` for a
module whose coverage nobody knows. Rule 2 — an unmeasured value is absent,
never zero — applied to the gate's own report.

Found while recording `run.py` as debt under ADR 0017, which is what made the
conflation visible: the entry had to explain in prose what the gate should have
said itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _judge(**kw):
    from scripts.pre_commit_coverage import _judge as judge

    kw.setdefault("module_path", Path("run.py"))
    kw.setdefault("test_path", Path("tests/unit/test_x.py"))
    kw.setdefault("recorded", False)
    return judge(**kw)


class TestATimeoutSaysSo:
    def test_a_timeout_is_not_reported_as_a_missing_import(self):
        v = _judge(pct=None, unmeasured_reason="Coverage check timed out for run.py", test_count=74)
        assert "timed out" in v.message.lower()
        assert "may not import the module" not in v.message, (
            "a timeout was reported as a probable missing import, which sends the reader to "
            "look for something that is already there"
        )

    def test_a_timeout_names_the_real_remedy(self):
        """74 resolved test files is the cause; the module's size is not."""
        v = _judge(pct=None, unmeasured_reason="Coverage check timed out for run.py", test_count=74)
        assert "74" in v.message

    def test_a_genuine_collection_failure_keeps_its_advice(self):
        """The old message is right for the case it was written for."""
        v = _judge(pct=None, unmeasured_reason="ERROR collecting tests/unit/test_x.py", test_count=1)
        assert "may not import the module" in v.message

    def test_no_reason_at_all_keeps_the_old_message(self):
        """Backward compatibility: `_judge` is called without a reason elsewhere."""
        v = _judge(pct=None, test_count=1)
        assert "could not be measured" in v.message


class TestUnmeasuredIsItsOwnState:
    def test_an_unmeasured_module_is_marked_unmeasured(self):
        v = _judge(pct=None, unmeasured_reason="Coverage check timed out for run.py")
        assert v.unmeasured is True

    def test_a_module_below_the_floor_is_not_marked_unmeasured(self):
        v = _judge(pct=41.0)
        assert v.unmeasured is False
        assert not v.ok

    def test_a_passing_module_is_not_marked_unmeasured(self):
        v = _judge(pct=95.0)
        assert v.unmeasured is False
        assert v.ok

    def test_recorded_debt_that_is_unmeasured_still_says_unmeasured(self):
        """`run.py`'s own case: recorded, so it does not block, but still not a
        number anyone knows."""
        v = _judge(pct=None, unmeasured_reason="Coverage check timed out for run.py", recorded=True)
        assert v.ok, "a recorded module must not block"
        assert v.unmeasured is True


class TestTheSummaryDoesNotClaimAMeasurement:
    def test_the_summary_separates_unmeasured_from_below_floor(self, monkeypatch, capsys, tmp_path):
        """`N module(s) below 80%` about a module nobody measured is the gate
        telling the same lie it exists to catch."""
        import scripts.pre_commit_coverage as gate

        module = tmp_path / "thing.py"
        module.write_text("x = 1\n", encoding="utf-8")
        test = tmp_path / "test_thing.py"
        test.write_text("def test_x():\n    assert True\n", encoding="utf-8")

        monkeypatch.setattr(gate, "_find_test_files", lambda p: [test])
        monkeypatch.setattr(gate, "_load_baseline", lambda: frozenset())
        monkeypatch.setattr(gate, "_coveragerc_omits", lambda p, **k: False)
        monkeypatch.setattr(gate, "_run_coverage", lambda p, t: (None, f"Coverage check timed out for {p}"))

        rc = gate.main([str(module)])
        err = capsys.readouterr().err

        assert rc != 0
        assert "could not be measured" in err or "unmeasured" in err.lower()
        assert "1 module(s) below" not in err, "the summary claimed a measurement it never took"
