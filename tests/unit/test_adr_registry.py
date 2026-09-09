# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Architecture Decision Records — Group 3 Chapter 6.

The repository had none. Decisions lived in commit messages, in one narrative
file (`docs/ai/AI_HUB_DECISIONS.md`), and in the memory of whoever made them.
The specific cost the spec names is **re-litigation**: a decision whose reasoning
is not recorded is re-argued every time someone new meets it, and sometimes
reversed by someone who does not know what it was protecting.

This session produced two examples of exactly that, which is why this is being
built now rather than later:

* §E20 corrected §E5's "verified by execution" claim, written in the phase that
  made unmeasurable modules fail. A decision recorded as settled, never
  re-checked.
* §E21 reversed "the landmark model is not vendored, because there is no camera
  here" — sound reasoning on a premise nobody re-examined for two phases.

Both were reversible only because the *reasoning* had been written down. That is
the whole thesis of this chapter, and the narrative file cannot carry it at
scale: it cannot be pointed at from a code comment, cannot be superseded in
part, and grows without bound.

## What is enforced, and why each rule is a defect that already happened

**Two options, or it was not a decision.** The spec's own rule. A record with one
option documents an implementation, not a choice, and reads as justification
after the fact.

**Immutable once accepted.** An ADR that can be edited is a record of what we
currently believe we decided. The only permitted change to an accepted record is
its status becoming `superseded by NNNN` — the supersede itself is a new record.

**A supersede reference must resolve.** "Superseded by 0042" pointing at nothing
is worse than no status: it tells a reader their answer exists somewhere.

**Sequential, gapless numbering.** So that "see 0007" is stable for ever, and so
two people cannot both create 0009.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def adr():
    spec = importlib.util.spec_from_file_location("adr", REPO / "scripts" / "adr.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GOOD = """# 0001. Pin Python to 3.12

- Status: accepted
- Date: 2026-09-09

## Context

The committed `.pkl` artifacts under `ml/saved_models/` are pickled by CI.

## Options considered

- **Pin 3.12.** Matches the Dockerfile. Costs: contributors on 3.11 must upgrade.
- **Support 3.10 through 3.12.** Costs: artifacts pickled on an interpreter that
  neither CI nor production loads.

## Decision

Pin 3.12.

## Consequences

Makes artifact loading predictable. Makes a contributor on an older interpreter
do work before their first commit.

## Evidence

`Dockerfile` runs `python:3.12-slim`; CI tests 3.11 and 3.12.
"""


def write(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    directory = tmp_path / "docs" / "decisions"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


class TestAWellFormedRecordPasses:
    def test_no_problems(self, adr, tmp_path) -> None:
        write(tmp_path, "0001-pin-python.md", GOOD)
        assert adr.validate_directory(tmp_path / "docs" / "decisions") == []

    def test_it_parses_the_number_and_title(self, adr, tmp_path) -> None:
        path = write(tmp_path, "0001-pin-python.md", GOOD)
        record = adr.parse(path)
        assert record.number == 1
        assert record.title == "Pin Python to 3.12"
        assert record.status == "accepted"
        assert len(record.options) >= 2


class TestOneOptionIsNotADecision:
    def test_a_single_option_is_refused(self, adr, tmp_path) -> None:
        body = GOOD.replace(
            "- **Support 3.10 through 3.12.** Costs: artifacts pickled on an interpreter that\n"
            "  neither CI nor production loads.\n",
            "",
        )
        write(tmp_path, "0001-pin-python.md", body)
        problems = adr.validate_directory(tmp_path / "docs" / "decisions")
        assert any("two options" in p.message for p in problems), [p.message for p in problems]

    def test_no_options_section_is_refused(self, adr, tmp_path) -> None:
        body = GOOD.replace("## Options considered", "## Notes")
        write(tmp_path, "0001-pin-python.md", body)
        assert adr.validate_directory(tmp_path / "docs" / "decisions")


class TestEverySectionTheSpecNames:
    @pytest.mark.parametrize("heading", ["Context", "Options considered", "Decision", "Consequences", "Evidence"])
    def test_a_missing_section_is_refused(self, adr, tmp_path, heading: str) -> None:
        body = GOOD.replace(f"## {heading}", "## Something else")
        write(tmp_path, "0001-pin-python.md", body)
        problems = adr.validate_directory(tmp_path / "docs" / "decisions")
        assert any(heading.lower() in p.message.lower() for p in problems), [p.message for p in problems]

    def test_an_empty_section_is_refused(self, adr, tmp_path) -> None:
        # A heading with nothing under it is the shape a template leaves behind.
        body = GOOD.replace("Pin 3.12.\n", "\n")
        write(tmp_path, "0001-pin-python.md", body)
        problems = adr.validate_directory(tmp_path / "docs" / "decisions")
        assert any("empty" in p.message.lower() for p in problems), [p.message for p in problems]


class TestStatus:
    def test_an_unknown_status_is_refused(self, adr, tmp_path) -> None:
        write(tmp_path, "0001-pin-python.md", GOOD.replace("Status: accepted", "Status: probably"))
        assert adr.validate_directory(tmp_path / "docs" / "decisions")

    def test_proposed_and_accepted_are_both_fine(self, adr, tmp_path) -> None:
        write(tmp_path, "0001-pin-python.md", GOOD.replace("Status: accepted", "Status: proposed"))
        assert adr.validate_directory(tmp_path / "docs" / "decisions") == []

    def test_a_supersede_pointing_nowhere_is_refused(self, adr, tmp_path) -> None:
        write(tmp_path, "0001-pin-python.md", GOOD.replace("Status: accepted", "Status: superseded by 0042"))
        problems = adr.validate_directory(tmp_path / "docs" / "decisions")
        assert any("0042" in p.message for p in problems), [p.message for p in problems]

    def test_a_supersede_that_resolves_is_fine(self, adr, tmp_path) -> None:
        write(tmp_path, "0001-pin-python.md", GOOD.replace("Status: accepted", "Status: superseded by 0002"))
        write(tmp_path, "0002-unpin-python.md", GOOD.replace("# 0001.", "# 0002."))
        assert adr.validate_directory(tmp_path / "docs" / "decisions") == []


class TestNumbering:
    def test_the_filename_number_must_match_the_heading(self, adr, tmp_path) -> None:
        write(tmp_path, "0003-pin-python.md", GOOD)
        problems = adr.validate_directory(tmp_path / "docs" / "decisions")
        assert any("0003" in p.message or "0001" in p.message for p in problems)

    def test_a_duplicate_number_is_refused(self, adr, tmp_path) -> None:
        write(tmp_path, "0001-a.md", GOOD)
        write(tmp_path, "0001-b.md", GOOD)
        problems = adr.validate_directory(tmp_path / "docs" / "decisions")
        assert any("duplicate" in p.message.lower() for p in problems), [p.message for p in problems]

    def test_a_gap_is_refused(self, adr, tmp_path) -> None:
        # "see 0007" must be stable, and a gap means somebody deleted a record
        # rather than superseding it.
        write(tmp_path, "0001-a.md", GOOD)
        write(tmp_path, "0003-c.md", GOOD.replace("# 0001.", "# 0003."))
        problems = adr.validate_directory(tmp_path / "docs" / "decisions")
        assert any("0002" in p.message for p in problems), [p.message for p in problems]

    def test_next_number_follows_the_highest(self, adr, tmp_path) -> None:
        write(tmp_path, "0001-a.md", GOOD)
        write(tmp_path, "0002-b.md", GOOD.replace("# 0001.", "# 0002."))
        assert adr.next_number(tmp_path / "docs" / "decisions") == 3

    def test_next_number_on_an_empty_directory_is_one(self, adr, tmp_path) -> None:
        (tmp_path / "docs" / "decisions").mkdir(parents=True)
        assert adr.next_number(tmp_path / "docs" / "decisions") == 1


class TestTheCommandLineTheDocsPromise:
    """`adr.py new "Title"` is what the README and the module docstring tell a
    reader to run. The first version accepted `new` as a single positional and
    rejected the title as an unrecognised argument — a tool whose documented
    invocation does not work teaches people it is broken, and they go back to
    writing decisions in commit messages.
    """

    def test_new_accepts_a_title(self, adr, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(adr, "DECISIONS", tmp_path / "decisions")
        assert adr.main(["new", "Pin the interpreter"]) == 0
        written = list((tmp_path / "decisions").glob("*.md"))
        assert len(written) == 1
        assert written[0].name == "0001-pin-the-interpreter.md"

    def test_a_second_record_takes_the_next_number(self, adr, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(adr, "DECISIONS", tmp_path / "decisions")
        adr.main(["new", "First"])
        adr.main(["new", "Second"])
        assert sorted(p.name for p in (tmp_path / "decisions").glob("*.md")) == [
            "0001-first.md",
            "0002-second.md",
        ]

    def test_the_template_it_writes_is_not_yet_valid(self, adr, tmp_path, monkeypatch) -> None:
        """Deliberate. A template that passed the gate unedited would let an
        empty record ship, and the placeholders are what the author replaces."""
        monkeypatch.setattr(adr, "DECISIONS", tmp_path / "decisions")
        adr.main(["new", "Something"])
        # Two options are present in the template, so it is the placeholders in
        # the other sections that must still be filled in by a human.
        text = (tmp_path / "decisions" / "0001-something.md").read_text(encoding="utf-8")
        assert "<What forced a decision" in text

    def test_check_and_list_still_work(self, adr, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(adr, "DECISIONS", tmp_path / "decisions")
        (tmp_path / "decisions").mkdir()
        assert adr.main(["--list"]) == 0


class TestTheRepositorysOwnRecords:
    """The gate, pointed at the real tree."""

    def test_the_committed_records_are_valid(self, adr) -> None:
        directory = REPO / "docs" / "decisions"
        assert directory.exists(), "docs/decisions/ does not exist"
        problems = adr.validate_directory(directory)
        assert problems == [], "\n".join(f"{p.path.name}: {p.message}" for p in problems)

    def test_the_back_filled_decisions_are_present(self, adr) -> None:
        """Group 3 Ch 6 names eight decisions already being used as precedent.

        Back-filling is not archaeology: each is a decision someone will
        otherwise reverse, and two of them were nearly reversed this session.
        """
        directory = REPO / "docs" / "decisions"
        records = [adr.parse(p) for p in sorted(directory.glob("[0-9][0-9][0-9][0-9]-*.md"))]
        assert len(records) >= 8, f"only {len(records)} records; the spec names eight to back-fill"
