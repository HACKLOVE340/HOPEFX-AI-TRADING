#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/repair_model_registry.py
================================
Apply the fix the model-registry audit already prescribes.

``ModelRegistry.audit_manifest()`` correctly diagnoses the deployed CRITICAL finding::

    model_registry  CRITICAL
    1 artifact(s) carry conflicting metrics — including the version serving
    inference; 3 entr(y/ies) disagree with their artifact's own metadata
    (advanced_oos_v1, advanced_oos_v2, xgb_horizon5_v1); 1 artifact file(s)
    missing (mtf_ensemble_v1)

and its remediation text names the fix exactly:

    The <stem>_meta.json beside each artifact is the measurement; a registry
    entry is a copy of it. Entries listed under stale_metrics describe a model
    that was overwritten in place — delete or re-register them. Do not average
    conflicting scores.

There was no way to do any of that. The audit is read-only by design — the
docstring on ``_entries_disagreeing_with_their_artifact`` says so, and it is
right to be: rewriting a stale entry's accuracy to the current artifact's would
assert that the entry describes the current model, and it does not. That is an
operator decision.

So this is the operator's tool for making it. It does not average, and it does
not guess:

* **stale metrics** — an entry whose recorded ``oos_accuracy`` disagrees with
  its artifact's ``_meta.json``. The sidecar is the measurement, written by the
  trainer in the same run that produced the ``.pkl``. ``--resync`` copies the
  measurement onto the entry, which is correct only when the entry is meant to
  describe the *current* artifact. ``--prune-stale`` deletes it instead, which
  is correct when it describes a model that was overwritten in place. There is
  no default: the two are not interchangeable and the tool will not choose.
* **missing artifacts** — an entry pointing at a file that does not exist.
  ``--prune-missing`` removes it. Nothing on disk is deleted.

Nothing is written without ``--apply``. The active version is never pruned
without ``--allow-active``, because removing the entry that serves inference is
not a cleanup.

Usage
-----
    python scripts/repair_model_registry.py                     # report only
    python scripts/repair_model_registry.py --resync --apply
    python scripts/repair_model_registry.py --prune-stale --prune-missing --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run from anywhere: `python scripts/repair_model_registry.py` puts scripts/ on
# sys.path, not the repo root, so `import ml.model_registry` would fail.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UTC = timezone.utc


def _registry():
    from ml.model_registry import get_registry

    return get_registry()


def _print_audit(audit: dict) -> None:
    print(f"Registry: {audit['total_versions']} version(s), active={audit['active_version']!r}")
    if audit["ok"]:
        print("  no findings")
        return

    stale = audit.get("stale_metrics", [])
    if stale:
        print(f"\n  {len(stale)} entr(y/ies) disagree with their artifact's own metadata:")
        for item in stale:
            print(
                f"    {item['version']:<24} recorded={item['recorded_oos_accuracy']:.4f}  "
                f"artifact={item['artifact_oos_accuracy']:.4f}  (trained {item.get('artifact_trained_at')})"
            )

    missing = audit.get("missing_artifacts", [])
    if missing:
        print(f"\n  {len(missing)} entr(y/ies) point at a file that does not exist:")
        for name in missing:
            print(f"    {name}")

    conflicts = audit.get("metric_conflicts", [])
    if conflicts:
        print(f"\n  {len(conflicts)} artifact(s) carry conflicting metrics across entries:")
        for c in conflicts:
            marker = "  <-- SERVING INFERENCE" if c.get("active_among_them") else ""
            print(f"    sha {c['sha256'][:8]}  {', '.join(c['versions'])}{marker}")
            for field, values in c["conflicting"].items():
                print(f"        {field}: {values}")


def _backup(path: Path) -> Path:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(f"{path.name}.{stamp}.bak")
    shutil.copy2(path, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--resync",
        action="store_true",
        help="copy each artifact's measured oos_accuracy onto its registry entry "
        "(correct when the entry is meant to describe the CURRENT artifact)",
    )
    parser.add_argument(
        "--prune-stale",
        action="store_true",
        help="delete entries whose metrics disagree with their artifact "
        "(correct when they describe a model that was overwritten in place)",
    )
    parser.add_argument("--prune-missing", action="store_true", help="delete entries whose artifact file is gone")
    parser.add_argument(
        "--allow-active",
        action="store_true",
        help="permit pruning the version currently serving inference (refused by default)",
    )
    parser.add_argument("--apply", action="store_true", help="write the changes (default: report only)")
    args = parser.parse_args(argv)

    if args.resync and args.prune_stale:
        print(
            "error: --resync and --prune-stale are opposites. Re-syncing asserts the entry describes the "
            "current artifact; pruning asserts it describes one that no longer exists. Pick one.",
            file=sys.stderr,
        )
        return 2

    registry = _registry()
    audit = registry.audit_manifest()
    _print_audit(audit)

    if audit["ok"]:
        return 0
    if not (args.resync or args.prune_stale or args.prune_missing):
        print("\nNo action selected. Re-run with --resync, --prune-stale and/or --prune-missing.")
        print("Nothing has been changed.")
        return 1

    manifest_path = Path(registry._path) if hasattr(registry, "_path") else None
    if manifest_path is None or not manifest_path.exists():
        print("error: could not locate the registry manifest on disk", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text())
    versions = manifest.get("versions", {})
    active = manifest.get("active_version")
    changes: list[str] = []

    if args.resync:
        for item in audit.get("stale_metrics", []):
            name = item["version"]
            if name in versions:
                versions[name]["oos_accuracy"] = item["artifact_oos_accuracy"]
                changes.append(
                    f"resync  {name}: oos_accuracy "
                    f"{item['recorded_oos_accuracy']:.4f} -> {item['artifact_oos_accuracy']:.4f}"
                )

    to_remove: list[str] = []
    if args.prune_stale:
        to_remove += [i["version"] for i in audit.get("stale_metrics", [])]
    if args.prune_missing:
        to_remove += list(audit.get("missing_artifacts", []))

    for name in dict.fromkeys(to_remove):
        if name not in versions:
            continue
        if name == active and not args.allow_active:
            print(
                f"\nrefusing to prune {name!r}: it is the active version serving inference. "
                "Promote another version first, or pass --allow-active if you are certain.",
                file=sys.stderr,
            )
            return 3
        versions.pop(name)
        changes.append(f"prune   {name}")

    if not changes:
        print("\nNothing matched the selected actions.")
        return 0

    print("\nPlanned changes:")
    for line in changes:
        print(f"  {line}")

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply to commit.")
        return 1

    backup = _backup(manifest_path)
    manifest["versions"] = versions
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"\nWritten. Previous manifest saved to {backup.name}")

    after = _registry().audit_manifest()
    print(f"Re-audit: ok={after['ok']}")
    if not after["ok"]:
        _print_audit(after)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
