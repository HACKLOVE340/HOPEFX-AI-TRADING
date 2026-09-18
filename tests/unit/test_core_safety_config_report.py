# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`core/safety_config_report.py` — which safety gates is this process running?

The module answers one question at startup and on `/api/health/detailed`: of the
~20 flags that decide whether the system will refuse a trade, which are actually
protecting anything. It measured 0% under the per-module gate.

The property that matters here is not coverage. A report that says "everything
is fine" because it is structurally unable to say anything else is the F176
shape — `scripts/invariant_coverage.py` printed FULL COVERAGE while three of the
components it certified were provably unprotected. So the first test in this
file is that the report can fail at all, and the rest hold the paths by which it
does.
"""

from __future__ import annotations

import logging
import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.safety_config_report import (
    SAFETY_FLAGS,
    SafetyFlag,
    log_safety_config,
    resolve_safety_config,
)


class TestTheReportCanFail:
    """`hopefx-dead-controls` sub-shape 3: a measurement that cannot fail.

    A safety report is worth exactly as much as its ability to say "no". These
    hold that ability rather than any particular verdict.
    """

    def test_at_least_one_flag_declares_what_unsafe_looks_like(self) -> None:
        """With no `unsafe_when` anywhere, `unsafe_count` is a hardcoded zero
        wearing a measurement's clothes."""
        declaring = [f for f in SAFETY_FLAGS if f.unsafe_when]
        assert declaring, "no flag can ever report unsafe — the report cannot fail"

    def test_disarming_a_gate_is_reported(self, monkeypatch) -> None:
        """Proven by moving the real environment, not by reading the code."""
        monkeypatch.setenv("PAPER_TRADING", "true")
        before = resolve_safety_config()
        paper_before = next(f for f in before["flags"] if f["env_var"] == "PAPER_TRADING")
        assert paper_before["unsafe"] is False

        monkeypatch.setenv("PAPER_TRADING", "false")
        after = resolve_safety_config()
        paper_after = next(f for f in after["flags"] if f["env_var"] == "PAPER_TRADING")
        assert paper_after["unsafe"] is True
        assert after["unsafe_count"] > before["unsafe_count"]

    def test_every_declared_unsafe_value_actually_reports_unsafe(self, monkeypatch) -> None:
        """Each listed value is a claim the module makes about itself. A value
        in `unsafe_when` that does not trip `is_unsafe` is a gate documented as
        watched and not watched."""
        for flag in SAFETY_FLAGS:
            for value in flag.unsafe_when:
                monkeypatch.setenv(flag.env_var, value)
                assert flag.is_unsafe, f"{flag.env_var}={value!r} is listed unsafe but does not report unsafe"


class TestReadingOneFlag:
    def test_it_takes_the_environment_over_the_default(self, monkeypatch) -> None:
        flag = SafetyFlag("x", "HOPEFX_TEST_FLAG_A", "default-value")
        monkeypatch.setenv("HOPEFX_TEST_FLAG_A", "from-env")
        assert flag.resolved() == "from-env"

    def test_it_falls_back_to_the_default(self, monkeypatch) -> None:
        monkeypatch.delenv("HOPEFX_TEST_FLAG_A", raising=False)
        assert SafetyFlag("x", "HOPEFX_TEST_FLAG_A", "default-value").resolved() == "default-value"

    def test_a_flag_with_no_unsafe_values_is_never_unsafe(self, monkeypatch) -> None:
        """The numeric thresholds are in this position deliberately: there is no
        single unsafe value for `max drawdown pct`, so the report states it
        rather than judging it."""
        flag = SafetyFlag("x", "HOPEFX_TEST_FLAG_B", "5")
        monkeypatch.setenv("HOPEFX_TEST_FLAG_B", "anything at all")
        assert flag.is_unsafe is False

    @pytest.mark.parametrize("value", ["false", "FALSE", "False", "  false  ", "\tFalse\n"])
    def test_case_and_whitespace_do_not_hide_a_disarmed_gate(self, monkeypatch, value) -> None:
        """`PAPER_TRADING=FALSE ` must not read as protecting. An operator who
        types it in a shell with a trailing space has still disarmed it."""
        flag = SafetyFlag("x", "HOPEFX_TEST_FLAG_C", "true", unsafe_when=("false", "0"))
        monkeypatch.setenv("HOPEFX_TEST_FLAG_C", value)
        assert flag.is_unsafe is True

    def test_a_safe_value_is_not_reported_unsafe(self, monkeypatch) -> None:
        """The other direction. A report that cries wolf is switched off."""
        flag = SafetyFlag("x", "HOPEFX_TEST_FLAG_D", "true", unsafe_when=("false", "0"))
        monkeypatch.setenv("HOPEFX_TEST_FLAG_D", "true")
        assert flag.is_unsafe is False


class TestTheResolvedReport:
    def test_it_covers_every_declared_flag(self) -> None:
        report = resolve_safety_config()
        assert report["total"] == len(SAFETY_FLAGS)
        assert len(report["flags"]) == len(SAFETY_FLAGS)
        assert {f["env_var"] for f in report["flags"]} == {f.env_var for f in SAFETY_FLAGS}

    def test_it_distinguishes_a_set_value_from_a_default(self, monkeypatch) -> None:
        """`is_default` is the difference between "somebody chose this" and
        "nobody has looked at it", which is the whole point of the report."""
        monkeypatch.delenv("PAPER_TRADING", raising=False)
        assert next(f for f in resolve_safety_config()["flags"] if f["env_var"] == "PAPER_TRADING")["is_default"]

        monkeypatch.setenv("PAPER_TRADING", "true")
        assert not next(f for f in resolve_safety_config()["flags"] if f["env_var"] == "PAPER_TRADING")["is_default"]

    def test_the_counts_agree_with_the_rows(self, monkeypatch) -> None:
        """A count computed separately from the rows it counts is a count that
        can drift from them."""
        monkeypatch.setenv("PAPER_TRADING", "false")
        report = resolve_safety_config()
        assert report["unsafe_count"] == sum(1 for f in report["flags"] if f["unsafe"])
        assert report["explicit_count"] == sum(1 for f in report["flags"] if not f["is_default"])

    def test_every_row_carries_what_an_operator_needs(self) -> None:
        for row in resolve_safety_config()["flags"]:
            assert set(row) >= {"name", "env_var", "value", "is_default", "unsafe", "note"}
            assert row["name"] and row["env_var"]


class TestTheStartupLog:
    def test_a_disarmed_gate_is_logged_at_warning(self, monkeypatch, caplog) -> None:
        """INFO is where this would be invisible. The module's own docstring
        gives the reason: a gate left at its warn-only default looks identical
        in the logs to a gate that is passing legitimately."""
        monkeypatch.setenv("PAPER_TRADING", "false")
        with caplog.at_level(logging.WARNING):
            log_safety_config()
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "a disarmed gate produced no warning"
        assert any("NOT PROTECTING" in r.getMessage() for r in warnings)

    def test_the_summary_names_how_many_are_not_protecting(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv("PAPER_TRADING", "false")
        with caplog.at_level(logging.WARNING):
            report = log_safety_config()
        assert any(
            "configured NOT to protect" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert report["unsafe_count"] >= 1

    def test_it_returns_the_same_report_it_logged(self, monkeypatch) -> None:
        """The health endpoint serves this return value; if it diverged from the
        log, two operators reading two surfaces would disagree."""
        monkeypatch.setenv("PAPER_TRADING", "false")
        assert log_safety_config() == resolve_safety_config()

    def test_it_logs_and_returns_even_with_nothing_disarmed(self, monkeypatch, caplog) -> None:
        """Every flag at a protecting value: the summary warning must not fire,
        and the call must still report."""
        for flag in SAFETY_FLAGS:
            if flag.unsafe_when:
                safe = "true" if "false" in {v.lower() for v in flag.unsafe_when} else "off-limits"
                monkeypatch.setenv(flag.env_var, safe)
        with caplog.at_level(logging.WARNING):
            report = log_safety_config()
        assert report["unsafe_count"] == 0
        assert not [r for r in caplog.records if "configured NOT to protect" in r.getMessage()]
