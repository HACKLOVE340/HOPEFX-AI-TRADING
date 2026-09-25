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
    python scripts/correction_register.py --write      # rewrite §3, keeping the prose
    python scripts/correction_register.py --markdown   # the register's body, to stdout
    python scripts/correction_register.py --check      # CI/pre-commit gate
    python scripts/correction_register.py --id F97     # one finding, verbose
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Two probes below import a repository package — `ml.inference_engine`, to read
# the shipped model's age and its provenance. Run the obvious way, as
# `python scripts/correction_register.py`, `sys.path[0]` is `scripts/` and those
# imports raised ModuleNotFoundError, so both probes degraded to UNVERIFIED. Run
# from a shell with the repository root on PYTHONPATH — an activated dev
# environment, or `python -m` — the same imports resolved and both measured
# OWNER. One commit, two headlines, and `--check` passing or failing with them.
#
# A register whose status column depends on how the reader invoked it is not
# measuring the repository. It is worse than a wrong answer in one particular
# way: UNVERIFIED is reserved here for "cannot honestly be called open or
# fixed", and it was being produced by a measurement that never ran, on two
# findings that are squarely the owner's to resolve.
#
# So the path is settled here rather than left to the caller. Inserted at the
# front because `scripts/` is already `sys.path[0]` and shadows nothing at the
# root; appending would leave a `scripts/ml.py` able to win the lookup.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The document this script reads and writes. `HOPEFX_CORRECTION_REGISTER` points
# it somewhere else, and exists for one reason: the gate's own tests need a
# register they are allowed to vandalise. They used to vandalise the committed
# one — editing `docs/audit/CORRECTION_REGISTER.md` in place and restoring it in
# a fixture's `finally`, including one test that `unlink()`ed it. Between the
# unlink and the restore the register did not exist, so any hard stop in that
# window (an OOM, a container kill, a cancelled CI job) left the single list of
# outstanding work deleted in the working tree. The override costs one
# environment variable and removes that window entirely.
#
# Nothing in production sets it: unset, this is exactly the path it always was.
_REGISTER_OVERRIDE = os.environ.get("HOPEFX_CORRECTION_REGISTER")
REGISTER = Path(_REGISTER_OVERRIDE) if _REGISTER_OVERRIDE else ROOT / "docs" / "audit" / "CORRECTION_REGISTER.md"

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


def _blank(match: re.Match[str]) -> str:
    """Replace a stripped region with its own newlines, so lines do not move.

    Deleting a triple-quoted block removed its newlines with it, and `_grep`
    numbers lines against this output. Every location the register printed was
    therefore short by however much prose sat above the hit — F206 reported
    `monetization/stripe_integration.py:297` for code on line 329, a 32-line
    error, and fifteen probes report locations this way. The register's whole
    proposition is "here is the evidence, go and look"; a coordinate that lands
    thirty lines away spends the reader's trust for nothing.

    Blanking keeps the file's shape while still removing the prose, which is the
    only reason this function exists.
    """
    return "\n" * match.group(0).count("\n")


def _code(rel: str) -> str:
    """Source with comments and docstrings removed, line numbers preserved.

    A probe that greps raw text finds the defect quoted inside the comment that
    explains its fix. Strip prose first, always — but strip it in place: see
    `_blank`, and `tests/unit/test_correction_register_gate.py` for the
    assertion that a reported line still resolves in the real file.
    """
    text = _read(rel)
    if not text:
        return ""
    if rel.endswith((".py",)):
        text = re.sub(r'"""[\s\S]*?"""', _blank, text)
        text = re.sub(r"'''[\s\S]*?'''", _blank, text)
        # Line-preserving already: `#.*$` stops before the newline.
        text = re.sub(r"(?m)#.*$", "", text)
    elif rel.endswith((".yml", ".yaml", ".cfg", ".coveragerc", ".ini", ".toml")):
        text = re.sub(r"(?m)^\s*#.*$", "", text)
    elif rel.endswith((".ts", ".tsx", ".js", ".jsx")):
        text = re.sub(r"/\*[\s\S]*?\*/", _blank, text)
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


def _scanned(files: list[str], what: str) -> tuple[str, str] | None:
    """Refuse rather than report clean when the scan matched nothing.

    Rule 2 — an unmeasured value is absent, never zero — applied to the register
    itself. Ten probes decided `OPEN if hits else FIXED`, so an empty file list
    read as "no violations" rather than "nothing was measured": a renamed
    package, a moved directory or a glob that stopped matching closed the
    finding silently. F108 already refuses this way; the others did not.

    Returns a status tuple to return, or None to carry on.
    """
    if not files:
        return UNVERIFIED, f"no {what} matched — the scan is broken, not the code"
    return None


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _p_f96() -> tuple[str, str]:
    """A deploy must be gated on a verification workflow that SUCCEEDED."""
    body = _code(".github/workflows/deploy.yml")
    if not body:
        return UNVERIFIED, "deploy.yml not found"
    by_run = "workflow_run:" in body
    by_needs = re.search(r"^\s+needs:", body, re.M) is not None
    # workflow_run fires on completion, failures included. Without the
    # conclusion check the trigger reads as a gate and ships red builds.
    checks_conclusion = "workflow_run.conclusion" in body and "success" in body
    if by_needs and not by_run:
        return FIXED, "deploy is gated by a job-level needs:"
    if by_run and checks_conclusion:
        return FIXED, (
            "deploy triggers on the CI workflow completing and runs only when its "
            "conclusion is success; workflow_dispatch is allowed through explicitly"
        )
    if by_run:
        return OPEN, "triggers on workflow_run but does not check the conclusion — it deploys red builds"
    return OPEN, "deploy.yml has no `needs:` and no `workflow_run:` — it fires on push regardless of CI"


def _p_f97() -> tuple[str, str]:
    """No secret-holding action may be pinned to a mutable tag.

    Reports PARTIAL while the known reference is still a tag but a ratchet
    prevents a second one. The pin itself needs a SHA lookup against
    appleboy/ssh-action, which this session's repository-scoped GitHub access
    cannot perform — and a guessed SHA breaks every deploy.
    """
    _wf = _tracked(".github/workflows/*.yml")
    if (unscanned := _scanned(_wf, "workflow file")) is not None:
        return unscanned
    hits = []
    for wf in _wf:
        body = _code(wf)
        for block in re.split(r"\n(?=\s*-\s+(?:name|uses):)", body):
            m = re.search(r"uses:\s*(\S+)", block)
            if not m or "secrets." not in block:
                continue
            ref = m.group(1)
            if "@" in ref and not re.fullmatch(r"[0-9a-f]{40}", ref.rsplit("@", 1)[1]):
                hits.append(f"{wf.split('/')[-1]}: {ref}")

    ratcheted = _exists("tests/unit/test_deploy_workflow_is_gated_and_pinned.py")
    if not hits:
        return FIXED, "every secret-holding action is pinned to a commit SHA"
    return _named(
        PARTIAL if ratcheted else OPEN,
        f"{len(hits)} secret-holding action(s) still on a mutable tag ({hits[0]}). "
        "A ratchet blocks a second one and the recorded set may only shrink; the pin "
        "itself needs the tag resolved to its 40-character SHA on GitHub"
        if ratcheted
        else f"{len(hits)} secret-holding action(s) on a mutable tag: {hits[0]}",
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


def _chart_env_for_argocd() -> dict[str, str] | None:
    """`.Values.env` of the chart every ArgoCD Application syncs.

    `templates/deployment.yaml` expands `.Values.env` wholesale, so values.yaml
    is the whole answer and no `helm` binary is needed.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return None
    env: dict[str, str] = {}
    found = False
    for rel in _glob("k8s/*.yaml") + _glob("deployments/k8s/*.yaml"):
        try:
            docs = list(yaml.safe_load_all(_read(rel)))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("kind") != "Application":
                continue
            path = ((doc.get("spec") or {}).get("source") or {}).get("path")
            if not path:
                continue
            values = ROOT / str(path).strip("/") / "values.yaml"
            if not values.is_file():
                continue
            found = True
            try:
                loaded = [d for d in yaml.safe_load_all(values.read_text(encoding="utf-8")) if isinstance(d, dict)]
            except yaml.YAMLError:
                continue
            block = (loaded[0].get("env") if loaded else None) or {}
            if isinstance(block, dict):
                env.update({str(k): str(v) for k, v in block.items()})
    return env if found else None


def _p_deploy_chart() -> tuple[str, str]:
    """The chart ArgoCD syncs must carry the safety posture the trees declare."""
    env = _chart_env_for_argocd()
    if env is None:
        return UNVERIFIED, "no ArgoCD Application names a chart with a values.yaml"
    absent = [k for k in ("HOPEFX_INVARIANT_MODE", "DRIFT_BLOCK", "STALE_MODEL_BLOCK") if k not in env]
    if absent:
        return OPEN, f"the deployed chart declares none of {absent} — each falls back to a code default"

    weak = [f"{k}={env[k]}" for k in ("DRIFT_BLOCK", "STALE_MODEL_BLOCK") if env.get(k, "").strip().lower() != "true"]
    mode = env.get("HOPEFX_INVARIANT_MODE", "").strip().lower()
    if mode != "enforce" and not env.get("HOPEFX_INVARIANT_ENFORCE_KINDS", "").strip():
        weak.append(f"HOPEFX_INVARIANT_MODE={mode} enforces no kinds")
    if weak:
        return OPEN, "the deployed chart ships a weakened value: " + ", ".join(weak)

    # _glob, not _tracked: git ls-files cannot see a template added in the same
    # commit as this probe, and a probe that reports a fix as absent because the
    # file is not yet staged is a probe measuring the index, not the tree.
    templates = "\n".join(_read(f) for f in _glob("helm/hopefx/templates/*.yaml"))
    if not templates:
        return UNVERIFIED, "no chart templates found — the scan is broken, not the chart"
    missing = []
    if "hopefx-kill-switch" not in templates:
        missing.append("the kill-switch ConfigMap")
    if "kind: RoleBinding" not in templates or "serviceAccountName:" not in templates:
        missing.append("RBAC/ServiceAccount to reach it")
    if missing:
        return OPEN, f"the deployed chart omits {' and '.join(missing)}"

    return FIXED, (
        "the chart ArgoCD syncs states all three safety keys at safe values and ships "
        "the kill switch's layer-5 ConfigMap with least-privilege RBAC"
    )


def _p_ks_selfheal() -> tuple[str, str]:
    """A GitOps sync must not revert a pod-engaged kill switch."""
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return UNVERIFIED, "PyYAML unavailable"

    apps = 0
    unprotected: list[str] = []
    for rel in _glob("k8s/*.yaml") + _glob("deployments/k8s/*.yaml"):
        try:
            docs = list(yaml.safe_load_all(_read(rel)))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("kind") != "Application":
                continue
            apps += 1
            spec = doc.get("spec") or {}
            policy = (spec.get("syncPolicy") or {}).get("automated") or {}
            if not policy.get("selfHeal"):
                continue
            options = [str(o) for o in ((spec.get("syncPolicy") or {}).get("syncOptions") or [])]
            covered = any(
                e.get("kind") == "ConfigMap"
                and e.get("name") == "hopefx-kill-switch"
                and any(str(ptr).rstrip("/") == "/data" for ptr in (e.get("jsonPointers") or []))
                for e in (spec.get("ignoreDifferences") or [])
                if isinstance(e, dict)
            )
            if not covered:
                unprotected.append(f"{rel}: selfHeal on, /data of hopefx-kill-switch not exempt")
            elif "RespectIgnoreDifferences=true" not in options:
                unprotected.append(f"{rel}: exempt in Git but RespectIgnoreDifferences is not set, so sync ignores it")

    if not apps:
        return UNVERIFIED, "no ArgoCD Application parsed — the scan is broken, not the config"
    if unprotected:
        return OPEN, "; ".join(unprotected)
    return FIXED, f"{apps} ArgoCD Application(s): a sync cannot revert an engaged kill switch"


def _p_f178() -> tuple[str, str]:
    """Two ConfigMaps named `hopefx-config` with contradictory safety values.

    The first version of this probe collected every `HOPEFX_INVARIANT_MODE`
    across both manifest trees and reported OPEN whenever two differed. That
    measured the wrong thing, and kept reporting the finding as open after it
    was fixed: the defect was never that the two files disagreed, it was that
    they carried the SAME NAME in the same namespace, so `kubectl apply`
    replaced one's `data` with the other's and whichever went last defined the
    safety posture for both deployments.

    Once renamed, a difference is not a contradiction. `k8s/` runs full
    enforcement against a live broker; `deployments/k8s/` runs the staged
    rollout documented in docs/INVARIANT_ROLLOUT.md, where the global mode stays
    `monitor` while HOPEFX_INVARIANT_ENFORCE_KINDS turns kinds on one at a time.
    Reporting that as a defect asks a contributor to delete a deliberate lever.

    So this probes the three rules that are actually load-bearing, each pinned by
    tests/unit/test_configmaps_do_not_contradict_on_safety.py:

      1. no ConfigMap name is declared twice — the structural fix;
      2. a manifest below full enforcement names the kinds it still enforces,
         since without them the same file enforces nothing;
      3. a manifest below full enforcement names its broker, since the rule
         "enforce wherever a live broker is" cannot be evaluated against a
         broker that arrives from a code default.
    """
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML is a hard dependency here
        return UNVERIFIED, "PyYAML unavailable, cannot parse the manifests"

    seen: dict[str, list[str]] = {}
    data_by_name: dict[str, dict[str, str]] = {}
    weak: list[str] = []
    parsed = 0
    for rel in _glob("k8s/*.yaml") + _glob("deployments/k8s/*.yaml"):
        try:
            docs = list(yaml.safe_load_all(_read(rel)))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("kind") != "ConfigMap":
                continue
            parsed += 1
            meta = doc.get("metadata") or {}
            name = meta.get("name")
            data = doc.get("data") or {}
            if name:
                seen.setdefault(str(name), []).append(rel)
                data_by_name.setdefault(str(name), {})[rel] = json.dumps(data, sort_keys=True)
            mode = str(data.get("HOPEFX_INVARIANT_MODE", "")).strip().lower()
            if not mode or mode == "enforce":
                continue
            if not str(data.get("HOPEFX_INVARIANT_ENFORCE_KINDS", "")).strip():
                weak.append(f"{rel}: mode={mode} enforces no kinds")
            if not str(data.get("BROKER_TYPE", "")).strip():
                weak.append(f"{rel}: mode={mode} names no broker")

    if not parsed:
        # A scan that matched nothing agrees with every rule below (F255).
        return UNVERIFIED, "no ConfigMap documents parsed — the scan is broken, not the manifests"

    # A shared name is not itself the defect. `hopefx-kill-switch` is declared in
    # both trees on purpose — it is one cross-pod STATE object that every pod
    # reads by that exact name and whose RBAC grants it by name. Divergent data
    # under a shared name is the defect, because apply order then decides the
    # contents. Same rule as
    # tests/unit/test_configmaps_do_not_contradict_on_safety.py.
    collisions = {
        name: sorted(files)
        for name, files in seen.items()
        if len(files) > 1 and len({data_by_name[name][f] for f in files}) > 1
    }
    if collisions:
        return OPEN, f"{len(collisions)} ConfigMap name(s) declared twice with different data: {collisions}"
    if weak:
        return OPEN, "; ".join(sorted(weak))

    # The manifests above are not what the deployer syncs. k8s/argocd-app.yaml
    # points at helm/hopefx, which carried none of this posture — measured, and
    # fixed, in the same commit as this probe. Ask the deployed chart directly,
    # or this probe certifies trees nothing applies.
    chart_env = _chart_env_for_argocd()
    if chart_env is None:
        return UNVERIFIED, "could not read the chart the ArgoCD Application syncs"
    absent = [k for k in ("HOPEFX_INVARIANT_MODE", "DRIFT_BLOCK", "STALE_MODEL_BLOCK") if k not in chart_env]
    if absent:
        return OPEN, f"the deployed chart does not declare {absent} — each falls back to a code default"

    return FIXED, (
        f"{parsed} ConfigMap(s), {len(seen)} distinct names, no divergent duplicate. "
        f"The staged set runs monitor + enforce-kinds by design and names its broker, "
        f"and the chart ArgoCD syncs states all three safety keys"
    )


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


def _p_create_all_upgrade() -> tuple[str, str]:
    """`alembic upgrade head` over a create_all() database dies on a collision.

    Static, not executed: running the migration chain takes seconds and needs a
    scratch database, which a pre-commit probe should not do. It asks the
    question the failure turns on — does a migration call `op.create_table` for
    a table the ORM also declares, without first checking whether it exists?
    """
    import ast

    declared: set[str] = set()
    for rel in ("database/models.py", "database/user_models.py"):
        try:
            tree = ast.parse(_read(rel))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in node.targets)
            ):
                declared.add(node.value.value)

    if not declared:
        return UNVERIFIED, "no __tablename__ found — the scan is broken, not the ORM"

    unguarded: list[str] = []
    files = _glob("alembic/versions/*.py")
    if not files:
        return UNVERIFIED, "no migrations found — the scan is broken"

    for rel in files:
        body = _read(rel)
        try:
            tree = ast.parse(body)
        except SyntaxError:
            continue
        # TABLE guards only. A first version also accepted the generic
        # `if_not_exists`, which matches `_add_index_if_not_exists` and
        # `_add_column_if_not_exists` — so `n1o2p3q4r5s6`, the migration that
        # actually fails, was skipped as guarded while a different file was
        # reported. A probe that names the wrong file to fix is worse than one
        # that names none.
        guarded = any(token in body for token in ("_tbl(", "_table_exists", "has_table", "get_table_names"))
        if guarded:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "create_table"):
                continue
            arg = node.args[0] if node.args else None
            name = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
            if name in declared:
                unguarded.append(f"{rel.split('/')[-1]}:{name}")

    if unguarded:
        return OPEN, (
            f"{len(unguarded)} unguarded create_table call(s) for a table the ORM also "
            f"declares: {', '.join(sorted(unguarded)[:4])} — `alembic upgrade head` over a "
            "database built by create_all() dies there"
        )
    return FIXED, (
        f"every migration that creates one of the {len(declared)} ORM tables checks first, so "
        "a create_all() database can be brought under migration control"
    )


def _p_drift_absence() -> tuple[str, str]:
    """Absent features must not be scored as drift.

    `_check_feature_drift` computed `z = |live - train_mean| / std` for every
    feature, and a feature the pipeline could not supply arrives zero-filled —
    so `|0 - train_mean|` is large whenever the training mean is far from zero
    and a DEAD FEED read as feature drift. With DRIFT_BLOCK=true that halts the
    desk and the log blames the model.

    Measured by scripts/drift_guard_report.py on the shipped stats: 103 of 176
    features zero-filled, and 12 of the 14 exceeding z=4.0 are absent rather
    than drifted. The deployed chart runs z=3.0, where it is 15.
    """
    body = _code("ml/inference_engine.py")
    if not body:
        return UNVERIFIED, "ml/inference_engine.py not readable — the scan is broken"

    separates = "_drift_absent_count" in body and "train_mean != 0.0" in body
    exposed = "absent_features" in body
    if not separates:
        return OPEN, (
            "a zero-filled feature is scored as drift, so a feed outage trips DRIFT_BLOCK "
            "and is reported as feature_drift"
        )
    if not exposed:
        return PARTIAL, "absence is separated from drift but not exposed on the status payload"
    return FIXED, (
        "absence and drift are counted apart, z_max is over measured features only, absence "
        "is logged at ERROR and both counts are on the status payload. Whether absence should "
        "itself halt inference is a separate gate and is the owner's call (DRIFT-ABSENCE)"
    )


def _p_f218() -> tuple[str, str]:
    """Model tables that exist only via create_all() and have no migration.

    Delegates to scripts/schema_migration_check.py, which resolves names instead
    of matching text. The previous probe searched the migration corpus for

        create_table(  "table_name"

    and reported "36 of 44 tables have no migration". The real number was 0 of
    47, and the gap was entirely the probe's:

      * 35 tables are created through a local `_tbl(name, *args, **kwargs)`
        idempotency wrapper, so the literal never sits beside `create_table`;
      * four more are created as `op.create_table(_TABLE, ...)` against a
        module-level constant;
      * three live in `database/user_models.py`, which the probe never read —
        it would have missed a genuine gap there entirely.

    32 false positives is worse than no probe: a real missing migration would
    have been invisible in the noise, and the figure was quoted in three
    documents as a P1.
    """
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_schema_migration_check", ROOT / "scripts" / "schema_migration_check.py"
        )
        if spec is None or spec.loader is None:
            return UNVERIFIED, "scripts/schema_migration_check.py could not be loaded"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        return UNVERIFIED, f"schema_migration_check unavailable: {type(exc).__name__}: {exc}"

    # Read the inputs through THIS module's readers first. The helper opens the
    # filesystem directly, which is correct for a standalone gate and wrong
    # here: it made this probe unreachable by
    # tests/unit/test_correction_register_gate.py's starvation audit, which
    # blanks _read/_code/_glob and asserts no probe still says FIXED. A probe
    # the audit cannot starve is a probe nobody can check for the F255 class.
    if not _code("database/models.py") or not _glob("alembic/versions/*.py"):
        return UNVERIFIED, "the schema scan found no models or no migrations — broken scan, not a clean tree"

    declared = mod.declared_tables(ROOT)
    created = mod.migrated_tables(ROOT)
    if not declared or not created:
        # A scan that matched nothing agrees with any conclusion (F255).
        return UNVERIFIED, "the schema scan found no tables or no migrations — broken scan, not a clean tree"

    missing = sorted(set(declared) - set(created))
    if missing:
        return OPEN, (
            f"{len(missing)} of {len(declared)} tables have no migration and exist only via "
            f"create_all(), which never ALTERs: {', '.join(missing[:6])}"
        )
    return FIXED, (
        f"all {len(declared)} ORM tables across {len(set(declared.values()))} models module(s) "
        f"are created by a migration; pinned by tests/unit/test_schema_migration_check.py"
    )


def _p_f61() -> tuple[str, str]:
    """Can `BROKER_TYPE=oanda` place an order, and does startup refuse if not?

    The previous probe matched the line `AsyncOANDAConnector = OANDABroker` and
    reported PARTIAL whenever it existed — "the bare alias remains". But the
    alias was never the defect: it is a legitimate name binding that
    `core/startup_factories.py` imports, and the probe could only have reached
    FIXED if somebody DELETED it, which would break the import. A probe that can
    only be satisfied by a harmful change is worse than no probe, and this one
    also told every reader to go and build an adapter that already existed.

    What the finding actually asks is whether the connector the executor calls
    implements `place_market_order`, and whether it maps the side rather than
    guessing it — `_units()` treats an unrecognised direction as a SELL, so a
    default there places the opposite of the intended trade.

    Three states, because the honest answer is not binary: the adapter is
    written and refuses ambiguity, and nothing in this tree has spoken to OANDA.
    Venue verification needs a practice account, so it cannot be measured here —
    the probe says what it checked and names what it did not.
    """
    body = _code("brokers/oanda.py")
    if not body:
        return UNVERIFIED, "brokers/oanda.py not found"
    if not _grep(r"AsyncOANDAConnector\s*=", "brokers/oanda.py"):
        return OPEN, "AsyncOANDAConnector is gone; core/startup_factories.py imports it by name"

    adapter = re.search(r"async def place_market_order\s*\(", body) is not None
    refuses = re.search(r"def _normalise_side", body) is not None and "Unrecognised order side" in _read(
        "brokers/oanda.py"
    )
    if not adapter:
        return OPEN, (
            "the connector AsyncOANDAConnector aliases has no place_market_order — "
            "execution/trade_executor.py calls it, so the first live order raises AttributeError"
        )
    if not refuses:
        return OPEN, (
            "place_market_order exists but nothing refuses an unrecognised side; "
            "_units() defaults to SELL, so a bad side places the opposite trade"
        )

    # Both startup paths must refuse a connector that cannot place an order.
    startup = _code("core/startup_factories.py")
    guards = len(re.findall(r'_required\s*=\s*\(\s*"place_market_order"', startup))
    guarded = _exists("tests/unit/test_broker_type_oanda_is_not_silently_broken.py")
    if guards < 2:
        return PARTIAL, (
            f"the adapter is written and refuses an unrecognised side, but only {guards} of the 2 "
            "startup broker paths verifies the connector can place an order — the factory path "
            "states it in a docstring and checks nothing"
        )
    # The only thing left is venue verification, which cannot be read out of the
    # source — so it is read out of a record instead. Without this branch the
    # probe could never reach FIXED, and the finding would stay PARTIAL for ever
    # even after somebody placed the order: a measurement that cannot succeed,
    # which is the mirror of the controls-that-cannot-fail this register hunts.
    #
    # To close it: place ONE order on an OANDA practice account with
    # OANDA_PRACTICE=true, and record it in docs/VENUE_EVIDENCE.toml as
    #
    #     [oanda]
    #     verified_on = "YYYY-MM-DD"
    #     account_type = "practice"
    #     order_id = "<the id OANDA returned>"
    #     side_confirmed = "buy"   # that the venue booked the side we asked for
    #
    # The side matters more than the fill: `_units()` treats an unrecognised
    # direction as a SELL, so "it placed an order" is not the claim being made —
    # "it placed the side we asked for" is.
    evidence = _read("docs/VENUE_EVIDENCE.toml")
    verified = bool(re.search(r"(?ms)^\s*\[oanda\].*?^\s*side_confirmed\s*=", evidence))
    if verified:
        return _named(
            FIXED,
            "the adapter is written, refuses an unrecognised side, both startup paths verify the "
            "connector can place an order, and docs/VENUE_EVIDENCE.toml records a practice-account "
            "order with the booked side confirmed",
        )
    return _named(
        PARTIAL,
        "the adapter is written, maps OrderSide/long/short and refuses anything else rather than "
        "defaulting to SELL, and both startup paths refuse a connector that cannot place an order"
        + (" (pinned by tests)" if guarded else "")
        + ". NOT venue-verified: every test runs against a stubbed place_order and nothing here has "
        "spoken to OANDA. Record a practice order in docs/VENUE_EVIDENCE.toml to close it — the "
        "probe reads that file, so this can reach FIXED without anyone editing the probe",
    )


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
    """Does the creator ledger persist — and does that persistence *run*?

    This probe used to ask only whether ``revenue_split.py`` contained a
    session factory and a commit. It did, so F208 read FIXED for months while
    the module singleton the API uses was built as ``RevenueSplitEngine()``
    with no factory and nothing assigned one, so every write returned at
    ``if not self._session_factory``. The persistence was complete, correct and
    unreachable, and the probe could not tell the difference — which is the
    register's own rule 4: evidence that resolves is not evidence that runs.

    So it now measures both halves: the write-through exists, *and* startup
    hands the singleton a factory through a registered component.
    """
    body = _code("monetization/revenue_split.py")
    if not body:
        return UNVERIFIED, "monetization/revenue_split.py not found"
    persisted = "session_factory" in body and "commit()" in body
    if not persisted:
        return _named(OPEN, "balances live in module dicts; a restart erases what creators are owed")

    startup = _code("core/startup_factories.py")
    if not startup:
        return UNVERIFIED, "core/startup_factories.py not found"
    entry = "init_revenue_engine" in body
    wired = "init_revenue_engine" in startup
    registered = '"revenue_ledger"' in startup
    if not (entry and wired and registered):
        return _named(
            PARTIAL,
            "the creator ledger writes through a session factory, but nothing gives the "
            "module singleton one at startup — every write is a no-op in production",
        )
    return _named(
        FIXED,
        "creator ledger writes through a session factory, and startup wires the singleton "
        "to it through the registered revenue_ledger component",
    )


def _p_f222() -> tuple[str, str]:
    t = _tracked("tests/**/*revenue_split*")
    return _named(FIXED if t else OPEN, f"{len(t)} test file(s): {', '.join(t[:3]) or 'none'}")


def _p_f175() -> tuple[str, str]:
    """Emoji as UI icons: measured by the ratchet, not by this probe's own regex.

    The first version of this probe counted emoji with a regex of its own and
    reported OPEN. That was true but useless — it restated the size of the debt
    every run and could only ever go green after a 154-file codemod, which is
    the owner's call, not a probe's.

    So it now measures the two things this repository can actually be held to:
    the debt is capped by a gate that has been proven able to fail, and the
    worst instance is gone. FIXED still means zero, and only zero.
    """
    ratchet = "scripts/frontend_emoji_ratchet.py"
    baseline = "docs/FRONTEND_EMOJI_DEBT.json"
    wired = "frontend-emoji-ratchet" in _read(".pre-commit-config.yaml")
    evidenced = "frontend-emoji-ratchet" in _read("docs/GATE_EVIDENCE.toml")

    if not (_exists(ratchet) and _exists(baseline) and wired and evidenced):
        return OPEN, (
            "no ratchet: emoji can be added to frontend/src without anything noticing "
            f"(script {_exists(ratchet)}, baseline {_exists(baseline)}, "
            f"pre-commit {wired}, evidence {evidenced})"
        )

    try:
        recorded = json.loads(_read(baseline)).get("files", {})
    except ValueError:
        return UNVERIFIED, f"{baseline} is not readable JSON"

    total = sum(recorded.values())
    palette = "frontend/src/components/CommandPalette.tsx"
    palette_clean = palette not in recorded
    derives = "buildNavCommands" in _code(palette) and "buildStaticCommands" not in _code(palette)

    if not total:
        return FIXED, "no emoji remain in frontend/src"
    if not (palette_clean and derives):
        return OPEN, (
            f"{total} emoji across {len(recorded)} files, and CommandPalette still carries its own navigation list"
        )
    return PARTIAL, (
        f"{total} emoji across {len(recorded)} files remain, capped: the ratchet is "
        "wired into pre-commit and proven able to fail, so the number can only go "
        "down. CommandPalette's 60 are gone — its hand-written nav list, which had "
        "drifted from NAV_ITEMS (Dashboard to /home, 2FA Setup to a route that does "
        "not exist, eleven sidebar pages never added), is now derived from NAV_ITEMS "
        "with its Lucide icons. Converting the remaining 154 files is a codemod and "
        "an owner decision"
    )


def _derivation_probe() -> tuple[bool, str]:
    """Run the catch-all's ownership rule against a throwaway app.

    Executed rather than grepped. A probe that greps for `_registered_paths`
    measures how the module is written; this one builds three routes and asks
    the derivation what it concludes, so it fails if the walk stops descending
    into an included router — the exact way the previous
    `_claimed_by_a_real_route` check was dead while reading as correct.
    """
    try:
        from fastapi import APIRouter, FastAPI

        from core.page_routes import server_namespaces
    except Exception as exc:  # pragma: no cover - reported, never swallowed
        return False, f"could not import the derivation: {exc}"

    app = FastAPI()
    router = APIRouter(prefix="/probe-namespace")

    @router.get("/thing")
    async def _thing() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    namespaces = server_namespaces(app)

    if "/probe-namespace" not in namespaces:
        return False, "the route walk cannot see a route inside an included router"
    if "/probe-namespace/thing" in namespaces:
        # The asymmetry that IS F198: a registered leaf makes the paths BELOW
        # its parent the server's, and never the leaf itself.
        return False, "a registered leaf was treated as a namespace of its own"
    return True, "derived from the route table"


def _p_f198() -> tuple[str, str]:
    """`/kyc` and `/mobile` returned raw JSON 404 on direct navigation."""
    page = _code("core/page_routes.py")
    if not page:
        # Fail closed. `hand_list_gone` below is a NOT-in test, and an empty
        # read satisfies it — a probe that read nothing would otherwise report
        # the list gone because it never looked (F255/F257).
        return UNVERIFIED, "core/page_routes.py not found"
    proven = _exists("tests/unit/test_every_spa_route_serves_the_app.py") and _exists(
        "tests/unit/test_the_catchall_derives_api_ownership.py"
    )
    hand_list_gone = "_passthrough_prefixes" not in page
    derived, why = _derivation_probe()
    if not (proven and derived):
        return OPEN, f"the catch-all does not derive path ownership from the route table ({why})"
    if not hand_list_gone:
        return OPEN, "the hand-maintained prefix list is still what the catch-all consults"
    return PARTIAL, (
        "the SHAPE is fixed: the catch-all reads the route table instead of a "
        "hand-maintained prefix list — a path is the server's when something is "
        "registered at it, at it + '/', or strictly below it, and the React router's "
        "when nothing is, under a stated floor of /api/ and /ws/ so a router that fails "
        "to register cannot become an HTML 200 on every API path. /kyc serves the SPA "
        "because nothing claims it, and /kyc/webhooks/sumsub still reaches its handler "
        "because something does; a router added at a brand-new prefix needs no edit "
        "here in either direction. What REMAINS is /mobile, and it is a product "
        "decision rather than a wiring one: App.tsx declares the page AND "
        "router_registry mounts the mobile API sub-application at the same path, so "
        "serving the SPA there would shadow a live API. Resolving it means renaming the "
        "page or moving the mount to /api/mobile — pinned by a test so the exemption "
        "cannot quietly become permanent"
    )


def _p_f199() -> tuple[str, str]:
    """Every declared SPA route must serve the app on a direct GET.

    The original probe compared the hand-maintained `_SPA_ROUTES` list (60) to
    App.tsx (88) and called the gap the defect. It is not: an unlisted path
    still reaches the `/{full_path:path}` catch-all and still gets index.html,
    so the list is an optimisation. What matters is whether anything CLAIMS a
    page path ahead of it — which is what F198 actually was.
    """
    page = _code("core/page_routes.py")
    if not page:
        return UNVERIFIED, "core/page_routes.py not found"
    proven = _exists("tests/unit/test_every_spa_route_serves_the_app.py")
    # The bare-name entries in _passthrough_prefixes used to 404 a page path
    # purely on a string match, with no route behind it. The list is gone; what
    # is measured now is that the replacement can see a route at all, executed
    # rather than grepped.
    asks_the_route_table, _why = _derivation_probe()
    if proven and asks_the_route_table:
        return FIXED, (
            "the catch-all passes a bare page path through only when a route or mount "
            "really claims it, instead of guessing from a prefix string; and every path "
            "App.tsx declares is fetched directly in a test built on the real router "
            "registry, so a future router mounted at a bare prefix fails immediately"
        )
    return OPEN, f"direct_get_test={proven} route_table_check={asks_the_route_table}"


def _p_f200() -> tuple[str, str]:
    """The docs page must be able to load its own assets where it is mounted.

    The original probe looked for a vendored swagger-ui-dist. That presumed the
    fix; the requirement is that the page can load, and vendoring is one way to
    get there — the wrong one here, since `static/` is gitignored and /docs does
    not exist in production at all.
    """
    body = _code("core/middleware.py")
    if not body:
        return UNVERIFIED, "core/middleware.py not found"

    vendored = bool(_glob("static/swagger*") or _glob("**/swagger-ui-dist"))
    if vendored:
        return FIXED, "swagger assets are served from this origin"

    # Allowed only outside production, which is exactly where docs_url is set.
    conditional = "docs_cdn" in body and '"" if _is_production()' in body
    prod_locked = re.search(r'script_src = "\'self\'" if _is_production\(\)', body) is not None
    proven = _exists("tests/unit/test_docs_page_can_load_its_own_assets.py")

    if conditional and prod_locked and proven:
        return FIXED, (
            "the CSP admits the Swagger CDN exactly where /docs is mounted — everywhere "
            "except production, whose script-src stays 'self' and is guarded by its own "
            "test. The coupling is the invariant: a CDN allowed in production, or a docs "
            "page that still cannot load, both fail"
        )
    return OPEN, (
        f"vendored={vendored} conditional_cdn={conditional} production_locked={prod_locked} "
        f"test={proven} — /docs loads swagger-ui from a CDN the CSP refuses, so the page "
        "renders blank and only the browser console says why"
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
    # Through the module's own reader, not Path.read_text.
    #
    # Reading the file directly made this probe the one thing in the register
    # that `test_no_probe_reports_fixed_when_it_scanned_nothing` could not
    # starve: with every reader stubbed out it still opened the real manifest,
    # found eleven matching artifacts and reported FIXED — a clean answer from
    # a scan that, by the test's construction, had matched nothing. That is the
    # shape the test exists to catch, and it was catching it: this assertion has
    # been red since before 2026-09-14.
    raw = _read("ml/saved_models/model_checksums.json")
    if not raw.strip():
        return UNVERIFIED, "model_checksums.json is absent or unreadable — nothing was measured"
    try:
        stored = json.loads(raw)
    except Exception as exc:
        return OPEN, f"manifest unparseable: {exc}"
    if not stored:
        return UNVERIFIED, "model_checksums.json lists no artifact — nothing to verify"

    mismatch, absent = [], []
    for name, want in sorted(stored.items()):
        f = d / name
        if not f.exists():
            absent.append(name)
        elif hashlib.sha256(f.read_bytes()).hexdigest() != want:
            mismatch.append(name)

    if not mismatch and not absent:
        return FIXED, f"all {len(stored)} listed artifacts match their recorded sha256"

    # A MISMATCH and a LISTED-BUT-ABSENT entry are not the same severity, and
    # reporting them together hid that. A mismatch means a SHIPPED artifact does
    # not load in production — `_verify_checksum` is fail-closed there. An entry
    # for a file that is not shipped refuses nothing and blocks nothing; it is a
    # stale line, not a broken load.
    if mismatch:
        return OPEN, (
            f"{len(mismatch)} of {len(stored)} artifacts fail their recorded sha256 "
            f"({', '.join(mismatch)}). ml/__init__.py::_verify_checksum reads this file on "
            "every load and refuses in production, so each mismatch is a refused load"
        )
    return PARTIAL, (
        f"all {len(stored) - len(absent)} shipped artifacts match their recorded sha256 — the "
        f"refused loads are fixed. {len(absent)} entr(y/ies) describe a file that is not "
        f"committed ({', '.join(absent)}): inert, since _verify_checksum only reads files "
        "that exist, but the manifest should describe what ships"
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


_F146_ADR = "docs/decisions/0019-drift-blocking-model-quality-blocking-and-the-z-threshold.md"

# The surfaces that deploy this system. The code default is the fifth, and the
# finding is that it disagrees with all four of these.
_F146_SURFACES = (
    "helm/hopefx/values.yaml",
    "k8s/k8s-configmap.yaml",
    "deployments/k8s/configmap.yaml",
    ".env.example",
)


def _yaml_key(rel: str, key: str) -> str | None:
    """Read a scalar key, ignoring any mention of it inside a comment.

    `_code()` only strips prose for `.py`, and these files discuss their own
    flags at length — `deployments/k8s/configmap.yaml` carries the sentence
    "and DRIFT_BLOCK defaults to FALSE" in a comment explaining why the key is
    stated explicitly. A probe that greps raw text reads that as the setting and
    reports the opposite of the truth.
    """
    text = _read(rel)
    if not text:
        return None
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    # `.env.example` is KEY=value; the manifests are `KEY: "value"`.
    match = re.search(rf'(?m)^\s*{re.escape(key)}\s*[:=]\s*["\']?([A-Za-z0-9_.]+)', body)
    return match.group(1).lower() if match else None


def _p_f146() -> tuple[str, str]:
    """Drift blocking: one default, two riders, and the ADR that decides them.

    The previous probe asked a single question — does `DRIFT_BLOCK` default to
    true? — so FIXED was reachable by flipping one line. Measured 2026-09-13,
    that flip would have stopped inference outright: 12 of the 14 features over
    the z threshold had a live value of exactly 0.0, because a feature the
    pipeline cannot supply is zero-filled before the guard sees it. The guard
    was therefore measuring imputation far more than drift, and blocking on it
    turns a feed outage into a total halt reported as `feature_drift`. A probe
    that green-lights that flip is recommending it. See ADR 0019 and
    `scripts/drift_guard_report.py`.

    So this measures what the decision actually spans — the code default, its
    two riders, and whether the deployment surfaces agree — and takes its
    verdict from ADR 0019's status line. While the ADR is `proposed` the finding
    is OWNER, which is honest: nobody has decided. Once it is `accepted` the
    probe enforces the decision, so a choice made cannot quietly drift back.
    """
    body = _code("ml/inference_engine.py")
    if "_DRIFT_BLOCK" not in body:
        return OPEN, "no block path exists — drift is computed and gates nothing"

    def _default(name: str) -> bool:
        return re.search(rf'{name}",\s*"(true|1|yes)"', body) is not None

    drift_on = _default("DRIFT_BLOCK")
    quality_on = _default("MODEL_QUALITY_BLOCK")
    z_match = re.search(r'DRIFT_Z_THRESHOLD",\s*"([0-9.]+)"', body)
    code_z = z_match.group(1) if z_match else "?"

    # Which surfaces disagree with the code default, and how.
    surfaces = {rel: _yaml_key(rel, "DRIFT_BLOCK") for rel in _F146_SURFACES}
    set_true = sorted(rel for rel, val in surfaces.items() if val in {"true", "1", "yes"})
    helm_z = _yaml_key("helm/hopefx/values.yaml", "DRIFT_Z_THRESHOLD")
    z_agree = helm_z is None or helm_z == code_z

    adr = _read(_F146_ADR)
    accepted = bool(re.search(r"(?m)^-\s*Status:\s*accepted\b", adr))

    if not accepted:
        detail = (
            f"the block path exists; code defaults DRIFT_BLOCK={str(drift_on).lower()}, "
            f"MODEL_QUALITY_BLOCK={str(quality_on).lower()}, DRIFT_Z_THRESHOLD={code_z}, "
            f"while {len(set_true)} of {len(_F146_SURFACES)} deployment surface(s) set "
            f"DRIFT_BLOCK=true"
        )
        if not z_agree:
            detail += f" and the deployed chart sets DRIFT_Z_THRESHOLD={helm_z}, not {code_z}"
        if not adr:
            return _named(OWNER, detail + ". No ADR records the decision")
        return _named(
            OWNER,
            detail + ". ADR 0019 is proposed, not accepted — the decision is the owner's and the "
            "measured z is dominated by zero-filled features "
            "(python scripts/drift_guard_report.py)",
        )

    # Accepted: the ADR's decision is now the requirement.
    missing = []
    if not drift_on:
        missing.append("DRIFT_BLOCK still defaults false")
    if not quality_on:
        missing.append("MODEL_QUALITY_BLOCK still defaults false (ADR 0019 rider 1)")
    if not z_agree:
        missing.append(f"chart DRIFT_Z_THRESHOLD={helm_z} disagrees with code {code_z} (rider 2)")
    if missing:
        return _named(OPEN, "ADR 0019 is accepted but " + "; ".join(missing))
    return _named(
        FIXED,
        f"ADR 0019 accepted and honoured: DRIFT_BLOCK and MODEL_QUALITY_BLOCK default on, "
        f"threshold {code_z} agrees across code and the deployed chart",
    )


_ADR_DIR = "docs/decisions"
# The seven fields the constitution's Chapter 9 requires of the pair. The first
# five are what `adr.py` enforces; the last two are the finding.
_LEDGER_SECTIONS = ("actual outcome", "lessons")


def _p_adr_ledger() -> tuple[str, str]:
    """The Decision Registry is built; is the Decision Ledger?

    GROUP4_CONSTITUTION Chapter 9 requires "an Architecture Decision Registry AND
    Decision Ledger recording context, alternatives, evidence, decision, expected
    outcome, actual outcome and lessons" — seven fields across two artefacts, and
    the chapter singles out the last three as the ones that matter: "a decision
    record that stops at 'decision' is a minute; one that returns to compare
    expectation against result is memory."

    Five of the seven are enforced by `scripts/adr.py::REQUIRED_SECTIONS`. The
    other two now live in `docs/decisions/outcomes/NNNN.md` — a second artefact,
    keyed by decision number and deliberately mutable, because an accepted record
    is immutable but for its status line and buying the ledger by relaxing that
    would have destroyed the registry to build the ledger (ADR 0020).

    **This probe counts `observed`, not files.** Eighteen `pending` placeholders
    would satisfy every structural rule and record nothing, which is the shape
    F176 had: a measurement that could not fail. So a ledger whose entries are
    mostly pending reads as PARTIAL here, and one with no gate behind it reads as
    OPEN — regardless of how many files exist.

    Measured rather than asserted, because "we have ADRs now" is exactly the
    answer that closed this prematurely once: the constitution read "there is no
    ADR directory" while nineteen records sat in one.
    """
    records = (
        sorted(p for p in (ROOT / _ADR_DIR).glob("[0-9][0-9][0-9][0-9]-*.md")) if (ROOT / _ADR_DIR).exists() else []
    )
    if not records:
        return _named(OPEN, f"no decision records under {_ADR_DIR}/ — the registry half is absent too")

    gate = _read("scripts/adr.py")
    asked = [s for s in _LEDGER_SECTIONS if re.search(rf'"{s}"', gate, re.IGNORECASE)]

    outcome_dir = ROOT / _ADR_DIR / "outcomes"
    entries = sorted(outcome_dir.glob("[0-9][0-9][0-9][0-9].md")) if outcome_dir.exists() else []
    observed, pending, hollow = [], [], []
    for entry in entries:
        text = entry.read_text(encoding="utf-8", errors="replace")
        if not all(re.search(rf"(?mi)^#+\s*{s}\b", text) for s in _LEDGER_SECTIONS):
            hollow.append(entry.name)
        elif re.search(r"(?mi)^-\s*Status:\s*observed\b", text):
            observed.append(entry.name)
        else:
            pending.append(entry.name)

    # Which decisions are owed one: a `proposed` record has not happened yet.
    owed = [
        p.name
        for p in records
        if re.search(r"(?mi)^-\s*Status:\s*(accepted|superseded)", p.read_text(encoding="utf-8", errors="replace"))
    ]
    missing = len(owed) - (len(observed) + len(pending))

    if not asked:
        return _named(
            OPEN,
            f"{len(entries)} outcome record(s) exist but adr.py requires neither of the 2 ledger fields — "
            "an unenforced convention is one commit from being absent",
        )
    if missing > 0 or hollow:
        return _named(
            OPEN,
            f"{missing} of {len(owed)} accepted decision(s) carry no outcome"
            + (f" and {len(hollow)} outcome record(s) are missing a required section" if hollow else "")
            + " — the Decision Ledger is incomplete",
        )
    if len(observed) <= len(pending):
        return _named(
            PARTIAL,
            f"every accepted decision has an outcome record, but only {len(observed)} of "
            f"{len(entries)} is observed — a ledger of placeholders is the minute the registry already was",
        )
    return _named(
        FIXED,
        f"all {len(owed)} accepted decision(s) carry an outcome record — {len(observed)} observed, "
        f"{len(pending)} pending with a review date — and adr.py requires both ledger fields, "
        f"refusing an overdue review",
    )


def _p_f205() -> tuple[str, str]:
    """A log call with more placeholders than arguments cannot emit."""
    # Counted with `ast`, not a regex. The first version of this probe stopped
    # its argument list at the first `)`, so `float(applied)` ended the match and
    # a correct three-argument call read as one — it reported six defects that
    # were not there. Balanced parentheses are not a regular language.
    import ast

    _money = _tracked("monetization/*.py") + _tracked("payments/**/*.py")
    if (unscanned := _scanned(_money, "monetization/payments module")) is not None:
        return unscanned
    bad = []
    for rel in _money:
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
    """Truncating to the cent always takes the creator's side of the rounding.

    The pattern was anchored to the literal name `amount`, so
    `int(payment.amount * 100)` in `payments/payment_gateway.py` was invisible —
    the same truncation, spelled with a dot. Fixing only the two sites the probe
    could see would have turned this finding FIXED with a live truncation still
    in the payment path: a probe satisfied by vocabulary rather than by
    behaviour, which is the defect class F108, F106 and AI-GATE each turned out
    to be.

    It now matches any dotted or underscored name truncated to cents by `int()`,
    and is asserted NOT to match the two correct spellings already in the tree —
    `to_cents`'s `int(amount.quantize(...) * 100)` and stripe_live's
    `int((converted * 100).quantize(...))` — because a probe that flags the fix
    is worse than one that misses the defect.
    """
    # `api/*.py` was added 2026-09-13. The list was monetization/ and payments/
    # only, so `int(req.amount * 100)` in `api/payments.py`'s Stripe deposit —
    # the same truncation, in a router rather than a service — was never
    # scanned, and this finding read FIXED for months with a live undercharge in
    # the deposit path. A probe that looks in the wrong place is a probe
    # satisfied by vocabulary, which is precisely what the paragraph above says
    # it must not be.
    _money = (
        _tracked("monetization/*.py") + _tracked("payments/**/*.py") + _tracked("payments/*.py") + _tracked("api/*.py")
    )
    if (unscanned := _scanned(_money, "monetization/payments/api module")) is not None:
        return unscanned
    bad = _grep(
        r"int\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*\*\s*100\s*\)",
        *_money,
    )
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
    # Both halves, for the reason F208 records: a write-through nothing wires
    # is a write-through that never runs, and `"session_factory" in body` alone
    # cannot tell the two apart.
    startup = _code("core/startup_factories.py")
    persisted = (
        ("session_factory" in body or "session.commit" in body)
        and "def init_affiliate_manager" in body
        and "init_affiliate_manager" in startup
        and '"affiliate_ledger"' in startup
    )
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
        return FIXED, (
            "affiliate commissions are conserved, serialised and persisted — the ledger "
            "writes through to affiliates/affiliate_referrals/affiliate_payouts, and "
            "startup wires the singleton through the registered affiliate_ledger component"
        )
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


#: A production reference to the *fiat* wallet — see `_p_wallet_dead` for the
#: three near-misses the boundaries exist to exclude.
_WALLET_CONSUMER = re.compile(
    r"(?<![A-Za-z0-9_])(?<!Crypto)WalletManager\b"
    r"|(?<![A-Za-z0-9_.])wallet_manager\b"
    r"|payments\.wallet\.wallet_manager\b"
)


def _production_python() -> list[str]:
    """Tracked .py files that are neither tests nor tooling."""
    return [
        f
        for f in _tracked("*.py")
        if not f.startswith(("tests/", "scripts/", "alembic/"))
        and "/tests/" not in f
        and not f.rsplit("/", 1)[-1].startswith("test_")
    ]


def _WALLET_CONSUMER_FILES() -> list[str]:
    """Production files that use the fiat wallet — shared by two probes."""
    plumbing = {
        "payments/wallet.py",
        "payments/__init__.py",
        "core/startup_factories.py",
        "core/app_state.py",
    }
    return [rel for rel in _production_python() if rel not in plumbing and _WALLET_CONSUMER.search(_code(rel) or "")]


def _p_load_ambiguity() -> tuple[str, str]:
    """Can a caller tell a REFUSED model artifact from an absent one?"""
    body = _code("ml/__init__.py")
    if not body:
        return UNVERIFIED, "ml/__init__.py not found"
    if "_verify_checksum" not in body:
        return UNVERIFIED, "the integrity check moved — this probe no longer measures it"

    distinguishes = "def load_artifact" in body and '"refused"' in body
    # A distinction nothing consults is not a distinction. The registry path is
    # the caller that could not afford the ambiguity.
    consumed = body.count("load_artifact") >= 3 and 'loaded.status == "refused"' in body
    if distinguishes and consumed:
        return _named(
            FIXED,
            "load_artifact reports absent / refused / unreadable separately, and the "
            "registry path reports a refused ACTIVE model at CRITICAL instead of returning "
            "the same value as an unconfigured registry",
        )
    return _named(
        OPEN,
        f"distinguishes={distinguishes} consumed={consumed} — a refused artifact is "
        "indistinguishable from one that was never installed, so an integrity refusal on the "
        "active model falls through the chain and loads a different model silently",
    )


def _p_gate_unmeasured() -> tuple[str, str]:
    """Does the coverage gate tell 'no number' apart from 'below the floor'?"""
    body = _code("scripts/pre_commit_coverage.py")
    if not body:
        return UNVERIFIED, "scripts/pre_commit_coverage.py not found"
    knows = "unmeasured" in body and "unmeasured_reason" in body
    reports = "could not be measured" in body and "TIMED OUT" in body
    wired = "unmeasured_reason=output" in body
    if knows and reports and wired:
        return _named(
            FIXED,
            "a module the gate could not measure is counted and reported apart from one "
            "below the floor, and a timeout says so rather than blaming a missing import",
        )
    return _named(
        OPEN,
        f"knows={knows} reports={reports} wired={wired} — an unmeasured module is reported "
        "as 'below 80% threshold', which is a measurement the gate never took",
    )


def _p_api_trading_role() -> tuple[str, str]:
    """Can an operator see whether this API process is trading?"""
    health = _code("core/health.py")
    if not health:
        return UNVERIFIED, "core/health.py not found"
    if "_probe_components" not in health:
        return UNVERIFIED, "the health probe moved — this no longer measures it"

    # The decisive LINE, not the token. Checking `'"engine"' in health` passed
    # against a tree where the engine was hard-wired to None — the third time
    # today a probe of mine measured vocabulary instead of behaviour.
    reports = 'getattr(app_state, "engine", None)' in health and '"healthy" if running else "stopped"' in health
    # Reported but NOT folded into the overall verdict: an API-only deployment
    # has no engine by design, and a permanently degraded field is ignored.
    # Parsed rather than matched: the list grew "schema" on 2026-09-25 (a
    # verified schema is part of the verdict), and an exact-string match read
    # that as the engine having been made critical.
    _critical = re.search(r"^\s*critical = (\[[^\]]*\])", health, re.MULTILINE)
    try:
        _critical_names = ast.literal_eval(_critical.group(1)) if _critical else None
    except (ValueError, SyntaxError):
        _critical_names = None
    not_critical = bool(_critical_names) and "database" in _critical_names and "engine" not in _critical_names
    documented = "ENGINE_AUTOSTART" in (_read("CLAUDE.md") or "")

    if reports and not_critical and documented:
        return _named(
            FIXED,
            "/health reports the engine as unavailable/stopped/healthy without folding it "
            "into the overall verdict, and ENGINE_AUTOSTART — the API-only switch — is "
            "documented",
        )
    return _named(
        OPEN,
        f"reports={reports} not_critical={not_critical} documented={documented} — /health "
        "answers identically whether or not this process is running a trading engine",
    )


def _p_mode_resolver() -> tuple[str, str]:
    """Do the displayed plan and the dispatch read ONE resolution?"""
    runner = _code("run.py")
    if not runner:
        return UNVERIFIED, "run.py not found"
    resolver = _code("core/run_mode.py")
    if not resolver:
        return _named(
            OPEN,
            "run.py derives the engine twice on different conditions — the printed pipeline and "
            "the dispatch disagree on the DEFAULT invocation (--mode paper --broker oanda)",
        )

    # Counted, not merely present: a resolver nothing calls resolves nothing.
    # The ROUTER-OVERRULE probe read FIXED against a neutered call site for
    # exactly this reason.
    wired = runner.count("resolve_run_mode") >= 2
    # The old second derivation must be gone from the dispatch.
    second_derivation = 'args.broker == "paper"' in runner
    # And the resolver must not PIN TRADING_MODE for api/backtest. The first
    # version published it unconditionally, so `--mode api` rewrote a deliberate
    # TRADING_MODE=live to paper — behaviour the pre-resolver run.py preserved
    # on purpose, with a comment saying why. Shipped in 20acc2a5 and caught the
    # next day while grounding M04.
    # The api/backtest BRANCH, not the flag's name: flipping the branch to True
    # restores the regression while leaving the identifier in place.
    preserves_trading_mode = "pins_trading_mode = False" in resolver
    publishes_broker_type = "BROKER_TYPE" in resolver
    publishes_venue = "OANDA_ENVIRONMENT" in resolver

    if wired and not second_derivation and publishes_broker_type and publishes_venue and preserves_trading_mode:
        return _named(
            FIXED,
            "run.py resolves the mode once (core/run_mode.py) and both the printed plan and the "
            "dispatch read it; BROKER_TYPE and OANDA_ENVIRONMENT are published from that one "
            "decision",
        )
    return _named(
        OPEN,
        f"wired={wired} second_derivation={second_derivation} "
        f"broker_type={publishes_broker_type} venue={publishes_venue} "
        f"preserves_trading_mode={preserves_trading_mode}",
    )


def _p_router_overrule() -> tuple[str, str]:
    """Does the engine's fallback overrule a router policy denial?

    `hopefx_engine._execute_decision` falls back to a direct `broker.place_order`
    when ExecutionEngine is unavailable. It consulted SmartRouter and then placed
    the order regardless of the answer.
    """
    body = _code("hopefx_engine.py")
    if not body:
        return UNVERIFIED, "hopefx_engine.py not found"
    if "route_and_execute" not in body:
        return UNVERIFIED, "the engine no longer routes — this probe no longer measures it"

    # Counted, not merely present. The first version of this probe asked
    # whether `_router_refusal_is_terminal` APPEARED in the file — which it
    # still does when the branch that calls it is neutered to `elif False:`,
    # because the definition remains. Injection-tested and it read FIXED
    # against a tree with the defect fully restored. That is F208's weak shape
    # reproduced inside the register itself: evidence that resolves is not
    # evidence that runs. It now requires a definition AND at least one call.
    classified = body.count("_router_refusal_is_terminal") >= 2
    allow_list = "_ROUTER_TRANSPORT_GAPS" in body
    # The exception path must refuse too: a router that raised may have
    # transmitted the order, so falling through to place another is the
    # duplicate fill ROUTER-TO exists to prevent.
    unknown_refused = "outcome UNKNOWN, no order placed" in body
    if classified and allow_list and unknown_refused:
        return _named(
            FIXED,
            "a router policy denial is terminal on the fallback path; only an allow-listed "
            "transport gap may still place directly",
        )
    return _named(
        OPEN,
        f"classified={classified} allow_list={allow_list} unknown_refused={unknown_refused} — "
        "the fallback treats a router refusal as a reason to call broker.place_order "
        "directly — an authorization block, a spread guard, a news or macro blackout and the "
        "FIA throttle are all overruled",
    )


def _p_wallet_dead() -> tuple[str, str]:
    """Does anything in production actually use the wallet ledger?

    `WalletManager` is the only production writer of `wallet_transactions`.
    Measured by asking which production modules reference it at all, rather than
    by reading the module and finding it correct — which it is.
    """
    files = _production_python()
    guard = _scanned(files, "production Python file")
    if guard:
        return guard

    # Where the singleton is *defined*, *exported*, *constructed at startup* or
    # declared as an empty app_state slot. A reference from one of these is not
    # a consumer.
    plumbing = {
        "payments/wallet.py",
        "payments/__init__.py",
        "core/startup_factories.py",
        "core/app_state.py",
    }
    consumers = []
    control = 0
    for rel in files:
        body = _code(rel)
        if not body:
            continue
        # Positive control: a singleton that genuinely has consumers. If this
        # stays at zero the scan is broken and the answer means nothing.
        if "revenue_engine" in body and rel != "monetization/revenue_split.py":
            control += 1
        if rel in plumbing:
            continue
        # Three near-misses this has to exclude, each of which reported the
        # finding FIXED against a file that has nothing to do with the fiat
        # wallet: `CryptoWalletManager` (substring), `crypto_wallet_manager`
        # (substring), and `from .wallet_manager import ...` in the crypto
        # package (a module path, not this singleton). A dotted path is only a
        # reference to this singleton when it is spelled out in full.
        if re.search(_WALLET_CONSUMER, body):
            consumers.append(rel)

    if control == 0:
        return UNVERIFIED, (
            "the control singleton was not found in any production file — the scan is broken, not the code"
        )
    if consumers:
        return _named(
            FIXED,
            f"the wallet ledger has {len(consumers)} production consumer(s): {', '.join(consumers[:3])}",
        )

    # No consumer. Which way that gets fixed is a product decision, not a
    # refactor — the same shape as F146, so the same mechanism: OWNER while
    # nothing records the decision, enforced once an ADR accepts one. Reporting
    # OPEN here would imply engineering may pick, and the two options (make the
    # wallet the withdrawal ledger, or retire it and repoint AML) are not
    # interchangeable.
    decided = any(
        re.search(r"(?m)^-\s*Status:\s*accepted\b", _read(rel)) and re.search(r"(?i)wallet", _read(rel))
        for rel in _tracked("docs/decisions/*.md")
    )
    detail = (
        "no production module uses WalletManager, so nothing writes wallet_transactions: "
        "the AML daily-withdrawal rules and the health-check aggregation both read a table "
        "that is permanently empty"
    )
    if not decided:
        return _named(
            OWNER,
            detail + ". No accepted ADR says whether the fiat wallet is the ledger the "
            "withdrawal path writes through or is retired — that is the owner's call",
        )
    return _named(OPEN, detail + ". An ADR has decided; the code has not followed it yet")


def _p_aml_unreached() -> tuple[str, str]:
    """Is the AML gate reachable from the endpoint that withdraws money?

    `check_withdrawal` is correct — both the single cap and the daily rules were
    reproduced firing against a populated ledger. The defect is that its only
    call site sits inside `WalletManager`, which nothing calls, and the live
    `/payments/withdraw` endpoint never consults it.
    """
    files = _production_python()
    guard = _scanned(files, "production Python file")
    if guard:
        return guard

    callers = [rel for rel in files if rel != "compliance/aml.py" and "check_withdrawal" in (_code(rel) or "")]
    if not callers:
        return _named(
            OPEN,
            "nothing in production calls check_withdrawal — the AML gate is wired at startup and never consulted",
        )

    endpoint = _code("api/payments.py")
    if not endpoint:
        return UNVERIFIED, "api/payments.py not found"
    withdraw_screened = "check_withdrawal" in endpoint

    unreachable_only = callers == ["payments/wallet.py"]
    if unreachable_only and not withdraw_screened:
        return _named(
            OPEN,
            "check_withdrawal is called only from payments/wallet.py, which has no production "
            "consumer, and /payments/withdraw does not consult the gate — every AML rule, the "
            "single-transaction cap included, is unreachable in production",
        )
    if not withdraw_screened:
        return _named(
            PARTIAL,
            f"check_withdrawal is called from {', '.join(callers[:3])}, but /payments/withdraw "
            "does not consult the gate",
        )
    # Consulted is not the same as effective. Two of the gate's four rules —
    # the daily withdrawal count and the daily volume — read
    # `wallet_transactions`, and nothing in production writes that table while
    # WALLET-DEAD stands. Reporting FIXED here would claim a daily limit that
    # cannot fire, which is the exact shape this register exists to refuse.
    ledger_written = bool(_WALLET_CONSUMER_FILES())
    if not ledger_written:
        return _named(
            PARTIAL,
            f"the withdrawal path consults the AML gate ({', '.join(callers[:3])}), so the "
            "single-transaction cap and sanctions/PEP screening now fire. The daily count and "
            "volume rules still cannot: they read wallet_transactions, which nothing writes "
            "while WALLET-DEAD stands",
        )
    return _named(
        FIXED,
        f"the withdrawal path consults the AML gate ({', '.join(callers[:3])}) and the ledger "
        "it counts against is written",
    )


def _p_aff_cents() -> tuple[str, str]:
    """A commission an affiliate is owed must be an amount that can be paid."""
    body = _code("monetization/affiliate.py")
    if not body:
        return UNVERIFIED, "monetization/affiliate.py not found"
    if "subscription_amount * commission_rate" not in body:
        return UNVERIFIED, "the commission calculation moved — this probe no longer measures it"
    quantized = "ROUND_HALF_UP" in body and ".quantize(" in body
    return _named(
        FIXED if quantized else OPEN,
        "commissions are quantized to cents with ROUND_HALF_UP where they become authoritative"
        if quantized
        else "the raw Decimal product is stored, so a commission carries a fraction of a cent "
        "that no transfer can move and no withdrawal can ever clear",
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
    py = _tracked("**/*.py")
    if (unscanned := _scanned(py, "python source file")) is not None:
        return unscanned
    classes = _grep(r"^class SecureVault\b", *py)
    others = [c for c in classes if not c.startswith("config/vault.py")]
    live = [c for c in classes if c.startswith("config/vault.py")]
    if not live:
        # `len(classes) <= 1` reported FIXED "one SecureVault, in config/vault.py"
        # on ZERO matches, so a renamed or deleted live vault read as the fix.
        return OPEN, "no SecureVault in config/vault.py — the live credential store is gone or renamed"
    if len(classes) == 1:
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
    _tests = _tracked("tests/**/*.py")
    if (unscanned := _scanned(_tests, "test file")) is not None:
        return unscanned
    files = [f for f in _tests if re.search(r"(coverage_boost|coverage\d|_coverage)\.py$", f)]
    return _named(
        OPEN if files else FIXED,
        f"{len(files)} test file(s) named after the metric rather than the behaviour "
        "(was 75) — these hold the highest concentration of assertion-free tests"
        if files
        else "no test file is named after the coverage metric",
    )


#: What counts as asserting. `\bassert\b` alone does not match `self.assertEqual`
#: — there is no word boundary inside `assertEqual` — so every unittest.TestCase
#: file in the suite read as empty. That is how this probe reported
#: test_backtest.py (18 assertions across 9 tests) and test_risk_calculations.py
#: (6 across 6) as asserting nothing, both of which pass when run. A probe that
#: measures the wrong mechanism produces a confident wrong answer, which is the
#: same defect it was written to find.
_ASSERTS_RE = re.compile(
    r"\bassert\b"  # bare pytest assert
    r"|\bself\.assert\w+\("  # unittest: assertEqual, assertRaises, assertIn, ...
    r"|\bself\.fail\("  # unittest: explicit failure
    r"|\bpytest\.raises\b"  # context-manager assertion
    r"|\bpytest\.fail\b"
)


def _p_f108() -> tuple[str, str]:
    """A test file with no assertion asserts nothing, whatever it is named."""
    empty = []
    checked = 0
    for f in _tracked("tests/unit/*.py"):
        if f.endswith("conftest.py"):
            continue  # fixtures, not tests — nothing to assert
        body = _code(f)
        if "def test" not in body:
            continue
        checked += 1
        if not _ASSERTS_RE.search(body):
            empty.append(f)
    if not checked:
        # A scan that matched nothing agrees with the conclusion below (F255).
        return UNVERIFIED, "no unit-test file matched — the scan is broken, not the suite"
    return _named(
        OPEN if empty else FIXED,
        f"{len(empty)} of {checked} test file(s) define tests and assert nothing: {', '.join(empty[:3])}"
        if empty
        else f"all {checked} unit-test files that define a test also assert",
    )


def _p_f106() -> tuple[str, str]:
    """Nothing exercises TradeExecutor against a connector that can refuse.

    Measured by content, not by filename. The first version matched any test
    path containing "executor" and a connector word, which a file could satisfy
    while passing `MagicMock()` throughout — the exact thing the finding is
    about. What closes F106 is `create_autospec`, because only a specced double
    rejects what the real class would.
    """
    # Both conditions must hold in CODE, not prose: the file must import from
    # `brokers` and must autospec. A first version matched the word "connector"
    # anywhere and credited a file that autospecs an unrelated class — a probe
    # satisfied by vocabulary is the same defect as a test satisfied by a mock.
    joined = []
    for f in _tracked("tests/**/*.py"):
        body = _code(f)
        if "create_autospec" not in body:
            continue
        if re.search(r"^\s*(from|import)\s+brokers\b", body, re.M):
            joined.append(f)
    if not joined:
        return OPEN, (
            "TradeExecutor is tested against MagicMock brokers only. A mock with no spec "
            "agrees with every call, so nothing in the suite can tell a real connector "
            "surface from an invented one"
        )
    return FIXED, (
        f"exercised against autospec'd connectors by {joined[0]}. Note the finding's premise "
        "was wrong: BrokerConnector.place_market_order is a concrete base method every "
        "connector inherits, so the signature mismatch F61 describes does not exist"
    )


def _p_f119() -> tuple[str, str]:
    """Annualisation must use the bar frequency, not the sample length."""
    files = _tracked("backtesting/*.py") + _tracked("risk/*.py") + _tracked("analytics/*.py")
    if (unscanned := _scanned(files, "backtesting/risk/analytics module")) is not None:
        return unscanned
    bad = _grep(r"252\s*/\s*len\(", *files)
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
    _fe = [f for f in _tracked("frontend/src/**") if f.endswith((".tsx", ".ts"))]
    if (unscanned := _scanned(_fe, "frontend source file")) is not None:
        return unscanned
    bad = [
        h
        for h in _grep(r"Math\.random\(\)", *_fe)
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
    _fe = [f for f in _tracked("frontend/src/**") if f.endswith((".tsx", ".ts"))]
    if (unscanned := _scanned(_fe, "frontend source file")) is not None:
        return unscanned
    bad = _grep(
        r"(api[_-]?key)\s*[:=]\s*[`'\"][^`'\"]*\$\{|btoa\([^)]*api[_-]?key",
        *_fe,
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
    if (unscanned := _scanned(paths, "route declaration in frontend/src/App.tsx")) is not None:
        return unscanned
    dupes = sorted({p for p in paths if paths.count(p) > 1})
    return _named(
        OPEN if dupes else FIXED,
        f"{len(dupes)} duplicated path(s): {dupes[:5]}"
        if dupes
        else f"{len(set(paths))} distinct paths, none declared twice",
    )


def _p_f201() -> tuple[str, str]:
    """Telling a subscriber 15 courses are available when all are placeholders."""
    _fe = [f for f in _tracked("frontend/src/**") if f.endswith((".tsx", ".ts"))]
    if (unscanned := _scanned(_fe, "frontend source file")) is not None:
        return unscanned
    bad = _grep(
        r"COMING SOON|available on your plan",
        *_fe,
        code_only=False,
    )
    return _named(
        OPEN if bad else FIXED,
        bad[0] if bad else "no page advertises unavailable content as available",
    )


def _p_f173() -> tuple[str, str]:
    """The dashboard must expose a heading outline.

    The original probe counted `<h[123]` in Dashboard.tsx and reported zero.
    It could not see the `<h1>` the shared `<PageHeader>` component renders, so
    it described a page with no outline at all when the real gap was narrower:
    one landmark and seven sections marked up as spans. Measured in the DOM by
    a vitest render now, not by grepping a file that delegates its header.
    """
    page = _code("frontend/src/pages/Dashboard.tsx")
    if not page:
        return UNVERIFIED, "Dashboard.tsx not found"
    sections_are_headings = page.count("<h2 style={s.cardTitle}>") >= 6
    proven = _exists("frontend/src/test/dashboard_heading_outline.test.tsx")
    return _named(
        FIXED if sections_are_headings and proven else OPEN,
        "the page renders one h1 (from PageHeader) and an h2 per section, asserted "
        "against the rendered DOM including that no level is skipped"
        if sections_are_headings and proven
        else f"section_titles_are_headings={sections_are_headings} dom_test={proven}",
    )


def _p_f187() -> tuple[str, str]:
    """Dashboard metrics must drill into the page that explains them.

    This probe counted `onClick` in Dashboard.tsx, found one, and reported that
    the metrics do not drill through. They do, and did before this audit
    touched them: `StatCard` renders a react-router `<Link>` when given `to`,
    and all eight tiles pass one. Counting the wrong mechanism produced a
    confident wrong answer on a P2 line.
    """
    page = _code("frontend/src/pages/Dashboard.tsx")
    if not page:
        return UNVERIFIED, "Dashboard.tsx not found"
    linked_tiles = len(re.findall(r"<StatCard[^>]*\bto=", page, re.S))
    accessible = "aria-label={`${label}: ${value}" in page
    sized = "min-h-[44px]" in page
    proven = _exists("frontend/src/test/dashboard_heading_outline.test.tsx")
    if linked_tiles >= 8 and accessible and sized and proven:
        return FIXED, (
            f"{linked_tiles} headline figures are links to the page that explains them, "
            "each with a 44px minimum target and an accessible name naming the figure, "
            "its value and its destination"
        )
    return OPEN, (f"linked_tiles={linked_tiles} accessible_name={accessible} target_44px={sized} dom_test={proven}")


def _p_f172() -> tuple[str, str]:
    """Icon-only buttons without an accessible name.

    This reported UNVERIFIED for a structural reason, not a slip: a JSX opening
    tag cannot be bracketed by ``<button\b([^>]*)>``, because an attribute may
    contain ``>`` — ``onClick={() => navigate('/x')}`` ends the match at the
    arrow, so everything after it reads as the button's children and "does this
    button contain text" is answered from the wrong span. One regex reported
    FIXED across 552 buttons; another reported 9 offending files. Neither had
    measured anything.

    `eslint-plugin-jsx-a11y`'s `control-has-associated-label` parses the JSX and
    answers it: 138 violations across 67 files. It is wired into
    `eslint.config.js` at `error`, downgraded to `warn` only for the files in
    `frontend/a11y-debt.json` — so a violation anywhere else fails
    ``npm run lint``, and the list may only shrink.

    This probe reads that committed measurement rather than re-running eslint,
    which needs node_modules and twelve seconds. `a11y_debt_is_accurate.test.ts`
    is what holds the file to the tree.

    The 138 were classified with the same parser on 2026-09-14, because "icon-only
    buttons" is not what they are: by tag, input 108, textarea 17, div 5, td 4,
    th 2, **button 1**, option 1. Sixteen more were controls carrying ``id="x"``
    beside a ``<label htmlFor="x">`` — correctly labelled at runtime, and
    unresolvable by this rule, which inspects one element's own props and
    children (``mayHaveAccessibleLabel.js``) and cannot follow a reference to a
    sibling. Clearing one of those means giving the label an ``id`` and the
    control an ``aria-labelledby``, never copying the text into an ``aria-label``
    that can then drift from what is on screen (WCAG 2.5.3). The remaining 121
    are controls with no accessible name at all, and are real.
    """
    debt = _read("frontend/a11y-debt.json")
    if not debt:
        return UNVERIFIED, (
            "not decidable by regex — a JSX attribute containing `>` breaks any attempt to "
            "bracket the opening tag. Wire eslint-plugin-jsx-a11y and this becomes a real "
            "measurement"
        )
    try:
        recorded = json.loads(debt)
    except ValueError:
        return UNVERIFIED, "frontend/a11y-debt.json is not readable JSON"

    files = recorded.get("files") or {}
    total = sum(files.values())
    config = _read("frontend/eslint.config.js")
    wired = "jsx-a11y/control-has-associated-label" in config and "a11y-debt.json" in config

    if not wired:
        return OPEN, "a11y-debt.json exists but eslint.config.js does not enforce the rule against it"
    if not total:
        return FIXED, "no control lacks an accessible name"
    return PARTIAL, (
        f"{total} violation(s) across {len(files)} file(s), measured by a parser rather than a "
        "regex and capped: the rule is an error everywhere except these files, so new debt "
        "fails `npm run lint`, and a11y_debt_is_accurate.test.ts refuses an entry that no "
        "longer describes anything. Fixing the rest is follow-up work"
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
    """An agent acting outside its scope must fail the build, not a review.

    Measured by CONTENT. The first version matched filenames — a path containing
    "approval" or "proposal" alongside "ai" — and reported OPEN while both
    acceptance tests had existed for some time in
    `test_agent_actions_are_enforced_not_prompted.py`, which is named after the
    behaviour instead. A probe satisfied by vocabulary answers a different
    question than the one it was asked, and here it answered "no" to a question
    whose answer was "yes".

    The third condition is the one worth keeping. A suite can drive
    `enforce_agent_action` through every branch and still not prove the tool
    layer asks it: the predicate could stay flawless while `ToolBus.invoke`
    stops honouring the answer, and those tests would all still pass. A gate
    nobody invokes refuses nothing — the first sub-shape in
    `hopefx-dead-controls`.

    Proven by injection rather than assumed. Replacing `invoke`'s
    `if result.blocking or not result.allowed:` with `if False:` leaves all
    thirteen predicate tests green and turns five in `test_ai_tool_bus.py` red,
    including `test_a_refusal_never_runs_the_tool` and
    `test_the_bus_refuses_even_in_monitor_mode`. So the bus condition below is
    genuinely covered — by a file that already existed. Nothing needed writing
    here; the probe needed fixing.
    """
    scope = approval = bus = None
    for f in _tracked("tests/**/*.py"):
        body = _code(f)
        if "enforce_agent_action" not in body and "ToolBus" not in body:
            continue
        refuses = "allowed is False" in body or "ToolDenied" in body
        if scope is None and "allowed_actions" in body and refuses:
            scope = f
        if approval is None and "approval_required" in body and refuses:
            approval = f
        if bus is None and "ToolBus" in body and "ToolDenied" in body:
            bus = f

    missing = [
        name for name, found in (("out-of-scope action", scope), ("execution-without-approval", approval)) if not found
    ]
    if missing:
        return OPEN, (
            f"acceptance tests absent: {', '.join(missing)}. `enforce_agent_action` and "
            "`ToolBus.invoke` exist and are called; what is missing is the pair of build-"
            "failing tests that keep them that way as the AI layer grows"
        )
    if bus is None:
        return PARTIAL, (
            f"both acceptance tests exist (scope: {scope}, approval: {approval}), but nothing "
            "drives them through ToolBus.invoke — the predicate is proven, the tool layer's "
            "call to it is not, so a bus that stopped honouring the gate would keep the suite green"
        )
    return FIXED, f"scope: {scope} · approval: {approval} · enforced through the bus: {bus}"


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
    """An affiliate clearing two tiers at once is granted only one.

    PARTIAL is the honest ceiling. Whether tiers should be skippable is a
    COMMERCIAL decision — it changes what the platform pays — and a probe must
    not close it by deciding for the owner. What is not a commercial decision,
    and is fixed: the shortfall used to be invisible. `check_level_upgrade`'s
    name and signature gave a caller no way to tell "the next step" from "the
    level they qualify for", so an affiliate earning 15% instead of the 25%
    their numbers cleared was under-paid by omission rather than by policy.
    """
    body = _code("monetization/affiliate.py")
    m = re.search(r"def check_level_upgrade.*?(?=\n    def )", body, re.S)
    if not m:
        return UNVERIFIED, "check_level_upgrade not found"

    # Returning inside the ascending loop grants the FIRST qualifying tier.
    grants_one_step = re.search(r"for level in .*?:\s*.*?return level", m.group(0), re.S) is not None
    legible = "def highest_qualifying_level" in body and "def tiers_behind" in body

    if not grants_one_step:
        return FIXED, "the highest qualifying tier is granted"
    if not legible:
        return OPEN, (
            "check_level_upgrade returns the first qualifying tier above the current one, so "
            "an affiliate whose numbers already clear a higher tier is granted the next one up "
            "and earns the lower commission rate until the following conversion"
        )
    return PARTIAL, (
        "still one tier per conversion — a commercial decision, not closed here. But the "
        "shortfall is now legible rather than silent: highest_qualifying_level() reports the "
        "tier the numbers earn and tiers_behind() reports the gap, so paying below it is a "
        "visible choice. Today's behaviour is pinned by a test that must be rewritten if the "
        "policy changes"
    )


def _p_of_voter() -> tuple[str, str]:
    """One of the three bias voters cannot vote, and the count must say so.

    PARTIAL is the honest ceiling here. Wiring the advanced voter to a real
    signal is a quantitative decision — choosing which of the analyzer's seven
    methods constitutes a bullish or bearish read is a modelling choice, and
    picking one to make the count come out right would be inventing a signal.
    What is fixable without that decision, and now is: the voter declines
    knowingly instead of raising AttributeError into a WARNING handler on every
    call, and `bias_with_quorum` / `get_summary` report how many of the three
    declared voters actually answered — so a majority of two can no longer read
    as a majority of three.
    """
    dash = _code("analysis/order_flow_dashboard.py")
    adv = _code("analysis/advanced_order_flow.py")
    if not dash or not adv:
        return UNVERIFIED, "order-flow dashboard or advanced analyzer not found"

    has_analyze = re.search(r"^\s{4}def analyze\(", adv, re.M) is not None
    blind_call = re.search(r"self\._adv\.analyze\(", dash) is not None
    quorum = "bias_with_quorum" in dash and "bias_voters" in dash

    if blind_call and not has_analyze:
        return OPEN, (
            "_bias_vote_advanced calls self._adv.analyze(), which AdvancedOrderFlowAnalyzer "
            "does not define — every call raises AttributeError into a WARNING handler and "
            "returns None, so the majority is decided by two voters wearing three hats"
        )
    if not quorum:
        return OPEN, "the bias is reported without the number of voters that produced it"
    if has_analyze:
        return FIXED, "the advanced analyzer exposes a directional read and all three voters can vote"
    return PARTIAL, (
        "the voter declines knowingly rather than raising on every call, and the bias now "
        "carries its quorum (bias_voters / bias_voters_total), so a two-of-three majority "
        "cannot read as three. The vote itself is still absent: wiring it means choosing "
        "which of the analyzer's seven methods is a directional read, which is a "
        "quantitative decision and not a wiring fix"
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

# ── Frontend correctness, found by driving the app rather than reading it ───


def _p_zero_balance_does_not_raise() -> tuple[str, str]:
    """Does a broker balance of ZERO still fall through to a mapping lookup?

    `getattr(account, name, 0) or account.get(name, 0)` conflates "missing" with
    "zero", because 0.0 is falsy. Measured from the source rather than asserted.
    """
    src = _read("api/billing.py")
    if not src:
        return UNVERIFIED, "api/billing.py could not be read here"
    if 'getattr(account, "balance", 0) or account.get(' in src:
        return OPEN, "the falsy-or is still there: a zero balance falls through to .get()"
    if "_account_field" not in src:
        return UNVERIFIED, "neither the old falsy-or nor the _account_field helper is present"
    return FIXED, "_account_field reads the attribute, then the mapping, without conflating zero"


def _p_balance_source_split() -> tuple[str, str]:
    """Does /billing/balance show the same number a withdrawal is checked against?

    Three outcomes, because "reports the disagreement" and "has no disagreement"
    are not the same state and must not read alike:

      FIXED    the shown balance is DERIVED from the wallet ledger
      PARTIAL  the split still exists but the response says so, and reports both
      OPEN     two numbers, one shown, nothing saying they differ

    The first version of this probe asked only whether `wallet_manager` appeared
    in the body. Reporting the ledger alongside the broker figure would have
    flipped it to FIXED while the sources still disagreed — a measurement that
    stops being able to fail, which is the shape (F176) this register exists to
    refuse.

    Read through `_read` so the starvation harness can empty it.
    """
    src = _read("api/billing.py")
    if not src:
        return UNVERIFIED, "api/billing.py could not be read here"

    marker = "async def get_balance"
    if marker not in src:
        return UNVERIFIED, "get_balance is not in api/billing.py on this tree"

    body = src[src.index(marker) : src.index(marker) + 6000]
    reads_broker = 'getattr(app_state, "broker"' in body or 'app_state, "broker"' in body
    reports_split = "ledger_balance" in body and "sources_agree" in body
    # The shown number comes from the ledger only if `balance` is assigned from it.
    derives_from_ledger = "balance = " in body and "wallet_manager.get_balance" in body.split("ledger_balance")[0]

    if derives_from_ledger:
        return FIXED, "the shown balance is derived from the wallet ledger"
    if reports_split:
        return (
            PARTIAL,
            "the response now reports the ledger alongside the shown balance and whether they "
            "agree, so the split is visible and measurable — but the shown number still comes "
            "from the broker or the subscription manager, not the ledger a withdrawal is "
            "refused against. Reconciliation is an owner decision, not a refactor",
        )
    if reads_broker:
        return (
            OPEN,
            "get_balance promises 'wallet balance' and reads the broker account; the "
            "ledger the withdrawal path debits is a different number, and nothing says so",
        )
    return UNVERIFIED, "get_balance neither reads the broker nor reports a ledger comparison"


def _p_suite_does_not_rewrite_models() -> tuple[str, str]:
    """Does the suite still overwrite a checksum-verified model artifact?

    Read through this module's own `_read`, so the starvation harness in
    `test_no_probe_reports_fixed_when_it_scanned_nothing` can empty it. The
    first version of this probe called `Path.read_text` directly, which the
    harness cannot reach, and it reported FIXED against a tree that had been
    emptied — the exact shape (F176) this register exists to refuse. The gate
    caught it.
    """
    conftest = _read("tests/conftest.py")
    writer = _read("tests/unit/test_coverage_boost_ml_misc.py")
    if not conftest or not writer:
        return UNVERIFIED, "tests/conftest.py or the writing test could not be read here"

    guard = "_refuse_to_rewrite_committed_models" in conftest
    redirected = 'setattr(twm, "MODEL_DIR"' in writer or "setattr(twm, 'MODEL_DIR'" in writer

    if guard and redirected:
        return FIXED, "the conftest guard is present and the oos_eval writer redirects MODEL_DIR"
    missing = []
    if not guard:
        missing.append("the conftest guard is gone")
    if not redirected:
        missing.append("test_oos_eval_returns_dict no longer redirects MODEL_DIR")
    return OPEN, "; ".join(missing)


def _p_meta_registry_agree() -> tuple[str, str]:
    """Do the meta file and the registry agree on when the model was trained?

    Measured from both records, not stated: they are the two places this repo
    keeps a training date, and nothing had ever compared them.
    """
    try:
        from datetime import datetime

        import ml.inference_engine as ie

        path = ie._saved("advanced_oos.pkl")
        if not path.exists():
            return UNVERIFIED, "the active artifact is not on disk here"
        provenance, why = ie._model_training_time(path)
        if provenance is None:
            return UNVERIFIED, f"no sha-bound provenance to compare against: {why}"
        meta = ie.InferenceEngine()._load_meta() or {}
        raw = meta.get("validated_at") or meta.get("trained_at")
        if not raw:
            return UNVERIFIED, "the meta file states no training date — nothing to compare"
        meta_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        gap_days = abs(meta_at - provenance) / 86_400.0
        if gap_days <= 1.0:
            return FIXED, f"the meta file and the registry agree to within {gap_days:.1f} day(s)"
        return OWNER, (f"the meta file and the registry disagree by {gap_days:.0f} days about the same bytes")
    except Exception as exc:
        return UNVERIFIED, f"could not compare the two records ({type(exc).__name__}: {exc})"


def _p_shipped_model_age() -> tuple[str, str]:
    """How old the committed model actually is, measured, not stated.

    This probe reports OWNER work while the shipped artifact is past
    MODEL_MAX_AGE_DAYS. It is deliberately not satisfiable by editing a document
    — only by retraining and registering a model, or by the owner deciding the
    limit should be different.
    """
    try:
        import time as _time

        import ml.inference_engine as ie

        path = ie._saved("advanced_oos.pkl")
        if not path.exists():
            return UNVERIFIED, "the active artifact is not on disk here"
        trained_at, why = ie._model_training_time(path)
        if trained_at is None:
            return OPEN, f"the shipped model has no usable provenance: {why}"
        age = (_time.time() - trained_at) / 86_400.0
        limit = ie._MODEL_MAX_AGE_DAYS
        if limit <= 0:
            return UNVERIFIED, "MODEL_MAX_AGE_DAYS is 0 here, so the gate is off — re-measure"
        if age > limit:
            return OWNER, f"the shipped model is {age:.0f} days old against a {limit:.0f}-day limit"
        return FIXED, f"the shipped model is {age:.0f} days old, within the {limit:.0f}-day limit"
    except Exception as exc:
        return UNVERIFIED, f"could not measure the shipped model's age ({type(exc).__name__}: {exc})"


def _p_chat_per_user() -> tuple[str, str]:
    """Chat conversations are keyed by the authenticated subject."""
    # `_code`, not `_read`: this module's own comments explain the singleton it
    # replaced, so a raw-text probe would find the defect quoted inside the note
    # describing its fix. That is F255, and this register has already shipped it
    # twice.
    body = _code("api/brain.py")
    if not body:
        return UNVERIFIED, "api/brain.py is not readable"
    if "_chat_agent: object | None = None" in body or "global _chat_agent" in body:
        return OPEN, "one module-level agent serves every user of the worker"
    if "_chat_key(" not in body:
        return OPEN, "no conversation key function"
    # Parse it. A substring search for "user.sub" reported FIXED against a tree
    # where `_chat_key` computed `sub` and then returned a constant instead —
    # the exact defect — because the name still APPEARED. Presence is not use,
    # and this is the property the whole finding rests on, so read the return.
    try:
        tree = ast.parse(body)
    except SyntaxError as exc:
        return UNVERIFIED, f"api/brain.py does not parse ({exc})"
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_chat_key"),
        None,
    )
    if fn is None:
        return UNVERIFIED, "_chat_key is gone — re-measure"
    subject_bound = any(
        isinstance(t, ast.Name)
        and t.id == "sub"
        and isinstance(getattr(a, "value", None), ast.Attribute | ast.Call | ast.BinOp | ast.Name)
        for a in ast.walk(fn)
        if isinstance(a, ast.Assign)
        for t in a.targets
    )
    returns_subject = any(
        isinstance(n, ast.Return) and any(isinstance(x, ast.Name) and x.id == "sub" for x in ast.walk(n))
        for n in ast.walk(fn)
    )
    if not (subject_bound and returns_subject):
        return OPEN, "the conversation key does not derive from the authenticated subject"
    if "convo.lock" not in body:
        return OPEN, "concurrent requests on one conversation are not serialised"
    if "_CHAT_MAX_CONVERSATIONS" not in body:
        return OPEN, "retained conversations are unbounded"
    return FIXED, "keyed on (authenticated sub, session label), serialised, bounded and expiring"


def _p_model_age_from_provenance() -> tuple[str, str]:
    """Model staleness is measured from training provenance, not file mtime."""
    text = _code("ml/inference_engine.py")
    if not text:
        return UNVERIFIED, "ml/inference_engine.py is not readable"
    if "_model_training_time" not in text:
        return OPEN, "no provenance lookup exists"
    # Prose is already stripped by `_code`; narrow to the call site as well, so
    # an `st_mtime` read somewhere else in this 1,400-line module cannot be
    # mistaken for this gate's input.
    start = text.find("def _check_model_staleness")
    if start == -1:
        return UNVERIFIED, "_check_model_staleness is gone — re-measure"
    window = text[start : text.find("\n    def ", start + 10)]
    call = re.search(r"trained_at, reason = (.+)", window)
    if not call:
        return OPEN, "the staleness check does not read a provenance timestamp"
    if "st_mtime" in call.group(1):
        return OPEN, "the staleness check still reads the artifact's mtime"
    if "_model_training_time" not in call.group(1):
        return OPEN, f"the staleness check reads {call.group(1).strip()}, not provenance"
    return FIXED, "age comes from a sha256-bound timestamp in registry.json"


def _p_agent_deadline() -> tuple[str, str]:
    """An agent run that overran its budget cannot report completion."""
    text = _code("ai/agent/loop.py")
    if not text:
        return UNVERIFIED, "ai/agent/loop.py is not readable"
    start = text.find("def run_loop(")
    if start == -1:
        return UNVERIFIED, "run_loop is gone — re-measure"
    body = text[start:]
    if "deadline = time.monotonic() + budget.max_seconds" not in body:
        return OPEN, "no absolute deadline is computed for the run"
    # The deadline must be consulted more than once, and one of those must come
    # AFTER the planner returns — that is the whole defect.
    planner_call = body.find("plan = planner(context)")
    finished = body.find('run.stopped_reason = "planner_finished"')
    if planner_call == -1 or finished == -1:
        return UNVERIFIED, "the loop's shape changed — re-measure"
    if "_expired()" not in body[planner_call:finished]:
        return OPEN, "completion is accepted without rechecking the deadline"
    if body.count("_expired()") < 3:
        return OPEN, f"the deadline is consulted only {body.count('_expired()')} time(s)"
    if "remaining_seconds" not in body:
        return OPEN, "the planner is not told how long it has left"
    return FIXED, "one absolute deadline, rechecked after planning and after each tool call"


def _p_shell_fills_scroller() -> tuple[str, str]:
    """PageShell grows to fill `.app-shell-scroller`, as `.page-content` did.

    Probed from the source rather than declared: the class it replaced is
    `flex: 1 0 auto` in index.css, and a shell without an equivalent rule takes
    the initial `flex: 0 1 auto` and stops where its content stops.
    """
    text = _read("frontend/src/components/system/PageShell.tsx")
    if not text:
        return UNVERIFIED, "PageShell.tsx is not readable"
    css = _read("frontend/src/index.css")
    if "flex: 1 0 auto" not in css:
        return UNVERIFIED, "index.css no longer states .page-content's flex rule — re-measure"
    # Read the className template, not the file. A whole-file substring search
    # reported FIXED against a tree with the class REMOVED, because the comment
    # explaining the class names it — the same defect as F255, where the nan_leak
    # rule scanned docstrings as source. Proven by injection: strip the utility
    # and this must say OPEN.
    m = re.search(r"className=\{`([^`]*)`\}", text)
    if not m:
        return UNVERIFIED, "PageShell's className is no longer one template literal — re-measure"
    classes = m.group(1).split()
    if "flex-[1_0_auto]" not in classes:
        return OPEN, "PageShell sets no grow rule, so a short page leaves bare scroller under it"
    if "flex-1" in classes:
        return OPEN, "PageShell uses flex-1 (1 1 0%), the clamp index.css records as trapping tall content"
    return FIXED, "PageShell's className carries flex-[1_0_auto], matching the .page-content it replaced"


def _p_refusal_not_failure() -> tuple[str, str]:
    """A 403 from the admin-only capability surface is not reported as an outage."""
    text = _read("frontend/src/hub/PresenceAnywhereMount.tsx")
    app = _read("frontend/src/App.tsx")
    core = _read("api/ai_core.py")
    if not text or not app or not core:
        return UNVERIFIED, "one of PresenceAnywhereMount.tsx / App.tsx / api/ai_core.py is not readable"
    if "<PresenceAnywhereMount />" not in app:
        return UNVERIFIED, "the mount moved — re-measure who renders it before trusting this row"
    if '_VIEWER_ROLE = "admin"' not in core:
        return UNVERIFIED, "ai_core's viewer role changed; the premise of this finding no longer holds"
    if "response.status === 403" not in text:
        return OPEN, "every non-admin is told the platform failed, on every page, for a refusal by design"
    return FIXED, "a 403 renders an empty surface; a timeout or 500 is still reported"


def _p_link_dup_key() -> tuple[str, str]:
    """A link list keyed by destination duplicates one of its links.

    Measured, not asserted: on first mount React renders both, and on the next
    re-render that reorders the list it duplicates the shared key — a
    three-link bar becomes four anchors with a stale pill in the wrong order.
    """
    renderers = {
        "frontend/src/components/CrossLinkBar.tsx": "link.href",
        "frontend/src/components/RelatedPages.tsx": "l.to",
        "frontend/src/components/EmptyState.tsx": "l.href",
        "frontend/src/components/system/SubPageGrid.tsx": "item.to",
    }
    bare = []
    for rel, expr in renderers.items():
        text = _read(rel)
        if not text:
            return UNVERIFIED, f"{rel} is not readable"
        if f"key={{{expr}}}" in text:
            bare.append(rel.rsplit("/", 1)[-1])
    if bare:
        return OPEN, f"keyed on destination alone, so a repeat drops a link: {', '.join(bare)}"

    # A repeat only matters WITHIN one list: a page may hold several bars, and
    # each may legitimately link to /settings once. Counting file-wide called a
    # correct page broken.
    for rel in ("frontend/src/pages/TwoFactorSetup.tsx",):
        page = _read(rel)
        for block in re.findall(r"links=\{\[(.*?)\]\}", page, re.S):
            hrefs = re.findall(r"href:\s*'([^']+)'", block)
            dupes = {h for h in hrefs if hrefs.count(h) > 1}
            if dupes:
                return PARTIAL, (f"renderers fixed, but one list in {rel.rsplit('/', 1)[-1]} repeats {sorted(dupes)}")
    return FIXED, (
        f"all {len(renderers)} link renderers key on destination AND label, and the "
        "call site that failed points at a tab that pill could not previously reach"
    )


def _p_chart_gate_vacuous() -> tuple[str, str]:
    """The suite guarding the deployed safety posture emptied itself.

    Its assertions iterated only synced paths containing a Chart.yaml, so
    repointing ArgoCD at anything else left the list empty and every
    `assert not missing` passed over nothing — which is the original P0.
    """
    text = _read("tests/unit/test_the_deployed_chart_carries_the_safety_posture.py")
    if not text:
        return UNVERIFIED, "the deployed-chart suite is not readable"
    # Strip docstrings and comments FIRST. This file names both `_charts()` and
    # the new control in the prose that explains what was wrong, so every check
    # below must read code only — a probe that reads prose is the defect this
    # register calls F255, and the first draft of this one hit it twice.
    code = re.sub(r'"""[\s\S]*?"""', "", text)
    code = re.sub(r"(?m)^\s*#.*$", "", code)
    if "_deployed_targets(" not in code:
        return OPEN, "assertions still iterate charts only; a non-chart sync path empties them"
    if not re.search(r"(?m)^def test_every_synced_path_is_checkable\b", code):
        return PARTIAL, "non-chart paths are read, but nothing fails when a path yields nothing"
    if re.search(r"\b_charts\s*\(", code):
        return PARTIAL, "_charts() still called — some assertion may still skip a synced path"
    return FIXED, (
        "every synced path is resolved to (env, manifests) whether or not it is a chart, "
        "and a second positive control fails when a synced path yields neither"
    )


def _p_env_example_documents_dead_keys() -> tuple[str, str]:
    """Does .env.example document a knob the code does not read?

    A key an operator can set that changes nothing is worse than an undocumented
    one, because it reads as a control. Counted the way the test counts it: a
    literal that appears in no source file cannot be read by anything. Markdown
    is excluded — a key named in a document is documented, not read.
    """
    example = _read(".env.example")
    if not example:
        return ("UNKNOWN", ".env.example is not present")

    declared = set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*=", example, re.M))
    if not declared:
        return ("UNVERIFIED", "no keys parsed from .env.example")

    exts = {".py", ".ts", ".tsx", ".sh", ".yml", ".yaml", ".json", ".template", ".toml", ".tf", ".conf"}
    skip = {".venv", "node_modules", ".git", "static", "dashboard", "htmlcov"}
    guard = ROOT / "tests" / "unit" / "test_env_example_documents_real_variables.py"
    blob: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in exts:
            continue
        if any(s in path.parts for s in skip) or path.name.startswith(".env") or path == guard:
            continue
        try:
            blob.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    source = "\n".join(blob)

    dead = sorted(k for k in declared if k not in source)
    if not dead:
        return ("FIXED", f"all {len(declared)} documented keys appear in the source")
    return ("OPEN", f"{len(dead)} of {len(declared)} documented keys appear in no source file: {', '.join(dead[:8])}")


def _p_leakage_guard_checked_nothing() -> tuple[str, str]:
    """Does the calibration-leakage guard assert against code that exists?

    It patched `sklearn.calibration.CalibratedClassifierCV` and read the `cv=`
    argument. `cv='prefit'` was removed in scikit-learn 1.4 and the code moved
    to `_calibrate_prefit`, which fits an `IsotonicRegression` on the base
    model's output — so nothing constructed a `CalibratedClassifierCV`, the
    tracking list was always empty, and every `for cv_arg in ...` loop ran zero
    times.
    """
    test = _read("tests/unit/test_mtf_ensemble_leakage.py")
    if not test:
        return ("UNKNOWN", "tests/unit/test_mtf_ensemble_leakage.py is not present")

    source = _read("scripts/retrain_mtf_accuracy.py")
    still_uses_cccv = "CalibratedClassifierCV(" in source
    guard_patches_cccv = 'patch("sklearn.calibration.CalibratedClassifierCV"' in test
    asserts_one_fit = "must not re-fit it" in test
    asserts_it_measured = "so nothing was checked" in test

    if guard_patches_cccv and not still_uses_cccv:
        return (
            "OPEN",
            "the guard patches CalibratedClassifierCV, which retrain_mtf_accuracy no longer "
            "constructs \u2014 the tracking list is always empty and the assertions run zero times",
        )
    if asserts_one_fit and asserts_it_measured:
        return (
            "FIXED",
            "the guard asserts the base model is fitted exactly once and that it observed a "
            "fit at all, against _calibrate_prefit as it is actually written",
        )
    return ("PARTIAL", "the guard no longer chases CalibratedClassifierCV but does not assert it measured anything")


def _p_density_cannot_reach() -> tuple[str, str]:
    """Is the density control able to reach the interface it is stamped on?

    `data-density` is set on every route and redefines eleven tokens per tier.
    It can only change a pixel where a component reads one of those tokens. This
    counts both sides from the tree: the token-reading utilities against the
    literal sizes that no token can reach.
    """
    root = ROOT / "frontend" / "src"
    if not root.is_dir():
        return ("UNKNOWN", "frontend/src is not present")

    # One counter, not two. This probe used to keep its own three regexes, and
    # `scripts/frontend_size_ratchet.py` now holds the same population at a
    # baseline — two definitions of one number drift at the first edit, which
    # is how the page-shell ratchet came to print "37 of 72" against a real
    # population of 63.
    sys.path.insert(0, str(ROOT / "scripts"))
    from frontend_size_ratchet import count_split

    token_uses, literal_sizes, literal_space = count_split(ROOT)

    unreachable = literal_sizes + literal_space
    if unreachable == 0:
        return ("FIXED", f"every size reaches the token layer ({token_uses} token uses)")
    return (
        "OPEN",
        f"{token_uses} token-reading utilities against {literal_sizes} inline fontSize "
        f"and {literal_space} numeric spacing utilities — {unreachable} sizes the density "
        f"control cannot reach",
    )


def _p_docker_build_crashed_on_optional_peers() -> tuple[str, str]:
    """Could the production image be built at all?

    Reads the Dockerfile and the test that claims to run what it runs. It does
    NOT run `npm ci` — that needs the network and twelve seconds, and a probe
    that does either is a probe nobody runs. So this measures the fix, not the
    upstream bug: the flag being present and the test being bound to it.
    """
    dockerfile = _read(ROOT / "Dockerfile")
    if not dockerfile:
        return ("UNKNOWN", "Dockerfile is not present")

    m = re.search(r"^RUN\s+npm\s+ci\b(?P<flags>.*)$", dockerfile, re.MULTILINE)
    if not m:
        return ("UNKNOWN", "Dockerfile has no `RUN npm ci` line")
    has_flag = "--legacy-peer-deps" in m.group("flags")

    test = _read(ROOT / "tests" / "unit" / "test_frontend_lockfile_installs_cleanly.py")
    bound = "_dockerfile_npm_ci_flags()" in test

    if has_flag and bound:
        return (
            "FIXED",
            "Dockerfile runs `npm ci --legacy-peer-deps` and the lockfile test derives its "
            "flags from that line, so the two cannot diverge",
        )
    if has_flag:
        return (
            "PARTIAL",
            "the workaround is in the Dockerfile but the test hard-codes its own argv — "
            "it is no longer running what the image runs",
        )
    return (
        "OPEN",
        "Dockerfile runs a bare `npm ci`; if npm still crashes loading optional peer sets, no image can be built",
    )


def _p_field_has_no_label() -> tuple[str, str]:
    """Settings fields showed a label and had no accessible name.

    `Field` rendered `<label>` as a SIBLING with no `for` and no id, in ~60
    places; `RiskCalculator`'s `Label` was a styled `<div>`, so the page where
    a mistyped number becomes a position size had no association at all.
    """
    ui = _read("frontend/src/pages/settings/ui.tsx")
    calc = _read("frontend/src/pages/RiskCalculator.tsx")
    if not ui or not calc:
        return UNVERIFIED, "the settings ui module or RiskCalculator is not readable"

    problems = []
    # The label must ENCLOSE the control; a sibling label with no `for` names nothing.
    head = ui.split("export const Field")[-1][:900]
    if "<label" not in head or "{children}" not in head:
        problems.append("settings Field does not wrap its control")
    elif head.index("<label") > head.index("{children}"):
        problems.append("settings Field renders its label after the control")
    if "const Label: React.FC<{ text: string }> = ({ text }) => (\n  <div" in calc:
        problems.append("RiskCalculator Label is still a <div>")
    if "htmlFor" not in calc:
        problems.append("RiskCalculator fields are not tied to their labels")
    if problems:
        return OPEN, "; ".join(problems)
    return FIXED, (
        "the settings Field label encloses its control, so every call site is named "
        "without an id; RiskCalculator's Label is a real <label> carrying htmlFor"
    )


FINDINGS: list[Finding] = [
    Finding(
        "BALANCE-ZERO-RAISES",
        "A broker balance of exactly zero crashed the balance lookup, silently",
        "P2",
        "Money",
        "This session, 2026-09-18 — surfaced by a test asserting a real zero is not a failed lookup",
        "`api/billing.py::get_balance` read the broker account as "
        '`float(getattr(account, "balance", 0) or account.get("balance", 0))`. The `or` '
        'conflates "the attribute is missing" with "the attribute is ZERO", because 0.0 is '
        "falsy. A broker reporting a genuine zero therefore fell through to the mapping "
        "branch, and an object-style account has no `.get`, so it raised AttributeError — "
        "into an `except Exception` that logged at DEBUG, which is off in production. The "
        "user was shown whatever the next source produced, and nothing recorded why. Fixed "
        "by `_account_field`, which tries the attribute, then the mapping, and treats None "
        "rather than falsiness as absence. The same `except` now logs at WARNING: the "
        "difference between an operator seeing why a balance was wrong and seeing nothing.",
        "`tests/unit/test_the_balance_says_where_it_came_from.py::"
        "test_a_zero_balance_does_not_crash_the_broker_read`, parametrised over an "
        "object-style and a mapping-style account because the fix has two branches and one "
        "that works only for the shape the test uses is not a fix. Red on the pre-fix tree "
        "for the object-style case.",
        "python scripts/correction_register.py --id BALANCE-ZERO-RAISES",
        _p_zero_balance_does_not_raise,
        [S_MONEY, S_TDD],
    ),
    Finding(
        "BALANCE-SOURCE-SPLIT",
        "The balance a user is shown and the balance a withdrawal checks are different numbers",
        "P1",
        "Money",
        "This session, 2026-09-18 — surfaced while planning the withdrawal debit (ADR 0021)",
        '`api/billing.py::get_balance` says in its own docstring "Return the authenticated '
        "user's wallet balance\" and then reads the BROKER account, falling back to the "
        "subscription manager. It never reads `wallet_transactions`. Meanwhile ADR 0021 makes "
        "the fiat wallet the ledger a withdrawal debits, and `_apply_movement` refuses when "
        "`before < amount`. So the number the UI shows and the number the refusal is computed "
        "from come from two different sources, and the ledger carries no history — nothing "
        "wrote it before deposits began crediting it. This is why "
        "`WITHDRAWAL_DEBITS_LEDGER` ships default-FALSE: with it on today, a user the UI says "
        "has funds is refused 402, which is an outage that looks like a money bug, and the "
        "pressure to fix it falls on the balance check, which is a real gate. The fix is "
        "reconciliation, not a wider tolerance and not a removed check: decide what is "
        "authoritative, and make `get_balance` read that, or seed the ledger from it. "
        "Deleting the docstring's promise instead would leave two numbers and no statement "
        "that they disagree.",
        "Assert that the value `/billing/balance` returns and the value a withdrawal is "
        "checked against come from the same source. It fails today at the point where one "
        "reads the broker and the other reads the ledger. Until then, "
        "`test_withdrawal_debits_the_wallet_ledger.py::test_the_flag_defaults_to_off_and_"
        "nothing_is_debited` pins the safe default.",
        "python scripts/correction_register.py --id BALANCE-SOURCE-SPLIT",
        _p_balance_source_split,
        [S_MONEY, S_VBC],
    ),
    Finding(
        "SUITE-REWRITES-MODEL",
        "Running the test suite overwrote a model artifact production verifies fail-closed",
        "P1",
        "ML",
        "This session, 2026-09-18 — surfaced by running the suite on Python 3.12 for the first time",
        "`tests/unit/test_coverage_boost_ml_misc.py::test_oos_eval_returns_dict` called "
        "`ml.train_with_macro.oos_eval` without redirecting that module's `MODEL_DIR`, and "
        "`oos_eval` dumps the model it trains (train_with_macro.py:536). Every run of this suite "
        "therefore rewrote the committed `ml/saved_models/xgb_macro_oos.pkl`, whose sha256 is in "
        "`model_checksums.json` and is enforced fail-closed by `ml/__init__.py::_verify_checksum` "
        "in production. Nothing caught it because on the 3.11 interpreter the retrained bytes are "
        "IDENTICAL to the committed ones — the tree stayed clean and the provenance ratchet passed, "
        "having never been exercised. On the 3.12 interpreter that ships the image, the bytes differ "
        "and the artifact stops verifying: a green suite produced a model production refuses to load. "
        "Neither a grep nor an AST sweep found the writer; a probe that wrapped `joblib.dump` and "
        "recorded the stack did. Fix: redirect MODEL_DIR in that test, and guard the whole suite "
        "in conftest so the next one fails loudly instead of silently. The guard refuses writes to "
        "the 11 manifest artifacts only — writing a NEW file into the model directory stays "
        "allowed, because `test_ml_online_learner.py` must do that to exercise the "
        "permitted-directory check in `SklearnOnlineLearner.load`.",
        "The guard IS the regression test, and it is the only formulation that fails "
        "deterministically on both interpreters: an assertion on the artifact's bytes passes on "
        "the older interpreter even while the write happens. Proven red by stashing only the test fix and running "
        "the unfixed test against the guard on 3.11 — it raised the guard's AssertionError.",
        "python scripts/correction_register.py --id SUITE-REWRITES-MODEL",
        _p_suite_does_not_rewrite_models,
        [S_TDD, S_VBC],
    ),
    Finding(
        "MODEL-PROVENANCE-DISAGREES",
        "Two records disagree by nearly three months about when the same bytes were trained",
        "OWNER",
        "ML",
        "This session, 2026-09-14 — surfaced by fixing MODEL-AGE-IS-MTIME",
        "`advanced_oos_meta.json` gives `validated_at` 2026-06-26; the earliest `registry.json` "
        "version carrying the artifact's sha256 gives 2026-04-01 — the same bytes, and the probe "
        "above states today's gap rather than a figure typed here that would drift. "
        "Nothing had ever compared them, and the mtime the staleness gate used to read (0.69 "
        "days) agreed with neither, which is why the disagreement was invisible. It is now "
        "visible in one payload: `health()` reports `last_trained_at` 2026-06-26 from the meta "
        "file beside `model_age_days` 166.75 from the registry, and `MlSafetyStrip.tsx` renders "
        'the former as "Trained: 26/06/2026" next to a stale badge — an operator reading that '
        "screen saw a model trained twelve weeks ago flagged stale at twenty-four. Engineering "
        "has done what it can without deciding: `health()` now also reports "
        "`model_provenance_at`, the timestamp the gate actually blocked on, so the age it "
        "enforces is attributable rather than a third unexplained figure — and both screens that "
        "render a training date (`MlSafetyStrip.tsx`, `ModelHealthWorkspace.tsx`) now show THAT "
        "date, falling back to the meta file's only when the gate reports no provenance, so the "
        "date on screen is the one the platform acted on. Which record is right "
        "is an ML-side call — most likely `validated_at` means validated rather than trained, in "
        "which case the artifact needs a real `trained_at` — and picking one silently would be "
        "engineering deciding what a model's age means.",
        "tests/unit/test_health_states_one_model_age.py — three tests, red before the fix: the "
        "payload must name the timestamp the gate used, the age must be arithmetic on it, and "
        "unusable provenance must be reported as unknown WITH a reason rather than omitted. "
        "frontend/src/test/the_trained_date_matches_the_staleness_claim.test.tsx — three more, "
        "for the screen: it must prefer the gate's date, fall back to the meta file's when there "
        "is none, and show nothing rather than a wrong date when neither is known.",
        "python scripts/correction_register.py --id MODEL-PROVENANCE-DISAGREES",
        _p_meta_registry_agree,
        [S_TDD, S_VBC],
    ),
    Finding(
        "MODEL-166-DAYS-OLD",
        "The model the platform ships is months past its own freshness limit",
        "OWNER",
        "ML",
        "This session, 2026-09-14 — surfaced by fixing MODEL-AGE-IS-MTIME",
        "Not a new defect; a fact the old gate was hiding. With age read from the artifact's "
        "sha256-bound provenance rather than its mtime, the committed advanced_oos.pkl measures "
        "166 days old against MODEL_MAX_AGE_DAYS=30, while the mtime the gate used to read said "
        "0.69 days — the file having been written by the clone. Four registry versions "
        "(advanced_oos_v1/v2, xgb_horizon5_v1/v3) carry the SAME sha256, so the bytes have not "
        "changed since 2026-04-01 whatever they were re-registered as; even taking the latest of "
        "those four (2026-06-26) the model is 80 days old, so it is past the limit on any "
        "reading. STALE_MODEL_BLOCK defaults to true, so with this fix in place inference is "
        "refused until the situation is resolved. That is the gate doing its job, and it is why "
        "this is recorded rather than quietly worked around: lowering the check or raising "
        "MODEL_MAX_AGE_DAYS to make the platform trade again would restore exactly the behaviour "
        "the fix removed. Three ways out, and all three are the owner's to choose: retrain and "
        "register a model; decide 30 days is the wrong limit for this strategy and change it "
        "deliberately, with the reason recorded; or run with MODEL_MAX_AGE_DAYS=0 in a "
        "non-trading deployment. This entry reports OWNER until the measured age is inside the "
        "limit, and it cannot be closed by editing a document.",
        "No test — a test asserting the model is fresh would fail for a true reason and be "
        "deleted. The probe measures the shipped artifact directly, so it closes itself when a "
        "current model is registered.",
        "python scripts/correction_register.py --id MODEL-166-DAYS-OLD",
        _p_shipped_model_age,
        [S_VBC],
    ),
    Finding(
        "CHAT-SHARED-HISTORY",
        "One conversation per worker, shared by every user on it",
        "P0",
        "Security",
        "External audit of 40cb9419, 2026-09-14 — reproduced here before the fix",
        "POST /api/brain/chat held a module-level `_chat_agent`, built on first use and reused "
        "for every request in the worker. LLMAgent keeps the conversation on the instance, and "
        "nothing about the authenticated caller chose which instance answered, so one worker had "
        "one history shared by everyone on it. Reproduced by calling the endpoint function with "
        "two identities and a recording backend: user A's \"my account number is "
        '9137-SECRET-ALPHA" appeared verbatim in the outgoing prompt sent on behalf of user B. '
        "On this platform that box holds balances, positions, strategy and intent, so it is a "
        "confidentiality defect rather than untidiness. Conversations are now keyed on "
        "(authenticated `sub`, client session label) — the subject first, because a session id is "
        "a label the client picks and keying on it alone would let anyone read another user's "
        "history by guessing one, or by two clients both defaulting to the same string. "
        "`ChatRequest` still carries no user field, for the same reason. Each conversation has "
        "its own lock (LLMAgent.chat appends the user turn, awaits, then appends the reply, so "
        "concurrent requests interleave into a history whose turns do not alternate), the "
        "registry is LRU-bounded, idle conversations expire, and a token with no subject is "
        "refused rather than falling back to a shared agent.",
        "tests/unit/test_chat_history_is_per_user.py — ten tests, each injection-proven. Two of "
        "them were rewritten for proving nothing: the concurrency test took the lock inside the "
        "TEST body, so it still passed with the lock deleted from the endpoint (it was proving "
        "that asyncio.Lock works), and the clearing test popped a key from the registry dict and "
        "asserted the other was still there, which tests dict.pop. Both now drive the endpoint. A "
        "tenth walks the route's dependency chain to `get_current_user`, because every other test "
        "supplies a TokenPayload directly and would keep passing if the route were ever handed a "
        "shared or body-supplied identity.",
        "pytest tests/unit/test_chat_history_is_per_user.py -q",
        _p_chat_per_user,
        [S_TDD, S_VBC, S_DEAD],
    ),
    Finding(
        "MODEL-AGE-IS-MTIME",
        "Deploying a stale model was how the staleness gate got cleared",
        "P0",
        "ML",
        "External audit of 40cb9419, 2026-09-14 — reproduced here before the fix",
        "`_check_model_staleness()` measured the artifact's filesystem mtime. Reproduced against "
        "a disposable file: a 90-day-old artifact reported stale=True age=90.0; the SAME BYTES "
        "with the timestamp touched reported stale=False age=0.0, with no retraining. Every "
        "ordinary operational act writes that timestamp — git checkout, docker build, cp -r, "
        "rsync without -t, restoring a backup — so the gate that exists to stop the platform "
        "trading on an out-of-date model was cleared by the act of deploying the out-of-date "
        "model. It failed in the unsafe direction and silently. Age now comes from a timestamp "
        "bound to the artifact's sha256 in registry.json, which makes it a property of the BYTES: "
        "`trained_at` preferred, `registered_at` as the fallback (today's registry records only "
        "the latter, and it is still sha-bound and still immune to a touch). Where several "
        "versions carry the same digest the EARLIEST wins — re-registering unchanged bytes under "
        "a new version is the same defect wearing a different hat, and the earliest date can only "
        "make a model look older. Every way provenance can be unusable — absent, malformed, not "
        "matching the bytes, or future-dated beyond clock skew — reports STALE, so "
        'STALE_MODEL_BLOCK blocks, which is the right answer to "I cannot tell you how old this '
        'model is". SEE MODEL-166-DAYS-OLD: turning this on revealed that the committed model '
        "is well past the limit, which the mtime had been hiding.",
        "tests/unit/test_model_age_is_training_age.py — fifteen tests, twelve of which fail when "
        "the mtime read is put back. Two existing tests asserted the defect "
        "(test_fresh_file_returns_false, test_fresh_model_not_stale: a just-written file with no "
        'provenance was "fresh") and were rewritten with what they used to claim recorded in '
        "the docstring, not deleted.",
        "pytest tests/unit/test_model_age_is_training_age.py tests/unit/test_inference_engine.py "
        "tests/unit/test_ml_inference_engine.py -q",
        _p_model_age_from_provenance,
        [S_TDD, S_VBC, S_DEAD, S_DEBUG],
    ),
    Finding(
        "AGENT-DEADLINE-UNENFORCED",
        "An agent run that blew its deadline reported success",
        "P1",
        "AI",
        "External audit of 40cb9419, 2026-09-14 — reproduced here before the fix",
        "`run_loop` checked the clock at the TOP of each step and nowhere else, so the budget "
        "bounded when work was allowed to START rather than when it had to be finished. "
        "Reproduced with a planner that consumed 2s against a 1s budget: completed=True, "
        'stopped_reason="planner_finished". That is worse than a late answer — `completed` is '
        "what a caller reads to decide whether to act on the run, and `_remember()` writes it to "
        "memory, so a run that blew its deadline became a successful precedent for the next one. "
        "There is now one absolute deadline computed once (not re-derived per step, which would "
        "let N steps of just-under-the-limit each pass while the run ran N times over), rechecked "
        "after the planner returns and after every tool call, and `LoopContext.remaining_seconds` "
        "tells the planner how long it has so an overrun can be avoided rather than only "
        "detected. What it deliberately does NOT claim is cancellation: Python cannot interrupt "
        "arbitrary synchronous code, and a thread timeout only abandons the waiter while the work "
        "continues — and a tool handler here may be mid-way through a broker or database call, so "
        "abandoning one is worse than waiting. The loop bounds what it STARTS and what it "
        "ACCEPTS, and says so. The remaining time is NOT given to tool handlers, which is a "
        "deliberate gap: `ToolBus.invoke` forwards `**context` straight to "
        "`registered.handler(**context)`, so an extra keyword raises TypeError in every handler "
        "that does not declare it — every tool on the platform. Doing it properly needs an opt-in "
        "on the registration the way `wants_operator` already works, which is a change to the "
        "tool contract rather than to this loop. An earlier draft of the fix CLAIMED in a comment "
        "that handlers were told; that comment was false and is corrected, because a note "
        "describing a mechanism that does not exist is the same defect class as a gate that does "
        "not run.",
        "tests/unit/test_agent_deadline_is_enforced.py — nine tests. Four injections were run; "
        "one of them (removing the post-tool recheck) initially passed all of them, which made "
        "that branch a control no test held, so a ninth test was added for what it actually "
        "changes: the audit record. It now fails under that injection.",
        "pytest tests/unit/test_agent_deadline_is_enforced.py tests/unit/test_agentic_loop.py -q",
        _p_agent_deadline,
        [S_TDD, S_VBC, S_DEAD],
    ),
    Finding(
        "DOCKER-NPM-PEER-CRASH",
        "npm ci crashed loading optional peer sets, so no image could be built",
        "P0",
        "Deployment",
        "Reproduced 2026-09-18 from a clean directory on npm 10.9.7 and npm 10.8.2",
        "`Dockerfile:4` builds the frontend on `node:20-alpine` and stage 1 is "
        "`COPY frontend/package.json frontend/package-lock.json ./` then `RUN npm ci`. "
        "npm's arborist loads the OPTIONAL peer sets of packages named in the lockfile even "
        "for `ci`, which resolves nothing and should not need the registry at all. That walk "
        "reached `@vitest/browser-playwright@5.0.1` — an optional peer of the locked "
        "`vitest@4.1.11` — which peers on `vitest@*`, resolving to the newly published vitest 5, "
        "whose `@vitejs/devtools-*@^0.7.5` peers sent it into a recursion that dereferences "
        "null: `Cannot read properties of null (reading 'edgesOut')` at `#loadPeerSet "
        "(build-ideal-tree.js:1289)`. Nothing in this repository changed — the trigger was a "
        "registry publish — and the lockfile is sound: `npm ci --legacy-peer-deps` installs 738 "
        "packages at 0 version mismatches and 0 packages absent from the lock, which is exactly "
        "the locked tree. The flag is therefore a WORKAROUND and is commented as one; remove it "
        "when npm ships the fix and let the slow test prove it is safe to. Found by the repo's "
        "own gate while verifying an unrelated frontend change, on a tree whose full suite had "
        "been green hours earlier — which is the whole argument for a gate that starts from two "
        "files and an empty directory rather than from a populated `node_modules`.",
        "tests/unit/test_frontend_lockfile_installs_cleanly.py::"
        "test_npm_ci_succeeds_from_a_clean_directory fails with the arborist crash on the "
        "pre-fix tree — verified against a detached worktree at the previous commit, not just "
        "against the edited one — and passes in 12s after it. Its sibling "
        "test_the_install_command_is_read_from_the_dockerfile holds the binding: the slow test "
        "now READS the Dockerfile's `npm ci` flags rather than repeating them, so a test that "
        "claims to run what the image runs cannot quietly stop doing so.",
        "python scripts/correction_register.py --id DOCKER-NPM-PEER-CRASH",
        _p_docker_build_crashed_on_optional_peers,
        [S_VBC, S_TDD],
    ),
    Finding(
        "ENV-EXAMPLE-DEAD-KNOBS",
        "Three risk limits an operator could set, and nothing read any of them",
        "P1",
        "Configuration",
        "Measured 2026-09-18 by comparing every key against the whole source tree",
        "`.env.example` is the only description of this platform's configuration an operator "
        "has, and 26 of its 969 keys appeared in NO source file. They were not random rot \u2014 "
        "almost every one was a near-miss of a live name: `SELF_HEAL_ENABLED` for "
        "`SELF_HEALER_ENABLED`, `SPREAD_SPIKE_THRESHOLD` for `SPREAD_SPIKE_MULTIPLIER`, "
        "`TWAP_DURATION_S` for `TWAP_DEFAULT_SECS`, `PAPER_SPREAD_BPS` for "
        "`PAPER_FALLBACK_SPREAD_PCT`. Three sat under a heading reading `# Risk limits` on a "
        "money-moving system: `RISK_DAILY_LOSS_LIMIT=500` (the live knob is "
        "`RISK_MAX_DAILY_LOSS_PCT`, a fraction rather than dollars), `RISK_MAX_LEVERAGE=10` "
        "(`MAX_LEVERAGE_RATIO`) and `RISK_PER_TRADE_PCT=0.01` (`MAX_RISK_PCT_PER_TRADE`). The "
        "last is the worst of them: 0.01 is also the DEFAULT of the live name, so an operator "
        "halving it to 0.005 saw a file that agreed with the risk actually in force and had no "
        "way to tell it had changed nothing. Each dead line is now a comment naming the live "
        "key, so the old spelling stays searchable. Two keys going the other way \u2014 `JWT_SECRET` "
        "and `REQUIRE_EMAIL_VERIFICATION`, written into every generated `.env` by "
        "`scripts/bootstrap_dev.py` \u2014 were documented for the first time; `JWT_SECRET` signs "
        "white-label tenant tokens and is now placeholder-guarded at startup.",
        "tests/unit/test_env_example_documents_real_variables.py fails with all 26 named and "
        "line-numbered on the pre-fix tree. Its rule is deliberately weak in the safe "
        "direction \u2014 a key must appear as a literal SOMEWHERE in the source \u2014 because the "
        'first version scanned for `os.getenv("X")` and would have reported eleven live '
        "trading-strategy knobs as dead: this codebase reads env through helpers "
        '(`_env_float("EDGE_SELECTOR_MAX_LOT", 0.01)`) and declarative tables '
        '(`_FeatureDef("FEATURE_COPY_TRADING", ...)`). The checker also excludes ITSELF: its '
        "docstring names seven dead keys to explain them, and on the first run that table was "
        "the only place they appeared, so it passed them \u2014 F257 committed by the checker "
        "written to prevent it.",
        "python scripts/correction_register.py --id ENV-EXAMPLE-DEAD-KNOBS",
        _p_env_example_documents_dead_keys,
        [S_DEAD, S_VBC],
    ),
    Finding(
        "LEAKAGE-GUARD-CHECKED-NOTHING",
        "The calibration-leakage guard asserted a mechanism the code no longer has",
        "P1",
        "ML",
        "Proven by injection 2026-09-18, after a 120s timeout drew attention to the test",
        "`tests/unit/test_mtf_ensemble_leakage.py` exists because "
        "`CalibratedClassifierCV(cv=3)` re-trained the stacking ensemble's base learners on "
        "sub-splits of the test fold and produced ~99% walk-forward accuracy that was not "
        "there. The guard patched `sklearn.calibration.CalibratedClassifierCV`, collected the "
        "`cv=` argument of every construction, and asserted each was `'prefit'`. "
        "**`cv='prefit'` was removed in scikit-learn 1.4**, and the code was rewritten to fit an "
        "`IsotonicRegression` on the base model's output (`_calibrate_prefit`). Nothing has "
        "constructed a `CalibratedClassifierCV` since, so the tracking list was always empty "
        "and `for cv_arg in captured_cv_args` ran zero times \u2014 the F176 shape, a measurement "
        "that cannot fail, on the control protecting the number this model is judged by. "
        "The `except Exception: pass` around the call hid the other half: on a machine without "
        "xgboost the guard was green having called nothing. Both were found because the test "
        "took 131s against a 120s `pytest-timeout` \u2014 it was flaky whenever the machine was "
        "busy, which is when CI runs, and CI has never run (F95). "
        "Rewritten to assert the PROPERTY against the mechanism that is there: the estimator "
        "the returned wrapper carries is the same object that was fitted, it was fitted exactly "
        "once, and the isotonic layer is handed a 1-D probability vector rather than the "
        "feature matrix \u2014 which is what makes a re-fit impossible by construction. Clamping "
        "`n_estimators` to 5 (it has nothing to do with the assertion) took the file from 131s "
        "to 2.4s.",
        "Proven by injection, not by reading: `_calibrate_prefit` was deleted from "
        "`train_xgboost` so it returned an uncalibrated model, and the OLD file stayed green "
        "\u2014 twice, at full runtime. The same injection turns the new "
        "`test_train_xgboost_does_not_refit_the_base_model` red, and every assertion is "
        "preceded by one that the test observed anything at all (`so nothing was checked`), "
        "because an empty list satisfies a `for` loop.",
        "python scripts/correction_register.py --id LEAKAGE-GUARD-CHECKED-NOTHING",
        _p_leakage_guard_checked_nothing,
        [S_DEAD, S_TDD, S_VBC],
    ),
    Finding(
        "DENSITY-CANNOT-REACH",
        "The density control is stamped on every route and can reach almost nothing",
        "P2",
        "Frontend",
        "Measured 2026-09-15 while making density a user choice",
        "`PageSurface` stamps `data-density` on every route, `index.css` fully specifies three "
        'tiers across eleven tokens each, and CLAUDE.md documents it as "one table, stamped on '
        'every route". Every part of that is true and none of it reaches a pixel on most pages: '
        "the tokens the tiers redefine are consumed by 29 class usages in the whole application, "
        "against 2,871 inline `fontSize: <number>` and 1,089 numeric Tailwind spacing utilities. "
        "A literal pixel is not in the cascade, so no tier can change it. That is why the "
        "interface does not feel dense at any setting, and it is the dead-control shape: a "
        "control that exists, is documented accurately, and never runs. It is the same defect as "
        "the 3,555 colour literals, in the size dimension — and the colour side already has a "
        "codemod and a ratchet, which is the precedent for closing this one. NOT fixed by making "
        "density a user preference: that made the control settable, which is a different thing "
        "from making it effective, and shipping the control without recording this would have "
        "been shipping a second dead control on top of the first. "
        "The band ABOVE the scale is now closed. 44 sizes sat at or above 28px, beyond "
        "`--fs-hero` (26px at `ultra`), and the obvious move — a `--fs-display` tier the codemod "
        "could bulk-convert — was wrong for most of them: 31 were sizing an EMOJI, where "
        "`fontSize` is the only lever a glyph has, and each disappears when "
        "`frontend_emoji_ratchet.py` turns it into an SVG sized by `width`/`height`. 13 sized "
        "type; two of those were dead style entries left behind by the `PageShell` migration and "
        "were deleted, and the remaining 11 were converted BY HAND to "
        "`--fs-display-sm` / `--fs-display` / `--fs-display-lg`, each assigned by role. The "
        "ultra values are byte-identical to the literals they replaced, so nothing moved at the "
        "tier `densityPref` gives a person by default. Those three sizes are deliberately "
        "ABSENT from the codemod's substitution tables — a bulk rewrite sees `fontSize: 32` and "
        "cannot tell a price from an emoji — and "
        "`tests/unit/test_size_codemod_only_touches_css.py` fails if one is ever added. "
        "`python scripts/frontend_size_ratchet.py --check` prints the split on every run, so it "
        "is measured rather than remembered from this sentence; it now reads 31 glyph, 0 type.",
        "frontend/src/test/density_is_not_a_dead_control.test.ts proves the three tiers are "
        "specified, monotonic and separated by a real margin rather than a rounding one — parsed "
        "from index.css, because the tiers live inside `@layer base`, which jsdom's CSSOM drops "
        "entirely, so a `getComputedStyle` assertion here would have been a test of jsdom's "
        "coverage rather than of the cascade. The live cascade is proved in a browser. This "
        "entry stays OPEN until the literal sizes reach the token layer; the probe counts both "
        "sides from the tree, so it closes itself and cannot be closed by assertion.",
        "python scripts/correction_register.py --id DENSITY-CANNOT-REACH",
        _p_density_cannot_reach,
        [S_DEAD, S_VBC],
    ),
    Finding(
        "SHELL-NO-GROW",
        "The standard page stopped where its content stopped",
        "P2",
        "Frontend",
        "This session, 2026-09-14 — found by measuring migrated pages against legacy ones in Chromium",
        "`PageShell` replaced `.page-content` without the one layout rule that class carried: "
        "`flex: 1 0 auto` inside `.app-shell-scroller`, which is a flex column. With no flex "
        "rule the shell took the initial `flex: 0 1 auto`, so a page shorter than the viewport "
        "ended at its content and left bare scroller beneath it. Measured at 1440x900 in a "
        "900px scroller: /observability 540, /support 560, /transparency 701 against /portfolio "
        "2074, /dashboard 2066 and every other unmigrated page filling. Nothing was clipped — a "
        "flex item's `min-height: auto` floors it at its content height, and /academy (1459) and "
        "/chat (2927) were measured rendering at natural height and scrolling — so this was "
        "invisible to every test and to a screenshot of a long page. The fix is `flex-[1_0_auto]` "
        "and deliberately NOT `flex-1`: that is `1 1 0%`, which index.css records as having "
        "clamped every page to the viewport and trapped taller content.",
        "frontend/src/test/page_shell_fills_the_scroller.test.tsx — red on the pre-fix tree. "
        "jsdom computes no flex layout, so the test holds the class contract and the browser "
        "measurement is the execution proof; both are recorded.",
        "npx vitest run src/test/page_shell_fills_the_scroller.test.tsx",
        _p_shell_fills_scroller,
        [S_TDD, S_VBC],
    ),
    Finding(
        "REFUSAL-AS-FAILURE",
        "Every non-admin was told the platform had failed, on every page",
        "P1",
        "Frontend",
        "This session, 2026-09-14 — found by capturing HTTP status while driving migrated routes",
        "`PresenceAnywhereMount` is rendered for EVERY authenticated user (`{isAuth && "
        "<PresenceAnywhereMount />}` in App.tsx) and fetches `/api/ai-core/capabilities/app`, "
        'which is `Depends(_viewer)` with `_VIEWER_ROLE = "admin"`. So for every non-admin the '
        "request is refused by design — and the component treated the refusal as a load failure, "
        'rendering a permanent amber "I could not load what I am allowed to do here (Error: HTTP '
        '403)." to a user for whom nothing was broken. Ruled out a credential fault by execution '
        "first: signed in as a trader in Chromium, /api/auth/me returned 200 over the same cookie, "
        'so the platform answered and the answer was "not you". A 403 now renders an empty '
        'surface and the honest "Nothing on this page is exposed to me"; 401, timeouts and 5xx '
        "are still reported, because those really are unloaded.",
        "frontend/src/test/a_refusal_is_not_a_failure.test.tsx — two tests, held apart so that "
        '"swallow the error" cannot pass. The first draft asserted on the COLLAPSED overlay and '
        "found the message in neither case, so the 403 test passed while measuring nothing.",
        "npx vitest run src/test/a_refusal_is_not_a_failure.test.tsx",
        _p_refusal_not_failure,
        [S_TDD, S_VBC, S_DEAD],
    ),
    # ── Frontend correctness ───────────────────────────────────────────────
    Finding(
        "LINK-DUP-KEY",
        "A link list rendered what its source did not say",
        "P1",
        "Frontend",
        "This session, 2026-09-14 — found by driving all 93 routes in a browser",
        '`/2fa-setup` listed `/settings` twice in one CrossLinkBar, once as "Settings" and '
        'once as "API Keys", and the four link renderers keyed on destination alone. What a '
        "repeated key does here was MEASURED rather than inferred from React's warning, and "
        "the warning misleads: on first mount both links render and nothing is wrong; on the "
        "next re-render that reorders the list React DUPLICATES the shared key, so a "
        "three-link bar becomes four anchors with a stale pill and the wrong order. It does "
        "not drop anything. Nothing throws, and a test that only mounts sees nothing — which "
        'is why this survived a suite of 2,809. Two separate defects: the DATA ("API Keys" '
        "pointed at /settings, not at its tab, so that pill could never reach the page it "
        "names) and the CLASS (CrossLinkBar, RelatedPages, EmptyState and SubPageGrid all "
        "keyed on destination, so any caller passing two routes to one page hits it). Both "
        "fixed; an AST scan of all 482 source files found only two other arrays with a "
        "repeated destination, both already keyed correctly.",
        "frontend/src/test/no_link_is_silently_dropped.test.tsx — five, all red on the "
        "pre-fix tree. They RE-RENDER with a reorder, because a mount-only assertion passes "
        "on the broken tree: the first draft of this test passed against the defect.",
        "npx vitest run src/test/no_link_is_silently_dropped.test.tsx",
        _p_link_dup_key,
        [S_TDD, S_VBC],
    ),
    Finding(
        "CHART-GATE-VACUOUS",
        "The deployed-chart safety gate emptied itself on the repoint it exists to catch",
        "P0",
        "Config",
        "This session, 2026-09-14 — found while confirming DEPLOY-CHART by injection",
        "DEPLOY-CHART's suite proves the chart ArgoCD syncs states all three safety keys and "
        "ships the kill switch. Its header claimed it 'follows `spec.source.path` rather than "
        "naming a directory, so repointing ArgoCD moves the assertions with it instead of "
        "silently emptying them'. It did not: `_charts()` filtered synced paths to those "
        "containing a `Chart.yaml`, and every assertion iterated that list, so a path without "
        "one produced an EMPTY list and each `assert not missing` passed over nothing. "
        "Measured by repointing `spec.source.path` — `docs` (no manifest, no posture) and "
        "`invariants` (no yaml at all) BOTH left all seven tests green, and those are the "
        "original P0 exactly: ArgoCD syncing a path that carries none of the safety posture. "
        "`deployments/k8s` also passed, having checked nothing. Fixed by resolving every "
        "synced path to (env, manifests) — from values.yaml for a chart, from ConfigMap data "
        "and container env for a plain directory — and adding a second positive control, "
        "because the first asserts only that some Application names a directory and `docs` "
        "satisfies that.",
        "tests/unit/test_the_deployed_chart_carries_the_safety_posture.py — "
        "`test_every_synced_path_is_checkable` is the new control. Red-green by repointing at "
        "the fixed revision: docs 7 pass -> 5 fail, invariants 7 pass -> 6 fail, "
        "deployments/k8s 7 pass -> 8 pass and now actually read. Every repoint was injected, "
        "measured and reverted; the two deployment files are byte-identical to before.",
        "python scripts/correction_register.py --id CHART-GATE-VACUOUS",
        _p_chart_gate_vacuous,
        [S_DEAD, S_VBC],
    ),
    Finding(
        "FIELD-NO-LABEL",
        "Every settings field showed a label and had no accessible name",
        "P1",
        "Frontend",
        "This session, 2026-09-14 — measured with eslint-plugin-jsx-a11y and Chromium's AX tree",
        "`frontend/src/pages/settings/ui.tsx`'s `Field` rendered `<label>Protected Paths</label>` "
        "and then the control as a SIBLING, with no `for` and no id. It is used in ~60 places, "
        "so across every settings page a label was on screen and the control had no name; "
        "clicking the label did nothing. `RiskCalculator`'s `Label` was worse — a styled "
        "`<div>`, no association possible at all — on the page where a mistyped number becomes "
        "a position size. Fixed by making the settings label WRAP its control, which needs no "
        "ids and corrects all ~60 call sites without touching one of them, and by making "
        "RiskCalculator's Label a real `<label>` with `htmlFor` (plus `display:block`, since "
        "`<label>` is inline and the `<div>` it replaces was not). Part of 82 -> 18 on the "
        "jsx-a11y rule, with 29 files leaving a11y-debt.json.",
        "frontend/a11y-debt.json is the ratchet and `src/test/a11y_debt_is_accurate.test.ts` "
        "fails on an entry that no longer describes anything — it caught 29 stale entries the "
        "moment these were fixed. Verified at runtime too: Chromium's accessibility tree "
        "reports 0 controls without an accessible name across all 93 routes, and that probe "
        "was itself injection-tested before being believed.",
        "python scripts/correction_register.py --id FIELD-NO-LABEL",
        _p_field_has_no_label,
        [S_DEAD, S_VBC],
    ),
    # ── Verification capability ────────────────────────────────────────────
    Finding(
        "DRIFT-ABSENCE",
        "A feed outage was scored as feature drift",
        "P1",
        "ML",
        "This session, 2026-09-13 — measured by scripts/drift_guard_report.py",
        "`_check_feature_drift` scored every feature as `|live - train_mean| / std`. A "
        "feature the pipeline could not supply arrives ZERO-FILLED, so its z is large "
        "whenever the training mean is far from zero — and absent data read as drift. "
        "Measured on the shipped stats: 103 of 176 features zero-filled, and 12 of the 14 "
        "exceeding z=4.0 absent rather than drifted; at the deployed chart's z=3.0 it is 15 "
        "of 15. So with DRIFT_BLOCK armed a FEED OUTAGE halts the desk and the log blames "
        "the model — an operator chases a retrain while the real fault is a dead feed. "
        "This became live when DEPLOY-CHART set DRIFT_BLOCK=true on the chart ArgoCD "
        "deploys, which previously set nothing and inherited the false default. Fixed with "
        "the same rule scripts/drift_guard_report.py already used — live exactly zero while "
        "the training mean is not — so the block fires on distribution change, `z_max` is "
        "computed over measured features only (it feeds model-quality scoring, which would "
        "otherwise draw a second wrong conclusion from the same missing data), absence is "
        "logged at ERROR, and both counts reach the status payload. **Whether absence should "
        "itself halt inference is NOT decided here**: it arguably should — a model "
        "predicting from 103 zero-filled features is not predicting from much — but that is "
        "a new gate with its own blast radius, and inventing it would be the same mistake in "
        "the other direction. That is the owner's call.",
        "tests/unit/test_drift_guard_separates_absence_from_drift.py — seven, six red on the "
        "pre-fix tree. Two are controls that matter: a genuine 30-sigma move must STILL be "
        "caught (a guard that stopped reporting drift would pass the main test), and a "
        "feature whose TRAINING mean is legitimately zero must not be exempted — otherwise "
        "the rule becomes a hole in the guard rather than a fix to it.",
        "python scripts/correction_register.py --id DRIFT-ABSENCE",
        _p_drift_absence,
        [S_DEAD, S_VBC],
    ),
    Finding(
        "MIGRATE-OVER-CREATEALL",
        "`alembic upgrade head` cannot run over a database built by `create_all()`",
        "P2",
        "Persistence",
        "This session, 2026-09-13 — reproduced by execution; noted but untracked in docs/audit/TODO.md #3",
        "`create_all()` is called from five places — `database/connection.py`, "
        "`database/models.py`, `cli.py` (twice), `scripts/bootstrap_dev.py` and "
        "`scripts/create_superadmin.py` — so a developer who bootstraps and then runs "
        "`alembic upgrade head` hits this, and a deployment first stood up that way can "
        "**never** be brought under migration control. Reproduced: build the schema with "
        "`Base.metadata.create_all()` (47 tables), then `alembic upgrade head` fails at "
        "`m1n2o3p4q5r6 -> n1o2p3q4r5s6` with `sqlite3.OperationalError: table "
        "trade_journal already exists`. Most migrations define a local `_tbl()` wrapper "
        "that skips an existing table for exactly this reason; three do not, and "
        "`n1o2p3q4r5s6` is simply the first one reached. The fix is to give those three "
        "the same guard their siblings already use — not to change what `create_all()` "
        "does. Recorded in docs/audit/TODO.md as 'still open, deliberately not fixed "
        "here', where nothing measured it; tracked now so it cannot be lost.",
        "**Fixed 2026-09-13.** Both migrations now define the `_tbl()` / `_idx()` guards "
        "their siblings already use. tests/unit/test_migrations_run_over_a_create_all_"
        "database.py carries four, two of them red on the pre-fix tree: upgrade-to-head "
        "over a create_all() database, and the same run twice (an operator re-running a "
        "failed deploy). Two are controls and both earned their place — one asserts "
        "create_all() really produced the colliding table, without which the regression "
        "could pass for want of a collision; the other asserts a FRESH migration run still "
        "creates all 47 tables, because a guard computing `_existing_tables` wrongly would "
        "make every create_table a no-op and leave an empty schema behind a green run. "
        "Verified up -> down -> up as well, and the pre-existing column-level suite "
        "(test_migrated_schema_matches_models.py, 9 tests) still passes.",
        "python scripts/correction_register.py --id MIGRATE-OVER-CREATEALL",
        _p_create_all_upgrade,
        [S_TDD, S_DEBUG],
    ),
    Finding(
        "DEPLOY-CHART",
        "The chart ArgoCD deploys carried none of the safety posture the tests verify",
        "P0",
        "Config",
        "This session, 2026-09-13 — found by following spec.source.path instead of a directory",
        "Twenty-three tests over `k8s/` and `deployments/k8s/` proved HOPEFX_INVARIANT_MODE, "
        "DRIFT_BLOCK, STALE_MODEL_BLOCK, the kill-switch ConfigMap and its RBAC were all "
        "correct. `k8s/argocd-app.yaml` syncs `spec.source.path: helm/hopefx`, which is "
        "neither tree and carried none of them — so the cluster ArgoCD builds ran with "
        "invariants in `monitor` (they observe and never refuse), DRIFT_BLOCK false "
        "(inference continues on a drifted feature distribution), no object for the kill "
        "switch's Redis-outage fallback to patch, and no RBAC to reach one. Worse, "
        "`prune: true` DELETES a kill-switch ConfigMap applied by hand from `k8s/`, "
        "because it is not in the chart. Defaults proven by execution, not read: "
        "`invariants.enforcement._DEFAULT_MODE == 'monitor'`, "
        "`ml.inference_engine._DRIFT_BLOCK is False`. Fixed: values.yaml states all "
        "three keys, and helm/hopefx/templates/kill-switch.yaml ships the ConfigMap, "
        "ServiceAccount, Role and RoleBinding with the same least privilege as `k8s/`.",
        "Carried by tests/unit/test_the_deployed_chart_carries_the_safety_posture.py, which "
        "reads `spec.source.path` rather than naming a directory — so repointing ArgoCD "
        "moves the assertions with it instead of silently emptying them. Five of its seven "
        "assertions fail on the pre-fix tree; its positive control fails if the scan "
        "matches no Application, which is how the first draft's harness bug was caught.",
        "python scripts/correction_register.py --id DEPLOY-CHART",
        _p_deploy_chart,
        [S_DEAD, S_INV, S_TDD],
    ),
    Finding(
        "KS-SELFHEAL",
        "ArgoCD self-heal reverts a pod-engaged kill switch",
        "P0",
        "Config",
        "This session, 2026-09-13 — found while closing F178/F98",
        "Layer 5 of the kill switch engages by a pod PATCHING the `hopefx-kill-switch` "
        'ConfigMap to `kill_switch_active: "true"` through the Kubernetes API. '
        "`k8s/argocd-app.yaml` sets `syncPolicy.automated.selfHeal: true`, whose purpose "
        "in that file's own words is to *revert any manual changes made directly to live "
        "resources* — and a pod's API patch is exactly that, while Git says `false`. The "
        "control of last resort was switched back off by the deployment controller, on the "
        "next reconciliation and again every time it was re-engaged, while every manifest, "
        "RBAC rule and test read correct. Fixed with an `ignoreDifferences` entry on that "
        "ConfigMap's `/data`, which fails safe in both directions: an engaged switch "
        "survives a sync, and the documented reset is a `kubectl patch`, not a Git commit.",
        "Carried by test_kill_switch_layers_survive_deployment.py::"
        "test_self_heal_cannot_revert_an_engaged_kill_switch, plus a companion asserting "
        "RespectIgnoreDifferences stays set — without it the exemption applies only to the "
        "diff view and the defect returns while the Git entry still reads correct.",
        "python scripts/correction_register.py --id KS-SELFHEAL",
        _p_ks_selfheal,
        [S_DEAD, S_INV],
    ),
    Finding(
        "F95",
        "GitHub Actions does not run — every gate below is unverified until it does",
        "OWNER",
        "CI",
        "docs/audit/REMEDIATION_PLAN.md — Phase 0",
        "Not fixable from code. Check GitHub → Billing → Actions. Runs end with no runner "
        "assigned, which is the billing signature.\n\n"
        "**Confirmed against the API 2026-09-13**, so this is measured rather than inferred. "
        "Run 34780841624 on PR #315 (head 3cc8e217): 68 checks, every one `failure`, the "
        "whole run created and closed in 39 seconds — individual jobs in ONE TO THREE "
        "seconds. `GET /actions/jobs/103787449312` returns `runner_id: 0`, `runner_name: "
        '""`, `runner_group_id: 0`, and the job log 404s because nothing ever ran. '
        "Workflow runs ARE still being created — this one is run_number 5740 — so Actions is "
        "not disabled; no job reaches a machine.\n\n"
        "The practical consequence is worth stating plainly, because 68 red checks read as "
        "68 defects: **none of them is a code failure, and a green PR is currently "
        "unreachable by any change to this repository.** A week-old batch of the same "
        "failures (SHAs e55fcc37 and 067086ea, 2026-09-06) shows the identical 1-3 second "
        "signature, so nothing has executed in at least that long either.",
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
        "Done 2026-09-13. `deploy.yml` had no `needs:` and no `workflow_run:`, so the only "
        "thing between a push to main and `docker compose up` on the production VPS was "
        "the push. It now triggers on the CI workflow completing on main and runs only "
        "when the conclusion is `success` — the conclusion check matters as much as the "
        "trigger, because `workflow_run` fires on failure and cancellation too, and a "
        "trigger without it reads as a gate while shipping red builds. "
        "`workflow_dispatch` is allowed through explicitly so a manual deploy still works. "
        "Two consequences, both stated in the workflow: `workflow_run` does not support "
        "`paths-ignore`, so the docs-only skip is gone and a documentation push that "
        "passes CI now redeploys (idempotent, costs runner time); and deployment is now "
        "coupled to CI actually running, which while F95 holds means no deploy — but "
        "deploy.yml is not running today either, so nothing regresses and both return "
        "together when billing is restored.",
        "tests/unit/test_deploy_workflow_is_gated_and_pinned.py asserts the gate exists "
        "and that it requires success rather than mere completion.",
        "pytest tests/unit/test_deploy_workflow_is_gated_and_pinned.py -q",
        _p_f96,
        [S_TDD],
    ),
    Finding(
        "F97",
        "The only action holding `VPS_SSH_KEY` is float-pinned",
        "P1",
        "CI",
        "docs/audit/REMEDIATION_PLAN.md — Phase 0",
        "`appleboy/ssh-action@v1.2.5` was a tag, and a tag is mutable: whoever controls it "
        "controls a step that receives the private deploy key for the production VPS. It was the "
        "only `uses:` in the repository that both takes a secret and floats. **Closed 2026-09-14.** "
        "An earlier session recorded it as a ratchet rather than guessing, because the GitHub API "
        "is scoped to this repository and a guessed SHA breaks every deploy — the right call. The "
        "lookup that does work is `git ls-remote`, which the API being blocked had masked. "
        "Resolved to `0ff4204d59e8e51228ff73bce53f80d53301dee2`, and verified twice before "
        "pinning: `git ls-remote --tags` returns ONE ref for v1.2.5 with no `^{}` peel, so the "
        "tag is lightweight and that IS the commit rather than a tag object; the object was then "
        "fetched and confirmed to be a commit carrying `action.yml`. `_UNPINNED_SECRET_ACTIONS` "
        'is now empty, which cost the ratchet its teeth — with nothing exempted, "no offenders" '
        "is the whole verdict — so the scan now refuses to report clean when it matched nothing, "
        "and a positive control asserts the detector still calls a tagged secret-holding step an "
        "offender. Injection-tested end to end.",
        "tests/unit/test_deploy_workflow_is_gated_and_pinned.py — the ratchet, proven by "
        "injecting a second secret-holding action on a tag and watching it refuse.",
        "pytest tests/unit/test_deploy_workflow_is_gated_and_pinned.py -q",
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
        "Done, in two halves. The write-through, the three ledger tables and the reload "
        "landed first. They then ran nowhere: `revenue_engine = RevenueSplitEngine()` was "
        "built with no session factory and nothing assigned one, so `if not "
        "self._session_factory: return` was taken on every write and a restart still erased "
        "every creator balance — the persistence was complete, correct and unreachable, and "
        "this probe read FIXED throughout because it only asked whether the code existed. "
        "`monetization.revenue_split.init_revenue_engine` now wires the singleton and reloads "
        "its working set, `core.startup_factories.init_revenue_ledger` calls it, and the "
        "`revenue_ledger` component registers it after `database`. The probe measures both "
        "halves, and `tests/unit/test_creator_ledger_is_actually_persisted.py` executes them "
        "rather than grepping for them.",
        "`tests/unit/test_creator_ledger_is_actually_persisted.py` — four of its six tests "
        "fail on the pre-fix tree; the two that pass are controls proving the persistence "
        "layer itself worked and only the wiring was missing.",
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
        "`create_all()` never ALTERs, so a table with no migration drifts silently between "
        "a fresh install and an upgraded one. **The count was wrong, and that is the "
        "finding.** It read '36 of 44 tables have no migration'; measured with names "
        "resolved rather than matched as text it is 0 of 47. The probe searched the "
        "migration corpus for a string literal beside `create_table(`, and this repository "
        "does not write that: 35 tables are created through a local `_tbl()` idempotency "
        "wrapper, four via `op.create_table(_TABLE, ...)` against a module-level constant, "
        "and three live in `database/user_models.py`, which the probe never read — so a "
        "genuine gap THERE would have been missed entirely. 32 false positives is worse "
        "than no probe: a real missing migration is invisible in that noise, and the figure "
        "was quoted as a P1 in three documents. The CI check F218 asked for now exists as "
        "`scripts/schema_migration_check.py --check`, wired into pre-commit and registered "
        "in GATE_EVIDENCE.toml.",
        "tests/unit/test_schema_migration_check.py, deliberately in two halves. It can "
        "fail: a table added to EITHER models module with no migration is refused, removing "
        "a migration is refused, and a scan finding no tables or no migrations fails closed "
        "rather than certifying a tree it never read. It does not cry wolf: all three real "
        "declaration styles — plain literal, `_tbl()` wrapper, module-level constant — are "
        "exercised against a throwaway tree and must be recognised, because two of the three "
        "are exactly what produced the 32 false positives.",
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
        "The symptom was fixed first and the SHAPE second. `/kyc` was refused by one "
        "string in a hand-maintained tuple of prefixes the catch-all consulted to decide "
        "whether a path was the API's or the React router's — a user following a "
        'verification email got `{"detail":"No route for GET /kyc"}` on a regulatory '
        "gate. Editing that string fixed `/kyc` and left the mechanism, and the mechanism "
        "was wrong in BOTH directions, measured: `/replay/<session>` and `/decision/<id>` "
        "— declared pages with nothing mounted under them — were 404'd as raw JSON on the "
        "listed string alone, while a router at a namespace nobody had added to the list "
        "answered `200 text/html` for every path inside it that had no route. The second "
        "is the dangerous one here: a JSON client gets HTML and a 200, so a missing "
        "endpoint reads as a parse error three layers from the cause. **The list is now "
        "gone.** Ownership is derived from `app.routes` at request time: the server's if "
        "something is registered at the path, at the path + `/`, or strictly BELOW it; "
        "the React router's if nothing is. That last asymmetry is the whole finding — "
        "`/kyc/applicants` makes `/kyc/*` the server's without taking `/kyc` from the "
        "page. Under it sits ONE stated floor, `/api/` and `/ws/`, because derivation "
        "cannot describe a namespace that failed to register and 'the routers did not "
        "load' must not present as an HTML 200 on every API path. The walk it reads is "
        "not optional: this FastAPI records each `include_router` as an opaque "
        "`_IncludedRouter`, and the previous `_claimed_by_a_real_route` check read "
        "`.path` straight off `app.routes` — so it answered 'nothing claims /kyc' while "
        "six `/kyc/*` routes were registered, and the half-fix was correct by accident. "
        "**`/mobile` is a real collision and stays open**: App.tsx declares the page and "
        "`core/router_registry.py` mounts the mobile API sub-application at the same "
        "path, so serving the SPA there would shadow a live API. Renaming the page or "
        "moving the mount to `/api/mobile` is a product choice.",
        "tests/unit/test_the_catchall_derives_api_ownership.py — twelve, five red on the "
        "pre-fix tree, and it covers both directions because a catch-all that swallows an "
        "API path is worse than the bug it fixes: a page sub-path nothing is mounted "
        "under serves the app, and a namespace invented inside the test file (so it "
        "cannot be in any list) still answers its own route, still 404s JSON for a path "
        "it does not have, and is never answered with the SPA shell. Two guard the "
        "measurement rather than the result, per hopefx-dead-controls: one asserts the "
        "route walk can see inside an included router at all (it would otherwise report "
        "'nothing is registered' and the catch-all would serve HTML everywhere, which is "
        "exactly how the previous check was dead), and one holds it against "
        "`core.router_registry.iter_api_routes` so the two walks cannot diverge. "
        "tests/unit/test_every_spa_route_serves_the_app.py still fetches every path "
        "App.tsx declares.",
        "pytest tests/unit/test_the_catchall_derives_api_ownership.py "
        "tests/unit/test_every_spa_route_serves_the_app.py -q",
        _p_f198,
        [S_UI, S_TDD],
    ),
    Finding(
        "F199",
        "`_SPA_ROUTES` is hand-maintained and disagrees with `App.tsx`",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done 2026-09-13, by testing the property instead of syncing the list. The gap "
        "between `_SPA_ROUTES` (60) and App.tsx (88) was never the defect: an unlisted "
        "path reaches the `/{full_path:path}` catch-all and still gets index.html, so the "
        "list is an optimisation. The defect was that the catch-all decided what is a "
        "server path from a hand-maintained prefix STRING — and `kyc`, `mobile` and "
        "`godmode` are both API namespaces and page names, so `/kyc` 404ed with nothing "
        "behind it. It now asks the route table: a bare page path passes through only "
        "when a route or mount really claims it. Every path App.tsx declares is fetched "
        "directly in a test built on the real router registry, so the next router mounted "
        "at a bare prefix fails immediately rather than shadowing a page silently.",
        "tests/unit/test_every_spa_route_serves_the_app.py — extracts the routes from "
        "App.tsx rather than restating them, guards that the extraction still works "
        "before trusting what it reports, and checks the converse (that /api/ is not "
        "swallowed by the SPA).",
        "pytest tests/unit/test_every_spa_route_serves_the_app.py -q",
        _p_f199,
        [S_UI, S_TDD],
    ),
    Finding(
        "F200",
        "`/docs` is blank in every deployment",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Done 2026-09-13. Swagger UI fetches its JS and CSS from jsDelivr and the CSP "
        "admitted neither, so the page rendered empty with the reason visible only in the "
        'browser console. The finding said "blank in every deployment" and the '
        "difference decided the fix: `app.py` and `api/server.py` both set "
        '`docs_url=None if APP_ENV == "production"`, so in production /docs does not '
        "exist at all — it was blank in development, staging and local runs, which is "
        "where people open it. The CDN is now allowed **exactly where the page is "
        "mounted**, and production's `script-src 'self'` is untouched. Vendoring "
        "swagger-ui-dist — the usual answer — was rejected deliberately: `static/` is "
        "gitignored, so it would mean committing ~1.5 MB of vendor JavaScript to serve a "
        "page that does not exist in the environment the CSP protects.",
        "tests/unit/test_docs_page_can_load_its_own_assets.py pins the coupling in both "
        "directions — the CDN is admitted iff the docs are mounted — plus a regression "
        "guard that production script-src stays 'self' with no unsafe-inline, so a "
        "later relaxation cannot pass as part of this fix.",
        "pytest tests/unit/test_docs_page_can_load_its_own_assets.py -q",
        _p_f200,
        [S_UI],
    ),
    Finding(
        "F175",
        "Emoji used as UI icons",
        "P3",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "The plan recorded this as done for `frontend/src` — 'no source file carries "
        "emoji'. It was not: 1,389 across 145 files on 2026-09-13, concentrated exactly "
        "where icons live (PlatformConfiguration.tsx 136, SystemReliabilitySection.tsx "
        "62, Settings.tsx 52). `ui-ux-pro-max` forbids emoji as icons and navConfig.ts "
        "already records the cost (F170): no `currentColor`, so they ignore theme, hover "
        "and disabled state; per-platform rendering; announced literally by a screen "
        "reader. Capped by a ratchet rather than closed by a 154-file codemod, which is "
        "the owner's call.",
        "Carried by test_frontend_emoji_ratchet.py (five injections plus the exclusion "
        "test that keeps 79,148 box-drawing characters out of scope) and "
        "command_palette_follows_nav.test.tsx (the palette follows NAV_ITEMS and renders "
        "no emoji; four of its five assertions fail against the pre-fix component).",
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
        "The block path exists and works — proven in both directions by injection — but the "
        "code default ships false while all four deployment surfaces set it true. Recorded "
        "for decision in ADR 0019, which also carries the two riders this finding omitted: "
        "`MODEL_QUALITY_BLOCK` is advisory for the same reason and its own comment ties it "
        "to this default, and `DRIFT_Z_THRESHOLD` is 4.0 in code against 3.0 in the deployed "
        "chart. The decision is not the one-line flip it looks like: measured 2026-09-13, "
        "12 of the 14 features over the threshold had a live value of exactly 0.0, because a "
        "feature the pipeline cannot supply is zero-filled before the guard sees it. The "
        "guard is largely measuring imputation, so blocking on it today converts a feed "
        "outage into a total trading halt reported as `feature_drift`. Separate the two "
        "before flipping the default — `python scripts/drift_guard_report.py` shows the split.",
        "Whichever default is chosen: a test that shifts a feature past the z-threshold and "
        "asserts the configured behaviour — and one that asserts a zero-filled feature is "
        "not counted as drift, which is the half that decides whether blocking is safe.",
        "python scripts/correction_register.py --id F146",
        _p_f146,
        [S_DEAD],
    ),
    Finding(
        "ADR-LEDGER",
        "Decisions record what was chosen and never what happened",
        "P2",
        "Docs",
        "docs/ai/specs/GROUP4_CONSTITUTION.md Chapter 9 · Group 3 Ch 6 · Group 2 Ch 6",
        "Done 2026-09-13. The constitution requires a Decision Registry AND a Decision Ledger "
        "across seven fields; `scripts/adr.py` enforced the first five, nothing asked for "
        "**actual outcome** or **lessons**, and 0 of 19 records carried either — so every "
        "decision was a minute and none was memory. The governance choice was between a second "
        "artefact and a permitted amendment section, and it went to the second artefact "
        "(**ADR 0020**): `docs/decisions/outcomes/NNNN.md`, keyed by decision number and "
        "deliberately mutable, so ADR immutability keeps no exception to argue about later. "
        "`records()` globs non-recursively, so an outcome is never parsed as a decision record "
        "and `immutability_problems` never sees one — asserted, not left to the glob's shape. "
        "Three rules stop it being a box to tick: `pending` is counted separately from "
        "`observed`, a pending entry needs `Review by:` and an overdue one fails `--check`, and "
        "a `proposed` record is owed nothing. **The back-fill is what earned it**: writing "
        "nineteen entries surfaced two decisions recorded and never applied — 0014's nightly "
        "slow/e2e tier does not exist (210 tests selected by no workflow) and 0016's registry "
        're-subjecting was never made (`subject = "architecture"` still, contested count 3 '
        "not 0 — applied the same day, baseline cleared with it, and now asserted against the "
        "live registry rather than the baseline). Neither was visible from the registry, "
        "because a registry records intent.",
        "Carried by tests/unit/test_adr_outcome_ledger.py — 16 of its 18 cases are red on the "
        "pre-fix tree; the 2 that are green both times are the immutability guards, which must "
        "not change. Positive controls run against this probe: removing one outcome takes it to "
        "OPEN, and flipping nine entries to `pending` takes it to PARTIAL.",
        "python scripts/correction_register.py --id ADR-LEDGER",
        _p_adr_ledger,
        [S_DOC, S_TDD],
    ),
    Finding(
        "LOAD-AMBIGUITY",
        "A refused model artifact was indistinguishable from one never installed",
        "P1",
        "ML",
        "MASTER_OUTSTANDING §A8 — named there as the half engineering may do without a decision",
        "`ml.__init__._try_load` returned `None` for three different things: the file is absent, "
        "`_verify_checksum` REFUSED it (a mismatch, or in production a file that arrived "
        "unlisted — an integrity event), or it passed integrity and failed to unpickle. One "
        "caller could not afford the ambiguity. `_load_from_registry` checks `pkl_file.exists()` "
        "ITSELF before loading, so a `None` there can only mean refused or unreadable — never "
        'absent — and it returned `(None, "")`, which is exactly what it returns when there is '
        "no registry configured at all. `_load_models` is a priority chain (registry-active, "
        "then advanced_oos.pkl, then the macro and baseline pairs), so an integrity refusal on "
        "the ACTIVE model fell through and loaded a DIFFERENT model, with a warning as the only "
        "trace at the decision point. The control fired correctly and the caller carried on — "
        "hopefx-dead-controls, second shape. `load_artifact` now returns absent / refused / "
        "unreadable with a reason; `_try_load` is a thin wrapper over it so its five call sites "
        "are untouched; and the registry path logs a refused active model at CRITICAL, naming "
        "that inference is about to continue on a model that was not the one selected. The "
        "fall-through POLICY is deliberately unchanged — whether an integrity refusal should "
        "halt inference or substitute is the owner's call, and §A8 scopes engineering to making "
        "the distinction available. Also corrected while here: the remediation message told "
        "operators to re-save models on Python 3.10, which is an interpreter neither CI nor "
        "production runs.",
        "`tests/unit/test_artifact_load_distinguishes_refusal_from_absence.py` — six of its "
        "eight fail on the pre-fix tree. It builds a real manifest, tampers one artifact after "
        "recording it, and asserts each outcome separately; the control that passes both ways "
        "is `_try_load` still returning None for every failure, because changing that contract "
        "would be a refactor rather than this fix.",
        "python scripts/correction_register.py --id LOAD-AMBIGUITY",
        _p_load_ambiguity,
        [S_DEAD, S_TDD],
    ),
    Finding(
        "GATE-UNMEASURED",
        "The coverage gate reported a module it never measured as below the floor",
        "P2",
        "Tests",
        "Found 2026-09-14 while recording run.py as debt under ADR 0017",
        "`_run_coverage` returns `(None, reason)` and the reason distinguishes a TIMEOUT from a "
        "run that produced no row. `main` printed the reason as raw output but never passed it "
        "to `_judge`, so the verdict always read *the test may not import the module, or may "
        "fail to collect*. For `run.py` that is simply wrong: it is imported by 74 resolved test "
        "files, nothing is missing, and the gate ran out of its 600s budget — a reader following "
        "the message goes looking for an import that is already there. The summary line then "
        "said `N module(s) below 80% coverage threshold` about a module whose coverage nobody "
        "knows, which is rule 2 — an unmeasured value is absent, never zero — failing inside the "
        "gate that enforces it. `Verdict` now carries `unmeasured`, a timeout says so and names "
        "the resolved test-set size as the likely cost, and the summary counts the two apart. "
        "The conflation was visible only because run.py's debt entry had to explain in prose "
        "what the gate should have said itself.",
        "`tests/unit/test_coverage_gate_says_why_it_could_not_measure.py` — eight of its nine "
        "fail on the pre-fix tree, including one that drives `main` with a stubbed measurement "
        "and asserts the summary does not claim a figure it never took. The control that passes "
        "both ways is the genuine collection failure keeping its original advice, which is right "
        "for the case it was written for.",
        "python scripts/correction_register.py --id GATE-UNMEASURED",
        _p_gate_unmeasured,
        [S_DEAD, S_TDD],
    ),
    Finding(
        "API-TRADING-ROLE",
        "`/health` could not say whether the API process was running a trading engine",
        "P2",
        "Runtime",
        "Found 2026-09-14 from an external source-inspection review (M04), grounded here",
        "Production runs `python app.py` — the Dockerfile's CMD — not `run.py`, so the run-mode "
        "resolver is not in that path at all. `app.py` builds the component registry, the "
        "registry registers `engine`, and `init_trading_engine` auto-starts it whenever "
        "`TRADING_MODE` is not live: `ENGINE_AUTOSTART` defaults to **true** on that branch. "
        "Live is properly gated (it needs ENGINE_AUTOSTART and LIVE_TRADING_ENABLED both), so "
        "the exposure is paper rather than real money. Two things were missing rather than "
        "wrong. `core/health.py::_probe_components` reported api, config, database, cache, auth, "
        "risk_manager, compliance, prop_enforcer, strategy_brain, websocket, email, broker and "
        "kill_switch — and not the engine, so `/health` answered identically whether or not this "
        "process was trading. And `ComponentRegistry.status_summary()` / `all_required_ok()` "
        "carry the docstring 'for health endpoints' with ZERO consumers, written for a caller "
        "that never arrived. `/health` now reports the engine as unavailable / stopped / "
        "healthy. It is deliberately NOT in the `critical` list that decides the overall "
        "verdict: an API-only deployment has no engine by design, and a permanently degraded "
        "field is one operators learn to ignore. `ENGINE_AUTOSTART=false` IS the API-only "
        "profile and already worked — it is reused rather than replaced with a new name, "
        "because a fourth spelling of one run-configuration concept is the defect MODE-SPLIT "
        "was about. What it lacked was documentation (audit F58 said 'documented nowhere'; F118 "
        "downgraded the gating half and left that one standing) and any way to see its effect "
        "from outside the process. Both are now closed.",
        "`tests/unit/test_api_process_declares_its_trading_role.py` — seven of its nine fail on "
        "the pre-fix tree. The two that pass both ways are the API-only profile itself, which "
        "already worked: ENGINE_AUTOSTART=false schedules no engine, and the default paper "
        "deployment still does — the second is the positive control, because 'never trade' "
        "would otherwise pass the first while removing the product.",
        "python scripts/correction_register.py --id API-TRADING-ROLE",
        _p_api_trading_role,
        [S_DEAD, S_TDD, S_DOC],
    ),
    Finding(
        "MODE-SPLIT",
        "The startup plan that is printed is not the system that is started",
        "P1",
        "Runtime",
        "Found 2026-09-14 from an external source-inspection review (M01/M02/M05), reproduced here",
        "`run.py` derived the engine twice, on different conditions: `_get_pipeline` asked "
        "`mode == 'paper' or PAPER_TRADING`, while `_run_trading` asked `PAPER_TRADING or "
        "args.broker == 'paper'`. `--mode paper` sets OANDA_PRACTICE, BROKER, DEFAULT_BROKER and "
        "INGEST_EXCHANGE — never PAPER_TRADING — and the defaults are `--mode paper --broker "
        "oanda`. So plain `python run.py` printed the paper pipeline and started HopeFXEngine, a "
        "different subsystem set. Reproduced by execution: displayed-is-paper=True, "
        "dispatch-takes-paper=False. It did NOT place real orders — `--mode paper` also sets "
        "TRADING_MODE=paper and `_execute_decision` returns before any broker call — and that "
        "second, independent control is what bounded it, which is luck rather than design. Two "
        "name collisions travelled with it: run.py wrote BROKER while `brokers/factory.py` reads "
        "`BROKER_TYPE or BROKER`, so an ambient .env value silently beat the explicit flag; and "
        "`--mode paper` forced OANDA_PRACTICE while `brokers/oanda.py` reads OANDA_ENVIRONMENT, "
        "which nothing set. `core/run_mode.py` now resolves once — a frozen `ResolvedRunMode` "
        "carrying requested mode, effective mode, engine, broker, venue, trading mode, the "
        "environment it implies, its reasons and its conflicts — and `run.py` reads it for both "
        "the printed plan and the dispatch, publishes every name from that one decision, and "
        "exits 2 on a contradiction rather than picking a side. **One regression shipped with the "
        "first version and was caught the next day**: it published TRADING_MODE unconditionally, "
        "so `--mode api` rewrote a deliberate `TRADING_MODE=live` to paper — exactly what the "
        "pre-resolver run.py preserved on purpose, with a comment saying why. Safer-sounding and "
        "still wrong: it is the operator's setting and the API is the production serving "
        "process. Only the two trading run modes pin it now; api and backtest report it and "
        "publish no override, and the probe checks that. M05 travelled with it: CLAUDE.md "
        "and AGENTS.md both documented `--mode api | engine | backtest`, and `engine` has never "
        "been a mode — `python run.py --mode engine` is an argparse error, so an agent following "
        "the two files it is told to read first issued a command that cannot run.",
        "`tests/unit/test_run_mode_resolves_once.py` — all 29 fail on the pre-fix tree. They "
        "assert the printed plan and the resolved engine agree for every combination that used "
        "to diverge, that `_setup_env` publishes BROKER_TYPE and both venue names, that a "
        "contradiction exits 2, and that neither T0 document names a mode the parser rejects. "
        "The mode list is asserted identical in `core/run_mode.py` and `run.py`, because two "
        "copies of one list is how the documented set drifted in the first place.",
        "python scripts/correction_register.py --id MODE-SPLIT",
        _p_mode_resolver,
        [S_DEAD, S_TDD, S_DOC],
    ),
    Finding(
        "ROUTER-OVERRULE",
        "A router policy denial was overruled by the engine that asked for it",
        "P0",
        "Brokers",
        "Found 2026-09-14 from an external source-inspection review (M03), then reproduced here",
        "`hopefx_engine._execute_decision` falls back to a direct `broker.place_order` when "
        "ExecutionEngine is unavailable. On that path it called SmartRouter and then did this: if "
        "the status was `rejected` or `error`, log a warning and place the order anyway. "
        "`rejected` is not only 'no venue was reachable' — `execution/smart_router.py` returns it "
        "for five POLICY denials: `unauthorized:…` (enforce_order_authorization refused, logged "
        "CRITICAL as 'Router BLOCKED order', under a comment reading *no order may reach a broker "
        "without a risk-approval token + decision id*), `spread_too_wide:…`, "
        "`sentiment_blackout:…`, `macro_impact_blackout:…` and `fia_throttle:…` (FIA 3.4). All "
        "five were followed by the order reaching the broker. The purest `hopefx-dead-controls` "
        "shape: the control fires correctly and the caller ignores it. The path runs only when "
        "ExecutionEngine is unavailable, which makes it rare rather than safe — the 12-check "
        "pre-trade gate is absent there too, so the router's verdict was the last policy control "
        "standing. Fixed by classifying the refusal: `_router_refusal_is_terminal` allow-lists "
        "the transport GAPS (`no_brokers_available` — nothing transmitted, and the pre-route "
        "gates already passed to reach it) and treats everything else as terminal. An allow-list, "
        "not a deny-list, so a policy reason added to the router later is terminal by default "
        "rather than silently overruled. `all_brokers_failed:…`, `timeout:…` and an exception out "
        "of the router are terminal too: a broker was reached, so an order may be in flight and "
        "sending another is the duplicate fill ROUTER-TO exists to prevent — recovering those "
        "needs order-identity reconciliation, not a retry.",
        "`tests/unit/test_router_policy_denial_is_terminal.py` — 17 of its 20 tests fail on the "
        "pre-fix tree. They drive the real `_execute_decision` with a spy broker rather than "
        "re-implementing its branch. The 3 that pass both ways are controls: a policy-clean "
        "transport gap must STILL be able to place (otherwise 'never trade' passes every other "
        "test), a routed fill must not be sent twice, and the reason strings asserted here are "
        "checked to be strings the router really produces rather than fiction.",
        "python scripts/correction_register.py --id ROUTER-OVERRULE",
        _p_router_overrule,
        [S_DEAD, S_TDD],
    ),
    Finding(
        "WALLET-DEAD",
        "The wallet ledger has no production consumer, so `wallet_transactions` is never written",
        "P0",
        "Money",
        "Found while wiring the creator and affiliate ledgers (F208, F31/F32)",
        "`payments/wallet.py::WalletManager` is 700 lines of correct, tested, exact-Decimal "
        "ledger — balance validation, a rollback when the ledger write is refused, freeze and "
        "transfer paths — and no production module uses it. Measured by an exhaustive sweep of "
        "every tracked `.py`: the only references are its own module, the `payments/__init__.py` "
        "export, `core/app_state.py` declaring the slot as `None`, and "
        "`core/startup_factories.py::init_wallet`, which builds one into `app_state.wallet_manager` "
        "that nothing ever reads. Dynamic access was checked too — no string form of the name "
        "appears anywhere. This is `portfolio/pms.py`'s shape (F158), not F208's: the module is "
        "not merely unwired, it is unreferenced. The user-facing surface reads elsewhere — "
        "`/billing/balance` reads the broker account and the subscription manager, "
        "`/billing/transactions` reads Stripe and subscription events. So `WalletManager` is the "
        "only production writer of `wallet_transactions`, and it never runs: the table is "
        "permanently empty, which is what makes AML-UNREACHED's daily rules unfireable and what "
        "`health_check_service.py` aggregates to zero. The fix is a decision, not a refactor: "
        "either the wallet becomes the ledger the withdrawal path writes through, or it is "
        "retired and AML and the health check are pointed at whatever is authoritative instead. "
        "Deleting it silently is the one wrong answer — the AML rules would then read an empty "
        "table with nothing left to explain why.",
        "Assert a production caller exists: drive a withdrawal through the API and assert a row "
        "lands in `wallet_transactions`. It will fail today, at the point where there is no "
        "path from any endpoint to the ledger.",
        "python scripts/correction_register.py --id WALLET-DEAD",
        _p_wallet_dead,
        [S_MONEY, S_DEAD],
    ),
    Finding(
        "AML-UNREACHED",
        "Every AML withdrawal rule is unreachable in production",
        "P0",
        "Compliance",
        "Found while measuring WALLET-DEAD",
        "`compliance/aml.py::check_withdrawal` enforces a single-transaction cap, a daily "
        "withdrawal count, a daily volume limit and sanctions/PEP screening. It is built "
        "correctly and wired correctly — `core/startup_factories.py::init_aml` hands it a session "
        "factory through the registered `aml` component — and it is never consulted. The gate "
        "itself was proved to work, called directly against a populated ledger: a 40,000 "
        "withdrawal was refused by the 10,000 single cap, and a 100 withdrawal was refused "
        "after six same-day rows by the 5-per-day rule. The defect is reachability, and it is "
        "doubled. `check_withdrawal` has exactly one production call site — "
        "`payments/wallet.py::debit_wallet` — inside the class WALLET-DEAD shows nothing calls. "
        "And the live endpoint that withdraws money, `POST /payments/withdraw`, never mentions "
        "it: it checks KYC through a dependency, a minimum amount and a rate limit, and returns. "
        "What is NOT true today is that money leaves unscreened — that endpoint is documented "
        "NOT YET PERSISTED, queues nothing and disburses nothing. That is exactly why this is "
        "worth fixing now rather than later: the day `FIAT_PROVIDER` is configured and the "
        "endpoint is made real, it would have disbursed without ever touching the gate, and the "
        "gate would still have looked wired at startup to anyone who read it. "
        "**Half-closed 2026-09-13**: `api/payments.py::_screen_withdrawal_for_aml` now consults "
        "the gate before the endpoint returns, refusing with a 403 carrying the gate's own "
        "reason. Strictness mirrors `require_kyc`, which guards the same endpoint — reject in "
        "production when the gate cannot be reached, pass through in development where nothing "
        "wires one, `HOPEFX_REQUIRE_AML_STRICT` overriding either way. The amount crosses as "
        "`Decimal(str(x))`, because the gate compares against Decimal thresholds. The single "
        "cap and sanctions/PEP screening therefore fire today. The daily count and volume rules "
        "still cannot, and no amount of work on this endpoint will change that: they read "
        "`wallet_transactions`, which nothing writes while WALLET-DEAD stands. That is why this "
        "reads PARTIAL rather than FIXED.",
        "`tests/unit/test_withdrawal_is_screened_by_aml.py` — six of its ten tests fail on the "
        "pre-fix tree. A spy proves the call happens; a real `AMLGate` over a real session "
        "factory, driven through the endpoint, proves the refusal is real. The pair that pass "
        "both ways are controls: a sub-minimum request is still rejected on its own terms "
        "without consulting the gate, and a withdrawal under every limit is still allowed, so a "
        "gate that refused everything could not pass as a fix.",
        "python scripts/correction_register.py --id AML-UNREACHED",
        _p_aml_unreached,
        [S_DEAD, S_TDD],
    ),
    Finding(
        "AFF-CENTS",
        "An affiliate commission carried a fraction of a cent that could never be paid",
        "P1",
        "Money",
        "Found while adding the affiliate ledger tables (F31/F32, second half)",
        "`Referral.convert` stored `subscription_amount * commission_rate` raw. Decimal "
        "multiplication keeps every digit, so 10% of 3,333.33 was 333.3330. Reproduced with no "
        "concurrency and no database: withdrawing the 333.33 that *can* be paid left 0.0030 "
        "outstanding, which is below MIN_PAYOUT (100.00) so no withdrawal could ever take it, "
        "and which kept `outstanding_commission` above zero so the referral never reached PAID "
        "— it sat in the CONVERTED working set permanently, showing the affiliate a pending "
        "balance they could not withdraw. The new `Numeric(18, 2)` ledger columns exposed the "
        "same defect from the other side: storage truncated 333.3330 to 333.33, so the "
        "database and memory disagreed about what was owed. Fixed by quantizing to cents with "
        "ROUND_HALF_UP where the commission becomes authoritative, matching "
        "`monetization/revenue_split.py`. `round()` would round half to even, which is not how "
        "money rounds.",
        "`tests/unit/test_affiliate_commission_is_payable_in_cents.py` — eight of its ten tests "
        "fail on the pre-fix tree, including the stranding reproduction above.",
        "python scripts/correction_register.py --id AFF-CENTS",
        _p_aff_cents,
        [S_MONEY, S_TDD],
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
        "Truncation toward zero always takes the same side of the rounding, so the loss "
        "accumulates in one direction. Closed across four sites, in three passes, which is the "
        "point worth keeping: `revenue_split.py` quantizes ROUND_HALF_UP; "
        "`monetization/stripe_integration.py`'s charge and refund now use `to_cents`; "
        "`payments/payment_gateway.py` quantizes inline rather than importing across the "
        "package boundary; and `api/payments.py`'s Stripe deposit was found on 2026-09-13, "
        "months after the others, because the probe scanned `monetization/` and `payments/` and "
        "never looked in `api/`. A 10.999 deposit was collected as 10.99, and 1.005 lost its "
        "cent twice — once to the float's binary error, once to the truncation. The probe now "
        "scans `api/*.py` too, and was injection-tested against exactly that site.",
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
        "**Persistence landed 2026-09-13.** Three tables (`affiliates`, "
        "`affiliate_referrals`, `affiliate_payouts`) with `Numeric(18, 2)` money and a "
        "migration, a write-through on every mutation — the payout and the referrals it "
        "settled in one transaction, so a payout cannot land without them — a reload that "
        "rebuilds the code and user-id indexes as well as the records, and "
        "`init_affiliate_manager` wired by the registered `affiliate_ledger` component. That "
        "last part is the half F208 proves is not optional: the creator ledger's identical "
        "write-through ran nowhere for months because nothing handed the singleton a factory. "
        "Adding the `Numeric(18, 2)` columns also exposed AFF-CENTS — the commission carried a "
        "fraction of a cent that could never be paid.",
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
        "Done: `security/encryption.py`'s copy is renamed `CredentialCipher`, so exactly one "
        "importable class is called `SecureVault` and it is the live one in `config/vault.py` "
        "(Argon2id, crash-safe rotation). Renamed rather than deleted: the module is "
        "load-bearing — `hash_password` has 31 production references and `verify_password` 18 "
        "— so only the misleading name went. The new name is what it is: it holds no "
        "credentials, only a key, a cipher and a salt, which is why `rotate_key` refuses. "
        "This entry previously said that `rotate_key()` 'returns True and destroys every "
        "credential'. Measured by execution 2026-09-13 it RAISES RuntimeError, pinned by "
        "test_rotation_never_returns_true — fixed earlier and never re-measured here, so the "
        "register was describing a danger that had already been closed. What remained, and is "
        "now closed, was the name collision itself. Still true and unaddressed: a random salt "
        "when `HOPEFX_SALT` is unset loses anything this cipher encrypted across a restart — "
        "harmless while nothing in production constructs it, and a trap if anything starts.",
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
        "**Done 2026-09-13.** A file called `*_coverage_boost.py` says what it was written "
        "for rather than what it protects. The last 39 are renamed after the behaviour they "
        "assert, derived from their own test names — `test_execution_coverage6.py` asserts "
        "stop-loss and take-profit breaches, `test_kill_switch_coverage2.py` asserts the "
        "Redis latch, `test_risk_modules_coverage.py` asserts self-trade prevention. The "
        "original finding also said these held the highest concentration of assertion-free "
        "tests; that was true when written and is not now — F108 measures it, and every "
        "unit-test file that defines a test asserts. `docs/audit/CODE_READING_FINDINGS.md` "
        "keeps the original list as the evidence, with a note that the names in it no longer "
        "exist and that `git log --follow` resolves any of them.",
        "None — this is a rename, so the tests are their own regression: all 2,611 in the "
        "renamed files pass and the suite still collects 24,169. The coverage gate pairs a "
        "module to its tests by IMPORT as well as by filename (`_find_test_files`), which is "
        "why renaming does not orphan a module's coverage — verified rather than assumed.",
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
        "`TradeExecutor` was tested against `MagicMock` brokers only. A mock with no spec "
        "agrees with every call, so nothing in the suite could tell a real connector "
        "surface from an invented one. Closed with `create_autospec(..., spec_set=True)` "
        "against all 15 concrete connectors. **The finding's stated cause was wrong, and "
        "this is the correction.** It said F61's mismatch — the executor calling "
        "`place_market_order` while connectors implement `place_order` — would surface at "
        "the first live order, and `grep -c 'def place_market_order' brokers/*.py` returns "
        "1, which appears to confirm it. It does not. "
        "`BrokerConnector.place_market_order` is a CONCRETE base method (brokers/base.py:558) "
        "adapting the router's (symbol, side, quantity) contract onto each connector's "
        "`place_order`, handling sync and async bodies and normalising the result. Every "
        "connector inherits it; a per-file grep cannot see an inherited method, so it "
        "counted the one class that overrides it and called the other fourteen broken. An "
        "adapter was written against that phantom before these tests caught it — carrying a "
        "fallback branch getattr could never reach, a guard that can never open, added "
        "while closing a finding about guards that can never open. It was reverted.",
        "Carried by tests/unit/test_trade_executor_against_real_connectors.py — 37 "
        "assertions across 15 connectors. Three are shaped to fail if a belief drifts: one "
        "fails the moment BrokerConnector.place_market_order is removed (when the "
        "register's original claim would become true), one fails if any override narrows "
        "the signature the executor calls, and a positive control shows in four lines why "
        "a spec-less mock could not have caught either outcome.",
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
        "Done 2026-09-13, and the finding was overstated. It said the page renders zero "
        "h1-h3. It renders one h1 — from the shared `<PageHeader>` component, which a grep "
        "of Dashboard.tsx cannot see. The real gap was the level below: all seven section "
        "titles (Live Equity Curve, Open Positions, Active Signals, Market Regime, Risk "
        "Snapshot, ML Model Accuracy, Quick Navigation) were `<span>`s carrying a "
        "`cardTitle` style, so the page offered one landmark and no way for a screen "
        "reader to move between its regions. They are `<h2>` now; `margin: 0` and the "
        "explicit size neutralise the browser defaults, so the change is semantic with no "
        "visual difference.",
        "frontend/src/test/dashboard_heading_outline.test.tsx asserts the outline against "
        "the RENDERED DOM — one h1, an h2 per named section, and no skipped level — which "
        "is the only way to see a heading a child component contributes.",
        "cd frontend && npx vitest run src/test/dashboard_heading_outline.test.tsx",
        _p_f173,
        [S_UI],
    ),
    Finding(
        "F187",
        "Dashboard metrics do not drill through",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Not a defect, and this register said it was until 2026-09-13. The probe counted "
        "`onClick` in Dashboard.tsx, found one, and concluded the metrics do not drill "
        "through. They do, and did before this audit began: `StatCard` renders a "
        "react-router `<Link>` when given `to`, and all eight headline figures pass one — "
        "Balance to /wallet, Win Rate to /journal, Sharpe and Account DD to /performance, "
        "and so on. Each carries a 44px minimum target, a chevron affordance, and an "
        "`aria-label` naming the figure, its value and what the destination answers. The "
        "component's own docstring cites F187. Counting the wrong mechanism produced a "
        "confident wrong answer on a page this register called the product's front door.",
        "Now covered by frontend/src/test/dashboard_heading_outline.test.tsx, which "
        "resolves the tiles by accessible name and asserts both the href and the target "
        "size.",
        "cd frontend && npx vitest run src/test/dashboard_heading_outline.test.tsx",
        _p_f187,
        [S_UI],
    ),
    Finding(
        "F172",
        "Controls without an accessible name",
        "P2",
        "Frontend",
        "docs/audit/REMEDIATION_PLAN.md — Phase 6",
        "Was deliberately UNVERIFIED: two regex attempts each produced a confident wrong "
        "answer (one said FIXED across 552 buttons, the other found 9 offending files) "
        "because a JSX opening tag cannot be bracketed by a regex — an attribute may contain "
        "`>`, and `onClick={() => nav('/x')}` ends the match at the arrow. **Measured "
        "2026-09-13 with a parser: 138 violations across 67 files.** "
        "`eslint-plugin-jsx-a11y` is now a devDependency and "
        "`jsx-a11y/control-has-associated-label` is an ERROR in eslint.config.js, downgraded "
        "to `warn` only for the files listed in `frontend/a11y-debt.json` — so a violation in "
        "any other file fails `npm run lint` and new debt cannot arrive quietly, while the "
        "existing 67 do not wall off a codebase nobody could then adopt the rule in. "
        "**Classified 2026-09-14, and the original framing was wrong:** exactly ONE of the "
        "138 is a button (input 108, textarea 17, div 5, td 4, th 2, button 1, option 1), and "
        "16 are controls already labelled by a sibling `<label htmlFor>` that a static rule "
        "cannot resolve. The title said icon-only buttons, so a successor would have gone "
        "looking for buttons and found one. **Auth flow cleared 2026-09-14** — Login (3), "
        "Register (4) and Profile (4) are off the list, 138 -> 127 across 64 files. Profile's "
        "three edit-form labels were bound to nothing and its avatar upload had no name at "
        "all; Login and Register were the false-positive shape and were made resolvable with "
        "`aria-labelledby`, not with a duplicated `aria-label`. The rest is follow-up work "
        "and is not this entry.",
        "src/test/a11y_debt_is_accurate.test.ts runs eslint and compares it to the list "
        "entry by entry. Three refusals proven by injection: a listed file with no violations "
        "left must be DELETED from the list (otherwise the entry is a standing permission), a "
        "count that ROSE inside an already-listed file (invisible to eslint, since the whole "
        "file is downgraded), and a new violating file (which eslint also errors on "
        "independently). It uses spawnSync rather than execFileSync because eslint exits "
        "non-zero on this tree's 14 pre-existing errors from other rules, and a throwing call "
        "discarded the JSON and failed with 'Command failed' — a red for the wrong reason. "
        "src/test/auth_flow_controls_have_names.test.tsx asserts the other half, which the "
        "ratchet cannot: that the names RESOLVE in a DOM. A cleared debt entry only says the "
        "rule went quiet. Red-green — the Profile assertions fail on the pre-fix tree "
        "(git stash of the three pages), while Login and Register pass on it, which is the "
        "honest split: those two were already labelled and the change made the association "
        "machine-checkable.",
        "npm run lint · npx vitest run src/test/a11y_debt_is_accurate.test.ts "
        "src/test/auth_flow_controls_have_names.test.tsx",
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
        "commission rate until the following conversion triggers another check — bronze to "
        "platinum is three conversions at 10%, 15% and 20% before the 25% their numbers "
        "already earned. Whether tiers should be skippable is a COMMERCIAL decision rather "
        "than a bug, and is not made here; today's behaviour is pinned by a test that must "
        "be rewritten if the policy changes. What was not a commercial decision, and is "
        "fixed: the shortfall was invisible. The method's name and signature gave a caller "
        "no way to tell 'the next step' from 'the level they qualify for', so an affiliate "
        "was under-paid by omission rather than by policy. `highest_qualifying_level()` now "
        "reports the tier the numbers earn and `tiers_behind()` the gap, so paying below it "
        "is a visible choice someone can price.",
        "tests/unit/test_affiliate_commissions_conserve.py carries five: today's one-step "
        "policy is pinned by name, the earned tier and the gap are asserted against it, a "
        "control proves an up-to-date affiliate reports no gap, and two guard the "
        "arithmetic — that BOTH thresholds are required (`and` becoming `or` is a "
        "one-character change that raises every commission rate and would pass everything "
        "else) and that a tier is earned exactly AT its threshold. Four fail against the "
        "pre-fix module.",
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
        "voters while reading as three. Wiring it stays a quantitative decision — choosing "
        "which of those seven methods is a directional read is a modelling choice, and "
        "picking one to make the count come out right would be inventing a signal, which is "
        "worse than declining to emit one. Two halves of it were NOT that decision and are "
        "fixed: the voter now checks for the capability and declines, warning once per "
        "process rather than raising `AttributeError` on every call; and `bias_with_quorum` "
        "plus `get_summary`'s `bias_voters` / `bias_voters_total` report how many of the "
        "three declared voters answered, so a consumer weighting this signal can see the "
        "quorum instead of reading a majority of two as a majority of three. `get_bias` is "
        "unrouted today — reachable only from `get_summary`, which nothing serves — so "
        "nothing acts on it yet.",
        "tests/unit/test_order_flow_says_when_it_has_no_data.py carries three, all red "
        "against the pre-fix module: the voter declines without raising and warns exactly "
        "once across two calls, `bias_with_quorum` reports fewer voters than it declares, "
        "and `get_summary` carries the quorum beside the bias. The first was written as a "
        "grep for `self._adv.analyze(` and failed against the FIXED code, because the new "
        "docstring quotes the call it replaced — a text match tests how code is written, so "
        "it asserts behaviour instead.",
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
        "(a) **Settled 2026-09-13 by git history, not by asking.** The manifest has ONE "
        "commit (`334e50f3`) and the artifacts hash to `d20ee7a6…`/`4714e96b…` AT THAT "
        "COMMIT while it records `b236e4aa…`/`dc33b5a1…` — so it never described any "
        "committed version of these files; it was wrong the moment it was written. The bytes "
        "on disk are neither the manifest's nor the leak's (`05efdbab`): they are "
        "`776b59cf`, *fix(ml): a missing feature reaches the model as neutral, not as -15 "
        "sigma (F145)* — a named, deliberate regeneration. So there was nothing to restore, "
        "and re-recording blesses a deliberate fix rather than an accident. Both entries "
        "re-recorded; `_verify_checksum` under APP_ENV=production went False -> True for "
        "both, verified by execution before and after. The evidence the two ever disagreed "
        "now lives here and in the commit, which is what the earlier caution was protecting. "
        "**Closed 2026-09-14.** `lstm_signal.pt` was listed and never committed. Inert to "
        "_verify_checksum, which only reads files that exist — but strictly MORE permissive than "
        "not listing it: in production an unlisted file is refused outright (MODEL NOT IN "
        "INTEGRITY BASELINE) while a listed one loads if its bytes match the recorded hash, so a "
        "record for a file nobody has ever shipped is a pre-approved load. It is a training "
        "target of `scripts/train_lstm_signal.py` and the only other use of the name is a "
        "training-job label in `api/ml.py`, so the entry went rather than the file arriving. All "
        "11 remaining entries were then run through `_verify_checksum` under APP_ENV=production "
        "and all 11 returned True. "
        "(b) **Done 2026-09-13 — this half was never an owner decision.** "
        "`ml/advanced_predictor.py` guarded `if self._meta_scaler is not None`, so a "
        "refused or absent scaler removed the transform and fed RAW probabilities into a "
        "Ridge fitted on standardised ones. Its coefficients are in units of standard "
        "deviations from the training mean, so the output is not a probability of "
        "anything — and it was clipped into [0,1] and returned as the ensemble's answer. "
        "Success reported for work that did not happen, on the money path, behind a guard "
        "that reads like an ordinary None check. The blend is now extracted into "
        "`_blend_probabilities`; an unusable meta-blender falls through to the weighted "
        "average — the path this ensemble used before the blender existed, so it is a "
        "fallback rather than a halt — and logs at ERROR once per process instead of "
        "passing silently. `_try_load` still returns None identically for absent and "
        "refused, which matters less now its most consequential caller refuses rather "
        "than degrading. What REMAINS for the owner is (a): which side of each mismatch "
        "is wrong. Meanwhile `scripts/model_provenance_report.py --check` ratchets the "
        "surrounding debt — 12 ungated loaders, 7 unlisted artifacts — so it cannot grow "
        "while (a) is open, and deliberately does not block on the mismatches.",
        "`tests/unit/test_model_artifact_manifest_gate.py::test_the_manifest_describes_exactly_"
        "what_ships` — fails on the pre-fix tree with `['lstm_signal.pt'] are recorded ... but do "
        "not ship`. It asserts both directions, because an artefact that ships WITHOUT an entry "
        "is the 7-unlisted debt and this must not quietly permit a new one. Still uncovered, and "
        "still worth writing: an injection test that corrupts a committed artefact and asserts "
        "the caller can tell refusal from absence.",
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


#: The first line of the generated block. Everything from here to the next
#: top-level heading is the script's; everything either side is a human's.
GENERATED_MARKER = "<!-- generated by scripts/correction_register.py — do not hand-edit this block -->"


def splice(document: str, body: str) -> str:
    """Replace the generated block in ``document`` with ``body``, keeping the prose.

    `--markdown > docs/audit/CORRECTION_REGISTER.md` is the obvious command and
    it is wrong: the document is prose §1-§3, then the generated block, then
    prose §4-§6, and the redirect deletes four of the six sections. It happened
    twice on 2026-09-13, and `--check` agreed both times because it compares
    counts and the counts were right. Only the §4-versus-OWNER test noticed, and
    only because that count had also moved.

    So the splice is the supported operation and the redirect is not.
    """
    start = document.find(GENERATED_MARKER)
    if start < 0:
        raise ValueError(
            "the document has no generated block — refusing to write, because the alternative "
            "is replacing somebody's prose with a table"
        )
    rest = document.index("\n## ", start)
    return document[:start] + body.strip("\n") + "\n" + document[rest:]


def cmd_write(rows: list[tuple[Finding, str, str]], path: Path = REGISTER) -> int:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cmd_markdown(rows)
    document = path.read_text(encoding="utf-8")
    updated = splice(document, buffer.getvalue())
    if updated == document:
        print(f"{path.name}: already current")
        return 0
    path.write_text(updated.rstrip("\n") + "\n", encoding="utf-8")
    print(f"{path.name}: generated block rewritten, {document.count(chr(10) + '## ')} prose section(s) kept")
    return 0


def cmd_markdown(rows: list[tuple[Finding, str, str]]) -> None:
    c = _counts(rows)
    print(GENERATED_MARKER)
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


def cmd_check(rows: list[tuple[Finding, str, str]], path: Path = REGISTER) -> int:
    """Fail if the register document disagrees with the probes.

    `path` is the document to judge, defaulting to the committed register — the
    same shape `cmd_write` already had. `cmd_selftest` passes a throwaway copy,
    so proving this gate can fail no longer requires breaking the real one.
    """
    if not path.exists():
        # `relative_to` raises for a register outside the tree, which is the
        # normal case under HOPEFX_CORRECTION_REGISTER — and raising here would
        # turn "the document is missing" into a traceback.
        try:
            shown: Path | str = path.relative_to(ROOT)
        except ValueError:
            shown = path
        print(f"MISSING {shown} — run --write")
        return 1
    body = path.read_text()
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
        print("  Regenerate: python scripts/correction_register.py --write")
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
    """Prove --check can fail. A gate nobody has watched fail is not a gate.

    The wrong headline goes into a throwaway copy, never into the committed
    register. It used to go into the real document, with the original restored in
    a `finally` — so the one command a contributor is invited to run by hand left
    `docs/audit/CORRECTION_REGISTER.md` holding a deliberately false headline for
    as long as the probes took to run, and anything that killed the process in
    that window left it there.
    """
    if not REGISTER.exists():
        print("selftest: no register to mutate")
        return 1
    original = REGISTER.read_text()
    m = re.search(r"\*\*(\d+) tracked", original)
    if not m:
        print("selftest: no headline to mutate")
        return 1
    broken = original.replace(m.group(0), f"**{int(m.group(1)) + 99} tracked", 1)
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "CORRECTION_REGISTER.md"
        scratch.write_text(broken, encoding="utf-8")
        rc = cmd_check(_measure_all(), path=scratch)
    if rc == 0:
        print("SELFTEST FAILED: --check accepted a wrong count")
        return 1
    print("selftest: --check refused a wrong count, as it must")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markdown", action="store_true", help="emit the register body to stdout")
    ap.add_argument(
        "--write",
        action="store_true",
        help="rewrite the generated block in the document, keeping the prose either side "
        "(do NOT redirect --markdown over the file: it deletes four of the six sections)",
    )
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
    if args.write:
        return cmd_write(rows)
    if args.markdown:
        cmd_markdown(rows)
        return 0
    cmd_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
