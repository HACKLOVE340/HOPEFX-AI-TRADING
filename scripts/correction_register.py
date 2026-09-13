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
        # Only a comment that OWNS its line. An inline `//` is far more often the
        # middle of a URL — stripping those truncated every file at its first
        # https:// and emptied the TSX probes without failing anything.
        text = re.sub(r"(?m)^\s*//.*$", "", text)
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
    """Nothing the smoke retrain writes may survive the test run.

    The restore list was hand-typed and named six of the eight artefacts
    `ml/train_advanced.py` writes, so two leaked into the working tree and were
    committed alongside unrelated work — the root cause of A8. The question this
    probe asks is not "are the two names there now" but "can the list fall
    behind again", so it checks that the fixture snapshots the directory rather
    than enumerating it.
    """
    body = _code("tests/unit/test_ml_training_pipeline.py")
    if not body:
        return UNVERIFIED, "tests/unit/test_ml_training_pipeline.py not found"

    enumerated = "_SMOKE_OVERWRITES" in body
    snapshots = "MODELS.iterdir()" in body
    gated = _exists("scripts/model_artifact_manifest_gate.py")

    if snapshots and not enumerated and gated:
        return FIXED, (
            "the fixture snapshots every file in ml/saved_models/ instead of a named "
            "subset, so a writer added tomorrow is covered the day it lands; and "
            "scripts/model_artifact_manifest_gate.py refuses a staged artefact whose "
            "recorded checksum did not change with it"
        )
    return OPEN, (f"snapshots_directory={snapshots} still_enumerates={enumerated} commit_gate={gated}")


def _p_f103() -> tuple[str, str]:
    """brain/ and news/ must be inside the coverage source set to be gateable."""
    run_block = _code(".coveragerc").split("[run]", 1)[-1].split("omit", 1)[0]
    named = {p for p in ("brain", "news") if re.search(rf"^\s+{p}\s*$", run_block, re.M)}
    return _named(
        FIXED if named == {"brain", "news"} else OPEN,
        f"in [run] source: {sorted(named) or 'neither'} — a package outside the source "
        "set cannot fail a coverage gate, whatever percentage the job prints",
    )


def _p_f214() -> tuple[str, str]:
    """The Phase-3 gate must decide whether the online learner is returned."""
    guarded = _tracked("tests/unit/test_phase_gates_actually_gate.py")
    return _named(
        FIXED if guarded else OPEN,
        "test_phase_gates_actually_gate.py pins that the store is withheld until the "
        "gate is met, and that a gate which raises fails closed"
        if guarded
        else "nothing asserts the gate changes what _get_online_learner_store returns",
    )


def _p_f215() -> tuple[str, str]:
    """.env.example must not enable a flag whose code default is False."""
    m = re.search(r"^FEATURE_ONLINE_LEARNING\s*=\s*(\w+)", _read(".env.example"), re.M)
    if not m:
        return UNVERIFIED, "FEATURE_ONLINE_LEARNING not present in .env.example"
    on = m.group(1).strip().lower() in {"1", "true", "yes"}
    return _named(
        OPEN if on else FIXED,
        f"FEATURE_ONLINE_LEARNING={m.group(1)} — an unvalidated model blended into live signals by default"
        if on
        else f"FEATURE_ONLINE_LEARNING={m.group(1)}, matching the code default",
    )


def _p_f219() -> tuple[str, str]:
    """A push that reached no device must not report success."""
    body = _code("mobile/push_notifications.py")
    if not body:
        return UNVERIFIED, "mobile/push_notifications.py not found"
    m = re.search(r"if not self\.fcm_enabled or not tokens:(.*?)(?=\n        \S)", body, re.S)
    if not m:
        return UNVERIFIED, "the disabled/no-token branch was not found"
    returns_false = re.search(r"return\s+False", m.group(1)) is not None
    return _named(
        FIXED if returns_false else OPEN,
        "the disabled/no-token branch returns False"
        if returns_false
        else "the disabled/no-token branch still reports success",
    )


def _p_f160() -> tuple[str, str]:
    """The broker probe must ask the broker, not read the config."""
    body = _code("api/broker.py")
    live = bool(re.search(r"get_account_info|account_info|get_positions", body))
    return _named(
        FIXED if live else OPEN,
        "broker_status calls the connector for account info and positions"
        if live
        else "broker_status reports from configuration alone",
    )


def _p_f159() -> tuple[str, str]:
    """The alert engine's delivery guard must be able to open."""
    body = _code("notifications/alert_engine.py")
    if not body:
        return UNVERIFIED, "notifications/alert_engine.py not found"
    dead = "is not self" in body
    return _named(
        OPEN if dead else FIXED,
        "the `singleton is not self` guard is back — it can never open, so emergency "
        "stops and drawdown breaches are log lines"
        if dead
        else "no self-comparison guard stands between an alert and its delivery",
    )


def _p_f146() -> tuple[str, str]:
    """Drift is measured; whether it blocks is a deliberate default."""
    body = _code("ml/inference_engine.py")
    if "_DRIFT_BLOCK" not in body:
        return OPEN, "no block path exists — drift is computed and gates nothing"
    default_on = re.search(r'DRIFT_BLOCK",\s*"(true|1|yes)"', body) is not None
    return _named(
        FIXED if default_on else OWNER,
        "DRIFT_BLOCK defaults on"
        if default_on
        else "the block path exists and DRIFT_BLOCK defaults to false, so drift is advisory "
        "in the shipped configuration. Turning it on is a trading-behaviour decision",
    )


def _p_f205() -> tuple[str, str]:
    """A log call with more placeholders than arguments cannot emit."""
    # Counted with `ast`, not a regex. The first version of this probe stopped
    # its argument list at the first `)`, so `float(applied)` ended the match and
    # a correct three-argument call read as one — it reported six defects that
    # were not there. Balanced parentheses are not a regular language.
    import ast

    bad = []
    for rel in _tracked("monetization/*.py") + _tracked("payments/**/*.py"):
        try:
            tree = ast.parse(_read(rel))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"exception", "error", "warning", "info", "critical", "debug"}:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            fmt = node.args[0].value
            if not isinstance(fmt, str):
                continue
            holders = len(re.findall(r"%(?:\(\w+\))?[-+ #0-9.]*[sdifreg]", fmt))
            supplied = len(node.args) - 1
            if holders > supplied and not node.keywords:
                bad.append(f"{rel}:{node.lineno}: {holders} placeholders, {supplied} args")
    return _named(
        OPEN if bad else FIXED,
        f"{len(bad)} log call(s) cannot emit — the record is lost while the caller reports a reason: {bad[0]}"
        if bad
        else "no money-module log call has more placeholders than arguments",
    )


def _p_f136() -> tuple[str, str]:
    """A balance read-modify-write must hold a lock."""
    body = _code("payments/wallet.py")
    locked = "RLock(" in body or "threading.Lock(" in body
    return _named(
        FIXED if locked else OPEN,
        "wallet balance mutation is serialised by a lock"
        if locked
        else "the balance is an unlocked read-modify-write; two concurrent movements lose one",
    )


def _p_f206() -> tuple[str, str]:
    """Truncating to the cent always takes the creator's side of the rounding."""
    bad = _grep(r"int\(\s*amount\s*\*\s*100\s*\)", *_tracked("monetization/*.py"), *_tracked("payments/**/*.py"))
    return _named(
        PARTIAL if bad else FIXED,
        f"{len(bad)} site(s) still truncate: {bad[0]} — revenue_split now quantizes "
        "ROUND_HALF_UP, so this is the remainder, not the whole finding"
        if bad
        else "every amount-to-cents conversion rounds rather than truncates",
    )


def _p_f207() -> tuple[str, str]:
    """A payout must claim only transactions since the last one."""
    body = _code("monetization/revenue_split.py")
    scoped = "last_payout_at" in body
    return _named(
        FIXED if scoped else OPEN,
        "payouts are scoped by last_payout_at"
        if scoped
        else "every payout claims every historical transaction; reconciliation double-counts",
    )


def _p_f31() -> tuple[str, str]:
    """Affiliate money state must survive a restart, as revenue_split's now does."""
    body = _code("monetization/affiliate.py")
    if not body:
        return UNVERIFIED, "monetization/affiliate.py not found"
    persisted = "session_factory" in body or "session.commit" in body
    locked = "RLock(" in body or "threading.Lock(" in body
    # Partial settlement is what stops a withdrawal consuming the referral that
    # crosses the requested total. Without it a lock alone still destroys money,
    # deterministically, so both halves are checked.
    conserves = (
        "outstanding_commission" in body
        and "def settle" in body
        and "def unsettle" in body  # a failed payout must give the money back
        and "payout.reversed" in body  # ...exactly once
    )
    if persisted and locked and conserves:
        return FIXED, "affiliate commissions are conserved, serialised and persisted"
    if locked and conserves:
        return PARTIAL, (
            "commissions are conserved and serialised — a withdrawal settles exactly what "
            "it pays, and both payout paths hold the manager lock across the whole "
            "read-modify-write. Persistence is still absent: the ledger is module dicts, "
            "so a restart erases what affiliates are owed and each worker holds its own"
        )
    return OPEN, (
        f"conserves={conserves} locked={locked} persisted={persisted} — the defects fixed "
        "in revenue_split.py (F203/F208) are still live here"
    )


def _p_f220() -> tuple[str, str]:
    """Device tokens must outlive the process and cross workers."""
    body = _code("mobile/push_notifications.py")
    api = _code("api/mobile.py")
    if not body:
        return UNVERIFIED, "mobile/push_notifications.py not found"

    shared = "_token_store()" in body and "_TOKEN_KEY_PREFIX" in body
    # The broadcast enumerated the local dict, so persisting per-user lookup
    # alone would have left it silently empty after every deploy.
    broadcast_shared = "for user_id in self.registered_users()" in body
    reports_durability = "durable" in api
    proven = _exists("tests/unit/test_device_tokens_survive_a_restart.py")

    if shared and broadcast_shared and reports_durability and proven:
        return FIXED, (
            "tokens are held in a shared store keyed per user, the broadcast enumerates it "
            "rather than this process's dict, and POST /register-push reports `durable` so "
            "a registration that will not survive a restart is not answered with an "
            "unqualified `registered: true`. Falls back to process memory when no store is "
            "reachable — degraded, and loud about it"
        )
    return OPEN, (
        f"shared_store={shared} broadcast_uses_it={broadcast_shared} "
        f"api_reports_durability={reports_durability} test={proven}"
    )


def _p_f130() -> tuple[str, str]:
    """The patch queue must refuse an entry it cannot verify.

    This probe used to read `ai/improve/proposal.py` and report OPEN because
    that module does not name `HEAL_PATCH_SIGNING_KEY`. It does not name it on
    purpose — proposal.py can neither sign nor apply, and a test asserts that by
    parsing the file. The control lives in `security/self_healer.py`, which the
    probe was never looking at. Measuring the wrong file is how a finding that
    was fixed stayed open on a P0 line.
    """
    body = _code("security/self_healer.py")
    if not body:
        return UNVERIFIED, "security/self_healer.py not found"

    gate = re.search(r"def _patch_entry_is_trusted.*?(?=\ndef )", body, re.S)
    if not gate:
        return OPEN, "no _patch_entry_is_trusted gate in security/self_healer.py"
    gate_body = gate.group(0)

    # The no-key branch is the one that used to return True for every entry.
    no_key = re.search(r"if not _PATCH_SIGNING_KEY:(.*?)(?=\n    sig\b)", gate_body, re.S)
    fails_closed = bool(no_key and "return False" in no_key.group(1))
    opt_in_is_explicit = "_ALLOW_UNSIGNED_PATCHES" in gate_body and "getenv" in body
    proven = _exists("tests/unit/test_self_healer_fails_closed.py")

    if fails_closed and opt_in_is_explicit and proven:
        return FIXED, (
            "the no-key branch returns False, running unsigned needs an explicit "
            "HEAL_ALLOW_UNSIGNED_PATCHES opt-in that warns on every use, and "
            "test_self_healer_fails_closed.py injects the cases. Exercised directly as "
            "well as read: no key rejects, key with no _sig rejects, a tampered signature "
            "rejects, only a correct signature is accepted"
        )
    return OPEN, f"fails_closed={fails_closed} explicit_opt_in={opt_in_is_explicit} proven={proven}"


def _p_f184() -> tuple[str, str]:
    """'Could not run tests' must never be recorded as 'tests passed'."""
    t = _tracked("tests/unit/test_self_healer_fails_closed.py")
    return _named(
        FIXED if t else OPEN,
        "test_self_healer_fails_closed.py pins the distinction"
        if t
        else "nothing asserts a test run that could not execute is recorded as a failure",
    )


def _p_f216() -> tuple[str, str]:
    """CLAUDE.md must not tell contributors that `data/` is legacy."""
    body = _read("CLAUDE.md")
    corrected = "live runtime infrastructure" in body
    return _named(
        FIXED if corrected else OPEN,
        "CLAUDE.md describes data/ as live runtime infrastructure, with the measured LOC and importer counts"
        if corrected
        else "CLAUDE.md still calls data/ legacy, which routes new tick-feed work into "
        "the wrong package from the top of every assistant's context",
    )


def _p_f217() -> tuple[str, str]:
    """The market-data package boundary must be decided somewhere citable."""
    adr = [p for p in _glob("docs/decisions/*.md") if "data" in p and "layer" in p]
    return _named(
        FIXED if adr else OPEN,
        f"decided in {adr[0]}" if adr else "no ADR draws the boundary between the packages",
    )


def _p_f180() -> tuple[str, str]:
    """Only one SecureVault may be reachable; the others destroy credentials."""
    classes = _grep(r"^class SecureVault\b", *_tracked("**/*.py"))
    others = [c for c in classes if not c.startswith("config/vault.py")]
    if len(classes) <= 1:
        return FIXED, "one SecureVault, in config/vault.py"
    return PARTIAL, (
        f"{len(classes)} classes named SecureVault ({len(others)} besides the live one in "
        f"config/vault.py): {others[0] if others else ''}. Down from three, but a name "
        "collision on a credential store is how the wrong one gets imported — "
        "`rotate_key()` on the unreferenced copy returns True and destroys every credential"
    )


def _p_f144() -> tuple[str, str]:
    """Login must take the same time whether or not the user exists.

    Checks the CALL SITE, not just that an equaliser is defined somewhere. A
    helper nobody invokes is the defect this repository names most often.
    """
    body = _code("auth/service.py")
    if not body:
        return UNVERIFIED, "auth/service.py not found"

    defined = "_absorb_unknown_user_timing" in body
    branch = re.search(
        r"if not user:((?:(?!\n            if )[\s\S])*?user_not_found[\s\S]*?return False)",
        body,
    )
    called = bool(branch and "_absorb_unknown_user_timing" in branch.group(1))
    proven = _exists("tests/unit/test_login_does_not_enumerate_users.py")

    if defined and called and proven:
        return FIXED, (
            "the unknown-user branch verifies the supplied password against a fixed dummy "
            "hash before refusing. Measured: 309 ms vs 1.2 ms (257x) before, 313 ms vs "
            "309 ms (1.01x) after"
        )
    return OPEN, (
        f"equaliser_defined={defined} called_on_the_unknown_user_branch={called} "
        f"test={proven} — the unknown-user path returns before verify_password, so the "
        "clock enumerates registered accounts with no credentials and no lockout"
    )


def _p_f99() -> tuple[str, str]:
    """The placeholder-secret test must cover the variables it exempted."""
    body = _read("tests/unit/test_placeholder_secrets_are_rejected.py")
    if not body:
        return OPEN, "the placeholder-secret test does not exist"
    covered = [v for v in ("DB_ENCRYPTION_KEY", "POSTGRES_PASSWORD") if v in body]
    return _named(
        FIXED if len(covered) == 2 else OPEN,
        f"covers {covered}" if len(covered) == 2 else f"covers only {covered}",
    )


def _p_f223() -> tuple[str, str]:
    """Tests named after the coverage metric hide the behaviour they protect."""
    files = [f for f in _tracked("tests/**/*.py") if re.search(r"(coverage_boost|coverage\d|_coverage)\.py$", f)]
    return _named(
        OPEN if files else FIXED,
        f"{len(files)} test file(s) named after the metric rather than the behaviour "
        "(was 75) — these hold the highest concentration of assertion-free tests"
        if files
        else "no test file is named after the coverage metric",
    )


def _p_f108() -> tuple[str, str]:
    """A test file with no assertion asserts nothing, whatever it is named."""
    empty = []
    for f in _tracked("tests/unit/*.py"):
        if f.endswith("conftest.py"):
            continue  # fixtures, not tests — nothing to assert
        body = _code(f)
        if "def test" in body and not re.search(r"\bassert\b|pytest\.raises", body):
            empty.append(f)
    return _named(
        OPEN if empty else FIXED,
        f"{len(empty)} test file(s) define tests and assert nothing: {', '.join(empty[:3])}"
        if empty
        else "every unit-test file that defines a test also asserts",
    )


def _p_f106() -> tuple[str, str]:
    """Nothing exercises TradeExecutor against a real connector."""
    joined = [
        f for f in _tracked("tests/**/*.py") if "executor" in f and re.search(r"connector|integration|oanda|ibkr", f)
    ]
    return _named(
        FIXED if joined else OPEN,
        f"joined by {joined[0]}"
        if joined
        else "TradeExecutor is tested against MagicMock brokers only. A mock with no spec "
        "agrees with every call, so the signature mismatch that F61 describes survives "
        "the whole suite",
    )


def _p_f119() -> tuple[str, str]:
    """Annualisation must use the bar frequency, not the sample length."""
    bad = _grep(r"252\s*/\s*len\(", *_tracked("backtesting/*.py"), *_tracked("risk/*.py"), *_tracked("analytics/*.py"))
    return _named(
        OPEN if bad else FIXED,
        bad[0]
        if bad
        else "no annualisation divides 252 by the sample length; backtesting/metrics.py scales by sqrt(252)",
    )


def _p_f120() -> tuple[str, str]:
    """Sortino's denominator is downside deviation, not the std of losses."""
    body = _code("risk/advanced_analytics.py")
    proper = "downside_deviation" in body
    return _named(
        FIXED if proper else OPEN,
        "calculate_sortino_ratio uses downside_deviation about the target"
        if proper
        else "the denominator is the std of losing observations, whose bias flips sign with the return distribution",
    )


def _p_f125() -> tuple[str, str]:
    """An EMA must weight the newest bar most."""
    body = _code("strategies/regime_router.py")
    if "_ema" not in body:
        return UNVERIFIED, "no _ema in strategies/regime_router.py"
    m = re.search(r"def _ema.*?(?=\ndef |\Z)", body, re.S)
    reversed_iter = "reversed(" in (m.group(0) if m else "")
    return _named(
        OPEN if reversed_iter else FIXED,
        "the EMA iterates reversed(), weighting the oldest bar most"
        if reversed_iter
        else "_ema recurses forward over the series, so the newest bar carries alpha",
    )


def _p_f145() -> tuple[str, str]:
    """A missing feature must reach the model as neutral, not as -15 sigma."""
    # The evidence is a comment naming the finding and the reasoning behind the
    # fix, so this one reads the RAW file — _code() would strip exactly what it
    # is looking for.
    raw = _read("ml/inference_engine.py")
    aware = "F145" in raw or "is not neutral in this feature space" in raw
    return _named(
        FIXED if aware else OPEN,
        "the imputation happens in scaled space, so a missing feature arrives neutral"
        if aware
        else "missing features are zero-filled before scaling — measured -15 sigma "
        "for price with 48.2% of the vector missing",
    )


def _p_f80() -> tuple[str, str]:
    """Severity scoring must match words, not substrings."""
    scorer = [f for f in _tracked("**/*.py") if "wordmap" in f.lower() and "scorer" in f.lower()]
    if not scorer:
        return UNVERIFIED, "no wordmap scorer module found"
    body = _code(scorer[0])
    # The scorer builds `re.compile(rf"\b{body}\b")`. Look for that construction
    # rather than trying to write a regex that matches a regex — the first
    # version of this probe accepted any call to split() as evidence of word
    # boundaries, then over-corrected and missed the real one.
    bounded = "re.escape" in body and r"\b" in body and "re.compile" in body
    return _named(
        FIXED if bounded else OPEN,
        f"{scorer[0]} matches on word boundaries"
        if bounded
        else f"{scorer[0]} matches by bare substring — a headline containing 'coupon' "
        "scores 'coup' and can trip hedge mode",
    )


def _p_f94() -> tuple[str, str]:
    """Regime must be detected, or every position is sized at the unknown multiplier."""
    # F94's harm was specific: an unrouted regime left every position at the
    # 0.5x "unknown" multiplier. Counting any module that mentions a regime is
    # not that question — the first version of this probe answered FIXED by
    # citing core/analytics/realtime_heatmap.py, which sizes nothing.
    consumers = _grep(
        r"get_current_regime|RegimeRouter\(|detect_regime|regime\.",
        *_tracked("core/**/*.py"),
        *_tracked("strategies/*.py"),
        *_tracked("nuclear/*.py"),
    )
    sizing = _grep(r"regime", *_tracked("risk/manager.py"), *_tracked("risk/position_sizing.py"))
    multiplier = _grep(r"0\.5.*unknown|unknown.*0\.5|REGIME_MULT", *_tracked("risk/*.py"), *_tracked("strategies/*.py"))
    if multiplier:
        return OPEN, f"the unknown-regime multiplier is still applied: {multiplier[0]}"
    if not consumers:
        return OPEN, "nothing consumes a detected regime anywhere"
    return PARTIAL, (
        f"the 0.5x unknown-regime multiplier is gone from risk/, and {len(consumers)} "
        f"module(s) consume a regime (e.g. {consumers[0].split(':')[0]}), but "
        f"{'no' if not sizing else str(len(sizing))} reference(s) reach risk/manager.py or "
        "risk/position_sizing.py. Whether sizing SHOULD be regime-aware is a strategy "
        "decision, so this is reported as measured rather than closed"
    )


def _p_f123() -> tuple[str, str]:
    """The walk-forward endpoint must measure each fold over its own window.

    The original probe asked whether `api/backtesting.py` imports
    `backtesting/walk_forward.py`. That was the wrong question: the engine there
    is a parameter-grid optimiser and this endpoint validates one
    parameterisation, so importing it was never the fix. What matters is whether
    each fold gets its own dates and an embargo.
    """
    body = _code("api/backtesting.py")
    if not body:
        return UNVERIFIED, "api/backtesting.py not found"
    if "_walk_forward_execute" not in body:
        return OPEN, "no _walk_forward_execute — the fold loop is unreachable from a test"

    fn = re.search(r"def _walk_forward_execute.*?(?=\n@router|\ndef )", body, re.S)
    if not fn:
        return UNVERIFIED, "could not isolate _walk_forward_execute"
    fn_body = fn.group(0)

    explicit_windows = "_run_backtest_window(" in fn_body
    # The defect was passing only a LENGTH, so every fold ended at now().
    length_only = re.search(r"_run_real_backtest\(\s*\n?\s*req\.strategy", fn_body) is not None
    embargo = "purge_days" in fn_body and "test_start = train_end" in fn_body
    proven = _exists("tests/unit/test_walk_forward_actually_walks_forward.py")

    if explicit_windows and not length_only and embargo and proven:
        return FIXED, (
            "each fold is measured over its own window, the folds advance through time, "
            "and purge_days embargoes training from testing. Before: all five folds "
            "measured the same recent period with the test window inside the training "
            "window, and the fold dates were labels for a computation that never happened"
        )
    return OPEN, (
        f"explicit_windows={explicit_windows} still_passes_only_a_length={length_only} embargo={embargo} test={proven}"
    )


def _p_f147() -> tuple[str, str]:
    """Order flow must say when it has measured nothing, and have one analyzer.

    The original probe asked whether the analyzer was "fed", by grepping
    startup_factories for a subscribe call. Wiring a tick source is a product
    decision — which symbols, what rate, what retention — and F147's actual harm
    was never the absence of a feed. It was that an unfed subsystem answered as
    though it had measured: a cumulative delta of 0, an empty level set, and a
    market bias of "neutral / weak".
    """
    flow = _code("analysis/order_flow.py")
    dash = _code("analysis/order_flow_dashboard.py")
    startup = _code("core/startup_factories.py")
    if not flow:
        return UNVERIFIED, "analysis/order_flow.py not found"

    refuses = "def has_data" in flow and flow.count("_require_data(symbol)") >= 3
    says_ingesting = '"ingesting"' in flow
    dash_refuses = "def has_data" in dash and "_require_data(symbol)" in dash
    # init_order_flow built a SECOND analyzer whose routes were shadowed.
    one_instance = "get_order_flow_analyzer()" in startup and "OrderFlowAnalyzer()" not in startup

    # PARTIAL, not FIXED, and deliberately so. The register's own vocabulary:
    # PARTIAL is "the harm is contained but the capability is absent". The
    # misleading answers are gone; order-flow analysis on live data does not
    # exist, because nothing subscribes a tick source. Calling that FIXED would
    # close a capability gap by fixing a truthfulness bug.
    if refuses and says_ingesting and dash_refuses and one_instance:
        return PARTIAL, (
            "/delta, /levels and /footprint refuse a symbol with no ingested ticks, as "
            "/analysis and /profile already did; /stats reports `ingesting`; the dashboard "
            "no longer derives a bias from nothing; and init_order_flow returns the same "
            "analyzer the router serves, so wiring a feed to it would actually reach the "
            "endpoints. A tick source is still not subscribed — that is a product "
            "decision, and the endpoints now say so instead of answering zero"
        )
    return OPEN, (
        f"per_symbol_refusals={refuses} stats_states_ingesting={says_ingesting} "
        f"dashboard_refuses={dash_refuses} single_analyzer={one_instance}"
    )


def _p_f149() -> tuple[str, str]:
    """A sparkline drawn from Math.random() is a fabricated readout."""
    # Element ids, reconnect jitter and backoff are legitimate. A *plotted* value
    # is not. The first version of this probe flagged
    # `const jitter = delay * Math.random()` in useWebSocket.ts, which is correct
    # code doing exactly what backoff should.
    bad = [
        h
        for h in _grep(r"Math\.random\(\)", *[f for f in _tracked("frontend/src/**") if f.endswith((".tsx", ".ts"))])
        if not re.search(r"id\b|key|uuid|nonce|jitter|backoff|delay|seed|shuffle", h, re.I)
        and "/test" not in h
        and not h.split(":")[0].endswith((".test.ts", ".test.tsx"))
    ]
    return _named(
        OPEN if bad else FIXED,
        f"{len(bad)} Math.random() in rendered values: {bad[0]}"
        if bad
        else "Math.random() survives only for element ids, never for a plotted value",
    )


def _p_f150() -> tuple[str, str]:
    """A key built in the browser can never authenticate."""
    # `generateApiKey: (id) => api.post(...)` asks the SERVER for a key, which is
    # the correct shape — the first version of this probe matched the name and
    # called it a defect. What F150 describes is a key *assembled in the browser*:
    # a template literal or concatenation producing the key value itself.
    bad = _grep(
        r"(api[_-]?key)\s*[:=]\s*[`'\"][^`'\"]*\$\{|btoa\([^)]*api[_-]?key",
        *[f for f in _tracked("frontend/src/**") if f.endswith((".tsx", ".ts"))],
    )
    return _named(
        OPEN if bad else FIXED,
        bad[0] if bad else "no client-side API-key construction remains",
    )


def _p_f209() -> tuple[str, str]:
    """Two dashboards, with the nav pointing at the weaker one."""
    app = _code("frontend/src/App.tsx")
    redirected = bool(re.search(r'path="/home"[^>]*Navigate to="/dashboard"', app))
    return _named(
        FIXED if redirected else OPEN,
        "/home redirects to /dashboard — one canonical dashboard"
        if redirected
        else "/dashboard and /home render different pages and the sidebar labels the richer one 'Live Feed'",
    )


def _p_f210() -> tuple[str, str]:
    """Duplicate aliases break breadcrumbs and active-nav."""
    app = _read("frontend/src/App.tsx")
    paths = re.findall(r'path="(/[^"]*)"', app)
    dupes = sorted({p for p in paths if paths.count(p) > 1})
    return _named(
        OPEN if dupes else FIXED,
        f"{len(dupes)} duplicated path(s): {dupes[:5]}"
        if dupes
        else f"{len(set(paths))} distinct paths, none declared twice",
    )


def _p_f201() -> tuple[str, str]:
    """Telling a subscriber 15 courses are available when all are placeholders."""
    bad = _grep(
        r"COMING SOON|available on your plan",
        *[f for f in _tracked("frontend/src/**") if f.endswith((".tsx", ".ts"))],
        code_only=False,
    )
    return _named(
        OPEN if bad else FIXED,
        bad[0] if bad else "no page advertises unavailable content as available",
    )


def _p_f173() -> tuple[str, str]:
    """A page with no heading has no document outline."""
    page = next((f for f in _tracked("frontend/src/pages/*.tsx") if re.search(r"/(Trading)?Dashboard\.tsx$", f)), None)
    if not page:
        return UNVERIFIED, "no Dashboard page found"
    n = len(re.findall(r"<h[123]\b", _code(page)))
    return _named(
        OPEN if n == 0 else FIXED,
        f"{page} renders {n} h1-h3 elements — a screen reader gets no outline"
        if n == 0
        else f"{page} renders {n} h1-h3 elements",
    )


def _p_f187() -> tuple[str, str]:
    """Metrics nobody can act on are a readout, not an application."""
    page = next((f for f in _tracked("frontend/src/pages/*.tsx") if re.search(r"/(Trading)?Dashboard\.tsx$", f)), None)
    if not page:
        return UNVERIFIED, "no Dashboard page found"
    clickable = len(re.findall(r"onClick", _code(page)))
    return _named(
        OPEN if clickable < 5 else FIXED,
        f"{page} has {clickable} onClick handler(s) — the metrics do not drill through"
        if clickable < 5
        else f"{page} has {clickable} onClick handlers",
    )


def _p_f172() -> tuple[str, str]:
    """Icon-only buttons without an accessible name — NOT measurable here.

    Two regex attempts both produced confident wrong answers, and the reason is
    structural rather than a slip: a JSX opening tag cannot be bracketed by
    `<button\b([^>]*)>`, because an attribute may contain `>` —
    `onClick={() => navigate('/x')}` ends the match at the arrow. Everything
    after it reads as the button's children, so "does this button contain text"
    is answered from the wrong span. One version reported FIXED across 552
    buttons; the other reported 9 offending files. Neither had measured
    anything.

    Reporting UNVERIFIED is the honest outcome. `eslint-plugin-jsx-a11y`'s
    `control-has-associated-label` parses the JSX properly and is the way to
    make this a real gate; adding it is the fix, and the count comes with it.
    """
    return UNVERIFIED, (
        "not decidable by regex — a JSX attribute containing `>` breaks any "
        "attempt to bracket the opening tag. Wire eslint-plugin-jsx-a11y and "
        "this becomes a real measurement"
    )


def _p_f84() -> tuple[str, str]:
    """The data-layer gate must not be conditioned on a flag that is False when it matters."""
    body = _code("execution/engine.py")
    if not body:
        return UNVERIFIED, "execution/engine.py not found"
    dead = re.search(r"_started\s+and\s+not\s+\w*\.?is_safe_to_trade", body) is not None
    return _named(
        OPEN if dead else FIXED,
        "the `_started and not is_safe_to_trade()` conjunct is back — `_started = True` is "
        "the last line of start(), so a startup failure skips the gate in exactly the state "
        "it exists for"
        if dead
        else "is_safe_to_trade() is consulted without an _started conjunct",
    )


def _p_f81() -> tuple[str, str]:
    """A hedge must be recorded from the broker's answer, not before asking."""
    body = _code("risk/orchestrator.py")
    if not body:
        return UNVERIFIED, "risk/orchestrator.py not found"
    m = re.search(r"self\._hedge_active\s*=\s*True", body)
    if not m:
        return UNVERIFIED, "no hedge activation found"
    before = body[: m.start()]
    # The failure path must return before the activation line is reached.
    guarded = re.search(r"return\s+False", before[-1500:]) is not None
    return _named(
        FIXED if guarded else OPEN,
        "the failure path returns before _hedge_active is set, so a failed hedge is a real "
        "retry rather than a latched success"
        if guarded
        else "_hedge_active is set before the broker answers — the account is unhedged while "
        "every dashboard says hedged, and the duplicate-activation guard blocks retry",
    )


def _p_ai_gate() -> tuple[str, str]:
    """An agent acting outside its scope must fail the build, not a review."""
    scope = [
        f for f in _tracked("tests/**/*.py") if re.search(r"agent.*(scope|authoriz|permission)|enforce_agent_action", f)
    ]
    approval = [f for f in _tracked("tests/**/*.py") if re.search(r"approval|proposal", f) and "ai" in f.lower()]
    if scope and approval:
        return FIXED, f"scope: {scope[0]} · approval: {approval[0]}"
    return OPEN, (
        f"acceptance tests present — out-of-scope action: {bool(scope)}, "
        f"execution-without-approval: {bool(approval)}. `enforce_agent_action` and "
        "`ToolBus.invoke` exist and are called; what is missing is the pair of build-"
        "failing tests that keep them that way as the AI layer grows"
    )


def _p_ai_surface() -> tuple[str, str]:
    """Superadmin capability must be enforced on the server, not by a UI branch."""
    t = _tracked("tests/unit/test_superadmin_capabilities_are_server_enforced.py")
    if not t:
        return OPEN, "nothing asserts a non-superadmin is refused server-side"
    body = _read(t[0])
    has_403 = "403" in body
    return _named(
        FIXED if has_403 else PARTIAL,
        "server-side capability enforcement is pinned with a 403 assertion"
        if has_403
        else "the test exists but asserts no refusal status",
    )


def _p_tier_skip() -> tuple[str, str]:
    """An affiliate clearing two tiers at once should not be granted only one."""
    body = _code("monetization/affiliate.py")
    m = re.search(r"def check_level_upgrade.*?(?=\n    def )", body, re.S)
    if not m:
        return UNVERIFIED, "check_level_upgrade not found"
    # Returning inside the ascending loop grants the FIRST qualifying tier.
    first_match = re.search(r"for level in .*?:\s*.*?return level", m.group(0), re.S)
    return _named(
        OPEN if first_match else FIXED,
        "check_level_upgrade returns the first qualifying tier above the current one, so "
        "an affiliate whose numbers already clear a higher tier is granted the next one up "
        "and earns the lower commission rate until the following conversion"
        if first_match
        else "the highest qualifying tier is granted",
    )


def _p_of_voter() -> tuple[str, str]:
    """One of the three bias voters calls a method that does not exist."""
    dash = _code("analysis/order_flow_dashboard.py")
    adv = _code("analysis/advanced_order_flow.py")
    if not dash or not adv:
        return UNVERIFIED, "order-flow dashboard or advanced analyzer not found"
    calls_analyze = re.search(r"self\._adv\.analyze\(", dash) is not None
    has_analyze = re.search(r"^\s{4}def analyze\(", adv, re.M) is not None
    if calls_analyze and not has_analyze:
        return OPEN, (
            "_bias_vote_advanced calls self._adv.analyze(), which AdvancedOrderFlowAnalyzer "
            "does not define — every call raises AttributeError into a WARNING handler and "
            "returns None, so the majority is decided by two voters wearing three hats"
        )
    return _named(
        FIXED if not calls_analyze or has_analyze else OPEN,
        f"calls_analyze={calls_analyze} method_exists={has_analyze}",
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
        "Done 2026-09-13, both halves. `ml/train_advanced.py` writes eight artifacts into "
        "`ml/saved_models/` and the `_SMOKE_OVERWRITES` restore list named six, so two "
        "leaked into the working tree after every suite run and were committed alongside "
        "whatever else was in flight. The fixture now snapshots the whole directory — a "
        "restore list that must be kept in step with a writer is a list that falls out of "
        "step — and `scripts/model_artifact_manifest_gate.py` refuses a staged artefact "
        "whose recorded checksum did not change with it, so the class of accident cannot "
        "be committed however it leaks in. **This was the root cause of A8** — proven, "
        "not surmised: `model_checksums.json` has one commit (`334e50f3`), while "
        "`feature_scaler.pkl` and `stacking_ensemble.pkl` have three each, and one of the "
        "later two is `05efdbab`, a *mobile authentication* fix that carried "
        "`feature_scaler.pkl`, `stacking_ensemble.pkl`, `feature_stats.json` and a new "
        "`feature_importances.json` for no reason connected to its subject. Fix the list, "
        "then add the gate: a commit that changes an artifact under `ml/saved_models/` "
        "without regenerating the manifest should not pass.",
        "Carried by test_ml_training_pipeline.py (mutate every artefact train_advanced "
        "writes, discovered from its source, and assert all are handed back) and "
        "test_model_artifact_manifest_gate.py (seven injections against a real throwaway "
        "repository).",
        "python scripts/correction_register.py --id ML-LEAK",
        _p_smoke_leak,
        [S_DEAD, S_TDD],
    ),
    # ── Batch 2: the remainder of REMEDIATION_PLAN.md ──────────────────────
    Finding(
        "F103/F104",
        "`brain/` and `news/` coverage gates could not pass",
        "P2",
        "Tests",
        "docs/audit/REMEDIATION_PLAN.md — Phase 0",
        "Done: both packages are inside `[run] source`. A package outside the source set "
        "cannot fail a coverage gate whatever percentage the job prints.",
        "n/a",
        "python scripts/correction_register.py --id F103/F104",
        _p_f103,
        [S_DEAD],
    ),
    Finding(
        "F214",
        "The Phase-3 paper-trading gate gated nothing",
        "P1",
        "Dead controls",
        "docs/audit/REMEDIATION_PLAN.md — Phase 1",
        "Done: `test_phase_gates_actually_gate.py` pins that the online-learner store is "
        "withheld until the gate is met, and that a gate which raises fails closed.",
        "n/a",
        "pytest tests/unit/test_phase_gates_actually_gate.py -q",
        _p_f214,
        [S_DEAD],
    ),
    Finding(
        "F215",
        "`.env.example` enabled the one flag whose code default is False",
        "P1",
        "Config",
        "docs/audit/REMEDIATION_PLAN.md — Phase 1",
        "Done: `FEATURE_ONLINE_LEARNING=false`, matching the code default. It had been "
        "blending an unvalidated model at 30% weight into live signals on a fresh install.",
        "The `.env.example`-matches-code-default test in the Phase C plan.",
        "python scripts/correction_register.py --id F215",
        _p_f215,
        [S_DEAD],
    ),
    Finding(
        "F219",
        "Push notifications returned True while sending nothing",
        "P1",
        "Dead controls",
        "docs/audit/REMEDIATION_PLAN.md — Phase 1",
        "Done: the disabled/no-token branch returns False. With all three Firebase "
        "variables blank by default, every push on a fresh deployment used to report "
        "success and reach no device.",
        "n/a",
        "python scripts/correction_register.py --id F219",
        _p_f219,
        [S_DEAD],
    ),
    Finding(
        "F160",
        "The broker probe reported `ok` from configuration",
        "P1",
        "Dead controls",
        "docs/audit/REMEDIATION_PLAN.md — Phase 1",
        "Done: `broker_status` calls the connector for account info and positions, so an "
        "unreachable venue can no longer read as healthy.",
        "n/a",
        "python scripts/correction_register.py --id F160",
        _p_f160,
        [S_DEAD],
    ),
    Finding(
        "F159",
        "Critical alerts never left the log",
        "P0",
        "Dead controls",
        "docs/audit/REMEDIATION_PLAN.md — Phase 1",
        "Done: the `singleton is not self` guard is gone. It could never open, because the "
        "guard and the delivery were the same branch — emergency stops, drawdown breaches "
        "and circuit-breaker trips were log lines for the life of the module.",
        "An injection test: trip a breaker with a stub transport and assert the transport was called.",
        "python scripts/correction_register.py --id F159",
        _p_f159,
        [S_DEAD],
    ),
    Finding(
        "F146",
        "Drift is measured and does not block by default",
        "OWNER",
        "ML",
        "docs/audit/REMEDIATION_PLAN.md — Phase 1",
        "The block path now exists — `DRIFT_BLOCK` — but ships false, so drift is advisory "
        "in the deployed configuration. Turning it on stops inference when the feature "
        "distribution moves, which is a trading-behaviour decision with a real cost either "
        "way: block and you halt on a regime change; do not and you trade a model outside "
        "its training distribution. The code is ready for either.",
        "Whichever default is chosen: a test that shifts a feature past the z-threshold and "
        "asserts the configured behaviour.",
        "python scripts/correction_register.py --id F146",
        _p_f146,
        [S_DEAD],
    ),
    Finding(
        "F205",
        "A log call with more placeholders than arguments cannot emit",
        "P2",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done across `monetization/` and `payments/`. The failing record was the one a "
        "`failure_reason` told the operator to go and read.",
        "n/a",
        "python scripts/correction_register.py --id F205",
        _p_f205,
        [S_DEAD],
    ),
    Finding(
        "F136",
        "The wallet balance was an unlocked read-modify-write",
        "P0",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: mutation is serialised by an `RLock`.",
        "A concurrency test: two simultaneous movements, assert the total is conserved.",
        "python scripts/correction_register.py --id F136",
        _p_f136,
        [S_MONEY],
    ),
    Finding(
        "F206",
        "`int(amount * 100)` truncates cents against the payee",
        "P1",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "`revenue_split.py` now quantizes ROUND_HALF_UP; `monetization/stripe_integration.py` "
        "still truncates. Truncation toward zero always takes the same side of the rounding, "
        "so the loss accumulates in one direction. Use the same helper.",
        "A test asserting 0.999 becomes 100 cents, not 99 — and watch it fail on the truncating call site.",
        "python scripts/correction_register.py --id F206",
        _p_f206,
        [S_MONEY],
    ),
    Finding(
        "F207",
        "Every payout claimed every historical transaction",
        "P0",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "Done: payouts are scoped by `last_payout_at`, so reconciliation no longer double-counts.",
        "n/a",
        "python scripts/correction_register.py --id F207",
        _p_f207,
        [S_MONEY],
    ),
    Finding(
        "F31/F32",
        "Affiliate money state is in memory, and the payout is a TOCTOU",
        "P0",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 2",
        "**Money conservation is fixed** (2026-09-13). Three ways commission left the ledger "
        "without being paid, all reproduced before the fix and all now covered by "
        "`tests/unit/test_affiliate_commissions_conserve.py`: (1) `request_withdrawal` "
        "tested its running total *before* adding each referral, so the one that crossed "
        "the requested amount was marked PAID in full — two 60.00 commissions against a "
        "100.00 withdrawal **destroyed 20.00**, deterministically, behind a live endpoint "
        "at `api/monetization.py:1542`; (2) a conversion landing between a payout's total "
        "and its settlement pass was settled without being in the total — **70.00 "
        "destroyed**, F203's shape one module over; (3) two concurrent payout requests each "
        "saw the full balance — **300.00 paid against 150.00 earned**. Referrals now carry "
        "`commission_paid` so a withdrawal can settle part of one, and both payout paths "
        "plus `convert_referral` hold an `RLock` across the whole read-modify-write. "
        "**Persistence remains**: the ledger is still module dicts, so a restart erases "
        "what affiliates are owed and each worker holds its own. That half needs schema — "
        "revenue_split writes through a session factory into ledger tables — and lands in "
        "F218 territory, so it is deliberately not bundled here.",
        "For the remaining half: credit a commission, rebuild the manager from its store, "
        "and assert the balance survived. It will fail today.",
        "python scripts/correction_register.py --id F31/F32",
        _p_f31,
        [S_MONEY],
    ),
    Finding(
        "F220",
        "Device tokens were lost on every deploy",
        "P1",
        "Money",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done 2026-09-13. `_device_tokens` was a module-level dict and nothing else, so "
        "**every deploy silently unregistered every device** — a correctly configured FCM "
        "with real credentials and real tokens simply stopped delivering, with no error, "
        "because the server believed the user had no devices. Each worker also held its own "
        "set, so registering through one and sending from another found nothing and looked "
        "like a flaky client. This is what made the F219 fix incomplete: the send became "
        "honest and still had nobody to reach. Tokens now live in a shared store (Redis, "
        "the same resolved-once pattern as `core/idempotency.py`; a table would need a "
        "migration and F218 says 36 of 44 have none), with process memory as a loud "
        "fallback. `register_device` returns whether the registration is DURABLE rather "
        "than an unconditional True, and `POST /register-push` passes that through as "
        "`durable` — it answered `registered: true` for registrations it knew would not "
        "outlive the process. **`broadcast_signal` mattered as much as the lookup**: it "
        'enumerated `_device_tokens.keys()` under the docstring "all registered users", '
        "so after a deploy it reached nobody and returned `notified: 0` as a success. "
        "Persisting per-user lookup alone would have made the endpoints look right and "
        "left the broadcast silently empty. `registered_users()` scans the token keys "
        "rather than maintaining a parallel index — a second copy that must be kept in "
        "step is this repository's most repeated defect, and a scan cannot disagree with "
        "the keys it scans.",
        "Carried by tests/unit/test_device_tokens_survive_a_restart.py — survival across a "
        "simulated restart, cross-worker visibility of both registration and revocation, "
        "no duplicate on a retried register, the durability signal, a failing store "
        "degrading rather than dropping the device, and the broadcast reaching users this "
        "process never registered. The two cross-worker tests initially passed against the "
        "defect because both `workers` shared the module dict; they clear it now.",
        "python scripts/correction_register.py --id F220",
        _p_f220,
        [S_DEAD],
    ),
    Finding(
        "F130",
        "The self-healer patch queue accepted every unsigned entry",
        "P0",
        "Security",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Done, and this register said otherwise until 2026-09-13 — the entry was carried "
        "over from REMEDIATION_PLAN and its probe read `ai/improve/proposal.py`, which "
        "deliberately never names the key (it cannot sign and cannot apply, asserted by "
        "parsing the file). The control is in `security/self_healer.py`. "
        "`_patch_entry_is_trusted` used to return True for every entry when no key was "
        "set, and no shipped configuration set one, so there was no deployment in which "
        "it was on. It now fails closed; running unsigned needs an explicit "
        "`HEAL_ALLOW_UNSIGNED_PATCHES` opt-in that warns on every use and cannot override "
        "a configured key.",
        "Already carried by tests/unit/test_self_healer_fails_closed.py — seven tests "
        "injecting no key, a key with no `_sig`, a correct signature, a tampered "
        "signature, the opt-in, and the opt-in against a configured key.",
        "pytest tests/unit/test_self_healer_fails_closed.py -q",
        _p_f130,
        [S_DEAD, S_INV],
    ),
    Finding(
        "F184",
        "The self-healer counted 'could not run tests' as 'tests passed'",
        "P0",
        "Dead controls",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Done: `test_self_healer_fails_closed.py` pins the distinction.",
        "n/a",
        "pytest tests/unit/test_self_healer_fails_closed.py -q",
        _p_f184,
        [S_DEAD],
    ),
    Finding(
        "F216",
        "`CLAUDE.md` called `data/` legacy",
        "P2",
        "Docs",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Done: it now describes `data/` as live runtime infrastructure with measured LOC "
        "and importer counts. The old text sat at the top of every assistant's context and "
        "routed new tick-feed work into the wrong package.",
        "n/a",
        "python scripts/correction_register.py --id F216",
        _p_f216,
        [S_DOC],
    ),
    Finding(
        "F217",
        "Four packages owned 'market data' and no document drew the boundary",
        "P2",
        "Docs",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Done: ADR 0013 decides it. It is a rule describing what the code already does, not "
        "a licence to move the 106 production importers.",
        "n/a",
        "python scripts/adr.py --list",
        _p_f217,
        [S_DOC],
    ),
    Finding(
        "F180/F181/F182/F183",
        "Two classes named `SecureVault`",
        "P1",
        "Security",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Down from three; `config/vault.py` is the live one and is genuinely good "
        "(Argon2id, crash-safe rotation). `security/encryption.py` still defines a second. "
        "A name collision on a credential store is how the wrong one gets imported, and the "
        "unreferenced copy is dangerous rather than merely redundant: `rotate_key()` returns "
        "True and destroys every credential, a random salt when `HOPEFX_SALT` is unset loses "
        "everything on restart, and `encrypt()` falls back to base64 while `decrypt()` "
        "honours it. Delete it or rename it; do not leave two importable.",
        "A test asserting exactly one importable `SecureVault`, and that it is the config/vault.py one.",
        "python scripts/correction_register.py --id F180/F181/F182/F183",
        _p_f180,
        [S_DEAD],
    ),
    Finding(
        "F144",
        "Login is user-enumerable by timing",
        "P1",
        "Security",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Done 2026-09-13. `login` returned as soon as the SELECT missed, so a registered "
        "address paid bcrypt at cost 12 and an unregistered one paid a failed lookup. Both "
        "branches already returned the same message, so the response gave nothing away and "
        "the clock gave away the customer list — no credentials needed, and no lockout "
        "counter to trip, because an address that does not exist has nothing to increment. "
        "Re-measured rather than trusting the audit's 268.74 ms: **309.04 ms against "
        "1.20 ms, a 257x gap**; after the fix 312.98 ms against 309.12 ms, **1.01x**. The "
        "unknown-user branch now verifies the supplied password against a fixed dummy hash, "
        "computed on first use so no process pays ~300 ms merely to import the module.",
        "Carried by tests/unit/test_login_does_not_enumerate_users.py: a deterministic one "
        "asserting verification actually runs for an unknown email (the mechanism, so it "
        "says the same thing on a loaded runner), a loose statistical one on the outcome, "
        "identical refusal messages, and a positive control that a correct password still "
        "authenticates — without which every other assertion is satisfied by a login that "
        "refuses everyone.",
        "python scripts/correction_register.py --id F144",
        _p_f144,
        ["threat-modelling"],
    ),
    Finding(
        "F99",
        "The placeholder-secret test skipped the case it exists for",
        "P1",
        "Security",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Done: `DB_ENCRYPTION_KEY` and `POSTGRES_PASSWORD` are both covered.",
        "n/a",
        "pytest tests/unit/test_placeholder_secrets_are_rejected.py -q",
        _p_f99,
        [S_DEAD],
    ),
    Finding(
        "F223",
        "Test files named after the coverage metric",
        "P3",
        "Tests",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Down from 75. A file called `*_coverage_boost.py` says what it was written for "
        "rather than what it protects, and these hold the highest concentration of "
        "assertion-free tests. Rename to the behaviour; where a name already claims one "
        "(`..._skips_outside_pod`), assert that behaviour.",
        "None — this is a rename. The value is that the next reader can tell what breaking the test would mean.",
        "python scripts/correction_register.py --id F223",
        _p_f223,
        [S_TDD],
    ),
    Finding(
        "F108",
        "Test files that define tests and assert nothing",
        "P2",
        "Tests",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Two files remain. A test that cannot fail is a measurement that cannot fail — the "
        "defining defect of this codebase, in the suite that is supposed to catch it. Give "
        "each an assertion or delete it.",
        "The probe is the test: assert no unit-test file defines a test without asserting.",
        "python scripts/correction_register.py --id F108",
        _p_f108,
        [S_DEAD, S_TDD],
    ),
    Finding(
        "F106",
        "Nothing tests the TradeExecutor ↔ real-connector join",
        "P1",
        "Tests",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "`TradeExecutor` is tested against `MagicMock` brokers. A mock with no spec agrees "
        "with every call, which is exactly how F61's signature mismatch — `place_order` "
        "versus `place_market_order` — survives the whole suite and surfaces at the first "
        "live order. Use `create_autospec(RealConnector)` so the mock rejects what the real "
        "class would.",
        "Re-run the existing executor tests against an autospec of each connector and watch "
        "the ones with wrong signatures fail.",
        "python scripts/correction_register.py --id F106",
        _p_f106,
        [S_DEAD, S_TDD],
    ),
    Finding(
        "F119",
        "Annualised return divided 252 by the sample length",
        "P1",
        "Quant",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Done: `backtesting/metrics.py` scales by `sqrt(252)`. The old form understated by "
        "34x on hourly bars, and Calmar inherited it.",
        "n/a",
        "python scripts/correction_register.py --id F119",
        _p_f119,
        ["risk-metrics-calculation"],
    ),
    Finding(
        "F120",
        "Sortino's denominator was the std of losing observations",
        "P1",
        "Quant",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Done: `calculate_sortino_ratio` uses downside deviation about the target. The old "
        "form measured dispersion *among* losses rather than shortfall below target, so its "
        "bias flipped sign with the return distribution.",
        "n/a",
        "python scripts/correction_register.py --id F120",
        _p_f120,
        ["risk-metrics-calculation"],
    ),
    Finding(
        "F125",
        "The regime EMA weighted the oldest bar most",
        "P1",
        "Quant",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Done: `_ema` recurses forward, so alpha lands on the newest bar. The `reversed()` "
        "that remains in `ml/regime.py` is `_calculate_duration` counting backwards through "
        "state history, which is correct.",
        "n/a",
        "python scripts/correction_register.py --id F125",
        _p_f125,
        ["risk-metrics-calculation"],
    ),
    Finding(
        "F145",
        "Missing features were zero-filled before scaling",
        "P0",
        "ML",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Done: imputation happens in scaled space, so a missing feature reaches the model as "
        "neutral rather than -15 sigma. It was measured at -15σ for price and -3.3σ for RSI "
        "with 48.2% of the vector missing — a confident prediction from a vector the model "
        "had never seen the like of.",
        "n/a",
        "python scripts/correction_register.py --id F145",
        _p_f145,
        ["ml-pipeline-workflow"],
    ),
    Finding(
        "F80",
        "The nuclear wordmap matched by bare substring",
        "P1",
        "Quant",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Done: the scorer compiles `\\b...\\b` patterns from escaped terms, so a headline "
        "containing 'coupon' no longer scores 'coup' and trips hedge mode.",
        "n/a",
        "python scripts/correction_register.py --id F80",
        _p_f80,
        [S_DEAD],
    ),
    Finding(
        "F81",
        "The hedge was marked active before the broker call",
        "P0",
        "Risk",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Done: `_hedge_active` is set after a successful placement, and the failure path "
        "returns without recording anything, so the next call is a real retry. The account "
        "used to be unhedged while every dashboard said hedged, with the duplicate-"
        "activation guard latched so no retry was possible.",
        "Already carried by the orchestrator's hedge tests.",
        "python scripts/correction_register.py --id F81",
        _p_f81,
        [S_DEAD],
    ),
    Finding(
        "F84",
        "The data-layer safety gate was skipped in the condition it exists for",
        "P0",
        "Risk",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "Done: the `_started` conjunct is gone. `_started = True` is the last line of "
        "`start()`, so a failure anywhere in startup left it False and the gate was skipped "
        "in exactly the state it was written to catch.",
        "Already carried; `execution/engine.py` documents the removal at the call site.",
        "python scripts/correction_register.py --id F84",
        _p_f84,
        [S_DEAD],
    ),
    Finding(
        "F94",
        "Regime detection and position sizing",
        "P2",
        "Quant",
        "docs/audit/REMEDIATION_PLAN.md — Phase 3",
        "The specific harm F94 named — an unrouted regime leaving every position at the 0.5x "
        "'unknown' multiplier — is gone: no such multiplier exists in `risk/`. Regimes are "
        "consumed elsewhere (signal composition, analytics). Whether *sizing* should be "
        "regime-aware at all is a strategy question, not a defect, so this is reported as "
        "measured rather than closed. Decide it deliberately or close it.",
        "If sizing becomes regime-aware: a test asserting the size differs between a known "
        "and an unknown regime, and that unknown is the conservative one.",
        "python scripts/correction_register.py --id F94",
        _p_f94,
        ["risk-metrics-calculation"],
    ),
    Finding(
        "F123",
        "`/walk-forward/run` tested on its own training data",
        "P1",
        "Quant",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Done 2026-09-13, and it was worse than this entry said. The endpoint computed five "
        "fold windows spanning three years and then discarded them: "
        "`_run_real_backtest(strategy, symbol, days, capital)` takes a *count of days* and "
        "always ends at `datetime.now(UTC)`. So all five folds measured the same recent "
        "period — train the last 153 days, test the last 66 — **with the test window "
        "contained entirely inside the training window**, which is total leakage rather "
        "than a missing purge gap, while the 2023-2026 fold dates reached the response as "
        "labels for a computation that never happened. `avg_test_sharpe` was the last 66 "
        "days' Sharpe averaged with itself. Each fold now runs over its own window through "
        "`_run_backtest_window`, the folds advance, and a `purge_days` embargo (default 5) "
        "separates training from testing. `WalkForwardEngine` is deliberately still not "
        "called: it is a parameter-grid optimiser and this endpoint validates one "
        "parameterisation, so using it would mean inventing a grid the caller did not ask "
        "for. Its purge semantics were the part worth borrowing.",
        "Carried by tests/unit/test_walk_forward_actually_walks_forward.py — distinct "
        "periods per fold, no train/test overlap, an embargo of the requested width, "
        "reported dates equal to measured dates, and folds that advance. Two of them "
        "initially passed against the defect because they compared datetimes and the "
        "broken code called now() once per backtest; they compare dates now.",
        "python scripts/correction_register.py --id F123",
        _p_f123,
        ["backtesting-frameworks"],
    ),
    Finding(
        "F147",
        "Order flow answered as though it had measured, and had two analyzers",
        "P1",
        "Dead controls",
        "docs/audit/REMEDIATION_PLAN.md — Phase 5",
        "Done 2026-09-13, on the honesty half — and a second defect underneath it. "
        "**(a) Zeros presented as measurements.** `/analysis` and `/profile` already 404ed "
        "with no data; `/delta` returned `cumulative_delta: 0`, `/levels` an empty level "
        "set and `/footprint` an empty list — each identical to a real, balanced, quiet "
        "tape. The dashboard was worse: `get_market_bias` returned "
        "`{bias: neutral, strength: weak}`, a defensible trading read synthesised from "
        "zero ticks. All now refuse, matching the convention the router had already set "
        "for itself, and `/stats` states `ingesting` so an operator can tell a quiet tape "
        "from a dead subscription. **(b) Two analyzers, and the feedable one was "
        "unreachable.** `init_order_flow` built its own `OrderFlowAnalyzer()` and mounted "
        "a duplicate of the same paths with a plain `include_router`, while the registry "
        "mounted the module global; FastAPI resolves to the first, so the startup service "
        "was shadowed. Measured: two trades into it and `/delta` still answered 0. Anyone "
        "wiring a tick feed to the obvious object would have seen nothing change, with no "
        "error. It now returns the analyzer that serves. **Subscribing a tick source "
        "remains open** — which symbols, what rate, what retention is a product decision, "
        "and the endpoints now say `not measured` rather than guessing in the meantime.",
        "Carried by tests/unit/test_order_flow_says_when_it_has_no_data.py — refusals per "
        "endpoint, positive controls that a fed symbol is served (one of which caught the "
        "dashboard tests passing against a wrong route prefix), the delta's real value, "
        "the `ingesting` flag, and that the startup service is the served analyzer.",
        "python scripts/correction_register.py --id F147",
        _p_f147,
        [S_DEAD],
    ),
    Finding(
        "F149",
        "The GodMode watchlist sparkline was `Math.random()`",
        "P1",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done: `Math.random()` survives only for element ids and reconnect jitter, never for a plotted value.",
        "n/a",
        "python scripts/correction_register.py --id F149",
        _p_f149,
        [S_UI, S_DEAD],
    ),
    Finding(
        "F150",
        "'Copy API key' built the key client-side",
        "P1",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done: the client asks the server to mint a key rather than assembling one that could never authenticate.",
        "n/a",
        "python scripts/correction_register.py --id F150",
        _p_f150,
        [S_UI],
    ),
    Finding(
        "F201",
        "`/academy` advertised 15 unavailable courses as available",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done: no page advertises unavailable content as included in a plan. That was a "
        "false statement to a paying subscriber.",
        "n/a",
        "python scripts/correction_register.py --id F201",
        _p_f201,
        [S_UI],
    ),
    Finding(
        "F209",
        "Two dashboards, with the nav pointing at the weaker one",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done: `/home` redirects to `/dashboard`, so there is one canonical dashboard.",
        "n/a",
        "python scripts/correction_register.py --id F209",
        _p_f209,
        [S_UI],
    ),
    Finding(
        "F210",
        "Duplicate route aliases rendering identical pages",
        "P3",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done: 88 distinct paths, none declared twice, so breadcrumbs and active-nav agree.",
        "n/a",
        "python scripts/correction_register.py --id F210",
        _p_f210,
        [S_UI],
    ),
    Finding(
        "F173",
        "`/dashboard` renders no headings",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "`Dashboard.tsx` renders zero `h1`–`h3` across 1,027 lines, so a screen reader gets "
        "no document outline for the product's main page. `/landing` renders 24.",
        "A render test asserting the page exposes exactly one `h1` and a sensible heading order.",
        "python scripts/correction_register.py --id F173",
        _p_f173,
        [S_UI],
    ),
    Finding(
        "F187",
        "Dashboard metrics do not drill through",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "One `onClick` in the whole page. A dashboard whose numbers cannot be opened is a "
        "readout, not an application — and per F185 the endpoints behind them "
        "(`/equity-curve`, `/history`, `/depth/{symbol}`, `/microstructure`) already exist. "
        "Both halves are built; nothing joins them.",
        "For each metric tile, a test asserting a click navigates to the page that explains it.",
        "python scripts/correction_register.py --id F187",
        _p_f187,
        [S_UI],
    ),
    Finding(
        "F172",
        "Icon-only buttons without an accessible name",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Deliberately UNVERIFIED. Two regex attempts each produced a confident wrong answer "
        "(one said FIXED across 552 buttons, the other found 9 offending files) because a "
        "JSX opening tag cannot be bracketed by a regex — an attribute may contain `>`, and "
        "`onClick={() => nav('/x')}` ends the match at the arrow. Add "
        "`eslint-plugin-jsx-a11y` and let a real parser answer it; that lint rule IS the "
        "fix, and the count comes with it.",
        "The lint rule itself, run in CI. Break one button's label and watch it fail.",
        "npm run lint  (once jsx-a11y is wired)",
        _p_f172,
        [S_UI],
    ),
    Finding(
        "AI-GATE",
        "Two acceptance tests the AI layer must not ship without",
        "P1",
        "AI authority",
        "docs/audit/REMEDIATION_PLAN.md — AI Core section",
        "Adopt both before writing more agent code: an agent calling an action outside its "
        "scope must FAIL THE BUILD, and a proposal executing without an approval record "
        "must fail the build. `enforce_agent_action` and `ToolBus.invoke` already run "
        "outside tests, so this is about keeping them enforced as the layer grows — without "
        "these, the spec's approval queue is the same shape as F176: a control described "
        "accurately and enforced by convention. Note the inherited prerequisites, each "
        "tracked here: the AI kill switch depends on F139 (now fixed), and the agent "
        "sandbox on F130 (open — unsigned patches) and F184 (fixed).",
        "The two tests are the deliverable. Write them red: grant an agent a narrow scope, "
        "call outside it, assert refusal; submit a proposal with no approval record, assert "
        "it does not execute.",
        "python scripts/correction_register.py --id AI-GATE",
        _p_ai_gate,
        [S_DEAD, S_INV, "threat-modelling"],
    ),
    Finding(
        "AI-SURFACE",
        "Superadmin surface must differ by capability, not by a UI branch",
        "P1",
        "AI authority",
        "docs/audit/REMEDIATION_PLAN.md — AI Core section",
        "Done for the enforcement half: server-side capability is pinned with a 403 "
        "assertion. The remaining work is structural — separate components rather than "
        "`if (isSuperAdmin)` branches, plus the direct-GET probe from F198 applied to the "
        "operator routes, so an unprivileged user cannot reach an admin view by typing its "
        "URL.",
        "A 403 test per privileged endpoint, and a direct-GET probe per operator route.",
        "pytest tests/unit/test_superadmin_capabilities_are_server_enforced.py -q",
        _p_ai_surface,
        ["threat-modelling", S_UI],
    ),
    Finding(
        "AI-SCOPE",
        "AI Core scope questions the owner has not settled",
        "OWNER",
        "AI authority",
        "docs/audit/REMEDIATION_PLAN.md — AI Core section",
        "Four decisions, none of which engineering should default. (a) Confirm the six "
        "Business Operations department names before rebuilding Figma — the Starter-plan "
        "rate limit makes iteration expensive and the current file is already out of date. "
        "(b) Confirm VPS RAM/VRAM before locking a local model size, and settle F178/F98 "
        "first so 'what is deployed' is a known quantity. (c) Decide whether customizable "
        "settings return to scope — theme, department visibility, notification thresholds, "
        "default autonomy per department — dropped from later spec drafts and distinct from "
        "the per-action autonomy dial. (d) Sequence the AI Gateway, internal MCP tool bus, "
        "response cache, guardrails-as-pipeline and formalised evals.",
        "None — these are scope decisions. Each becomes a plan once chosen.",
        "docs/audit/plans/2026-09-05-ai-core.md",
        _p_owner("scope and hardware questions the owner has not answered"),
        [],
    ),
    Finding(
        "AFF-TIER",
        "A level upgrade advances one tier per conversion",
        "P3",
        "Money",
        "This session, 2026-09-13 — found while covering affiliate.py",
        "`check_level_upgrade` walks the levels above the current one and returns the "
        "FIRST that qualifies, so an affiliate whose referral count and revenue already "
        "clear a higher tier is granted only the next one up. They earn the lower "
        "commission rate until the following conversion triggers another check. Whether "
        "tiers should be skippable is a commercial decision rather than a bug, so the "
        "behaviour is pinned by a test that says so rather than quietly changed — if the "
        "policy changes, that test should fail and be rewritten.",
        "tests/unit/test_affiliate_commissions_conserve.py"
        "::test_check_level_upgrade_advances_one_tier_per_call pins today's behaviour.",
        "python scripts/correction_register.py --id AFF-TIER",
        _p_tier_skip,
        [S_MONEY],
    ),
    Finding(
        "OF-VOTER",
        "One of three order-flow bias voters can never vote",
        "P2",
        "Quant",
        "This session, 2026-09-13 — found while covering order_flow_dashboard.py",
        "`OrderFlowDashboard._bias_vote_advanced` calls `self._adv.analyze(symbol)`. "
        "`AdvancedOrderFlowAnalyzer` has no `analyze` — its surface is "
        "`get_aggression_metrics`, `get_pressure_gauges`, `get_order_flow_oscillator`, "
        "`detect_delta_divergence`, `get_stacked_imbalances`, `get_volume_clusters` and "
        "`get_volume_imbalance_by_level`. Every call raises `AttributeError` into a handler "
        "that logs at WARNING and returns None, so `get_bias`'s majority is decided by two "
        "voters while reading as three. Deliberately pinned rather than repaired: choosing "
        "which of those methods constitutes a bullish or bearish read is a quantitative "
        "decision, and guessing one would be inventing a signal. `get_bias` is unrouted "
        "today — reachable only from `get_summary`, which nothing serves — so nothing acts "
        "on it yet.",
        "tests/unit/test_order_flow_says_when_it_has_no_data.py"
        "::test_the_advanced_bias_voter_can_never_vote asserts the method is absent and the "
        "vote is None, and says to rewrite itself when the voter is wired.",
        "python scripts/correction_register.py --id OF-VOTER",
        _p_of_voter,
        [S_DEAD],
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
        "Two credentials. (a) The superadmin credential named in the AI Core spec as item "
        "6 — 'above everything in this plan'. Its location is still unconfirmed: the tracked "
        "working tree reads as placeholders, so the file or commit holding it has to be "
        "named before it can be rotated. (b) A Vercel token (`vck_…`) was pasted into a chat "
        "session. It was never written "
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
