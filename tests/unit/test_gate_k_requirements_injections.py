# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate K — requirements.txt, requirements.lock and requirements-ci.txt must agree.

When they drift, CI and production install different code, and the difference is
invisible until something behaves differently in one of them.

It had no test. Proving it found one dead behaviour and one blind spot.

## Fixed here: a skip was reported as a pass

    $ mv requirements.lock elsewhere && python scripts/ci/gate_k_requirements_consistency.py
    [gate-k] SKIP  Missing file(s): requirements.lock
    $ echo $?
    0

All three files are committed, so one going absent is a rename, a deletion or a
bad checkout — never an environmental quirk. It fails closed now, with
`REQ_ALLOW_SKIP=1` as an explicit local opt-out. The identical defect was found
and fixed in gate M one phase earlier; this is the same shape in a second gate.

## Recorded, not fixed: the build toolchain is invisible to this gate

`_SKIP_NAMES` excludes `pip`, `wheel` and `setuptools`, and every rule iterates
the parsed package sets, so **the CVE-pinned build toolchain is checked by
nothing here**. requirements.txt pins those three against four named CVEs; the
lock could drift below those pins and gate K would still pass.

That is a scope decision, not a bug to change unilaterally — build-toolchain
versions in a lock are often environment-specific, and widening the gate could
produce false positives that train people to bypass it. It is recorded in
`docs/ai/MASTER_OUTSTANDING.md` and pinned below so the exclusion cannot quietly
grow.

## The method lesson this phase kept teaching

Three injections in this phase were the wrong *shape* before they were right: a
list-style compose entry where the file uses mapping style, a literal value where
the gate collects only `${VAR}` references, and `wheel` where the gate excludes
it by name. Each applied cleanly and still proved nothing.

So asserting the injection applied is necessary and not sufficient — **it must
also be the failure the gate declares it detects.** Read what a gate excludes
before concluding it is dead.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_k_requirements_consistency.py"
_FILES = (Path("requirements.txt"), Path("requirements.lock"), Path("requirements-ci.txt"))

#: In requirements.txt with a lower bound, in the lock, and not excluded by
#: `_SKIP_NAMES`. Asserted rather than assumed by `test_the_target_is_in_scope`.
TARGET = "alembic"


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    for rel in _FILES:
        shutil.copy2(REPO / rel, root / rel)
    return root


def _run(root: Path, **env: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(env)
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


def _edit(root: Path, rel: Path, pattern: str, replacement: str) -> None:
    path = root / rel
    before = path.read_text(encoding="utf-8")
    after = re.sub(pattern, replacement, before, count=1, flags=re.IGNORECASE | re.MULTILINE)
    assert after != before, f"injection {pattern!r} did not apply — it would prove nothing"
    path.write_text(after, encoding="utf-8")


class TestTheTargetIsInScope:
    """Three injections in this phase were wrong because the gate excluded the
    package or ignored the shape. This pins that the target is neither."""

    def test_the_target_is_not_excluded_by_name(self) -> None:
        source = GATE.read_text(encoding="utf-8")
        skipped = re.search(r"_SKIP_NAMES[^=]*=\s*frozenset\(\{([^}]*)\}\)", source)
        assert skipped, "_SKIP_NAMES not found — the exclusion list moved"
        assert TARGET not in skipped.group(1), f"{TARGET} is excluded; the injections below prove nothing"

    def test_the_target_is_declared_in_both_files(self) -> None:
        txt = (REPO / "requirements.txt").read_text(encoding="utf-8")
        lock = (REPO / "requirements.lock").read_text(encoding="utf-8")
        assert re.search(rf"(?im)^{TARGET}>=", txt), f"{TARGET} has no lower bound in requirements.txt"
        assert re.search(rf"(?im)^{TARGET}==", lock), f"{TARGET} is not in requirements.lock"


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    def test_the_gate_parsed_real_package_sets(self, mirror: Path) -> None:
        # A gate that parsed nothing passes every injection below.
        assert re.search(r"\d{2,} pkgs", _run(mirror).stdout), _run(mirror).stdout


class TestTheDriftItExistsToCatch:
    def test_a_direct_dependency_missing_from_the_lock_is_caught(self, mirror: Path) -> None:
        _edit(mirror, Path("requirements.lock"), rf"^{TARGET}==.*$\n?", "")
        result = _run(mirror)
        assert result.returncode != 0
        assert "Rule 1" in result.stdout and TARGET in result.stdout

    def test_a_lock_below_the_stated_lower_bound_is_caught(self, mirror: Path) -> None:
        _edit(mirror, Path("requirements.lock"), rf"^{TARGET}==.*$", f"{TARGET}==0.0.1")
        result = _run(mirror)
        assert result.returncode != 0
        assert "Rule 4" in result.stdout


class TestAnUnmeasuredRunIsNotAPass:
    """The defect this phase fixed. `[gate-k] SKIP … ` used to exit 0."""

    @pytest.mark.parametrize("missing", list(_FILES))
    def test_a_missing_requirements_file_fails(self, mirror: Path, missing: Path) -> None:
        (mirror / missing).unlink()
        result = _run(mirror, REQ_ALLOW_SKIP="")
        assert result.returncode != 0, f"gate K exited 0 with {missing} absent"
        assert "FAIL" in result.stdout

    def test_the_documented_opt_out_still_skips(self, mirror: Path) -> None:
        (mirror / "requirements.lock").unlink()
        result = _run(mirror, REQ_ALLOW_SKIP="1")
        assert result.returncode == 0
        assert "SKIP" in result.stdout

    @pytest.mark.parametrize("value", ["0", "false", "no", ""])
    def test_anything_else_does_not_open_the_hatch(self, mirror: Path, value: str) -> None:
        (mirror / "requirements.lock").unlink()
        assert _run(mirror, REQ_ALLOW_SKIP=value).returncode != 0

    def test_the_files_are_all_tracked(self) -> None:
        # The premise the fail-closed decision rests on. If one stops being
        # committed, revisit REQ_ALLOW_SKIP rather than leaving this stale.
        for rel in _FILES:
            result = subprocess.run(  # nosec B603 — fixed argument list, no shell
                ["git", "ls-files", "--error-unmatch", str(rel)],
                cwd=str(REPO),
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, f"{rel} is no longer tracked by git"


class TestTheBuildToolchainBlindSpot:
    """Recorded, not fixed. `pip`, `wheel` and `setuptools` are CVE-pinned in
    requirements.txt and excluded from every rule in this gate."""

    def test_the_exclusion_is_still_exactly_these_three(self) -> None:
        source = GATE.read_text(encoding="utf-8")
        skipped = re.search(r"_SKIP_NAMES[^=]*=\s*frozenset\(\{([^}]*)\}\)", source)
        assert skipped
        names = {n.strip().strip("\"'") for n in skipped.group(1).split(",") if n.strip()}
        assert names == {"pip", "wheel", "setuptools"}, (
            f"the exclusion list changed to {names}. Widening it removes packages from every "
            "gate-K rule; narrowing it may fix the recorded blind spot. Either way, decide it "
            "deliberately and update docs/ai/MASTER_OUTSTANDING.md."
        )

    def test_an_excluded_package_is_genuinely_unguarded(self, mirror: Path) -> None:
        # Not an assertion that this is correct — a record of what is true, so
        # the gap cannot be forgotten while the gate looks green.
        _edit(mirror, Path("requirements.lock"), r"^wheel==.*$\n?", "")
        assert _run(mirror).returncode == 0, (
            "gate K now catches build-toolchain drift. If that was deliberate, remove this "
            "test and the finding in MASTER_OUTSTANDING."
        )
