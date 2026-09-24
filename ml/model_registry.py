# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/model_registry.py
====================
Versioned model manifest with SHA-256 integrity, promotion gate, and
atomic symlink management.

Responsibilities
----------------
- Maintain a JSON manifest (registry.json) that records every registered
  model version: file path, SHA-256 digest, OOS metrics, and promotion state.
- Enforce a promotion gate: a model may only be promoted to ``"active"``
  when its OOS accuracy and Sharpe gate both pass the configured thresholds.
- Provide an atomic symlink ``ml/saved_models/current.pkl`` that always
  points to the active model, updated via a rename-swap so readers never see
  a broken link. The link is relative, so a committed one survives a clone.
- Compute and verify SHA-256 checksums so corrupted or tampered artifacts
  are detected before serving.

Manifest schema (registry.json)
--------------------------------
{
  "schema_version": 1,
  "active_version": "advanced_oos_v3",
  "versions": {
    "advanced_oos_v3": {
      "name": "advanced_oos_v3",
      "file": "advanced_oos.pkl",
      "sha256": "<hex>",
      "registered_at": "<iso8601>",
      "promoted_at": "<iso8601 | null>",
      "state": "active | staging | retired",
      "oos_accuracy": 0.6635,
      "oos_auc": 0.7108,
      "oos_p_value": 0.0,
      "sharpe_gate_passed": true,
      "n_trades": 1260,
      "sharpe": 1.52,
      "feature_count": 176,
      "notes": ""
    }
  }
}

Promotion gate thresholds (overridable via env)
-----------------------------------------------
REGISTRY_MIN_OOS_ACC   — minimum OOS accuracy (default: 0.60)
REGISTRY_MAX_OOS_PVAL  — maximum OOS p-value  (default: 0.05)
REGISTRY_REQUIRE_SHARPE_GATE — require sharpe_gate_passed=True (default: true)

Usage
-----
    from ml.model_registry import ModelRegistry, get_registry

    reg = get_registry()

    # Register a newly trained model
    version = reg.register(
        name="advanced_oos_v4",
        file_path=Path("ml/saved_models/advanced_oos_v4.pkl"),
        oos_accuracy=0.671,
        oos_auc=0.718,
        oos_p_value=0.0,
        sharpe_gate_passed=True,
        n_trades=1400,
        feature_count=176,
    )

    # Promote to active (runs gate checks)
    reg.promote(version["name"])

    # Verify integrity of the active model before serving
    ok, msg = reg.verify_active()
    if not ok:
        raise RuntimeError(msg)

    # Get path to the active model
    path = reg.active_path()
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_SAVED = Path(__file__).parent / "saved_models"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_REGISTRY_FILE = _SAVED / "registry.json"
_SYMLINK_NAME = "current.pkl"
_SCHEMA_VERSION = 1

# ── Promotion gate thresholds ─────────────────────────────────────────────────
_MIN_OOS_ACC: float = float(os.getenv("REGISTRY_MIN_OOS_ACC", "0.60"))
_MAX_OOS_PVAL: float = float(os.getenv("REGISTRY_MAX_OOS_PVAL", "0.05"))
_REQUIRE_SHARPE_GATE: bool = os.getenv("REGISTRY_REQUIRE_SHARPE_GATE", "true").lower() != "false"


# ── State vocabulary ──────────────────────────────────────────────────────────
#
# ONE value names the model that serves inference, and it is the one
# ``ml/verify_model.py`` requires and the shipped registry.json records.
# promote() and rollback() used to write "production", so neither could ever
# leave a registry that verify_model accepts, and every reader that looked for
# "production" did not recognise the model actually serving (A0 dry run).
STATE_ACTIVE = "active"
STATE_STAGING = "staging"
STATE_RETIRED = "retired"
#: Written by promote()/rollback() before 2026-09-24. Readers that must act on
#: the serving model (retire it, list it, avoid double-serving) accept it; no
#: writer produces it, and ``ml/verify_model.py`` still refuses it.
LEGACY_ACTIVE_STATES: frozenset[str] = frozenset({"production"})


def is_active_state(state: object) -> bool:
    """True when *state* marks the serving model, in current or legacy vocabulary."""
    return state == STATE_ACTIVE or state in LEGACY_ACTIVE_STATES


class StaleTrainingDataError(RuntimeError, ValueError):
    """Promotion refused: the candidate's training data is missing a
    ``data_end`` or ends more than ``MODEL_MAX_AGE_DAYS`` ago.

    Subclasses both ``RuntimeError`` (what existing promote callers such as
    :meth:`ModelRegistry.bootstrap_from_meta` already catch) and ``ValueError``
    (what the A0 plan specifies), so neither kind of caller is bypassed.
    """


def _max_model_age_days() -> int:
    """The same limit the runtime staleness gate reads; read at call time."""
    return int(os.getenv("MODEL_MAX_AGE_DAYS", "30"))


# ── SHA-256 helper ────────────────────────────────────────────────────────────


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Return the hex SHA-256 digest of *path* (streaming, 1 MiB chunks)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


# ── ModelRegistry ─────────────────────────────────────────────────────────────


class ModelRegistry:
    """
    Versioned model manifest with SHA-256 integrity and promotion gate.

    Thread-safety: manifest reads/writes are protected by a file-level
    write (atomic rename).  Concurrent readers always see a consistent
    snapshot because JSON is written to a temp file then renamed.
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self._path = registry_path or _REGISTRY_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Manifest I/O ──────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        """Load the manifest from disk, returning an empty skeleton if absent."""
        if not self._path.exists():
            return {
                "schema_version": _SCHEMA_VERSION,
                "active_version": None,
                "versions": {},
            }
        try:
            data = json.loads(self._path.read_text())
            # Migrate older manifests that lack schema_version
            data.setdefault("schema_version", _SCHEMA_VERSION)
            data.setdefault("active_version", None)
            data.setdefault("versions", {})
            return data
        except Exception as exc:
            logger.error("ModelRegistry: manifest read error: %s", exc)
            return {
                "schema_version": _SCHEMA_VERSION,
                "active_version": None,
                "versions": {},
            }

    def _save(self, manifest: dict[str, Any]) -> None:
        """Atomically write the manifest via a temp-file rename."""
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, prefix=".registry_tmp_", suffix=".json")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)
            Path(tmp_path).replace(self._path)
        except Exception:  # nosec B110 — cleanup temp file before re-raise
            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()
            raise

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        file_path: Path,
        oos_accuracy: float = 0.0,
        oos_auc: float = 0.0,
        oos_p_value: float = 1.0,
        sharpe_gate_passed: bool = False,
        n_trades: int = 0,
        feature_count: int = 0,
        notes: str = "",
        state: str = STATE_STAGING,
        data_end: str | None = None,
        sharpe: float | None = None,
    ) -> dict[str, Any]:
        """
        Register a model artifact in the manifest.

        Computes the SHA-256 digest of *file_path* and stores the entry
        with ``state="staging"`` by default.  Call :meth:`promote` to
        advance to production.

        Parameters
        ----------
        name          : Unique version identifier (e.g. "advanced_oos_v4").
        file_path     : Absolute or relative path to the .pkl artifact.
        oos_accuracy  : Out-of-sample accuracy from training report.
        oos_auc       : Out-of-sample AUC-ROC.
        oos_p_value   : Binomial p-value (lower is better).
        sharpe_gate_passed : Whether the Sharpe SE gate passed.
        n_trades      : Number of OOS trades used for Sharpe gate.
        feature_count : Number of features the model expects.
        notes         : Free-text annotation.
        state         : Initial state — "staging" or "retired".
        data_end      : ISO date of the last bar in the training data. Required
                        (and must be within MODEL_MAX_AGE_DAYS) for
                        :meth:`promote`; ``trained_at`` alone says when the
                        fit ran, not what market window it learned from.
        sharpe        : OOS Sharpe ratio. ``ml/verify_model.py`` refuses an
                        active model without one >= 1.0, so an entry
                        registered without it can never pass that check.

        Returns
        -------
        The version entry dict as stored in the manifest.

        Raises
        ------
        FileNotFoundError : If *file_path* does not exist.
        ValueError        : If *name* is empty or *state* is invalid.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        if state not in (STATE_STAGING, STATE_RETIRED):
            raise ValueError("state must be 'staging' or 'retired' on registration")

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Model artifact not found: {file_path}")

        logger.info("ModelRegistry: computing SHA-256 for %s …", file_path.name)
        digest = sha256_file(file_path)

        entry: dict[str, Any] = {
            "name": name,
            "file": str(file_path),
            "sha256": digest,
            "registered_at": datetime.now(UTC).isoformat(),
            "promoted_at": None,
            "state": state,
            "oos_accuracy": round(float(oos_accuracy), 6),
            "oos_auc": round(float(oos_auc), 6),
            "oos_p_value": round(float(oos_p_value), 8),
            "sharpe_gate_passed": bool(sharpe_gate_passed),
            "n_trades": int(n_trades),
            "feature_count": int(feature_count),
            "notes": notes,
            "data_end": data_end,
        }
        if sharpe is not None:
            entry["sharpe"] = round(float(sharpe), 6)

        manifest = self._load()
        manifest["versions"][name] = entry
        self._save(manifest)

        logger.info(
            "ModelRegistry: registered %s  sha256=%s…  state=%s",
            name,
            digest[:12],
            state,
        )
        return entry

    # ── Promotion gate ────────────────────────────────────────────────────────

    def _gate_check(self, entry: dict[str, Any]) -> tuple[bool, str]:
        """
        Evaluate promotion gate for *entry*.

        Returns (passed, reason).  All three sub-checks must pass:
          1. OOS accuracy >= _MIN_OOS_ACC
          2. OOS p-value  <  _MAX_OOS_PVAL
          3. sharpe_gate_passed == True  (when _REQUIRE_SHARPE_GATE)
        """
        acc = float(entry.get("oos_accuracy", 0.0))
        pval = float(entry.get("oos_p_value", 1.0))
        sharpe_ok = bool(entry.get("sharpe_gate_passed", False))

        if acc < _MIN_OOS_ACC:
            return False, (
                f"OOS accuracy {acc:.4f} < threshold {_MIN_OOS_ACC:.4f}. "
                "Retrain with more data or tune hyperparameters."
            )
        if pval >= _MAX_OOS_PVAL:
            return False, (
                f"OOS p-value {pval:.6f} >= threshold {_MAX_OOS_PVAL:.4f}. Result is not statistically significant."
            )
        if _REQUIRE_SHARPE_GATE and not sharpe_ok:
            return False, ("Sharpe gate not passed. Run multi-symbol backtest with N >= 600 trades.")
        return True, (f"Gate passed: acc={acc:.4f}, p={pval:.6f}, sharpe_ok={sharpe_ok}")

    @staticmethod
    def _data_recency_check(entry: dict[str, Any]) -> tuple[bool, str]:
        """Refuse a candidate whose training data is unknown or too old.

        A model retrained today on data ending months ago gets a fresh
        ``trained_at`` and would clear the runtime age gate while having
        learned nothing newer than the model it replaces (A0 / MODEL-AGE-IS-MTIME).
        Missing or unparseable ``data_end`` refuses: fail closed.
        """
        limit = _max_model_age_days()
        raw = entry.get("data_end")
        if not raw:
            return False, (
                f"training data ends unknown (no data_end recorded) — cannot show it is within MODEL_MAX_AGE_DAYS ({limit})"
            )
        try:
            end = datetime.fromisoformat(str(raw)).date()
        except ValueError:
            return False, f"training data ends {raw!r}, which is not an ISO date"
        age = (datetime.now(UTC).date() - end).days
        if age > limit:
            return False, f"training data ends {end.isoformat()}, {age} days old > MODEL_MAX_AGE_DAYS ({limit})"
        return True, f"training data ends {end.isoformat()}, {age} days old"

    def _pnl_reconciliation_check(self) -> tuple[bool, str]:
        """
        Check the P&L reconciliation gate from the persisted snapshot.

        Reads data/pnl_reconciliation.json written by PnLReconciler.reconcile().
        Blocks promotion when:
          - No fresh snapshot exists (broker has never been reconciled).
          - The snapshot shows divergence beyond tolerance.
          - Fewer than PNL_RECON_MIN_TRADES confirmed fills exist.

        This check is synchronous and reads only from disk — it does not
        make any broker API calls.  Run ``PnLReconciler.reconcile(broker)``
        before calling promote() to refresh the snapshot.

        Returns (passed, reason).
        """
        try:
            from ml.pnl_reconciler import get_reconciler

            result = get_reconciler().check_gate()
            return result.gate_passed, result.reason
        except Exception as exc:
            logger.warning("ModelRegistry: P&L reconciliation check failed: %s", exc)
            return False, f"P&L reconciliation gate unavailable: {exc}"

    def promote(self, name: str) -> dict[str, Any]:
        """
        Promote *name* to the active (serving) state.

        Runs two mandatory promotion gates in order.  Both must pass:

        Gate 1 — Statistical quality (``_gate_check``):
          - OOS accuracy >= REGISTRY_MIN_OOS_ACC (default 0.60)
          - OOS p-value  <  REGISTRY_MAX_OOS_PVAL (default 0.05)
          - sharpe_gate_passed == True (when REGISTRY_REQUIRE_SHARPE_GATE)

        Gate 2 — P&L reconciliation (``_pnl_reconciliation_check``):
          - Reads the persisted snapshot from ``data/pnl_reconciliation.json``
            written by ``PnLReconciler.reconcile(broker)``.
          - Blocks when ledger P&L diverges from broker P&L beyond tolerance,
            when fewer than PNL_RECON_MIN_TRADES fills exist, or when no
            fresh snapshot is available.
          - Call ``await PnLReconciler().reconcile(broker)`` before promoting
            to refresh the snapshot.

        On success:
          - Sets ``state="active"`` and ``promoted_at`` in the manifest.
          - Atomically updates the ``current.pkl`` symlink to point at the
            model's artifact file.
          - Retires the previously active version (sets state="retired").

        Parameters
        ----------
        name : Version name to promote.

        Returns
        -------
        The updated version entry.

        Raises
        ------
        KeyError    : If *name* is not in the registry.
        RuntimeError: If either promotion gate fails.
        FileNotFoundError: If the artifact the entry names does not exist.
        """
        manifest = self._load()
        if name not in manifest["versions"]:
            raise KeyError(f"Version '{name}' not found in registry")

        entry = manifest["versions"][name]

        # Gate 0: training-data recency. rollback() deliberately does not run
        # this, so an emergency restore of a validated model stays possible.
        fresh, fresh_reason = self._data_recency_check(entry)
        if not fresh:
            raise StaleTrainingDataError(f"Promotion gate BLOCKED for '{name}': {fresh_reason}")

        # Gate 1: OOS accuracy, p-value, Sharpe
        passed, reason = self._gate_check(entry)
        if not passed:
            raise RuntimeError(f"Promotion gate BLOCKED for '{name}': {reason}")

        # Gate 2: P&L reconciliation — ledger vs broker must agree
        pnl_passed, pnl_reason = self._pnl_reconciliation_check()
        if not pnl_passed:
            raise RuntimeError(f"Promotion gate BLOCKED for '{name}': {pnl_reason}")

        # Resolve before mutating anything: an entry naming no artifact cannot
        # be served, and recording it as active would be a promotion that did
        # not happen.
        artifact = self._require_artifact(name, entry)

        # Retire the currently serving model
        prev_active = manifest.get("active_version")
        if prev_active and prev_active != name:
            prev = manifest["versions"].get(prev_active)
            if prev and is_active_state(prev.get("state")):
                prev["state"] = STATE_RETIRED
                logger.info(
                    "ModelRegistry: retired previous active model '%s'",
                    prev_active,
                )

        # Promote
        now = datetime.now(UTC).isoformat()
        entry["state"] = STATE_ACTIVE
        entry["promoted_at"] = now
        manifest["active_version"] = name
        self._save(manifest)

        # Atomic symlink update
        self._update_symlink(artifact)

        logger.info(
            "ModelRegistry: promoted '%s' to active  sha256=%s…",
            name,
            entry["sha256"][:12],
        )

        # Notify the live performance monitor so it starts tracking the new version
        try:
            from ml.performance_monitor import get_monitor

            get_monitor().on_model_promoted(
                new_version=name,
                previous_version=prev_active,
            )
        except Exception as _mon_exc:
            logger.debug("ModelRegistry: performance monitor notify failed: %s", _mon_exc)

        return entry

    def _resolve_artifact(self, entry: dict[str, Any]) -> Path:
        """Where the artifact *entry* describes lives on disk.

        ``file`` is the one field :meth:`register` writes, and the only one read
        here. The shipped entries record it relative to the repository root
        (``ml/saved_models/advanced_oos.pkl``), so a bare ``Path(...)`` resolved
        against the working directory named nothing whenever the process was not
        started from the root. Tried in order: absolute as given; the repository
        root; the working directory; the registry's own directory by basename.
        The first that exists wins; if none does, the root-relative path is
        returned so the error names where it was expected.
        """
        raw = Path(str(entry.get("file") or ""))
        if raw.is_absolute():
            return raw
        candidates = [_REPO_ROOT / raw, Path.cwd() / raw, self._path.parent / raw.name]
        for candidate in candidates:
            if raw.name and candidate.exists():
                return candidate
        return candidates[0]

    def _require_artifact(self, name: str, entry: dict[str, Any]) -> Path:
        """Resolve *entry*'s artifact, or refuse before anything is mutated."""
        artifact = self._resolve_artifact(entry)
        if not entry.get("file") or not artifact.exists():
            raise FileNotFoundError(
                f"Version '{name}' names artifact {entry.get('file')!r}, which does not exist "
                f"(looked for {artifact}); current.pkl cannot be pointed at it."
            )
        return artifact

    def _update_symlink(self, target: Path) -> None:
        """
        Atomically update ``current.pkl`` symlink to point at *target*.

        Uses a temp-symlink + rename so readers never see a broken link. The
        link is written RELATIVE to the registry directory: the shipped
        ``current.pkl -> advanced_oos.pkl`` is committed, and an absolute link
        written in one checkout names a path that does not exist after a
        clone, which ``ml/verify_model.py`` then reports as a missing symlink.
        """
        symlink = self._path.parent / _SYMLINK_NAME
        tmp_link = self._path.parent / f".current_tmp_{os.getpid()}.pkl"

        abs_target = target.resolve()
        try:
            link_target: str | Path = os.path.relpath(abs_target, symlink.parent.resolve())
        except ValueError:  # different drive on Windows: no relative form exists
            link_target = abs_target

        try:
            # Remove stale temp link if it exists
            if tmp_link.exists() or tmp_link.is_symlink():
                tmp_link.unlink()
            tmp_link.symlink_to(link_target)
            tmp_link.replace(symlink)
            logger.info("ModelRegistry: symlink %s → %s", symlink.name, abs_target.name)
        except (OSError, NotImplementedError) as exc:
            logger.warning("ModelRegistry: symlink update failed (%s); skipping symlink", exc)

    # ── Integrity verification ────────────────────────────────────────────────

    def verify(self, name: str) -> tuple[bool, str]:
        """
        Verify the SHA-256 digest of a registered model version.

        Returns (True, ok_msg) or (False, error_msg).
        """
        manifest = self._load()
        if name not in manifest["versions"]:
            return False, f"Version '{name}' not found in registry"

        entry = manifest["versions"][name]
        artifact = Path(entry["file"])
        if not artifact.exists():
            return False, f"Artifact missing: {artifact}"

        expected = entry.get("sha256", "")
        if not expected:
            return False, f"No SHA-256 stored for '{name}'"

        actual = sha256_file(artifact)
        if actual != expected:
            return False, (f"SHA-256 MISMATCH for '{name}': expected {expected[:16]}… got {actual[:16]}…")
        return True, f"Integrity OK: {name}  sha256={actual[:16]}…"

    def verify_active(self) -> tuple[bool, str]:
        """Verify the integrity of the currently active model."""
        manifest = self._load()
        active = manifest.get("active_version")
        if not active:
            return False, "No active model in registry"
        return self.verify(active)

    def audit_manifest(self) -> dict[str, Any]:
        """Cross-entry consistency check over the whole manifest.

        ``verify()`` answers "do these bytes still hash to what we recorded?"
        one entry at a time, which cannot see a contradiction *between* entries.
        The shipped manifest has one:

            advanced_oos_v1   sha dc7454d8  advanced_oos.pkl  oos_accuracy 0.565
            advanced_oos_v2   sha dc7454d8  advanced_oos.pkl  oos_accuracy 0.565
            xgb_horizon5_v1   sha dc7454d8  advanced_oos.pkl  oos_accuracy 0.565
            xgb_horizon5_v3   sha dc7454d8  advanced_oos.pkl  oos_accuracy 0.5734   ← active

        Four names, one file, one digest — and two different out-of-sample
        accuracies. Identical bytes cannot have scored two different numbers on
        a held-out set, so at least one figure was measured against a model that
        is not this file and then attached to it. The one that disagrees is the
        version currently serving inference, and it is the number the dashboard
        prints as "ML MODEL ACCURACY 57.3%".

        Every per-entry check passes on this manifest: each digest matches its
        file, because it is the same file. Nothing in the system was positioned
        to notice, which is why this is reported rather than repaired — the
        correct accuracy is a measurement, not something a migration can infer.

        Returns a findings dict; ``ok`` is False when anything needs attention.
        """
        manifest = self._load()
        versions: dict[str, dict[str, Any]] = manifest.get("versions", {})

        by_digest: dict[str, list[str]] = {}
        missing: list[str] = []
        for name, entry in versions.items():
            digest = entry.get("sha256", "")
            if digest:
                by_digest.setdefault(digest, []).append(name)
            file_path = entry.get("file", "")
            if file_path and not Path(file_path).exists():
                missing.append(name)

        duplicates = {d: sorted(names) for d, names in by_digest.items() if len(names) > 1}

        conflicts: list[dict[str, Any]] = []
        for digest, names in duplicates.items():
            metrics: dict[str, set] = {}
            for field in ("oos_accuracy", "oos_sharpe", "train_rows"):
                values = {
                    round(float(versions[n][field]), 6)
                    for n in names
                    if versions[n].get(field) is not None and isinstance(versions[n][field], int | float)
                }
                if len(values) > 1:
                    metrics[field] = values
            if metrics:
                conflicts.append(
                    {
                        "sha256": digest,
                        "versions": names,
                        "file": versions[names[0]].get("file", ""),
                        "conflicting": {k: sorted(v) for k, v in metrics.items()},
                        "active_among_them": manifest.get("active_version") in names,
                    }
                )

        stale = self._entries_disagreeing_with_their_artifact(versions)

        return {
            "ok": not conflicts and not missing and not stale,
            "total_versions": len(versions),
            "active_version": manifest.get("active_version"),
            "duplicate_artifacts": duplicates,
            "metric_conflicts": conflicts,
            "missing_artifacts": missing,
            "stale_metrics": stale,
        }

    @staticmethod
    def _entries_disagreeing_with_their_artifact(versions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Entries whose recorded metrics contradict the artifact's own metadata.

        The trainer writes ``<stem>_meta.json`` beside the ``.pkl`` in the same
        run that produces it, so that file is the measurement and a registry
        entry is a copy of it. When a model is retrained **in place** — the same
        filename overwritten — every older entry still points at that path while
        describing the model that used to be there.

        That is what happened here. ``advanced_oos_meta.json`` records
        ``oos_accuracy 0.5734``, trained 2026-06-26, horizon 5. Three registry
        entries over that same file still claim 0.565, from before the retrain.
        Only ``xgb_horizon5_v3`` carries the artifact's real figure, which is why
        it was the odd one out in the conflict above — it is the only entry that
        was updated.

        Reported, not corrected: rewriting the stale entries to 0.5734 would
        assert that they describe the current model, and they do not. They
        describe a model that no longer exists on disk. Deleting them or
        re-registering is an operator decision.
        """
        findings: list[dict[str, Any]] = []
        for name, entry in versions.items():
            artifact = Path(entry.get("file", ""))
            if not artifact.name or not artifact.exists():
                continue
            sidecar = artifact.with_name(f"{artifact.stem}_meta.json")
            if not sidecar.exists():
                continue
            try:
                meta = json.loads(sidecar.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            measured = meta.get("oos_accuracy")
            recorded = entry.get("oos_accuracy")
            if measured is None or recorded is None:
                continue
            try:
                if abs(float(measured) - float(recorded)) > 1e-6:
                    findings.append(
                        {
                            "version": name,
                            "file": str(artifact),
                            "recorded_oos_accuracy": float(recorded),
                            "artifact_oos_accuracy": float(measured),
                            "artifact_trained_at": meta.get("trained_at"),
                            "sidecar": str(sidecar),
                        }
                    )
            except (TypeError, ValueError):
                continue
        return findings

    # ── Queries ───────────────────────────────────────────────────────────────

    def active_version(self) -> dict[str, Any] | None:
        """Return the active version entry, or None."""
        manifest = self._load()
        name = manifest.get("active_version")
        if not name:
            return None
        return manifest["versions"].get(name)

    def active_path(self) -> Path | None:
        """Return the Path to the active model artifact, or None."""
        entry = self.active_version()
        if not entry:
            return None
        return Path(entry["file"])

    def list_versions(self) -> dict[str, dict[str, Any]]:
        """Return all registered versions keyed by name."""
        return dict(self._load()["versions"])

    def get_version(self, name: str) -> dict[str, Any] | None:
        """Return a single version entry by name, or None."""
        return self._load()["versions"].get(name)

    def refresh_digest(self, name: str) -> str:
        """Recompute and persist the SHA-256 digest for *name* after the artifact changes.

        Call this immediately after retraining overwrites a model file so the
        manifest digest stays in sync with the artifact on disk. Without this,
        verify() will report a mismatch for every request after a retrain.

        Parameters
        ----------
        name : Version name whose artifact has been updated.

        Returns
        -------
        The new hex digest string.

        Raises
        ------
        KeyError          : If *name* is not in the registry.
        FileNotFoundError : If the artifact file no longer exists.
        """
        manifest = self._load()
        if name not in manifest["versions"]:
            raise KeyError(f"Version '{name}' not found in registry")

        entry = manifest["versions"][name]
        artifact = Path(entry["file"])
        if not artifact.exists():
            raise FileNotFoundError(f"Artifact missing: {artifact}")

        old_digest = entry.get("sha256", "")
        new_digest = sha256_file(artifact)

        if new_digest == old_digest:
            logger.debug("ModelRegistry: digest unchanged for '%s' (%s…)", name, new_digest[:12])
            return new_digest

        entry["sha256"] = new_digest
        self._save(manifest)
        logger.info(
            "ModelRegistry: digest refreshed for '%s'  old=%s… new=%s…",
            name,
            old_digest[:12],
            new_digest[:12],
        )
        return new_digest

    def retire(self, name: str) -> None:
        """Mark *name* as retired without changing the active version."""
        manifest = self._load()
        if name not in manifest["versions"]:
            raise KeyError(f"Version '{name}' not found in registry")
        manifest["versions"][name]["state"] = STATE_RETIRED
        self._save(manifest)
        logger.info("ModelRegistry: retired '%s'", name)

    def rollback(self, name: str) -> dict[str, Any]:
        """
        Force-promote *name* to active, bypassing quality gates.

        Used exclusively for emergency rollbacks where a previously-validated
        model must be restored immediately without re-running the Sharpe/PnL
        gates. The caller (superadmin endpoint) is responsible for ensuring
        the target version was previously in production or staging.

        Parameters
        ----------
        name : Version name to roll back to.

        Returns
        -------
        The updated version entry.

        Raises
        ------
        KeyError          : If *name* is not in the registry.
        FileNotFoundError : If the artifact *name* records does not exist. The
                            manifest is left untouched: a rollback that cannot
                            repoint ``current.pkl`` must not report itself done.
        RuntimeError      : If ``current.pkl`` does not resolve to the restored
                            artifact afterwards.

        The pointer is repointed from ``file``, the field :meth:`register`
        writes. This used to read ``artifact_path``, which nothing has ever
        written, so ``current.pkl`` kept serving the model being rolled back
        FROM while the manifest named the one rolled back TO (A0 dry run).
        """
        manifest = self._load()
        if name not in manifest["versions"]:
            raise KeyError(f"Version '{name}' not found in registry")

        entry = manifest["versions"][name]
        artifact = self._require_artifact(name, entry)

        # Retire the current active version
        prev_active = manifest.get("active_version")
        if prev_active and prev_active != name:
            prev = manifest["versions"].get(prev_active)
            if prev:
                prev["state"] = STATE_RETIRED
                logger.info("ModelRegistry.rollback: retired previous active '%s'", prev_active)

        # Promote the target version without gate checks
        entry["state"] = STATE_ACTIVE
        entry["promoted_at"] = datetime.now(UTC).isoformat()
        manifest["active_version"] = name
        self._save(manifest)

        self._update_symlink(artifact)
        symlink = self._path.parent / _SYMLINK_NAME
        if symlink.resolve() != artifact.resolve():
            logger.error(
                "ModelRegistry.rollback: manifest names '%s' active but current.pkl resolves to %s, not %s",
                name,
                symlink.resolve(),
                artifact.resolve(),
            )
            raise RuntimeError(
                f"rollback to '{name}' is recorded in the manifest but current.pkl was not repointed at {artifact}"
            )

        logger.info("ModelRegistry.rollback: rolled back to '%s' (gates bypassed)", name)
        return entry

    # ── Bootstrap from existing meta ──────────────────────────────────────────

    def bootstrap_from_meta(
        self,
        meta_path: Path | None = None,
        model_path: Path | None = None,
        name: str = "advanced_oos_v1",
        promote: bool = False,
    ) -> dict[str, Any] | None:
        """
        Seed the registry from an existing ``advanced_oos_meta.json``.

        Useful on first deploy when the registry.json does not yet exist.
        If *name* is already registered, this is a no-op.

        Parameters
        ----------
        meta_path  : Path to advanced_oos_meta.json (default: saved_models/).
        model_path : Path to the .pkl artifact (default: saved_models/advanced_oos.pkl).
        name       : Version name to register under.
        promote    : If True, attempt to promote after registration.

        Returns
        -------
        The version entry dict, or None if the artifact is missing.
        """
        meta_path = meta_path or (_SAVED / "advanced_oos_meta.json")
        model_path = model_path or (_SAVED / "advanced_oos.pkl")

        # Already registered — skip
        manifest = self._load()
        if name in manifest["versions"]:
            logger.debug("ModelRegistry.bootstrap_from_meta: '%s' already registered", name)
            return manifest["versions"][name]

        if not model_path.exists():
            logger.warning("ModelRegistry.bootstrap_from_meta: artifact not found: %s", model_path)
            return None

        # Parse meta
        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except Exception as exc:
                logger.warning("bootstrap_from_meta: meta parse error: %s", exc)

        sg = meta.get("sharpe_gate", {})
        entry = self.register(
            name=name,
            file_path=model_path,
            oos_accuracy=float(meta.get("oos_accuracy", 0.0)),
            oos_auc=float(meta.get("oos_auc", 0.0)),
            oos_p_value=float(meta.get("oos_p_value", 1.0)),
            sharpe_gate_passed=bool(sg.get("gate_passed", False)),
            n_trades=int(sg.get("n_trades", meta.get("oos_n", 0))),
            feature_count=int(meta.get("feature_count", 0)),
            notes="Bootstrapped from advanced_oos_meta.json",
            data_end=meta.get("data_end"),
        )

        if promote:
            try:
                entry = self.promote(name)
            except RuntimeError as exc:
                logger.warning("ModelRegistry.bootstrap_from_meta: promotion blocked: %s", exc)

        return entry


# ── Module-level singleton ────────────────────────────────────────────────────

_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    """Return the module-level ModelRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
