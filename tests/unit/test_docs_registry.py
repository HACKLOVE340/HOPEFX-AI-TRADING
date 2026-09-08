# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Group 3 Chapter 2 — the document registry, and proof that it can refuse.

Group 3 opened with five measured findings. This registry exists to make each of
them impossible to repeat, so the tests are written against those findings rather
than against the implementation.

## The ratchet is the interesting design, and the reason for it

Group 3 Chapter 2 says CI fails while any entry lacks an owner. Taken literally on
day one that fails on 198 documents, and a check that must be disabled to get any
work done is a check that gets disabled — `hopefx-dead-controls`, committed inside
the module written to prevent it. So a baseline records the debt that already
existed: anything NEW blocks immediately, and the recorded debt may only shrink.

The tests below therefore have to prove both halves. A ratchet that never blocks is
decoration; a ratchet that blocks on day one is a control nobody can keep.
"""

from __future__ import annotations

import pytest

from scripts.docs_registry import (
    AUTHORITY_TIERS,
    Baseline,
    Entry,
    check,
    discover,
    generate,
    infer_subject,
    infer_tier,
    load,
)

pytestmark = [pytest.mark.unit]


def _entry(path: str, **kw: object) -> Entry:
    return Entry(path=path, **kw)  # type: ignore[arg-type]


class TestItSeesTheFindingsItWasBuiltFor:
    def test_the_five_api_documents_collapse_to_one_subject(self) -> None:
        # Finding 1. Four were found by hand; the registry found five, because
        # `docs/api.md` and `docs/API.md` both exist — a pair that would collide
        # outright on a case-insensitive filesystem.
        subjects = {
            infer_subject(p)
            for p in (
                "docs/API.md",
                "docs/API_GUIDE.md",
                "docs/API_REFERENCE.md",
                "docs/API_ENDPOINTS.md",
                "docs/api.md",
            )
        }
        assert subjects == {"api"}

    def test_a_subject_claimed_twice_is_reported_with_both_paths(self) -> None:
        entries = [
            _entry("docs/API.md", tier="T2", subject="api", owner="x", state="active"),
            _entry("docs/API_GUIDE.md", tier="T2", subject="api", owner="x", state="active"),
        ]
        found = check(entries, [e.path for e in entries], Baseline(unowned_count=0))
        dupes = [f for f in found if f.rule == "duplicate_subject"]
        assert len(dupes) == 1
        # Both named. A finding that says "there is a duplicate" without saying
        # which sends the reader to look for it.
        assert "docs/API.md" in dupes[0].detail and "docs/API_GUIDE.md" in dupes[0].detail

    def test_it_sees_a_collision_that_spans_tiers(self) -> None:
        # Finding 2, and the hole in the first version of this check. Root
        # CONTRIBUTING.md is T0 and docs/CONTRIBUTING.md is T2, so a T2-only
        # comparison could not see the pair it was written to catch.
        entries = [
            _entry("CONTRIBUTING.md", tier="T0", subject="contributing", owner="x", state="active"),
            _entry("docs/CONTRIBUTING.md", tier="T2", subject="contributing", owner="x", state="active"),
        ]
        found = check(entries, [e.path for e in entries], Baseline(unowned_count=0))
        assert [f.rule for f in found if f.blocking] == ["duplicate_subject"]

    def test_a_file_on_disk_with_no_entry_blocks(self) -> None:
        # Finding 3. ~126 files were reachable only by somebody who already knew
        # the filename; an unregistered file is how that happens.
        found = check([], ["docs/GHOST.md"], Baseline())
        assert [f.rule for f in found] == ["unregistered"]
        assert found[0].blocking

    def test_a_dated_snapshot_is_tiered_as_a_record_not_a_reference(self) -> None:
        # Finding 4. A snapshot and a living contract age in opposite directions,
        # and filing them together is why a reader cannot tell which they hold.
        assert infer_tier("docs/AUDIT_2026-07-26.md") == "T3"
        assert infer_tier("docs/ARCHITECTURE.md") == "T2"

    def test_an_archive_location_outranks_a_date_in_the_name(self) -> None:
        # Most-specific-first. Archived working material stays T4 even when dated.
        assert infer_tier("docs/archive/CI_FIX_2026-07-26.md") == "T4"


class TestTheGeneratorNeverOverwritesAHuman:
    def test_human_annotations_survive_regeneration(self) -> None:
        # The rule from the chapter: generated from the filesystem, enriched by
        # hand, never the reverse. A generator that reset owners would make
        # ownership impossible to keep.
        existing = [_entry("docs/A.md", tier="T1", subject="alpha", owner="ada", state="active", note="keep me")]
        out = generate(existing, ["docs/A.md", "docs/B.md"])
        a = next(e for e in out if e.path == "docs/A.md")
        assert (a.tier, a.subject, a.owner, a.state, a.note) == ("T1", "alpha", "ada", "active", "keep me")

    def test_a_new_file_arrives_unowned_and_as_a_draft(self) -> None:
        # Visible rather than absent, and never silently authoritative.
        out = generate([], ["docs/NEW.md"])
        assert out[0].owner == "" and out[0].state == "draft"

    def test_a_vanished_file_is_dropped_and_reported_rather_than_invented(self) -> None:
        out = generate([_entry("docs/GONE.md", owner="ada")], [])
        assert out == []
        found = check([_entry("docs/GONE.md", owner="ada")], [], Baseline())
        assert [f.rule for f in found] == ["dangling"]

    def test_generation_is_idempotent(self) -> None:
        first = generate([], ["docs/A.md", "docs/B.md"])
        assert generate(first, ["docs/A.md", "docs/B.md"]) == first


class TestTheRatchetBlocksNewDebtAndToleratesOld:
    def test_a_new_unowned_document_blocks(self) -> None:
        # The half that makes it a control.
        entries = [_entry("docs/A.md"), _entry("docs/B.md")]
        found = check(entries, [e.path for e in entries], Baseline(unowned_count=1))
        blocking = [f for f in found if f.blocking]
        assert [f.rule for f in blocking] == ["unowned_increased"]

    def test_existing_unowned_documents_do_not_block(self) -> None:
        # The half that makes it keepable. 198 unowned documents on day one must
        # not stop all work, or the check is removed within a week.
        entries = [_entry("docs/A.md"), _entry("docs/B.md")]
        found = check(entries, [e.path for e in entries], Baseline(unowned_count=2))
        assert not [f for f in found if f.blocking]
        assert [f.rule for f in found] == ["unowned"]

    def test_paying_debt_down_does_not_re_arm_the_ratchet(self) -> None:
        entries = [_entry("docs/A.md", owner="ada"), _entry("docs/B.md")]
        found = check(entries, [e.path for e in entries], Baseline(unowned_count=2))
        assert not [f for f in found if f.blocking]

    def test_a_known_duplicate_is_baselined_and_a_new_one_is_not(self) -> None:
        entries = [
            _entry("docs/API.md", tier="T2", subject="api", owner="x", state="active"),
            _entry("docs/API_GUIDE.md", tier="T2", subject="api", owner="x", state="active"),
            _entry("docs/RISK.md", tier="T2", subject="risk", owner="x", state="active"),
            _entry("docs/RISK_GUIDE.md", tier="T2", subject="risk", owner="x", state="active"),
        ]
        found = check(entries, [e.path for e in entries], Baseline(unowned_count=0, known_duplicate_subjects=["api"]))
        blocking = [f for f in found if f.blocking]
        assert len(blocking) == 1
        # Named, not counted: the reader is told which collision is new.
        assert "risk" in blocking[0].detail
        assert "api" not in blocking[0].detail


class TestItReportsEverythingRatherThanStoppingAtTheFirst:
    def test_several_problems_are_all_reported(self) -> None:
        # A checker that stops at the first makes a reader fix one thing, run
        # again, and find the next — three times for a three-line defect.
        entries = [
            _entry("docs/A.md", tier="TX", owner="x"),
            _entry("docs/B.md", state="superseded", owner="x"),
            _entry("docs/GONE.md", owner="x"),
        ]
        found = check(entries, ["docs/A.md", "docs/B.md", "docs/NEW.md"], Baseline(unowned_count=0))
        rules = {f.rule for f in found}
        assert {"unregistered", "dangling", "bad_tier", "superseded_without_successor"} <= rules


class TestTheLiveRegistryIsHonest:
    def test_the_committed_registry_covers_every_document_on_disk(self) -> None:
        entries, baseline = load()
        found = check(entries, discover(), baseline)
        blocking = [f for f in found if f.blocking]
        assert not blocking, "blocking findings: " + "; ".join(f"[{f.rule}] {f.detail}" for f in blocking)

    def test_the_registry_still_reports_the_known_collisions(self) -> None:
        # Baselined is not the same as forgotten. If these stop being reported it
        # means the detector stopped looking, not that the problem was fixed —
        # fixing it means removing the subject from the baseline.
        entries, baseline = load()
        found = check(entries, discover(), baseline)
        subjects = {
            s
            for f in found
            if f.rule == "duplicate_subject"
            for s in baseline.known_duplicate_subjects
            if s in f.detail
        }
        # Derived from the baseline, not pinned to a literal set. The first
        # version hard-coded {"api", "contributing", "deployment"} and failed the
        # moment the api collision was FIXED and removed from the baseline — a
        # test that punishes paying down the debt it was written to track.
        assert subjects == set(baseline.known_duplicate_subjects), (
            "every baselined collision must still be reported; a baselined "
            "subject that stops appearing means the detector stopped looking, "
            "not that the collision was resolved"
        )
        assert subjects, "the baseline lists no collisions, so this proves nothing"

    def test_authority_tiers_are_the_three_that_claim_a_subject(self) -> None:
        assert set(AUTHORITY_TIERS) == {"T0", "T1", "T2"}
