"""F271 (TODO item 24) — the dependency scan must read the file with the pins.

`trivy fs .` reported `requirements.txt  pip  0` for as long as it had run. That
zero means "no version I could resolve", not "no vulnerabilities":
`requirements.txt` holds ranges (`chromadb>=0.4.0`), and Trivy cannot resolve a
range. The file with the real pins, `requirements.lock`, is not a name Trivy
recognises as a pip manifest, so it was never read at all.

Measured on 2026-09-06, once it was: **11 findings against the 6 that `uv.lock`
shows**, and five of the extra ones HAD upstream fixes — a Bleichenbacher oracle
in `cryptography`, and four `nltk` CVEs including a critical JVM argument
injection. A scan that reads ranges cannot see a fixable CVE at all, which is a
worse failure than seeing one and accepting it.

The second half of the finding was `--ignore-unfixed` in `security-scan.yml`:
it drops every CVE with no upstream fix, permanently and with no record, so all
six unfixable findings vanished from the job whose output populates the Security
tab. That is exactly where an unfixed CVE belongs.

These assertions read the workflow files as text on purpose. The property is
about what CI is configured to do, and a mocked scanner would prove nothing
about that.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

_CI = pathlib.Path(".github/workflows/ci.yml")
_SECURITY_SCAN = pathlib.Path(".github/workflows/security-scan.yml")
_LOCK = pathlib.Path("requirements.lock")
_RANGES = pathlib.Path("requirements.txt")

#: Fixed in the versions this lock now pins. Each was invisible while the scan
#: only read ranges.
FIXED_BY_UPGRADE = {
    "cryptography": ("50.0.0", "CVE-2026-69247 — PKCS#7 Bleichenbacher oracle"),
    "nltk": ("3.10.3", "CVE-2026-79675 (critical), CVE-2026-71513, CVE-2026-72818, CVE-2026-78680"),
}


def _pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _LOCK.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s#]+)", line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


# ── the pinned set is scanned ─────────────────────────────────────────────────


def test_ci_scans_the_lock_file_not_only_the_ranges() -> None:
    """The fix itself: requirements.lock reaches Trivy under a name it reads."""
    ci = _CI.read_text(encoding="utf-8")
    assert "requirements.lock" in ci, (
        "ci.yml never mentions requirements.lock, so the scan is reading "
        "requirements.txt's ranges and reporting 0 because it cannot resolve them"
    )
    assert ".trivy-pinned" in ci, "the pinned manifest is not built for the scanner"
    assert re.search(r"trivy fs \.trivy-pinned", ci), "the pinned directory is built but never scanned"


def test_the_pinned_scan_can_fail_the_build() -> None:
    """A scan that cannot fail is a scan that is not a gate (F104's shape)."""
    ci = _CI.read_text(encoding="utf-8")
    pinned = ci[ci.index(".trivy-pinned") :]
    assert "--exit-code 1" in pinned, "the pinned scan does not block on a finding"
    assert "--ignorefile .trivyignore.yaml" in pinned, (
        "the pinned scan does not read the acceptance file, so written, expiring "
        "exemptions are silently ignored — Trivy only auto-loads plain .trivyignore"
    )


def test_the_scan_job_is_wired_into_the_workflow() -> None:
    """Reading the YAML, not the text: a step in no job runs never."""
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if ".trivy-pinned" in str(step.get("run", ""))
    ]
    assert steps, "no job contains the pinned-dependency scan"


# ── unfixed CVEs are reported, not dropped ────────────────────────────────────


@pytest.mark.parametrize("workflow", [_CI, _SECURITY_SCAN], ids=lambda p: p.name)
def test_no_scan_drops_unfixed_cves(workflow: pathlib.Path) -> None:
    """`--ignore-unfixed` removes a CVE permanently and leaves no record.

    An unfixed CVE cannot be resolved by a bump; it needs a human decision, and
    the place that decision gets made is .trivyignore.yaml, where it carries a
    reason and an expiry. Dropping it at the scanner means nobody is ever asked.
    """
    text = workflow.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # the comment explaining why the flag is gone
        assert "--ignore-unfixed" not in stripped, f"{workflow.name} still drops unfixed CVEs: {stripped}"


def test_both_scans_share_one_acceptance_file() -> None:
    """Two lists of accepted risk is two sets of expiry dates nobody reconciles."""
    for workflow in (_CI, _SECURITY_SCAN):
        assert "--ignorefile .trivyignore.yaml" in workflow.read_text(encoding="utf-8"), (
            f"{workflow.name} does not read .trivyignore.yaml"
        )


# ── the CVEs the pinned scan exposed stay fixed ──────────────────────────────


@pytest.mark.parametrize(("package", "expected"), sorted(FIXED_BY_UPGRADE.items()))
def test_the_security_floor_holds_in_the_lock(package: str, expected: tuple[str, str]) -> None:
    """A regenerated lock must not silently drop back below the fix."""
    minimum, reason = expected
    pins = _pins()
    assert package in pins, f"{package} is not pinned in requirements.lock"
    assert _version_tuple(pins[package]) >= _version_tuple(minimum), (
        f"requirements.lock pins {package}=={pins[package]}, below {minimum} which fixes {reason}"
    )


def test_the_range_manifest_carries_the_floor_too() -> None:
    """The lock is generated from the ranges; a floor only there survives a regen."""
    ranges = _RANGES.read_text(encoding="utf-8")
    for package, (minimum, _reason) in FIXED_BY_UPGRADE.items():
        match = re.search(rf"^{package}>=([0-9][^\s#]*)", ranges, re.M | re.I)
        assert match, f"{package} has no floor in requirements.txt, so a regenerated lock could drop below it"
        assert _version_tuple(match.group(1)) >= _version_tuple(minimum), (
            f"requirements.txt floors {package} at {match.group(1)}, below the fixed {minimum}"
        )


def test_the_scratch_directory_is_not_committed() -> None:
    assert ".trivy-pinned" in pathlib.Path(".gitignore").read_text(encoding="utf-8")
