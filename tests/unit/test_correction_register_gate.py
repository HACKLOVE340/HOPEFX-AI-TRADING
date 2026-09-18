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

No test here writes to `docs/audit/CORRECTION_REGISTER.md`. The injections run
against a copy in `tmp_path`, reached through `HOPEFX_CORRECTION_REGISTER`.

This paragraph used to read "the register is restored after every test; none of
these mutate the tree that survives the run". That was true of every run that
*survived*, and it is why the real behaviour went unexamined: the tests did edit
the committed register, and one deleted it, restoring it in a fixture's
`finally`. `test_the_suite_leaves_the_committed_register_untouched` now asserts
the stronger claim this paragraph makes, so it cannot quietly stop being true.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "correction_register.py"
REGISTER = ROOT / "docs" / "audit" / "CORRECTION_REGISTER.md"


def _check(register: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the gate, optionally against a register held somewhere else."""
    env = dict(os.environ)
    if register is not None:
        env["HOPEFX_CORRECTION_REGISTER"] = str(register)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


@pytest.fixture
def register_copy(tmp_path: Path) -> tuple[Path, str]:
    """A scratch copy of the register, and its text. The committed file is not touched.

    This used to be `register_restored`, which handed back the real document's
    bytes, let the test edit `docs/audit/CORRECTION_REGISTER.md` in place, and
    put it back in a `finally`. That worked for every run that finished. It also
    meant the single list of outstanding work spent part of every test run in a
    deliberately broken state — and, in `test_a_missing_register_is_refused`,
    deleted outright. A `finally` does not run for `kill -9`, an OOM kill, or a
    container stopped mid-run, so the window was real.
    """
    copy = tmp_path / "CORRECTION_REGISTER.md"
    original = REGISTER.read_text()
    copy.write_text(original, encoding="utf-8")
    return copy, original


def test_the_gate_passes_on_the_committed_register():
    """The positive control.

    Without this, every refusal below could be a script that refuses
    everything — which would pass the injections and prove nothing.
    """
    r = _check()
    assert r.returncode == 0, f"clean tree should pass:\n{r.stdout}\n{r.stderr}"
    assert "document agrees" in r.stdout


def test_a_wrong_headline_count_is_refused(register_copy):
    """The drift that made fifteen separate fix lists untrustworthy.

    A register whose counts no longer match the code is the checkbox problem in
    a new file. This is the case that fires when someone lands a fix and does
    not regenerate.
    """
    copy, original = register_copy
    m = re.search(r"\*\*(\d+) tracked", original)
    assert m, "the register has no headline to check"
    copy.write_text(original.replace(m.group(0), f"**{int(m.group(1)) + 7} tracked", 1))

    r = _check(copy)
    assert r.returncode != 0, "a wrong count must not pass"
    assert "STALE" in r.stdout


def test_a_changed_status_count_is_refused(register_copy):
    """Not just the total — the OPEN/FIXED split is the part people read.

    A register that keeps the right total while calling an open item fixed is
    worse than one that is obviously stale, because it reads as current.
    """
    copy, original = register_copy
    m = re.search(r"OPEN (\d+) · PARTIAL (\d+)", original)
    assert m, "the register has no status breakdown"
    copy.write_text(original.replace(m.group(0), f"OPEN {int(m.group(1)) - 1} · PARTIAL {int(m.group(2)) + 1}", 1))

    r = _check(copy)
    assert r.returncode != 0, "a wrong OPEN/PARTIAL split must not pass"
    assert "STALE" in r.stdout


def test_a_dropped_finding_is_refused(register_copy):
    """Deleting an entry must not be a way to make the register agree.

    The counts alone would not catch this if someone edited both; the gate also
    asserts every tracked finding still has a section.
    """
    copy, original = register_copy
    m = re.search(r"^#### (\S+) ·", original, re.MULTILINE)
    assert m, "the register has no finding sections"
    heading = m.group(0)
    copy.write_text(original.replace(heading, "#### (removed) ·", 1))

    r = _check(copy)
    assert r.returncode != 0, f"a dropped finding must not pass:\n{r.stdout}"
    assert "absent from the register" in r.stdout


def test_a_missing_register_is_refused(register_copy):
    """Fail closed. Deleting the document must not read as 'nothing outstanding'."""
    copy, _ = register_copy
    copy.unlink()
    r = _check(copy)
    assert r.returncode != 0, "a missing register must not pass"
    assert "MISSING" in r.stdout


def test_selftest_proves_the_gate_can_fail_without_touching_the_committed_register():
    """`--selftest` must not vandalise the document to demonstrate the gate.

    It exists for a good reason — a gate nobody has watched fail is not a gate —
    and it proved that by writing a wrong headline into
    `docs/audit/CORRECTION_REGISTER.md`, running `--check` against it, and
    restoring the original in a `finally`. Same destructive window as the four
    injection tests that used to do this, and in the one command a contributor is
    actually invited to run by hand: between the two writes the register held a
    deliberately false headline, and a `kill -9`, an OOM kill or a closed
    terminal left it that way.

    Both halves are asserted. mtime, because a rewrite-and-restore leaves the
    bytes identical and a content check would pass against the defect. And exit
    0, because `--selftest` returns non-zero when `--check` accepts a wrong
    count — so a version that quietly stopped mutating anything at all, and
    therefore stopped proving anything, would fail here rather than read as a
    clean run.
    """
    before_bytes = REGISTER.read_bytes()
    before_mtime = REGISTER.stat().st_mtime_ns

    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert r.returncode == 0, f"--selftest must still prove --check refuses a wrong count:\n{r.stdout}\n{r.stderr}"
    assert REGISTER.exists(), "--selftest deleted the committed register"
    assert REGISTER.read_bytes() == before_bytes, "--selftest changed the committed register"
    assert REGISTER.stat().st_mtime_ns == before_mtime, (
        "--selftest wrote to the committed register and put it back — the bytes "
        "match, but the file was broken on disk in between"
    )


def test_the_verdict_does_not_depend_on_pythonpath():
    """The same tree must measure the same way however the script is invoked.

    Two probes import `ml.inference_engine` to read the shipped model's age and
    provenance. Run as `python scripts/correction_register.py`, `sys.path[0]` is
    `scripts/`, so that import raised ModuleNotFoundError and both probes
    degraded to UNVERIFIED. Run with the repository root on PYTHONPATH — which
    is how an activated dev shell and this container both invoke it — the import
    succeeded and both resolved OWNER. Same commit, same code, two headlines,
    and `--check` passed or failed accordingly.

    That made the register's own gate a report on the reader's shell. Worse in
    one direction than the other: UNVERIFIED is what the register uses for
    "cannot honestly be called open or fixed", and here it was being produced by
    a measurement that never ran, on two findings that are squarely the owner's.

    Asserts stdout as well as the exit code: two runs that agree only on "exit
    0" could still be reporting different counts.
    """
    clean = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    with_root = dict(clean, PYTHONPATH=str(ROOT))

    def run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=env,
        )

    bare, rooted = run(clean), run(with_root)

    assert bare.stdout == rooted.stdout, (
        "the register measures differently depending on PYTHONPATH:\n"
        f"  without: {bare.stdout}\n  with:    {rooted.stdout}"
    )
    assert bare.returncode == rooted.returncode

    # Two runs that agree only because BOTH went blind would satisfy the
    # assertion above, so the agreement needs a witness: with `ml/` on the tree
    # the model probes must have measured, not degraded.
    #
    # Conditioned on the tree actually carrying the provenance lookup, rather
    # than asserted outright. This test's subject is that the verdict does not
    # depend on PYTHONPATH; "the repository can measure a model's age" is a
    # different claim, and it is false on any tree cut for review where this
    # gate lands before the ML package (docs/audit/LANDING_PLAN.md). Asserting
    # it here made this file fail for the composition of the tree rather than
    # for the defect it watches.
    #
    # The witness is `_model_training_time`, not `ml/inference_engine.py`: the
    # module exists on `main` WITHOUT that function, so a file check reads as
    # "the capability is here" when it is not, and the probe then degrades to
    # UNVERIFIED for an honest reason. Read from source rather than imported,
    # so this stays a question about the tree and not about sys.path — which is
    # the very thing under test.
    _ie = ROOT / "ml" / "inference_engine.py"
    if _ie.exists() and "_model_training_time" in _ie.read_text(encoding="utf-8"):
        assert "UNVERIFIED 0" in bare.stdout, (
            "the model probes must measure rather than degrade — `ml/` is on "
            "this tree, so UNVERIFIED means the import is failing again, in "
            "both environments this time"
        )


def test_the_suite_leaves_the_committed_register_untouched():
    """The tests above must not write to the document they are about.

    They used to. `test_a_missing_register_is_refused` called `REGISTER.unlink()`
    on `docs/audit/CORRECTION_REGISTER.md` and relied on a fixture's `finally` to
    put it back; the other three rewrote it with a deliberately wrong headline.
    Every completed run restored it, so `git status` was clean afterwards and
    nothing ever reported a problem — which is exactly why this went unnoticed.
    A `finally` does not run for `kill -9`, an OOM kill, or a container stopped
    mid-run, and the register was observed mid-deletion during this audit:
    `git diff` reported 1,180 deletions and the path missing from the work tree.

    mtime is the assertion, not the bytes: a run that rewrites the file and
    restores it byte-for-byte leaves the content identical, so comparing content
    alone would pass against the defect this test exists to catch.

    Only the injection tests are re-run here — they are the four that held the
    old fixture — which keeps this to a few seconds rather than re-running the
    module's probe-heavy cases.
    """
    before_bytes = REGISTER.read_bytes()
    before_mtime = REGISTER.stat().st_mtime_ns

    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(Path(__file__)),
            "-q",
            "-p",
            "no:cacheprovider",
            "-k",
            "refused",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    # 0 = all passed, 1 = some failed. Anything else (2 interrupted, 3 internal
    # error, 4 usage, 5 nothing collected) means the inner run did not execute
    # the injections, and a register left alone by a run that never happened
    # proves nothing — the harness has to be live before its result counts.
    #
    # Whether those injections PASS is deliberately not asserted here. They are
    # sensitive to `PYTHONPATH`: with the repository root on it, `ml` imports,
    # two probes resolve OWNER instead of UNVERIFIED, and the gate reports STALE
    # against a register that is correct for the way pre-commit invokes it. That
    # is a real defect and it is recorded separately; binding it to this test
    # would mean this one goes red for a reason that has nothing to do with the
    # file it is watching.
    assert r.returncode in (0, 1), f"the injection tests did not run:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}"
    assert REGISTER.exists(), "the run deleted the committed register"
    assert REGISTER.read_bytes() == before_bytes, "the run changed the committed register"
    assert REGISTER.stat().st_mtime_ns == before_mtime, (
        "the run wrote to the committed register and restored it — the bytes "
        "match, but the file was open for writing, which is the window"
    )


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


def test_code_stripping_preserves_line_numbers(tmp_path):
    """A line's number in the stripped body is its number in the file.

    This first used `monetization/stripe_integration.py` and the live
    `int(amount * 100)` truncation as its fixture — and then F206 fixed that
    truncation and the test failed, exactly as its own guard message predicted:
    "the fixture line vanished from the file; re-point this test". A test
    anchored to a defect is a test scheduled to break the day somebody fixes it,
    which is the shape this repository keeps finding in other people's suites.

    It now asserts the PROPERTY on a constructed file, and separately that the
    property holds across real modules — neither of which depends on any
    particular defect still being present.
    """
    cr = _register_module()

    sample = tmp_path / "sample.py"
    sample.write_text(
        'x = 1\n"""\na docstring\nspanning\nseveral lines\n"""\n# a comment\nTARGET = 2\n',
        encoding="utf-8",
    )
    cr_root = cr.ROOT
    try:
        cr.ROOT = tmp_path
        stripped = cr._code("sample.py")
        assert len(stripped.splitlines()) == 8, "stripping changed the line count"
        assert "a docstring" not in stripped, "the docstring survived; _code stopped stripping prose"
        target = [n for n, line in enumerate(stripped.splitlines(), 1) if "TARGET" in line]
        assert target == [8], f"TARGET is on line 8 of the file, reported {target}"
    finally:
        cr.ROOT = cr_root


def test_code_stripping_preserves_line_numbers_on_real_modules():
    """The same property on files that actually carry prose, live.

    Chosen because they are heavily documented — the more prose a file has, the
    further a deleted-docstring offset would push its line numbers — and because
    none of them is tied to an open finding.
    """
    cr = _register_module()
    for rel in ("scripts/correction_register.py", "brokers/base.py", "risk/manager.py"):
        real = (cr.ROOT / rel).read_text(encoding="utf-8", errors="replace")
        stripped = cr._code(rel)
        assert len(stripped.splitlines()) == len(real.splitlines()), (
            f"{rel}: stripping changed the line count, so every line number it reports is offset"
        )


def test_grep_reports_a_line_that_exists_in_the_file():
    """Every location the register prints must resolve in the real file.

    Anchored on `class` declarations rather than on any defect: a class exists
    for as long as the module does, so this cannot be broken by fixing a finding.
    """
    cr = _register_module()
    hits = cr._grep(r"^class \w+", *cr._tracked("brokers/*.py"))
    assert len(hits) > 5, "almost nothing matched; the assertion below would be vacuous"
    for hit in hits:
        rel, line_no, _ = hit.split(":", 2)
        actual = (cr.ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines()[int(line_no) - 1]
        assert actual.lstrip().startswith("class "), (
            f"{rel}:{line_no} does not point at the reported declaration: {actual!r}"
        )


def test_the_cent_truncation_probe_sees_a_dotted_expression(tmp_path):
    """`int(payment.amount * 100)` truncates exactly as `int(amount * 100)` does.

    The probe's pattern was anchored to the literal name `amount`, so a call site
    spelling it `payment.amount` was invisible and F206 could have reported FIXED
    with a live truncation still in `payments/`.

    THIS DRIVES `_p_f206` ITSELF against a constructed tree. The first version
    passed the widened regex to `_grep` as a literal argument and therefore
    tested a copy of the pattern rather than the probe's — it passed against the
    reverted, `amount`-anchored code, which is the whole defect class this file
    exists to catch, committed inside the file that catches it. Caught by
    injecting the old pattern back and watching the test stay green.
    """
    cr = _register_module()
    (tmp_path / "monetization").mkdir()
    (tmp_path / "monetization" / "gw.py").write_text("b = int(payment.amount * 100)\n", encoding="utf-8")

    root, tracked = cr.ROOT, cr._tracked
    try:
        cr.ROOT = tmp_path
        cr._tracked = lambda pat: ["monetization/gw.py"] if "monetization" in pat else []
        status, evidence = cr._p_f206()
    finally:
        cr.ROOT, cr._tracked = root, tracked

    assert status != cr.FIXED, (
        "the probe reported FIXED with `int(payment.amount * 100)` in the tree — "
        "a dotted call site is invisible to it, so fixing only what it can see "
        "would close F206 with a live truncation in the payment path"
    )
    assert "gw.py" in evidence, f"the truncation was not named in the evidence: {evidence}"


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


def test_section_four_lists_exactly_the_owner_findings():
    """The register's prose and its probes must name the same owner decisions.

    §4 says what each owner choice *is*; the probes say which findings are
    waiting on one. Nothing checked the two against each other, so §4 carried
    five rows while the register measured six — a reader working the owner's
    queue from §4 would never have seen the sixth.
    """
    import re
    from pathlib import Path

    cr = _register_module()
    document = Path(cr.ROOT, "docs/audit/CORRECTION_REGISTER.md").read_text(encoding="utf-8")

    section = document.split("## 4. Owner decisions", 1)
    assert len(section) == 2, "the register has no §4 — it was dropped, not renamed"
    body = section[1].split("\n## ", 1)[0]
    listed = set(re.findall(r"^\|\s*\*\*([^*]+)\*\*\s*\|", body, re.M))
    assert listed, "§4's table is empty — this test would otherwise assert nothing"

    measured = {f.id for f in cr.FINDINGS if f.measure()[0] == cr.OWNER}
    known = {f.id for f in cr.FINDINGS}

    assert measured - listed == set(), (
        f"owner findings missing from §4: {sorted(measured - listed)} — the owner works their "
        "queue from this table, so a decision absent from it is a decision nobody is asked to make"
    )
    # The reverse does NOT hold, deliberately. A decision can outlive the status
    # of the finding that surfaced it: F61/F107 measures PARTIAL and F178/F98
    # measures FIXED, while "build the OANDA adapter now?" and "which k8s tree is
    # real?" are both still the owner's to answer. What must hold is that every
    # row names a finding the register actually knows, so a renamed or dropped id
    # cannot sit here pointing at nothing.
    assert listed - known == set(), f"§4 names findings the register does not track: {sorted(listed - known)}"


def test_the_documents_prose_sections_survive_a_regeneration():
    """`--markdown > CORRECTION_REGISTER.md` deletes four of the six sections.

    The document is prose §1-§3, then the generated block, then prose §4-§6. The
    obvious regeneration command is a redirect, and a redirect writes only the
    block. It happened twice on 2026-09-13, and `--check` agreed both times,
    because it compares counts and the counts were right. Only
    `test_section_four_lists_exactly_the_owner_findings` above noticed, and only
    because the OWNER count had moved in the same window — had it not, the loss
    would have been silent.

    So `--write` splices, and this asserts the shape the splice preserves.
    """
    from pathlib import Path

    cr = _register_module()
    document = Path(cr.ROOT, "docs/audit/CORRECTION_REGISTER.md").read_text(encoding="utf-8")
    headings = [line for line in document.splitlines() if line.startswith("## ")]
    assert len(headings) >= 6, (
        f"the register has {len(headings)} top-level sections, expected 6 — a redirect over the "
        f"file leaves only the generated block. Regenerate with `--write`. Found: {headings}"
    )
    assert cr.GENERATED_MARKER in document, "the generated block's marker is gone, so --write cannot find it"


def test_the_splice_keeps_what_it_did_not_generate():
    cr = _register_module()
    document = "\n".join(
        [
            "# Title",
            "",
            "## 1. Prose before",
            "",
            "kept",
            "",
            cr.GENERATED_MARKER,
            "**stale counts**",
            "",
            "### OPEN — 9",
            "",
            "## 4. Prose after",
            "",
            "also kept",
            "",
        ]
    )
    spliced = cr.splice(document, cr.GENERATED_MARKER + "\n**fresh counts**\n")
    assert "kept" in spliced and "also kept" in spliced
    assert "## 1. Prose before" in spliced and "## 4. Prose after" in spliced
    assert "**fresh counts**" in spliced
    assert "**stale counts**" not in spliced and "### OPEN — 9" not in spliced


def test_the_splice_refuses_a_document_it_cannot_find_the_block_in():
    """Refusing is the point: the alternative is replacing prose with a table."""
    import pytest as _pytest

    cr = _register_module()
    with _pytest.raises(ValueError, match="no generated block"):
        cr.splice("## 1. Only prose here\n\nnothing generated\n", "body")
