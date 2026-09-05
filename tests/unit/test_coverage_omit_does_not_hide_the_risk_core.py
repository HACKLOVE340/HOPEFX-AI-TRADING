# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The `risk/ >= 80%` gate must measure the part of `risk/` that carries the risk.

`.coveragerc`'s `omit` list removed four files from `risk/` with the
justification "depend on live event bus / orchestrator wiring; covered by
integration tests, not unit tests", among them `risk/manager.py` -- the file
CLAUDE.md names as the risk core: the pre-trade gate, VaR/CVaR, Kelly sizing and
the kill switch. The CI step `Coverage gate - risk/ (80% required)` therefore
made a true statement about the two thirds of `risk/` that is not the dangerous
part (F105).

The justification was checkable, and false. Measured against the unit suite with
the omit removed:

    risk/pre_trade_gate.py        94.39%
    risk/manager.py               89.65%
    risk/gatekeeper.py            85.63%
    risk/post_trade_analyzer.py   82.40%

All four clear the 80% gate they were excluded from, using the unit tests that
were said not to cover them -- 170 test files reference `risk.manager`, and two
of them are integration tests.

These tests are structural on purpose. An earlier version checked the
justification *text* in `.coveragerc`, which fails on the fixed file: the
correction quotes the claim it retracts. Grepping prose cannot tell a claim from
a description of a withdrawn claim -- F255, and this file is not going to be the
fifth occurrence.
"""

from __future__ import annotations

import configparser
import pathlib

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The risk core, by name. A count would let a regression hide behind a
# different file taking the same slot.
RISK_CORE = (
    "risk/manager.py",
    "risk/gatekeeper.py",
    "risk/pre_trade_gate.py",
    "risk/post_trade_analyzer.py",
)


def _omit_entries() -> list[str]:
    """The omit list as coverage.py parses it -- comments excluded by the parser
    rather than by a regex of mine."""
    parser = configparser.ConfigParser()
    parser.read(_ROOT / ".coveragerc")
    raw = parser.get("run", "omit", fallback="")
    return [line.strip() for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")]


@pytest.mark.parametrize("module", RISK_CORE)
def test_the_risk_core_is_measured(module):
    """If this fails, `risk/ >= 80%` has stopped describing the risk core."""
    assert module not in _omit_entries(), f"{module} is excluded from the coverage the risk gate reports"


def test_the_risk_gate_still_exists():
    """The other way to make the gate vacuous is to delete it."""
    ci = (_ROOT / ".github/workflows/ci.yml").read_text()
    assert '--include="risk/*" --fail-under=80' in ci, "the risk/ coverage gate is gone"


def test_the_omit_list_still_covers_the_files_it_should():
    """Not everything was wrong. Third-party and hardware-bound modules are
    legitimately excluded, and this fix must not have swept them back in."""
    entries = set(_omit_entries())
    for expected in ("*/tests/*", "*/site-packages/*", "core/acceleration/gpu_engine.py"):
        assert expected in entries, f"{expected} should still be omitted"


def test_no_risk_file_is_omitted_by_a_wildcard():
    """`risk/*` in the omit list would re-hide everything while leaving the four
    explicit entries absent, which is what these tests check for."""
    for entry in _omit_entries():
        assert not entry.startswith("risk/*"), f"{entry} excludes the whole risk package"


def test_the_execution_exclusions_are_recorded_with_measurements():
    """The execution files stay omitted, but the file has to say what their
    coverage actually is rather than naming a test suite that does not cover
    them. Checking that the numbers are present, not what they say -- the values
    go stale, and a stale number that is visible is still better than a
    justification nobody can check."""
    text = (_ROOT / ".coveragerc").read_text()
    for module in ("execution/engine.py", "core/decision/HOPEFXDecisionEngine.py"):
        assert module in text, f"{module} is omitted with no note at all"
    assert "%" in text, "the exclusions record no measured coverage"
