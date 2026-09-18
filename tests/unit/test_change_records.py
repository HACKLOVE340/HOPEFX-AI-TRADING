# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Change records with an expected effect — Group 2 Chapter 6.

The last open part of Decision Governance. §E22 recorded design decisions by
humans, §E23 operational decisions by the system; this is the same prediction
field one layer down, attached to a deployment.

The chapter's own sentence for why it exists:

> A deployment log records that something happened, and a change record records
> what it was *for*. Only the second can be evaluated. **A history without
> predictions cannot teach anything.**

## Generated, not written

Every field except one comes from git and the tree. The exception is the
expected effect, which is the point: it is the only thing a machine cannot
derive, and the only thing that makes the record evaluable. It arrives as an
`Expected-Effect:` commit trailer, because trailers are already how this
repository carries structured commit metadata (`Co-Authored-By`,
`Claude-Session`) and because a field kept anywhere else drifts from the commit
it describes.

## The tier is derived from paths, and says so

Chapter 6 sources "packages touched" from Chapter 1's package register. **That
register does not exist** — it is ranked item 10, still open. So the tier is
derived from path prefixes, which is a weaker thing, and the module says which
it is rather than implying a register it does not have.

## Unknown is not safe

A path matching no known prefix is `unknown`, never `presentation`. Rule 2, in
the place it costs most: a change whose blast radius nobody classified is not a
low-risk change, and treating it as one means the first unclassified package
added to this repository ships without a prediction.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from deployment import change_records as cr


class TestTheTierComesFromWhatWasTouched:
    @pytest.mark.parametrize(
        ("path", "tier"),
        [
            ("risk/manager.py", "core"),
            ("execution/oms.py", "core"),
            ("brokers/oanda.py", "core"),
            ("ml/inference_engine.py", "core"),
            ("ai/ledger/decisions.py", "ai"),
            ("frontend/src/hub/PresenceStage.tsx", "presentation"),
            ("docs/decisions/0001-x.md", "presentation"),
        ],
    )
    def test_a_single_path(self, path: str, tier: str) -> None:
        assert cr.tier_for_paths([path]) == tier

    @pytest.mark.parametrize(
        ("path", "tier"),
        [
            ("CLAUDE.md", "presentation"),
            ("ARCHITECTURE.md", "presentation"),
            ("README.md", "presentation"),
            (".gitignore", "presentation"),
            ("pyproject.toml", "presentation"),
            ("app.py", "core"),
            ("run.py", "core"),
            ("hopefx_engine.py", "core"),
            ("trader_full.py", "core"),
            ("kill_switch.py", "core"),
        ],
    )
    def test_files_at_the_repository_root(self, path: str, tier: str) -> None:
        """The root is where a blanket rule does the most damage in both
        directions.

        Everything at the root fell through to `unknown` at first, so editing
        CLAUDE.md demanded a deployment prediction — friction with no safety in
        it, and friction is how a gate earns a bypass. Calling the whole root
        presentation would have been the opposite mistake: `app.py`, `run.py`,
        `hopefx_engine.py` and `trader_full.py` all live there and all start the
        trading path.
        """
        assert cr.tier_for_paths([path]) == tier

    def test_ci_configuration_is_core(self) -> None:
        """CI is the control plane for every gate in this repository.

        A change there can silently disable a safety check — which is not
        hypothetical here: §E20 found that the pre-commit hooks had never been
        installed, so seven ratcheted checks protected nobody. Leaving `.github/`
        as `unknown` would have required a prediction anyway, but mislabelled a
        thing this repository knows exactly the risk of.
        """
        assert cr.tier_for_paths([".github/workflows/ci.yml"]) == "core"
        assert cr.tier_for_paths([".pre-commit-config.yaml"]) == "core"

    def test_an_unrecognised_root_python_file_is_still_core(self) -> None:
        # A new .py at the root is more likely a second entry point than a note.
        assert cr.tier_for_paths(["some_new_runner.py"]) == "core"

    def test_the_highest_tier_wins(self) -> None:
        # A release that touches the trading path is a trading-path release,
        # whatever else rode along with it.
        assert cr.tier_for_paths(["frontend/src/app.tsx", "risk/manager.py"]) == "core"
        assert cr.tier_for_paths(["docs/x.md", "ai/ledger/decisions.py"]) == "ai"

    def test_an_unclassified_path_is_unknown_not_presentation(self) -> None:
        # Rule 2 where it costs most. A blast radius nobody classified is not a
        # small one, and calling it presentation ships it without a prediction.
        assert cr.tier_for_paths(["some_new_package/thing.py"]) == "unknown"

    def test_unknown_outranks_presentation(self) -> None:
        assert cr.tier_for_paths(["docs/x.md", "some_new_package/thing.py"]) == "unknown"

    def test_no_paths_at_all_is_unknown(self) -> None:
        assert cr.tier_for_paths([]) == "unknown"

    def test_the_mapping_does_not_claim_to_be_the_register(self) -> None:
        """Chapter 1's package register is ranked item 10 and does not exist.

        A module that silently substituted a path table for it would make the
        register look delivered, which is the shape §E20 corrected in §E5.
        """
        assert "register" in cr.__doc__.lower()
        assert cr.TIER_SOURCE == "path-prefix"


class TestTheExpectedEffectTrailer:
    def test_it_is_read_from_the_commit_message(self) -> None:
        message = "Fix the gate\n\nSome body.\n\nExpected-Effect: refusals fall to zero within one session\n"
        assert cr.expected_effect(message) == "refusals fall to zero within one session"

    def test_it_is_absent_when_not_stated(self) -> None:
        assert cr.expected_effect("Fix the gate\n\nSome body.\n") is None

    def test_an_empty_trailer_is_absent_not_blank(self) -> None:
        # A trailer with nothing after it is somebody satisfying a linter.
        assert cr.expected_effect("Fix\n\nExpected-Effect:   \n") is None

    def test_the_trailer_is_case_insensitive(self) -> None:
        assert cr.expected_effect("Fix\n\nexpected-effect: latency drops\n") == "latency drops"

    def test_a_continuation_line_is_kept(self) -> None:
        message = "Fix\n\nExpected-Effect: latency drops below 900ms\n  measured over the hour after deploy\n"
        assert "measured over the hour" in (cr.expected_effect(message) or "")


class TestValidation:
    def _record(self, **overrides):
        payload = {
            "change_id": "abc123",
            "at": "2026-09-09T12:00:00+00:00",
            "actor": "someone",
            "commits": ("abc123",),
            "paths": ("risk/manager.py",),
            "expected_effect": "refusals fall to zero",
            "approvals": (),
        }
        payload.update(overrides)
        return cr.ChangeRecord(**payload)

    def test_a_core_change_with_a_prediction_is_fine(self) -> None:
        assert cr.validate(self._record()) == []

    def test_a_core_change_without_one_is_refused(self) -> None:
        problems = cr.validate(self._record(expected_effect=None))
        assert problems
        # The message names the exact trailer, which is what the author has
        # to type — more use than the prose phrase.
        assert "expected-effect" in problems[0].lower()
        assert "core-tier" in problems[0].lower()

    def test_an_unknown_tier_change_also_needs_one(self) -> None:
        """Fail closed. The alternative is that the first unclassified package
        added to this repository is the one that ships without a prediction."""
        problems = cr.validate(self._record(paths=("some_new_package/x.py",), expected_effect=None))
        assert problems

    def test_a_presentation_change_does_not(self) -> None:
        assert cr.validate(self._record(paths=("docs/x.md",), expected_effect=None)) == []

    def test_the_tier_is_on_the_record(self) -> None:
        assert self._record().risk_tier == "core"
        assert self._record(paths=("docs/x.md",)).risk_tier == "presentation"


class TestBuiltFromGit:
    def test_it_reads_a_real_range(self) -> None:
        record = cr.from_git("HEAD~1..HEAD")
        assert record.commits, "no commits found for HEAD~1..HEAD"
        assert record.change_id
        assert record.actor

    def test_the_paths_are_the_ones_that_changed(self) -> None:
        record = cr.from_git("HEAD~1..HEAD")
        assert record.paths, "a commit that changed no files is not a change"

    def test_an_empty_range_produces_no_commits(self) -> None:
        record = cr.from_git("HEAD..HEAD")
        assert record.commits == ()


class TestObservedEffectClosesTheLoop:
    def _record(self):
        return cr.ChangeRecord(
            change_id="abc123",
            at="2026-09-09T12:00:00+00:00",
            actor="someone",
            commits=("abc123",),
            paths=("risk/manager.py",),
            expected_effect="refusals fall to zero",
            approvals=(),
        )

    def test_an_observation_is_attached(self) -> None:
        observed = cr.observe(self._record(), observed="refusals fell to zero", held=True)
        assert observed.observed_effect is not None
        assert observed.observed_effect["held"] is True
        assert observed.observed_effect["expected"] == "refusals fall to zero"

    def test_it_cannot_be_observed_twice(self) -> None:
        once = cr.observe(self._record(), observed="fell to zero", held=True)
        with pytest.raises(ValueError, match="already"):
            cr.observe(once, observed="actually rose", held=False)

    def test_a_change_with_no_prediction_cannot_be_scored(self) -> None:
        # The chapter's whole argument: without a prediction the telemetry has
        # nothing to be compared against, and correlation is guesswork.
        record = cr.ChangeRecord(
            change_id="abc123",
            at="2026-09-09T12:00:00+00:00",
            actor="someone",
            commits=("abc123",),
            paths=("docs/x.md",),
            expected_effect=None,
            approvals=(),
        )
        with pytest.raises(ValueError, match="prediction|expected"):
            cr.observe(record, observed="nothing changed", held=True)

    def test_a_rollback_is_recorded_with_its_reason(self) -> None:
        rolled = cr.rolled_back(self._record(), reason="latency regression on the gold feed")
        assert rolled.rollback == {"occurred": True, "reason": "latency regression on the gold feed"}

    def test_a_rollback_needs_a_reason(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            cr.rolled_back(self._record(), reason="  ")
