# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
ml/verify_model.py
==================
Model integrity verifier — run in CI and before deployment.

Callers: `scripts/ci/gate_d_model_accuracy.py` (CI Gate D), `ci.yml`,
`retrain.yml`, `quarterly_retrain.yml`, and `scripts/retrain.sh`, which refuses
to deploy when this exits non-zero.

NOT run at process startup, which this line used to claim. `core/main_loop.py`
calls `_verify_model_registry()`, a narrower check that verifies the active
model's SHA-256 via ModelRegistry and nothing else — so the Sharpe floor, the
trade-count credibility floor, the state check and the meta reconciliation
below are enforced before deployment only. A model promoted out of band would
serve without meeting them.

Checks:
  1. current.pkl symlink exists and resolves to a real file
  2. Symlink target matches the registry active_version file
  3. SHA-256 of the pkl matches the registry entry
  4. Active model has sharpe_gate_passed=True
  5. Active model state == "active"
  6. Meta file is consistent with registry (horizon, sharpe, sha256)

Exit codes:
  0 — all checks passed
  1 — one or more checks failed (details printed to stderr)

Usage:
  python -m ml.verify_model
  python ml/verify_model.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

_SAVED = Path(__file__).parent / "saved_models"
_REGISTRY = _SAVED / "registry.json"
_SYMLINK = _SAVED / "current.pkl"
_META = _SAVED / "advanced_oos_meta.json"

_REQUIRED_SHARPE = 1.0  # minimum credible Sharpe for production
_REQUIRED_N = 600  # minimum OOS trades for credible Sharpe


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify() -> list[str]:
    """Return a list of failure messages. Empty list means all checks passed."""
    failures: list[str] = []

    # ── Load registry ─────────────────────────────────────────────────────────
    if not _REGISTRY.exists():
        return [f"registry.json not found at {_REGISTRY}"]
    try:
        reg = json.loads(_REGISTRY.read_text())
    except json.JSONDecodeError as exc:
        return [f"registry.json is not valid JSON: {exc}"]

    active_key = reg.get("active_version")
    if not active_key:
        failures.append("registry.json missing 'active_version'")
        return failures

    versions = reg.get("versions", {})
    if active_key not in versions:
        failures.append(f"active_version '{active_key}' not found in registry versions")
        return failures

    entry = versions[active_key]

    # ── Check 1: symlink exists ───────────────────────────────────────────────
    if not _SYMLINK.exists():
        failures.append(f"current.pkl symlink missing at {_SYMLINK}")
    elif not _SYMLINK.is_symlink():
        failures.append(f"current.pkl is not a symlink — must be a symlink to {entry['file']}")
    else:
        # ── Check 2: symlink resolves to registry file ────────────────────────
        resolved = _SYMLINK.resolve()
        expected = (_SAVED.parent.parent / entry["file"]).resolve()
        # Also accept relative resolution from saved_models dir
        expected_rel = (_SAVED / Path(entry["file"]).name).resolve()
        if resolved not in (expected, expected_rel):
            link_target = os.readlink(_SYMLINK)
            failures.append(
                f"current.pkl → '{link_target}' resolves to {resolved}\n"
                f"  expected: {expected} (registry active_version={active_key})"
            )
        else:
            # ── Check 3: SHA-256 integrity ────────────────────────────────────
            actual_sha = _sha256(resolved)
            expected_sha = entry.get("sha256", "")
            if not expected_sha:
                failures.append(f"registry entry '{active_key}' has no sha256 — cannot verify integrity")
            elif actual_sha != expected_sha:
                failures.append(
                    f"SHA-256 mismatch for {resolved.name}:\n  actual:   {actual_sha}\n  registry: {expected_sha}"
                )

    # ── Check 4: Sharpe gate ──────────────────────────────────────────────────
    sharpe = entry.get("sharpe", 0.0)
    gate_passed = entry.get("sharpe_gate_passed", False)
    n_trades = entry.get("n_trades", 0)

    if not gate_passed:
        failures.append(
            f"active model '{active_key}' has sharpe_gate_passed=False (sharpe={sharpe}, n_trades={n_trades})"
        )
    if sharpe < _REQUIRED_SHARPE:
        failures.append(f"active model '{active_key}' Sharpe={sharpe} < required {_REQUIRED_SHARPE}")
    if n_trades < _REQUIRED_N:
        failures.append(
            f"active model '{active_key}' n_trades={n_trades} < required {_REQUIRED_N} (Sharpe not credible)"
        )

    # ── Check 5: state == "active" ────────────────────────────────────────────
    state = entry.get("state", "unknown")
    if state != "active":
        failures.append(f"active_version '{active_key}' has state='{state}', expected 'active'")

    # ── Check 6: meta consistency ─────────────────────────────────────────────
    if _META.exists():
        try:
            meta = json.loads(_META.read_text())
        except json.JSONDecodeError as exc:
            failures.append(f"advanced_oos_meta.json is not valid JSON: {exc}")
            meta = {}

        # horizon must match
        meta_horizon = meta.get("horizon")
        reg_horizon = entry.get("horizon")
        if meta_horizon is not None and reg_horizon is not None and meta_horizon != reg_horizon:
            failures.append(f"horizon mismatch: meta={meta_horizon}, registry={reg_horizon}")

        # sha256 in meta must match registry
        meta_sha = meta.get("sha256")
        reg_sha = entry.get("sha256")
        if meta_sha and reg_sha and meta_sha != reg_sha:
            failures.append(f"sha256 mismatch between meta ({meta_sha[:12]}…) and registry ({reg_sha[:12]}…)")

        # oos_accuracy must not be null for the active production model
        if meta.get("oos_accuracy") is None:
            failures.append(
                "advanced_oos_meta.json has oos_accuracy=null — "
                "meta is not reconciled with the 50-year OOS run. "
                "Run: python ml/train_advanced.py --years 50 --oos-years 4 --stacking"
            )
    else:
        failures.append(f"advanced_oos_meta.json not found at {_META}")

    return failures


def main() -> int:
    failures = verify()
    if not failures:
        reg = json.loads(_REGISTRY.read_text())
        active_key = reg["active_version"]
        entry = reg["versions"][active_key]
        print(
            f"[verify_model] OK — active={active_key} "
            f"sharpe={entry.get('sharpe')} "
            f"n_trades={entry.get('n_trades')} "
            f"horizon={entry.get('horizon')} "
            f"state={entry.get('state')}"
        )
        return 0
    else:
        print("[verify_model] FAILED:", file=sys.stderr)
        for i, msg in enumerate(failures, 1):
            print(f"  [{i}] {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
