# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The correction-register gate must be able to refuse.

`docs/audit/CORRECTION_REGISTER.md` is the single list of outstanding work, and
its value rests entirely on its status column being measured rather than
remembered. The pre-commit hook `correction-register` is what enforces that. A
hook nobody has watched fail is not a hook — Group 2 Rule 1 — so each test below
introduces a specific way the register can go wrong and asserts `--check`
refuses it.

The register is restored after every test; none of these mutate the tree that
survives the run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "correction_register.py"
REGISTER = ROOT / "docs" / "audit" / "CORRECTION_REGISTER.md"


def _check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.fixture
def register_restored():
    """Hand back the original bytes whatever the test does to the file."""
    original = REGISTER.read_text()
    try:
        yield original
    finally:
        REGISTER.write_text(original)


def test_the_gate_passes_on_the_committed_register():
    """The positive control.

    Without this, every refusal below could be a script that refuses
    everything — which would pass the injections and prove nothing.
    """
    r = _check()
    assert r.returncode == 0, f"clean tree should pass:\n{r.stdout}\n{r.stderr}"
    assert "document agrees" in r.stdout


def test_a_wrong_headline_count_is_refused(register_restored):
    """The drift that made fifteen separate fix lists untrustworthy.

    A register whose counts no longer match the code is the checkbox problem in
    a new file. This is the case that fires when someone lands a fix and does
    not regenerate.
    """
    original = register_restored
    m = re.search(r"\*\*(\d+) tracked", original)
    assert m, "the register has no headline to check"
    REGISTER.write_text(original.replace(m.group(0), f"**{int(m.group(1)) + 7} tracked", 1))

    r = _check()
    assert r.returncode != 0, "a wrong count must not pass"
    assert "STALE" in r.stdout


def test_a_changed_status_count_is_refused(register_restored):
    """Not just the total — the OPEN/FIXED split is the part people read.

    A register that keeps the right total while calling an open item fixed is
    worse than one that is obviously stale, because it reads as current.
    """
    original = register_restored
    m = re.search(r"OPEN (\d+) · PARTIAL (\d+)", original)
    assert m, "the register has no status breakdown"
    REGISTER.write_text(original.replace(m.group(0), f"OPEN {int(m.group(1)) - 1} · PARTIAL {int(m.group(2)) + 1}", 1))

    r = _check()
    assert r.returncode != 0, "a wrong OPEN/PARTIAL split must not pass"
    assert "STALE" in r.stdout


def test_a_dropped_finding_is_refused(register_restored):
    """Deleting an entry must not be a way to make the register agree.

    The counts alone would not catch this if someone edited both; the gate also
    asserts every tracked finding still has a section.
    """
    original = register_restored
    m = re.search(r"^#### (\S+) ·", original, re.MULTILINE)
    assert m, "the register has no finding sections"
    heading = m.group(0)
    REGISTER.write_text(original.replace(heading, "#### (removed) ·", 1))

    r = _check()
    assert r.returncode != 0, f"a dropped finding must not pass:\n{r.stdout}"
    assert "absent from the register" in r.stdout


def test_a_missing_register_is_refused(register_restored):
    """Fail closed. Deleting the document must not read as 'nothing outstanding'."""
    REGISTER.unlink()
    r = _check()
    assert r.returncode != 0, "a missing register must not pass"
    assert "MISSING" in r.stdout


def test_a_probe_that_raises_does_not_report_the_finding_fixed():
    """A broken probe is UNVERIFIED, never FIXED.

    The failure mode this guards is the one the register exists to avoid: a
    measurement that cannot fail. If an exception inside a probe were swallowed
    into a passing status, the register would quietly report clean as the code
    moved out from under it.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from scripts.correction_register import FIXED, UNVERIFIED, Finding

        def _boom() -> tuple[str, str]:
            raise RuntimeError("probe is broken")

        f = Finding("TEST", "t", "P3", "test", "src", "fix", "test first", "verify", _boom)
        status, evidence = f.measure()
        assert status == UNVERIFIED
        assert status != FIXED
        assert "RuntimeError" in evidence
    finally:
        sys.path.remove(str(ROOT))


# ── the evidence must be findable ─────────────────────────────────────────────
#
# `_grep` reports `path:line` and numbers the lines against `_code()`, which
# strips comments and docstrings so a probe cannot match the prose that
# EXPLAINS a defect. Stripping a triple-quoted block removed its newlines too,
# so every line number the register printed was short by however much prose sat
# above the hit. F206 reported monetization/stripe_integration.py:297; the code
# is at 329. Fifteen probes report locations this way.
#
# The register's whole proposition is "here is the evidence, go and look", and a
# coordinate that lands 32 lines away costs the reader the trust that makes the
# document worth keeping. Stripping must blank a region, never delete it.


def _register_module():
    """Import the register as a module so its helpers can be called directly.

    It must be registered in `sys.modules` BEFORE exec_module: the script
    defines dataclasses, and `dataclasses` resolves field types by looking its
    own module up in `sys.modules`. Without that the import raises
    AttributeError on None, which fails every test here for a reason that has
    nothing to do with what they assert.
    """
    import importlib.util

    name = "_cr_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def test_code_stripping_preserves_line_numbers():
    """A line's number in the stripped body is its number in the file."""
    cr = _register_module()
    source = 'x = 1\n"""\na docstring\nspanning several\nlines\n"""\nTARGET = 2\n'
    path = ROOT / "monetization" / "stripe_integration.py"
    real = path.read_text(encoding="utf-8")
    stripped = cr._code("monetization/stripe_integration.py")
    assert len(stripped.splitlines()) == len(real.splitlines()), (
        "stripping changed the line count, so every reported line number is offset"
    )

    # And the specific regression, against the live file rather than a fixture.
    rx = re.compile(r"int\(\s*amount\s*\*\s*100\s*\)")
    real_lines = [n for n, line in enumerate(real.splitlines(), 1) if rx.search(line)]
    strip_lines = [n for n, line in enumerate(stripped.splitlines(), 1) if rx.search(line)]
    assert real_lines, "the fixture line vanished from the file; re-point this test"
    assert real_lines == strip_lines, f"reported {strip_lines}, file has {real_lines}"
    assert source  # documents the shape above; the live-file assertion is the test


def test_code_still_strips_prose():
    """The reason `_code` exists must survive the line-preserving fix."""
    cr = _register_module()
    body = cr._code("scripts/correction_register.py")
    # This very file's probes quote patterns inside docstrings. If stripping
    # stopped working, those quotes would be matchable and half the probes here
    # would start finding themselves.
    assert '"""' not in body, "docstrings are no longer stripped"


def test_grep_reports_a_line_that_exists_in_the_file():
    """Every location the register prints must resolve in the real file."""
    cr = _register_module()
    hits = cr._grep(
        r"int\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*\*\s*100\s*\)",
        *cr._tracked("monetization/*.py"),
    )
    assert hits, "nothing matched; the assertion below would be vacuous"
    for hit in hits:
        rel, line_no, _ = hit.split(":", 2)
        actual = (ROOT / rel).read_text(encoding="utf-8").splitlines()[int(line_no) - 1]
        assert "100" in actual, f"{rel}:{line_no} does not point at the reported code: {actual!r}"


def test_the_cent_truncation_probe_sees_a_dotted_expression():
    """`int(payment.amount * 100)` truncates exactly as `int(amount * 100)` does.

    The probe's pattern was anchored to the literal name `amount`, so a call
    site spelling it `payment.amount` was invisible. Fixing only what the probe
    could see would have turned F206 green with a live truncation still in
    `payments/payment_gateway.py` — a probe satisfied by vocabulary, which is
    the same defect as a test satisfied by a mock.
    """
    cr = _register_module()
    status, evidence = cr._p_f206()
    assert status in {"PARTIAL", "OPEN"}, f"reported {status} while a truncation remains"
    assert "payment_gateway" in evidence or "3 site" in evidence, (
        f"the dotted call site is still invisible to the probe: {evidence}"
    )


# ── no probe may report a clean result from a scan that found nothing ─────────
#
# Rule 2 — an unmeasured value is absent, never zero — applied to the register
# itself. Audited by execution on 2026-09-13, TEN of 75 probes decided
# `OPEN if hits else FIXED`, so an empty file list read as "no violations found"
# rather than "nothing was measured": _p_f97, _p_f119, _p_f149, _p_f150,
# _p_f180, _p_f201, _p_f205, _p_f206, _p_f210, _p_f223. A renamed package, a
# moved directory or a glob that stopped matching would have closed each of them
# silently, and `--check` would have agreed because the counts still tallied.
#
# _p_f180 was the worst of them: `len(classes) <= 1` returned the message
# "one SecureVault, in config/vault.py" on ZERO matches, so deleting the live
# credential store read as the fix.
#
# This test is the audit, kept, so the class cannot come back.


def _starved(cr):
    """Every file reader returns nothing, as if the tree had moved."""
    cr._read = lambda rel: ""
    cr._code = lambda rel: ""
    cr._grep = lambda *a, **k: []
    cr._tracked = lambda pat: []
    cr._glob = lambda pat: []
    cr._exists = lambda rel: False
    return cr


def test_no_probe_reports_fixed_when_it_scanned_nothing():
    cr = _starved(_register_module())
    probes = {n: f for n, f in vars(cr).items() if n.startswith("_p_") and callable(f)}
    assert len(probes) > 50, "almost no probes were collected; this assertion would be vacuous"

    reporting_clean = []
    for name, probe in sorted(probes.items()):
        try:
            status, _ = probe()
        except Exception:
            continue  # Finding.measure turns a raising probe into UNVERIFIED, which is fail-closed
        if status == cr.FIXED:
            reporting_clean.append(name)

    assert not reporting_clean, (
        f"{reporting_clean} report FIXED from a scan that matched nothing — "
        "an unmeasured value rendered as 'no defect found'"
    )


def test_the_starvation_harness_actually_starves():
    """The positive control.

    Without it, a typo in `_starved` leaves the readers live, every probe
    measures the real tree, and the assertion above passes while testing
    nothing — which is the defect it exists to catch, one level up.
    """
    cr = _starved(_register_module())
    assert cr._tracked("**/*.py") == []
    assert cr._code("scripts/correction_register.py") == ""
    assert cr._grep("anything", "some/file.py") == []
