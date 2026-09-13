#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Measure the status of every outstanding correction, from the code.

``docs/audit/CORRECTION_REGISTER.md`` is the single list of what is left to fix.
This script is what keeps it true. It does not read that document to find out
what is open — it probes the repository and says so, and then checks the
document agrees.

Why it exists
-------------
The outstanding work was spread across fifteen documents totalling ~29,000
lines: ``docs/audit/REMEDIATION_PLAN.md`` (80 open checkboxes),
five plans under ``docs/audit/plans/``, and three prose registers
(``CODE_READING_FINDINGS.md``, ``HARDENING_BACKLOG.md``,
``MASTER_OUTSTANDING.md``). Consolidating them by copying the open checkboxes
forward would have been wrong: measured on 2026-09-13, a substantial share of
those boxes describe work that is already done. F135's wallet id carries a
``uuid4`` suffix; F137's ``amount_crypto`` is ``Numeric(28, 8)``; F139's
kill-switch RBAC exists in both k8s trees; F142's ``FIXRouter`` takes an
injected ``OrderGate``; F176 prints ``DECLARED`` rather than
``FULL COVERAGE``. A register that re-reported those as open would breach the
audit plan's own Phase 11 rule — no previously fixed defect is re-reported as
open without evidence of regression — and would waste the reader's first hour.

So each finding here carries a probe. The probe returns what the code says
today, and the status follows from that rather than from anybody's memory.

Two traps this file is written to avoid
---------------------------------------
1. **Reading prose as code.** ``.coveragerc`` documents the F105 fix in a long
   comment naming ``risk/manager.py``; a naive grep for that path "finds" the
   defect inside its own fix note. Every probe here strips comments first --
   see ``_code()``. This is the same defect ``security/code_analyzer.py`` had
   (F255) and that ``scripts/verify_skill_claims.py`` then repeated.
2. **A measurement that cannot fail.** ``--check`` compares the document's
   stated counts against the probes and exits non-zero on a mismatch, so the
   register cannot drift silently. Run ``--selftest`` to see the checker itself
   turn red on a deliberately wrong count.

Usage
-----
    python scripts/correction_register.py              # status table
    python scripts/correction_register.py --markdown   # the register's body
    python scripts/correction_register.py --check      # CI/pre-commit gate
    python scripts/correction_register.py --id F97     # one finding, verbose
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "audit" / "CORRECTION_REGISTER.md"

# Status vocabulary — the audit plan's taxonomy, narrowed to what a probe can
# distinguish. PARTIAL and OWNER are not weaker forms of OPEN: PARTIAL means the
# defect's harm is contained but the capability is absent, and OWNER means
# engineering must not choose.
OPEN = "OPEN"
PARTIAL = "PARTIAL"
FIXED = "FIXED"
OWNER = "OWNER"
UNVERIFIED = "UNVERIFIED"

_STATUS_ORDER = {OPEN: 0, PARTIAL: 1, OWNER: 2, UNVERIFIED: 3, FIXED: 4}


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------


def _read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def _code(rel: str) -> str:
    """Source with comments and docstrings removed.

    A probe that greps raw text finds the defect quoted inside the comment that
    explains its fix. Strip prose first, always.
    """
    text = _read(rel)
    if not text:
        return ""
    if rel.endswith((".py",)):
        text = re.sub(r'"""[\s\S]*?"""', "", text)
        text = re.sub(r"'''[\s\S]*?'''", "", text)
        text = re.sub(r"(?m)#.*$", "", text)
    elif rel.endswith((".yml", ".yaml", ".cfg", ".coveragerc", ".ini", ".toml")):
        text = re.sub(r"(?m)^\s*#.*$", "", text)
    elif rel.endswith((".ts", ".tsx", ".js", ".jsx")):
        text = re.sub(r"/\*[\s\S]*?\*/", "", text)
        text = re.sub(r"(?m)//.*$", "", text)
    return text


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _grep(pattern: str, *rels: str, code_only: bool = True) -> list[str]:
    """Matching lines across the given files. Comment-stripped by default."""
    hits: list[str] = []
    rx = re.compile(pattern)
    for rel in rels:
        body = _code(rel) if code_only else _read(rel)
        for n, line in enumerate(body.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:120]}")
    return hits


def _glob(pattern: str) -> list[str]:
    return sorted(str(p.relative_to(ROOT)) for p in ROOT.glob(pattern))


def _tracked(pattern: str) -> list[str]:
    """git-tracked paths matching a glob — avoids .venv and build output."""
    try:
        out = subprocess.run(
            ["git", "ls-files", pattern],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
    except Exception:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# Finding model
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    id: str
    title: str
    priority: str  # P0 | P1 | P2 | P3 | OWNER
    area: str
    source: str  # where the full evidence lives
    fix: str  # what to do
    test_first: str  # the regression test to write before the fix
    verify: str  # the command that proves it
    probe: Callable[[], tuple[str, str]]
    skills: list[str] = field(default_factory=list)

    def measure(self) -> tuple[str, str]:
        try:
            return self.probe()
        except Exception as exc:  # a broken probe is not a pass
            return UNVERIFIED, f"probe raised {type(exc).__name__}: {exc}"


def _named(status: str, evidence: str) -> tuple[str, str]:
    return status, evidence


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _p_f96() -> tuple[str, str]:
    body = _code(".github/workflows/deploy.yml")
    if not body:
        return UNVERIFIED, "deploy.yml not found"
    gated = "needs:" in body or "workflow_run:" in body
    return _named(
        FIXED if gated else OPEN,
        "deploy.yml gates on another workflow"
        if gated
        else "deploy.yml has no `needs:` and no `workflow_run:` — it fires on push regardless of CI",
    )


def _p_f97() -> tuple[str, str]:
    hits = []
    for wf in _tracked(".github/workflows/*.yml"):
        for m in re.finditer(r"uses:\s*([\w.-]+/[\w.-]+)@(\S+)", _code(wf)):
            action, ref = m.group(1), m.group(2)
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                hits.append(f"{wf}: {action}@{ref}")
    secret_holders = [h for h in hits if "ssh-action" in h]
    if secret_holders:
        return OPEN, f"{len(hits)} unpinned action refs; secret-holding: {secret_holders[0]}"
    return (
        (FIXED, "no secret-holding action is float-pinned")
        if not hits
        else (PARTIAL, f"{len(hits)} unpinned refs, none holding a deploy secret")
    )


def _p_f176() -> tuple[str, str]:
    body = _code("scripts/invariant_coverage.py")
    if not body:
        return UNVERIFIED, "scripts/invariant_coverage.py not found"
    if "FULL COVERAGE" in body:
        return OPEN, "still prints FULL COVERAGE from declared booleans"
    if "DECLARED" in body:
        return FIXED, "prints DECLARED — the matrix no longer presents itself as a measurement"
    return UNVERIFIED, "neither marker found; read the file"


def _p_f135() -> tuple[str, str]:
    hits = _grep(r"def _(txn|transaction)_id|TXN-", "payments/wallet.py")
    has_uuid = any("uuid" in h for h in hits)
    return _named(
        FIXED if has_uuid else OPEN,
        hits[0] if hits else "no transaction-id generator found",
    )


def _p_f137() -> tuple[str, str]:
    hits = _grep(r"amount_crypto\s*=\s*Column", "database/models.py")
    if not hits:
        return UNVERIFIED, "amount_crypto column not found"
    return _named(FIXED if "Numeric" in hits[0] else OPEN, hits[0])


def _p_f138() -> tuple[str, str]:
    callers = [
        h
        for h in _grep(r"verify_balance_after", *_tracked("*.py"))
        if not h.startswith("invariants/payments.py") and not h.startswith("tests/")
    ]
    return _named(
        FIXED if callers else OPEN,
        f"{len(callers)} production caller(s): {callers[0] if callers else 'none'}",
    )


def _p_f139() -> tuple[str, str]:
    rbac = _glob("deployments/k8s/*rbac*") + _glob("k8s/*rbac*")
    return _named(
        FIXED if rbac else OPEN,
        f"kill-switch RBAC manifests: {', '.join(rbac) if rbac else 'none'}",
    )


def _p_f142() -> tuple[str, str]:
    body = _code("execution/fix_router.py")
    if not body:
        return UNVERIFIED, "execution/fix_router.py not found"
    injected = "OrderGate" in body
    return _named(
        FIXED if injected else OPEN,
        "FIXRouter takes an injected OrderGate" if injected else "FIXRouter._route has no gate beyond `self._halted`",
    )


def _p_f178() -> tuple[str, str]:
    modes = set()
    for f in _glob("k8s/*.yaml") + _glob("deployments/k8s/*.yaml"):
        for m in re.finditer(r'HOPEFX_INVARIANT_MODE:\s*"?(\w+)"?', _code(f)):
            modes.add((f, m.group(1)))
    values = {v for _, v in modes}
    if len(values) > 1:
        return OPEN, f"contradictory values across ConfigMaps: {sorted(modes)}"
    return _named(FIXED if values else UNVERIFIED, f"single value {values or 'none found'}")


def _p_f221() -> tuple[str, str]:
    """The omit list must not hide the money path.

    Pinned by tests/unit/test_coverage_gate_states_its_scope.py; this probe is
    the same question asked from outside pytest.
    """
    body = _code(".coveragerc")
    if not body:
        return UNVERIFIED, ".coveragerc not found"
    omit_block = body.split("omit", 1)[-1].split("\n[", 1)[0] if "omit" in body else ""
    hidden = [
        m
        for m in (
            "risk/manager.py",
            "risk/pre_trade_gate.py",
            "execution/engine.py",
            "execution/fix_router.py",
            "core/decision/HOPEFXDecisionEngine.py",
        )
        if m in omit_block
    ]
    return _named(
        OPEN if hidden else FIXED,
        f"omit hides {hidden}" if hidden else "no safety module appears in the omit list",
    )


def _p_f218() -> tuple[str, str]:
    """Model tables that exist only via create_all() and have no migration."""
    tables = set(re.findall(r'__tablename__\s*=\s*"([^"]+)"', _code("database/models.py")))
    # Only a create_table declaration counts. Searching the whole migration text
    # matched table names inside comments and reported 0 missing of 44.
    mig = "\n".join(_code(p) for p in _tracked("alembic/versions/*.py"))
    created = set(re.findall(r'create_table\(\s*["\']([^"\']+)["\']', mig))
    missing = sorted(tables - created)
    if not tables:
        return UNVERIFIED, "no __tablename__ found in database/models.py"
    return _named(
        OPEN if missing else FIXED,
        f"{len(missing)} of {len(tables)} tables have no migration"
        + (f": {', '.join(missing[:6])}" if missing else ""),
    )


def _p_f61() -> tuple[str, str]:
    alias = _grep(r"AsyncOANDAConnector\s*=", "brokers/oanda.py")
    guarded = _exists("tests/unit/test_broker_type_oanda_is_not_silently_broken.py")
    if alias and guarded:
        return PARTIAL, (
            "the bare alias remains, but a test now forces it to fail loudly rather "
            "than at the first live order — building the adapter is a feature, not a fix"
        )
    if alias:
        return OPEN, alias[0]
    return FIXED, "no bare alias"


def _p_f204() -> tuple[str, str]:
    body = _code("monetization/revenue_split.py")
    if not body:
        return UNVERIFIED, "monetization/revenue_split.py not found"
    ok = "SIMULATED" in body
    return _named(
        FIXED if ok else OPEN,
        "PayoutStatus.SIMULATED exists — a payout with no transfer backend is no longer PAID"
        if ok
        else "no SIMULATED status; a payout with no backend still reports PAID",
    )


def _p_f203() -> tuple[str, str]:
    body = _code("monetization/revenue_split.py")
    if not body:
        return UNVERIFIED, "monetization/revenue_split.py not found"
    locked = "RLock(" in body or "threading.Lock(" in body
    zeroed = re.search(r'pending_usd\s*=\s*Decimal\("0', body) is not None
    if locked and not zeroed:
        return FIXED, "balance is decremented under a lock"
    return OPEN, f"lock={locked} zeroing-assignment={zeroed}"


def _p_f208() -> tuple[str, str]:
    body = _code("monetization/revenue_split.py")
    if not body:
        return UNVERIFIED, "monetization/revenue_split.py not found"
    persisted = "session_factory" in body and "commit()" in body
    return _named(
        FIXED if persisted else OPEN,
        "creator ledger writes through a session factory"
        if persisted
        else "balances live in module dicts; a restart erases what creators are owed",
    )


def _p_f222() -> tuple[str, str]:
    t = _tracked("tests/**/*revenue_split*")
    return _named(FIXED if t else OPEN, f"{len(t)} test file(s): {', '.join(t[:3]) or 'none'}")


def _p_f175() -> tuple[str, str]:
    emoji = re.compile("[\U0001f300-\U0001faff]")
    files = [f for f in _tracked("frontend/src/**") if f.endswith((".ts", ".tsx")) and emoji.search(_read(f))]
    return _named(
        FIXED if not files else OPEN,
        f"{len(files)} frontend source file(s) still carry emoji" if files else "no emoji in frontend/src",
    )


def _p_f198() -> tuple[str, str]:
    body = _code("api/kyc.py")
    if not body:
        return UNVERIFIED, "api/kyc.py not found"
    bare = 'prefix="/kyc"' in body
    alias = "kyc_alias_router" in body
    if bare and alias:
        return PARTIAL, "the /api/kyc alias exists; the bare /kyc router still shadows the SPA route"
    return _named(FIXED if not bare else OPEN, f"bare-prefix router present={bare}")


def _p_f199() -> tuple[str, str]:
    spa = _grep(r"_SPA_ROUTES\s*=", *_tracked("core/*.py"), *_tracked("api/*.py"))
    app = _read("frontend/src/App.tsx")
    declared = len(re.findall(r"<Route\s", app))
    if not spa:
        return UNVERIFIED, f"_SPA_ROUTES not found; App.tsx declares {declared} <Route> elements"
    src = spa[0].split(":")[0]
    listed = len(re.findall(r'"/[^"]*"', _code(src).split("_SPA_ROUTES", 1)[-1].split("]", 1)[0]))
    return _named(
        OPEN if listed != declared else FIXED,
        f"{src} lists {listed}; App.tsx declares {declared} — hand-maintained",
    )


def _p_f200() -> tuple[str, str]:
    vendored = bool(_glob("static/swagger*") or _glob("**/swagger-ui-dist"))
    return _named(
        FIXED if vendored else OPEN,
        "swagger assets vendored"
        if vendored
        else "/docs loads the Swagger CDN, which the CSP blocks — the page is blank in every deployment",
    )


def _p_a8() -> tuple[str, str]:
    """Do the committed artifacts still match the baseline that gates their load?

    This probe replaced one that counted how many files mention
    ``model_checksums`` and concluded FIXED from 21 hits — almost all of them
    prose describing the problem. Counting mentions is not measuring integrity.
    """
    import hashlib
    import json

    d = ROOT / "ml" / "saved_models"
    manifest = d / "model_checksums.json"
    if not manifest.exists():
        return UNVERIFIED, "model_checksums.json not found"
    try:
        stored = json.loads(manifest.read_text())
    except Exception as exc:
        return OPEN, f"manifest unparseable: {exc}"

    mismatch, absent = [], []
    for name, want in sorted(stored.items()):
        f = d / name
        if not f.exists():
            absent.append(name)
        elif hashlib.sha256(f.read_bytes()).hexdigest() != want:
            mismatch.append(name)

    if not mismatch and not absent:
        return FIXED, f"all {len(stored)} listed artifacts match their recorded sha256"
    return OPEN, (
        f"{len(mismatch)} of {len(stored)} artifacts fail their recorded sha256 "
        f"({', '.join(mismatch) or 'none'}); {len(absent)} listed but absent "
        f"({', '.join(absent) or 'none'}). ml/__init__.py::_verify_checksum reads this "
        "file on every load and refuses in production, so each mismatch is a refused load"
    )


def _p_a9() -> tuple[str, str]:
    # A row written into the `trades`/`orders` tables, not any assignment of the
    # name: `position_manager.py` carries it inside a log FORMAT STRING, which the
    # first version of this probe counted as a writer and reported FIXED.
    writers = [
        h
        for h in _grep(r"client_order_id\s*=\s*(?!%s)", *_tracked("*.py"))
        if not h.startswith(("tests/", "scripts/", "alembic/", "database/models.py", "database/repositories/"))
        and "logger" not in h
        and '"' not in h.split("client_order_id")[0][-30:]
    ]
    trade_writers = [h for h in writers if "trade_executor" not in h]
    return _named(
        OWNER if not trade_writers else FIXED,
        "UNIQUE(client_order_id) is latent — no production writer populates the column "
        "(measured: 500 inserts, 500 NULLs, 0 refusals). The live guard is the intent "
        "journal in execution/trade_executor.py."
        if not trade_writers
        else f"{len(trade_writers)} writer(s)",
    )


def _p_fix_store() -> tuple[str, str]:
    body = _code("brokers/ibkr_fix_bridge.py")
    guarded = "_refuse_ephemeral_sequence_store" in body
    return _named(
        FIXED if guarded else OPEN,
        "start() refuses reset_on_logon=False on a $TMPDIR store"
        if guarded
        else "nothing couples reset_on_logon to a persistent IBKR_FIX_STORE_PATH",
    )


def _p_router_timeout() -> tuple[str, str]:
    body = _code("brokers/smart_router.py")
    if not body:
        return UNVERIFIED, "brokers/smart_router.py not found"
    n = len(re.findall(r"except TimeoutError", body))
    return _named(
        FIXED if n >= 2 else OPEN,
        f"{n} TimeoutError clause(s) — the fallback loop must stop the chain, not re-route",
    )


def _p_smoke_leak() -> tuple[str, str]:
    """Everything the smoke retrain writes must be on the restore list.

    `tests/unit/test_ml_training_pipeline.py::_preserve_saved_models` puts the
    tracked artifacts back after `retrain_model.py --smoke --advanced` rewrites
    them in place. The list is hand-maintained, and `ml/train_advanced.py` has
    since grown writers it does not cover — so those artifacts leak into the
    working tree and get committed alongside unrelated work.
    """
    written = set(re.findall(r'MODEL_DIR\s*/\s*"([^"]+)"', _code("ml/train_advanced.py")))
    block = _code("tests/unit/test_ml_training_pipeline.py")
    m = re.search(r"_SMOKE_OVERWRITES\s*=\s*\(([^)]*)\)", block, re.S)
    if not written or not m:
        return UNVERIFIED, "could not locate the writer list or the restore list"
    restored = set(re.findall(r'"([^"]+)"', m.group(1)))
    leaking = sorted(written - restored)
    return _named(
        OPEN if leaking else FIXED,
        f"{len(leaking)} artifact(s) written by the smoke retrain and not restored: {', '.join(leaking)}"
        if leaking
        else f"all {len(written)} artifacts the smoke retrain writes are restored",
    )


def _p_unmeasurable(reason: str) -> Callable[[], tuple[str, str]]:
    def probe() -> tuple[str, str]:
        return UNVERIFIED, reason

    return probe


def _p_owner(reason: str) -> Callable[[], tuple[str, str]]:
    def probe() -> tuple[str, str]:
        return OWNER, reason

    return probe


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------

S_TDD = "test-driven-development"
S_VBC = "verification-before-completion"
S_DEAD = "hopefx-dead-controls"
S_MONEY = "hopefx-money-precision"
S_INV = "hopefx-invariants"
S_FIX = "hopefx-fix-bridge"
S_DEBUG = "systematic-debugging"
S_UI = "ui-ux-pro-max"
S_DOC = "doc-freshness-review"

FINDINGS: list[Finding] = [
    # ── Verification capability ────────────────────────────────────────────
    Finding(
        "F95",
        "GitHub Actions does not run — every gate below is unverified until it does",
        "OWNER",
        "CI",
        "docs/audit/REMEDIATION_PLAN.md — Phase 0",
        "Not fixable from code. Check GitHub → Billing → Actions. Runs end in "
        "`startup_failure` with no runner assigned, which is the billing signature.",
        "None — this is an account setting, not a behaviour.",
        "Observe a green `ci.yml` run on a fresh push.",
        _p_owner("account-level; no repository change can clear it"),
        [S_VBC],
    ),
    Finding(
        "F96",
        "`deploy.yml` fires on every push to `main` with no CI gate",
        "P1",
        "CI",
        "docs/audit/REMEDIATION_PLAN.md — Phase 0",
        "Add `needs:` on the CI job, or convert the trigger to `workflow_run` "
        "completed+success. A deploy that cannot observe a red build is not gated.",
        "A workflow-lint test asserting every deploying workflow declares a dependency on a verification workflow.",
        "python scripts/correction_register.py --id F96",
        _p_f96,
        [S_TDD],
    ),
    Finding(
        "F97",
        "The only action holding `VPS_SSH_KEY` is float-pinned",
        "P1",
        "CI",
        "docs/audit/REMEDIATION_PLAN.md — Phase 0",
        "Pin `appleboy/ssh-action` to a 40-character commit SHA. A moving tag on an "
        "action that receives a deploy key is a supply-chain hole with a credential behind it.",
        "A test that walks `.github/workflows/*.yml` and fails on any `uses:` ref that "
        "is not a 40-hex SHA where the step also references a secret.",
        "python scripts/correction_register.py --id F97",
        _p_f97,
        [S_TDD],
    ),
    # ── Controls that report success without acting ────────────────────────
    Finding(
        "F176",
        "`invariant_coverage.py` printed `FULL COVERAGE ✅` from hardcoded booleans",
        "P0",
        "Dead controls",
        "docs/audit/REMEDIATION_PLAN.md — Phase 1",
        "Done: the report now prints `DECLARED — critical-component matrix (not a "
        "measurement)`. The remaining work is the real fix — each dimension resolving "
        "to a probe that can fail — which is tracked as its own item, not this one.",
        "Already carried by the report's own tests.",
        "python scripts/invariant_coverage.py",
        _p_f176,
        [S_DEAD],
    ),
    Finding(
        "F204",
        "Payouts marked `PAID` with no transfer",
        "P0",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: `PayoutStatus.SIMULATED` exists, so a cycle with no transfer backend no longer claims money moved.",
        "Carried by tests/unit/test_revenue_split_money.py.",
        "python scripts/correction_register.py --id F204",
        _p_f204,
        [S_MONEY, S_DEAD],
    ),
    Finding(
        "F203",
        "A sale recorded during a payout was destroyed",
        "P0",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: the balance is decremented rather than zeroed, under an `RLock`.",
        "Carried by tests/unit/test_revenue_splits_conserve.py.",
        "python scripts/correction_register.py --id F203",
        _p_f203,
        [S_MONEY],
    ),
    Finding(
        "F208",
        "Creator balances, sales and payouts existed only in RAM",
        "P0",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: the creator ledger writes through a session factory.",
        "Carried by the revenue-split money tests.",
        "python scripts/correction_register.py --id F208",
        _p_f208,
        [S_MONEY],
    ),
    Finding(
        "F222",
        "`revenue_split.py` had zero tests",
        "P1",
        "Tests",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: two test modules now cover it.",
        "n/a",
        "pytest tests/unit/test_revenue_split_money.py -q",
        _p_f222,
        [S_TDD],
    ),
    Finding(
        "F135",
        "Wallet ledger `transaction_id` collided at one-second resolution",
        "P0",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: the id carries a `uuid4` suffix, so two movements in the same second no longer collide and drop a row.",
        "Carried by the wallet ledger tests.",
        "python scripts/correction_register.py --id F135",
        _p_f135,
        [S_MONEY],
    ),
    Finding(
        "F137",
        "`amount_crypto` was a `Float` and could not hold 18-decimal tokens",
        "P1",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: the column is `Numeric(28, 8)`.",
        "n/a",
        "python scripts/correction_register.py --id F137",
        _p_f137,
        [S_MONEY],
    ),
    Finding(
        "F138",
        "`verify_balance_after` was never called — the check that catches F135/F136",
        "P0",
        "Invariants",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: the predicate has production callers. An invariant with no call site is "
        "not a control, however correct the predicate.",
        "An injection test: break the balance arithmetic and watch the invariant refuse.",
        "python scripts/correction_register.py --id F138",
        _p_f138,
        [S_INV, S_DEAD],
    ),
    # ── Broker, risk, execution ────────────────────────────────────────────
    Finding(
        "F61/F107",
        "`BROKER_TYPE=oanda` cannot place an order",
        "P1",
        "Brokers",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Half done, deliberately. `AsyncOANDAConnector = OANDABroker` is still a bare "
        "alias with no `place_market_order`, but a test now makes that fail where "
        "someone can see it instead of at the first live order. Writing the adapter is "
        "a feature and needs a practice venue to test against: `place_order` takes "
        "`direction` ('long'/'short') and returns a dict, while the caller passes an "
        "`_OrderSide` and expects a `MarketOrderResult`. Guessed wrong, it places the "
        "opposite side. Live OANDA is the stated next milestone, so this is the gating item.",
        "The existing loud-failure test stays; the adapter needs paper-venue contract "
        "tests for side, quantity and result shape before it is wired.",
        "pytest tests/unit/test_broker_type_oanda_is_not_silently_broken.py -q",
        _p_f61,
        [S_MONEY, S_DEBUG],
    ),
    Finding(
        "F142",
        "The active paper path had no risk layer",
        "P0",
        "Risk",
        "docs/audit/plans/2026-09-04-phase-e-risk-gates.md",
        "Done: `FIXRouter` takes an injected `OrderGate`; production injects the real "
        "`RiskManager`, tests inject a stub.",
        "Carried by tests/unit/test_order_gate.py.",
        "python scripts/correction_register.py --id F142",
        _p_f142,
        [S_INV, S_DEAD],
    ),
    Finding(
        "F139",
        "`deployments/k8s/` disabled cross-pod kill-switch propagation",
        "P0",
        "Risk",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Done: `kill-switch-rbac.yaml` exists in both k8s trees.",
        "n/a",
        "python scripts/correction_register.py --id F139",
        _p_f139,
        [S_DEAD],
    ),
    Finding(
        "F178/F98",
        "Two ConfigMaps named `hopefx-config` with contradictory safety values",
        "P0",
        "Config",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "`k8s/` says `HOPEFX_INVARIANT_MODE=enforce`; `deployments/k8s/` says `monitor`. "
        "Both objects carry the same name, so which one is live depends on apply order. "
        "Decide which tree deploys, delete or rename the other, and add a test that "
        "fails on two ConfigMaps sharing a name.",
        "A manifest test asserting no two ConfigMaps share `metadata.name`, and that "
        "`HOPEFX_INVARIANT_MODE` is `enforce` wherever `BROKER_TYPE != paper`.",
        "python scripts/correction_register.py --id F178/F98",
        _p_f178,
        [S_INV, S_TDD],
    ),
    Finding(
        "FIX-STORE",
        "FIX session continuity on an ephemeral sequence store",
        "P1",
        "Brokers",
        "This session, 2026-09-13 — commit 08df737a",
        "Done: `IBKRFIXBridge.start()` refuses `reset_on_logon=False` when `store_path` "
        "resolves under `tempfile.gettempdir()`.",
        "tests/unit/test_ibkr_fix_bridge.py::TestStart::test_start_refuses_session_continuity_on_an_ephemeral_store",
        "pytest tests/unit/test_ibkr_fix_bridge.py -q",
        _p_fix_store,
        [S_FIX, S_DEAD],
    ),
    Finding(
        "ROUTER-TO",
        "A fallback broker timeout re-routed and risked a duplicate fill",
        "P0",
        "Brokers",
        "This session, 2026-09-13 — commit 12bef2bb",
        "Done: a timeout in the fallback loop stops the chain. A timeout is not a "
        "confirmed failure, so the order outcome is unknown and re-routing can place a "
        "second live order.",
        "tests/unit/test_brokers_smart_router_coverage.py::TestExecuteWithFallback"
        "::test_a_fallback_timeout_does_not_place_a_second_order",
        "pytest tests/unit/test_brokers_smart_router_coverage.py -q",
        _p_router_timeout,
        [S_MONEY, S_DEAD],
    ),
    # ── Measurement integrity ──────────────────────────────────────────────
    Finding(
        "F221/F105",
        "The coverage gate omitted the money path",
        "P0",
        "Tests",
        "docs/audit/plans/2026-09-11-coverage-floor-programme.md",
        "Done for the omit list: no safety module is hidden. The wider half of F221 — "
        "`[run] source` naming a subset of the application — is tracked by the "
        "coverage-floor programme, not closed here.",
        "tests/unit/test_coverage_gate_states_its_scope.py::test_the_safety_modules_are_not_omitted",
        "pytest tests/unit/test_coverage_gate_states_its_scope.py -q",
        _p_f221,
        [S_DEAD, S_TDD],
    ),
    Finding(
        "F218",
        "Model tables that exist only via `create_all()` and have no migration",
        "P1",
        "Persistence",
        "docs/audit/REMEDIATION_PLAN.md — Phase 4",
        "`create_all()` never ALTERs, so these tables drift silently between a fresh "
        "install and an upgraded one. Add the missing migrations, then a CI check "
        "comparing `__tablename__`s against the migration history.",
        "The CI check itself is the test: assert every `__tablename__` appears in "
        "`alembic/versions/`, and watch it fail with one removed.",
        "python scripts/correction_register.py --id F218",
        _p_f218,
        [S_TDD],
    ),
    # ── Frontend ───────────────────────────────────────────────────────────
    Finding(
        "F198",
        "`/kyc` returns raw JSON 404 on direct navigation",
        "P1",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "`api/kyc.py` mounts a router at the bare `/kyc` prefix, which shadows the SPA "
        "route. The correctly-prefixed `/api/kyc` alias already exists, so the fix is to "
        "drop the bare mount. KYC is a regulatory gate — a user following a verification "
        "email currently gets a JSON error.",
        "A direct-`GET` probe asserting every SPA route returns 200 with an HTML content type, not JSON.",
        "python scripts/correction_register.py --id F198",
        _p_f198,
        [S_UI, S_TDD],
    ),
    Finding(
        "F199",
        "`_SPA_ROUTES` is hand-maintained and disagrees with `App.tsx`",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Generate the list from `App.tsx`, or add the direct-`GET`-returns-200 test that "
        "found F198 — either removes the hand-maintenance. Prefer the test: it catches "
        "the class, not just the drift.",
        "The same direct-GET probe as F198.",
        "python scripts/correction_register.py --id F199",
        _p_f199,
        [S_UI, S_TDD],
    ),
    Finding(
        "F200",
        "`/docs` is blank in every deployment",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "The CSP blocks the Swagger CDN the page loads. Vendor `swagger-ui-dist` and "
        "serve it locally rather than widening the CSP.",
        "A test asserting `/docs` returns a body referencing a same-origin asset.",
        "python scripts/correction_register.py --id F200",
        _p_f200,
        [S_UI],
    ),
    Finding(
        "F175",
        "Emoji used as UI icons",
        "P3",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done for `frontend/src`: no source file carries emoji. `ui-ux-pro-max` forbids "
        "emoji as icons; use the SVG set.",
        "n/a",
        "python scripts/correction_register.py --id F175",
        _p_f175,
        [S_UI],
    ),
    Finding(
        "ML-LEAK",
        "The smoke retrain leaks committed model artifacts into the working tree",
        "P1",
        "ML",
        "This session, 2026-09-13 — reproduced by execution",
        "`ml/train_advanced.py` writes eight artifacts into `ml/saved_models/`; the "
        "`_SMOKE_OVERWRITES` restore list in `tests/unit/test_ml_training_pipeline.py` "
        "names six. The uncovered ones stay dirty after the suite runs and get committed "
        "alongside whatever else was in flight. **This is the root cause of A8** — proven, "
        "not surmised: `model_checksums.json` has one commit (`334e50f3`), while "
        "`feature_scaler.pkl` and `stacking_ensemble.pkl` have three each, and one of the "
        "later two is `05efdbab`, a *mobile authentication* fix that carried "
        "`feature_scaler.pkl`, `stacking_ensemble.pkl`, `feature_stats.json` and a new "
        "`feature_importances.json` for no reason connected to its subject. Fix the list, "
        "then add the gate: a commit that changes an artifact under `ml/saved_models/` "
        "without regenerating the manifest should not pass.",
        "Run the smoke retrain and assert `git status --porcelain ml/saved_models/` is "
        "empty afterwards — the assertion the current fixture is missing. Watch it fail "
        "with one name removed from the restore list.",
        "python scripts/correction_register.py --id ML-LEAK",
        _p_smoke_leak,
        [S_DEAD, S_TDD],
    ),
    # ── Owner decisions ────────────────────────────────────────────────────
    Finding(
        "A8",
        "Two committed model artifacts fail the integrity baseline that gates their load",
        "P0",
        "ML",
        "docs/ai/MASTER_OUTSTANDING.md §A8",
        "`feature_scaler.pkl` and `stacking_ensemble.pkl` do not match the sha256 recorded "
        "in `ml/saved_models/model_checksums.json`. That file is not decorative: "
        "`ml/__init__.py::_verify_checksum` reads it on every load and, in production, "
        "returns False rather than bootstrapping — so `_try_load` returns None and the "
        "artifact is simply absent to the caller. Two consequences to fix together. "
        "(a) Establish which side is wrong — the recorded hash or the committed bytes — "
        "before regenerating anything; regenerating first destroys the only evidence, and "
        "the manifest has one commit in its whole history and already carried three "
        "mismatches at that commit, so it has never been correct. "
        "(b) `_try_load` returns None identically for 'file absent' and 'integrity "
        "refused'. A caller cannot tell a tampered artifact from an uninstalled one, and "
        "`ml/advanced_predictor.py:1004` then guards `if self._meta_scaler is not None`, "
        "so a refused scaler means unscaled meta-input rather than a refusal to predict. "
        "Make the two outcomes distinguishable.",
        "An injection test: corrupt one committed artifact and assert the load is refused "
        "AND that the caller can tell refusal from absence — the second half is the part "
        "no current test covers.",
        "python scripts/correction_register.py --id A8",
        _p_a8,
        [S_DEAD],
    ),
    Finding(
        "A9",
        "`UNIQUE(client_order_id)` is documented as the duplicate-fill guard and never fires",
        "OWNER",
        "Money",
        "docs/ai/MASTER_OUTSTANDING.md §A9",
        "Make it live (writers persist the id, `IntegrityError` becomes the duplicate "
        "signal), drop the constraint, or leave it latent as it now stands. If it is made "
        "live, feed it from `trade_executor`'s 64-bit id — never from `execution/oms.py`, "
        "whose `str(uuid.uuid4())[:8]` is 32 bits against a globally unique index.",
        "Under option 1: a test inserting the same client_order_id twice and asserting "
        "the second is refused, not silently accepted.",
        "python scripts/correction_register.py --id A9",
        _p_a9,
        [S_MONEY, S_DEAD],
    ),
    Finding(
        "SEC-ROTATE",
        "Rotate the credentials exposed outside the repository",
        "OWNER",
        "Security",
        "docs/audit/REMEDIATION_PLAN.md — spec item 6; this session",
        "A Vercel token (`vck_…`) was pasted into a chat session. It was never written "
        "to disk or into any commit — verified — but it left the machine, so it must be "
        "rotated. The tracked working tree reads as placeholders; `prop_firm_mode.json` "
        "and `.env.example` are committed deliberately and must stay placeholder-only.",
        "None — this is a credential action, not a behaviour.",
        "detect-secrets scan (already in pre-commit)",
        _p_owner("credential rotation is an account action outside the repository"),
        [],
    ),
]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _measure_all() -> list[tuple[Finding, str, str]]:
    rows = [(f, *f.measure()) for f in FINDINGS]
    rows.sort(key=lambda r: (_STATUS_ORDER[r[1]], r[0].priority, r[0].id))
    return rows


def _counts(rows: list[tuple[Finding, str, str]]) -> dict[str, int]:
    out = {OPEN: 0, PARTIAL: 0, OWNER: 0, UNVERIFIED: 0, FIXED: 0}
    for _, status, _ in rows:
        out[status] += 1
    return out


def cmd_table(rows: list[tuple[Finding, str, str]]) -> None:
    for f, status, evidence in rows:
        print(f"{status:<11} {f.priority:<6} {f.id:<12} {f.title[:62]}")
        print(f"{'':<11} {'':<6} {'':<12} {evidence[:100]}")
    c = _counts(rows)
    print()
    print(
        f"{len(rows)} findings · OPEN {c[OPEN]} · PARTIAL {c[PARTIAL]} · "
        f"OWNER {c[OWNER]} · UNVERIFIED {c[UNVERIFIED]} · FIXED {c[FIXED]}"
    )


def cmd_markdown(rows: list[tuple[Finding, str, str]]) -> None:
    c = _counts(rows)
    print("<!-- generated by scripts/correction_register.py — do not hand-edit this block -->")
    print(
        f"**{len(rows)} tracked · OPEN {c[OPEN]} · PARTIAL {c[PARTIAL]} · OWNER {c[OWNER]} "
        f"· UNVERIFIED {c[UNVERIFIED]} · FIXED {c[FIXED]}**"
    )
    print()
    for want in (OPEN, PARTIAL, OWNER, UNVERIFIED, FIXED):
        group = [r for r in rows if r[1] == want]
        if not group:
            continue
        print(f"### {want} — {len(group)}")
        print()
        for f, _, evidence in group:
            print(f"#### {f.id} · {f.title}")
            print()
            print(f"- **Priority** {f.priority} · **Area** {f.area}")
            print(f"- **Measured now** {evidence}")
            print(f"- **Fix** {f.fix}")
            print(f"- **Write this test first** {f.test_first}")
            print(f"- **Verify** `{f.verify}`")
            if f.skills:
                print(f"- **Skills** {', '.join('`' + s + '`' for s in f.skills)}")
            print(f"- **Full evidence** {f.source}")
            print()


def cmd_check(rows: list[tuple[Finding, str, str]]) -> int:
    """Fail if the register document disagrees with the probes."""
    if not REGISTER.exists():
        print(f"MISSING {REGISTER.relative_to(ROOT)} — run --markdown and write it")
        return 1
    body = REGISTER.read_text()
    c = _counts(rows)
    expected = (
        f"**{len(rows)} tracked · OPEN {c[OPEN]} · PARTIAL {c[PARTIAL]} · "
        f"OWNER {c[OWNER]} · UNVERIFIED {c[UNVERIFIED]} · FIXED {c[FIXED]}**"
    )
    if expected not in body:
        print("STALE — the register's headline does not match what the code measures.")
        print(f"  measured: {expected}")
        m = re.search(r"\*\*\d+ tracked[^*]*\*\*", body)
        print(f"  document: {m.group(0) if m else '(no headline found)'}")
        print("  Regenerate: python scripts/correction_register.py --markdown")
        return 1
    missing = [f.id for f, _, _ in rows if f"#### {f.id} ·" not in body]
    if missing:
        print(f"STALE — {len(missing)} finding(s) tracked here but absent from the register: {', '.join(missing)}")
        return 1
    print(
        f"correction register: {len(rows)} findings · OPEN {c[OPEN]} · PARTIAL {c[PARTIAL]} "
        f"· OWNER {c[OWNER]} · UNVERIFIED {c[UNVERIFIED]} · FIXED {c[FIXED]} · document agrees"
    )
    return 0


def cmd_selftest() -> int:
    """Prove --check can fail. A gate nobody has watched fail is not a gate."""
    if not REGISTER.exists():
        print("selftest: no register to mutate")
        return 1
    original = REGISTER.read_text()
    m = re.search(r"\*\*(\d+) tracked", original)
    if not m:
        print("selftest: no headline to mutate")
        return 1
    broken = original.replace(m.group(0), f"**{int(m.group(1)) + 99} tracked", 1)
    try:
        REGISTER.write_text(broken)
        rc = cmd_check(_measure_all())
    finally:
        REGISTER.write_text(original)
    if rc == 0:
        print("SELFTEST FAILED: --check accepted a wrong count")
        return 1
    print("selftest: --check refused a wrong count, as it must")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markdown", action="store_true", help="emit the register body")
    ap.add_argument("--check", action="store_true", help="fail if the document has drifted")
    ap.add_argument("--selftest", action="store_true", help="prove --check can fail")
    ap.add_argument("--id", help="one finding, with its full record")
    args = ap.parse_args()

    if args.selftest:
        return cmd_selftest()

    rows = _measure_all()

    if args.id:
        for f, status, evidence in rows:
            if f.id == args.id:
                print(f"{f.id} · {f.title}")
                print(f"  status     {status}")
                print(f"  measured   {evidence}")
                print(f"  priority   {f.priority}   area {f.area}")
                print(f"  fix        {f.fix}")
                print(f"  test first {f.test_first}")
                print(f"  verify     {f.verify}")
                print(f"  skills     {', '.join(f.skills) or '—'}")
                print(f"  evidence   {f.source}")
                return 0
        print(f"no finding with id {args.id!r}")
        return 1

    if args.check:
        return cmd_check(rows)
    if args.markdown:
        cmd_markdown(rows)
        return 0
    cmd_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
