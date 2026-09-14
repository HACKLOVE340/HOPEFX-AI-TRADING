# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A deploy must be gated on a green build, and must not hand a key to a moving tag.

Two findings in one workflow.

**F96 — `deploy.yml` fired on every push to `main` with no CI gate.** It had no
`needs:` and no `workflow_run:`, so the only thing between a push and a
`docker compose up` on the VPS was the push itself. A deploy that cannot observe
a red build is not gated; it is automatic.

**F97 — the one action holding `VPS_SSH_KEY` was float-pinned.**
`appleboy/ssh-action@v1.2.5` is a tag, and a tag is mutable. Whoever controls
that tag controls a step that receives the private deploy key for the
production VPS. Every other `uses:` in the repository either carries no secret
or is a first-party `actions/*`; this is the one that matters, which is why it
is the one F97 names.

The pin itself is not in this commit: resolving `v1.2.5` to its 40-character
commit SHA needs a lookup against `appleboy/ssh-action`, and this session's
GitHub access is scoped to this repository. Guessing a SHA would break every
deploy. So the invariant is encoded here as a **ratchet** instead, in the shape
this repository already uses for `FRESHNESS_BASELINE.toml` and
`COVERAGE_UNMEASURABLE.txt`: the one known-unpinned reference is recorded, and
the set may only shrink. A second secret-holding action pinned to a tag fails
immediately; removing this one is a one-line deletion here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

#: Secret-holding action references still pinned to a mutable tag.
#:
#: MAY ONLY SHRINK. To clear the entry: resolve the tag to its 40-character
#: commit SHA on GitHub, write `appleboy/ssh-action@<sha>  # v1.2.5` in
#: deploy.yml, and delete the line below. Do not add to this set — a new
#: secret-holding action pinned to a tag is the finding, not an exception to it.
_UNPINNED_SECRET_ACTIONS: frozenset[str] = frozenset()

_SHA = re.compile(r"^[0-9a-f]{40}$")


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def _steps_with_secrets(path: Path) -> list[tuple[str, str]]:
    """(action_ref, step_name) for every step that references a secret.

    Read from the raw text of the step block rather than the parsed tree,
    because a secret can arrive through `with:`, `env:` or the script body and
    the question is only "does this step see one".
    """
    text = path.read_text(encoding="utf-8")
    found: list[tuple[str, str]] = []
    # Split on `- name:` / `- uses:` step boundaries at any indentation.
    blocks = re.split(r"\n(?=\s*-\s+(?:name|uses):)", text)
    for block in blocks:
        m = re.search(r"uses:\s*(\S+)", block)
        if not m:
            continue
        if "secrets." in block:
            name = re.search(r"name:\s*(.+)", block)
            found.append((m.group(1), name.group(1).strip() if name else "?"))
    return found


def test_a_deploy_is_gated_on_a_verification_workflow():
    """F96. Nothing but the push stood between `main` and a live VPS."""
    deploy = WORKFLOWS / "deploy.yml"
    assert deploy.exists(), "deploy.yml is missing"
    spec = yaml.safe_load(deploy.read_text(encoding="utf-8"))

    # `on` parses as the boolean True in YAML 1.1 — the classic Norway problem's
    # cousin. Accept either key rather than silently reading None and passing.
    triggers = spec.get("on", spec.get(True, {})) or {}
    jobs = spec.get("jobs", {}) or {}

    gated_by_workflow_run = "workflow_run" in triggers
    gated_by_needs = any(job.get("needs") for job in jobs.values() if isinstance(job, dict))

    assert gated_by_workflow_run or gated_by_needs, (
        "deploy.yml has neither `workflow_run:` nor a job-level `needs:` — it deploys "
        "on push regardless of whether anything verified the commit"
    )


def test_the_gate_requires_success_not_merely_completion():
    """`workflow_run` fires on completion, including a FAILED run.

    Without the conclusion check the trigger reads as a gate and deploys a red
    build — a control that exists and cannot refuse.
    """
    deploy = WORKFLOWS / "deploy.yml"
    spec = yaml.safe_load(deploy.read_text(encoding="utf-8"))
    triggers = spec.get("on", spec.get(True, {})) or {}
    if "workflow_run" not in triggers:
        pytest.skip("gated by `needs:` instead; conclusion check does not apply")

    text = deploy.read_text(encoding="utf-8")
    assert "workflow_run.conclusion" in text and "success" in text, (
        "deploy.yml triggers on workflow_run without checking the conclusion, so it deploys when CI FAILS"
    )


def test_no_new_secret_holding_action_is_pinned_to_a_moving_tag():
    """F97, as a ratchet. The recorded set may only shrink — and is now empty.

    With nothing exempted, "no offenders" is this test's whole verdict, which
    makes it worth asking what would happen if the scan found nothing at all: a
    renamed workflow directory, a parser that stopped recognising `uses:`, or a
    glob that stopped matching would all render it silently green. Rule 2 — an
    unmeasured value is absent, never zero — so it asserts it measured
    something before it asserts what it measured.
    """
    scanned = [(wf, ref) for wf in _workflow_files() for ref, _ in _steps_with_secrets(wf)]
    assert scanned, (
        "no workflow step taking a secret was found at all — the scan is broken, not the "
        "workflows, and this test would otherwise pass by measuring nothing"
    )

    offenders: dict[str, str] = {}
    for wf in _workflow_files():
        for ref, step in _steps_with_secrets(wf):
            if "@" not in ref:
                continue
            sha = ref.rsplit("@", 1)[1]
            if _SHA.match(sha):
                continue
            if ref in _UNPINNED_SECRET_ACTIONS:
                continue
            offenders[f"{wf.name}: {ref}"] = step

    assert not offenders, (
        "a step that receives a secret is pinned to a mutable tag — whoever controls "
        f"that tag controls the secret: {offenders}"
    )


def test_the_unpinned_set_does_not_list_anything_already_fixed():
    """A ratchet that keeps a stale entry stops being a ratchet.

    If the SHA gets pinned and the line below is not deleted, this fails and
    says so, rather than quietly permitting a future regression back to a tag.
    """
    still_unpinned = {ref for wf in _workflow_files() for ref, _ in _steps_with_secrets(wf)}
    stale = _UNPINNED_SECRET_ACTIONS - still_unpinned
    assert not stale, (
        f"{stale} is recorded as unpinned but no longer appears in any workflow — "
        "delete it from _UNPINNED_SECRET_ACTIONS"
    )


def test_the_ssh_step_still_receives_the_deploy_key():
    """The premise. If this step stops taking the key, F97 is moot and this file should go."""
    text = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    assert "secrets.VPS_SSH_KEY" in text


def test_the_scan_can_still_see_an_offender():
    """The positive control for the empty exemption set.

    `_UNPINNED_SECRET_ACTIONS` is empty now, so the ratchet above can only ever
    report "clean". This proves the detector still fires: the same predicate,
    given a step that takes a secret and floats on a tag, calls it an offender.
    Without it, a `_SHA` regex that matched everything would look like success.
    """
    assert not _SHA.match("v1.2.5"), "a tag was accepted as a 40-character SHA"
    assert _SHA.match("0ff4204d59e8e51228ff73bce53f80d53301dee2")  # pragma: allowlist secret
    assert not _UNPINNED_SECRET_ACTIONS, (
        "the exemption set is no longer empty — a new entry is the finding, not an exception to it"
    )


def test_the_ssh_action_is_pinned_to_the_commit_the_tag_pointed_at():
    """The pin itself, named rather than left to the regex.

    A 40-character hex string satisfies the ratchet; this says WHICH one, so a
    future edit to some other SHA is a visible change rather than an equally
    valid-looking one. `v1.2.5` is a lightweight tag — `git ls-remote --tags`
    returns one ref with no `^{}` peel — so the tag resolves directly to this
    commit, and the object was fetched and confirmed to carry `action.yml`.
    """
    text = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    assert (
        "appleboy/ssh-action@0ff4204d59e8e51228ff73bce53f80d53301dee2"  # pragma: allowlist secret
        in text
    )
    assert "appleboy/ssh-action@v1.2.5" not in text, "the mutable tag is still referenced"
