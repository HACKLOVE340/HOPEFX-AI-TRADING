# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_model_accuracy_assertion.py
=======================================
Model accuracy consistency gate.

Reads ``ml/saved_models/advanced_oos_meta.json`` as the single source of
truth for OOS accuracy, then asserts that every other place in the codebase
that quotes an accuracy figure is within ±2 percentage points of it.

Why this matters
----------------
At one point the project had four different accuracy figures in circulation:
  - advanced_oos_meta.json  → 56.5%  (ground truth, computed by train script)
  - README.md               → 66.4%  (stale from an earlier model)
  - api/signals.py          → 56.5%  (correct)
  - docs/model_performance.md → 66.35% / 68.0%  (stale)
  - CHANGELOG.md            → 66.4% / 68.0%  (historical, not live claims)

When these diverge, operators, regulators, and users see contradictory
claims.  More critically, the deployment gate in api/trading.py reads the
JSON directly — if README.md and api/signals.py are not updated after a
retrain, the live system is running with a model whose real accuracy is
unknown to anyone reading the documentation.

Tolerance
---------
±2 percentage points (0.02 absolute) is intentionally tight.  The model
is retrained periodically; after each retrain the accuracy figures in
README.md, api/signals.py, and docs/model_performance.md must be updated
to match.  A 2pp tolerance accommodates minor rounding differences (e.g.
56.5% vs 56.3%) without allowing the four-figure divergence to recur.

CHANGELOG exemption
-------------------
CHANGELOG.md records historical accuracy figures for past model versions.
These are intentionally not updated when the model is retrained — they are
a historical record.  The gate scans CHANGELOG.md for *current-version*
accuracy claims (lines containing "production model" or "current") but
exempts historical entries (lines containing "v1." version tags or dates
before the current model's training date).

How to fix a failure
--------------------
1. Open ``ml/saved_models/advanced_oos_meta.json`` and read ``oos_accuracy``.
2. Update README.md: replace every OOS accuracy percentage in the performance
   table and the walk-forward section with the new figure.
3. Update api/signals.py: replace the percentage in ``SIGNAL_DISCLAIMER``.
4. Update docs/model_performance.md: replace the OOS accuracy table entry
   and any inline accuracy claims.
5. Re-run this test to confirm all figures are within tolerance.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
OOS_META_PATH = REPO_ROOT / "ml" / "saved_models" / "advanced_oos_meta.json"
README_PATH = REPO_ROOT / "README.md"
SIGNALS_PY_PATH = REPO_ROOT / "api" / "signals.py"
MODEL_PERF_DOC_PATH = REPO_ROOT / "docs" / "model_performance.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

# Tolerance: accuracy figures in docs/code must be within this many percentage
# points of the ground-truth oos_accuracy from the JSON.
TOLERANCE_PP = 2.0  # percentage points (absolute)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches OOS accuracy claims in prose and tables.
# Captures the numeric value before the % sign.
_OOS_ACCURACY_RE = re.compile(
    r"(?:"
    r"OOS\s+accuracy"
    r"|out.of.sample\s+accuracy"
    r"|oos_accuracy"
    r"|walk.forward\s+validated"
    r"|approximately\s+\d"  # "approximately 56.5%"
    r"|accuracy\s+is\s+approximately"
    r")"
    r"[^%\n]{0,80}?(\d{2,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

# Matches the disclaimer pattern in api/signals.py specifically
_DISCLAIMER_RE = re.compile(
    r"(?:approximately|accuracy\s+is)\s+(\d{2,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

# Matches table rows in model_performance.md: "| OOS accuracy | **66.35%** |"
_TABLE_ACCURACY_RE = re.compile(
    r"\|\s*OOS\s+accuracy\s*\|[^|]*?(\d{2,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

# Matches inline accuracy claims in model_performance.md prose
_INLINE_ACCURACY_RE = re.compile(
    r"OOS\s+accuracy[:\s]+(\d{2,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

# CHANGELOG: lines that claim to describe the *current* production model
# (not historical entries for past versions)
_CHANGELOG_CURRENT_RE = re.compile(
    r"(?:production\s+model\s+confirmed|current\s+model|live\s+model)"
    r"[^%\n]{0,120}?(\d{2,3}(?:\.\d+)?)\s*%\s*OOS",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_oos_meta() -> dict:
    """Load and return advanced_oos_meta.json."""
    return json.loads(OOS_META_PATH.read_text(encoding="utf-8"))


def _accuracy_pct_from_meta(meta: dict) -> float:
    """Return oos_accuracy as a percentage (0–100 scale)."""
    raw = float(meta["oos_accuracy"])
    # Handle both 0–1 and 0–100 representations
    return raw * 100.0 if raw <= 1.0 else raw


def _check_figures(
    text: str,
    pattern: re.Pattern,
    ground_truth: float,
    source_label: str,
) -> list[str]:
    """
    Scan *text* with *pattern*, return violation strings for any figure that
    deviates from *ground_truth* by more than TOLERANCE_PP.
    """
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in pattern.finditer(line):
            quoted = float(m.group(1))
            delta = abs(quoted - ground_truth)
            if delta > TOLERANCE_PP:
                violations.append(
                    f"  {source_label}:{lineno}  quoted={quoted:.2f}%  "
                    f"actual={ground_truth:.2f}%  delta={delta:.1f}pp  "
                    f"(tolerance=±{TOLERANCE_PP}pp)\n"
                    f"    {line.strip()}"
                )
    return violations


# ---------------------------------------------------------------------------
# Prerequisite tests
# ---------------------------------------------------------------------------


def test_oos_meta_exists() -> None:
    """advanced_oos_meta.json must exist before any accuracy assertion can run."""
    assert OOS_META_PATH.exists(), (
        f"OOS meta file not found: {OOS_META_PATH}\nRun scripts/train_advanced.py to generate it."
    )


def test_oos_meta_has_required_fields() -> None:
    """The meta file must contain oos_accuracy and sharpe_gate."""
    meta = _load_oos_meta()
    assert "oos_accuracy" in meta, (
        "advanced_oos_meta.json is missing 'oos_accuracy'.\nRe-run the training script to regenerate the file."
    )
    assert "sharpe_gate" in meta, (
        "advanced_oos_meta.json is missing 'sharpe_gate'.\nRe-run the training script to regenerate the file."
    )
    assert "gate_passed" in meta.get("sharpe_gate", {}), (
        "advanced_oos_meta.json['sharpe_gate'] is missing 'gate_passed'."
    )


def test_oos_meta_gate_passed() -> None:
    """
    The Sharpe gate must be passed before accuracy figures are meaningful.

    If gate_passed is False the model has not been validated for live trading
    and the accuracy figure should not be quoted anywhere.
    """
    meta = _load_oos_meta()
    gate = meta.get("sharpe_gate", {})
    assert gate.get("gate_passed") is True, (
        f"Sharpe gate has NOT passed: {gate.get('message', 'no message')}\n"
        "Do not quote accuracy figures until the gate passes."
    )


def test_ci_mode_not_active_in_production_model() -> None:
    """
    The saved model must not have been trained in CI mode (HOPEFX_CI=1).

    CI models use n_estimators=20 for speed and are not suitable for live
    trading.  If ci_mode=true is present in the meta file, the deployment
    gate in api/trading.py will block all live orders — but this test catches
    the condition earlier and with a clearer error message.
    """
    meta = _load_oos_meta()
    ci_mode = meta.get("ci_mode", False)
    assert ci_mode is False, (
        "advanced_oos_meta.json has ci_mode=true.\n"
        "The saved model was trained with HOPEFX_CI=1 (fast CI build, n_estimators=20).\n"
        "Retrain with HOPEFX_CI=0 on full data before deploying:\n"
        "  python scripts/train_advanced.py"
    )


# ---------------------------------------------------------------------------
# Gate D1 — README accuracy gate
# ---------------------------------------------------------------------------


def test_readme_accuracy_within_tolerance() -> None:
    """
    Every OOS accuracy percentage quoted in README.md must be within
    ±{TOLERANCE_PP}pp of the ground-truth oos_accuracy in advanced_oos_meta.json.

    Failure means README.md was not updated after the last model retrain.
    Update the accuracy figures in README.md to match the JSON, then re-run.
    """
    assert README_PATH.exists(), f"README.md not found at {README_PATH}"

    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)
    text = README_PATH.read_text(encoding="utf-8")

    violations = _check_figures(text, _OOS_ACCURACY_RE, ground_truth, "README.md")

    if violations:
        pytest.fail(
            f"\nREADME.md accuracy figure(s) are more than {TOLERANCE_PP}pp "
            f"from advanced_oos_meta.json (oos_accuracy={ground_truth:.2f}%).\n"
            "Update README.md to reflect the current model's accuracy:\n\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate D2 — api/signals.py disclaimer accuracy gate
# ---------------------------------------------------------------------------


def test_signals_disclaimer_accuracy_within_tolerance() -> None:
    """
    The accuracy figure in SIGNAL_DISCLAIMER (api/signals.py) must be within
    ±{TOLERANCE_PP}pp of the ground-truth oos_accuracy.

    The disclaimer is shown to users on every signal response.  A stale figure
    is a regulatory risk (misleading marketing claim) and a trust issue.
    """
    assert SIGNALS_PY_PATH.exists(), f"api/signals.py not found at {SIGNALS_PY_PATH}"

    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)
    text = SIGNALS_PY_PATH.read_text(encoding="utf-8")

    violations = _check_figures(text, _DISCLAIMER_RE, ground_truth, "api/signals.py")

    if violations:
        pytest.fail(
            f"\napi/signals.py SIGNAL_DISCLAIMER accuracy figure(s) are more than "
            f"{TOLERANCE_PP}pp from advanced_oos_meta.json "
            f"(oos_accuracy={ground_truth:.2f}%).\n"
            "Update SIGNAL_DISCLAIMER in api/signals.py to reflect the current model:\n\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate D3 — docs/model_performance.md accuracy gate
# ---------------------------------------------------------------------------


def test_model_performance_doc_accuracy_within_tolerance() -> None:
    """
    OOS accuracy figures in docs/model_performance.md must be within
    ±{TOLERANCE_PP}pp of the ground-truth oos_accuracy.

    This document is the primary technical reference for the model.  Stale
    figures here mislead developers, auditors, and regulators.

    Failure: update the OOS accuracy table entry and any inline claims in
    docs/model_performance.md to match advanced_oos_meta.json.
    """
    if not MODEL_PERF_DOC_PATH.exists():
        pytest.skip("docs/model_performance.md not found — skipping")

    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)
    text = MODEL_PERF_DOC_PATH.read_text(encoding="utf-8")

    # Check both table rows and inline prose claims
    violations: list[str] = []
    violations += _check_figures(text, _TABLE_ACCURACY_RE, ground_truth, "docs/model_performance.md")
    violations += _check_figures(text, _INLINE_ACCURACY_RE, ground_truth, "docs/model_performance.md")

    if violations:
        pytest.fail(
            f"\ndocs/model_performance.md accuracy figure(s) are more than "
            f"{TOLERANCE_PP}pp from advanced_oos_meta.json "
            f"(oos_accuracy={ground_truth:.2f}%).\n"
            "Update docs/model_performance.md after each model retrain:\n\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate D4 — docs/ directory scan
# ---------------------------------------------------------------------------


#: Documents that quote an accuracy figure they are not *claiming*.
#:
#: Kept as an explicit path→reason map rather than a glob, so adding one is a
#: visible decision with a written justification. This is the same carve-out
#: already made for ``archive/``: a record of what someone wrote is not a claim
#: about the current model, and forcing it to track retrains would falsify the
#: record. Anything that actually states the platform's accuracy belongs in the
#: scan — do not add it here to make a red test green.
_QUOTATION_ONLY_DOCS: dict[str, str] = {
    "docs/audit/AI_CORE_SPEC.md": (
        "Verbatim transcription of the owner's AI Core build spec. The figures "
        "in it are the spec author's words, not statements about the model "
        "this repo ships; editing them to match a retrain would corrupt the "
        "record it exists to preserve."
    ),
}


def test_every_quotation_only_exclusion_has_a_reason() -> None:
    """An exclusion without a written reason is a loophole, not a carve-out."""
    for path, reason in _QUOTATION_ONLY_DOCS.items():
        assert reason.strip(), f"{path} is excluded with no reason given"
        assert (REPO_ROOT / path).exists(), (
            f"{path} is excluded but does not exist — stale exclusions silently widen the scan's blind spot"
        )


def test_docs_directory_accuracy_within_tolerance() -> None:
    """
    All Markdown files in docs/ that quote OOS accuracy must be within
    ±{TOLERANCE_PP}pp of the ground-truth.

    Scans every .md file in docs/ (excluding archive/) for OOS accuracy
    claims.  Archive files are excluded because they document historical
    model versions and are intentionally not updated.
    """
    docs_dir = REPO_ROOT / "docs"
    if not docs_dir.exists():
        pytest.skip("docs/ directory not found — skipping")

    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)

    violations: list[str] = []

    for md_file in sorted(docs_dir.rglob("*.md")):
        # Skip archive — historical records are intentionally stale
        if "archive" in md_file.parts:
            continue
        # model_performance.md has its own dedicated test above
        if md_file == MODEL_PERF_DOC_PATH:
            continue
        # Documents that quote a figure rather than claim one.
        if str(md_file.relative_to(REPO_ROOT)) in _QUOTATION_ONLY_DOCS:
            continue

        text = md_file.read_text(encoding="utf-8")
        rel = str(md_file.relative_to(REPO_ROOT))
        violations += _check_figures(text, _OOS_ACCURACY_RE, ground_truth, rel)
        violations += _check_figures(text, _TABLE_ACCURACY_RE, ground_truth, rel)

    if violations:
        pytest.fail(
            f"\n{len(violations)} OOS accuracy figure(s) in docs/ are more than "
            f"{TOLERANCE_PP}pp from advanced_oos_meta.json "
            f"(oos_accuracy={ground_truth:.2f}%).\n"
            "Update each file after a model retrain:\n\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate D5 — CHANGELOG current-version accuracy claims
# ---------------------------------------------------------------------------


def test_changelog_current_model_accuracy_within_tolerance() -> None:
    """
    Lines in CHANGELOG.md that explicitly describe the *current* production
    model must quote an accuracy within ±{TOLERANCE_PP}pp of the ground truth.

    Historical entries (documenting past model versions) are intentionally
    exempt — they are a record of what was true at the time.  Only lines
    containing "production model confirmed", "current model", or "live model"
    are checked.
    """
    if not CHANGELOG_PATH.exists():
        pytest.skip("CHANGELOG.md not found — skipping")

    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)
    text = CHANGELOG_PATH.read_text(encoding="utf-8")

    violations = _check_figures(text, _CHANGELOG_CURRENT_RE, ground_truth, "CHANGELOG.md")

    if violations:
        pytest.fail(
            f"\nCHANGELOG.md current-model accuracy claim(s) are more than "
            f"{TOLERANCE_PP}pp from advanced_oos_meta.json "
            f"(oos_accuracy={ground_truth:.2f}%).\n"
            "Update the current-version entry in CHANGELOG.md:\n\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate D6 — cross-consistency: all live-claim files agree with each other
# ---------------------------------------------------------------------------


def test_all_live_accuracy_claims_consistent() -> None:
    """
    The accuracy figures in README.md, api/signals.py, and
    docs/model_performance.md must all agree with each other within
    ±{TOLERANCE_PP}pp.

    If they diverge it means one was updated after a retrain and the others
    were not — a split-brain state that confuses users and auditors.

    This test is a cross-file consistency check independent of the JSON
    ground truth.  It catches the case where the JSON itself is stale but
    two of the three files were updated to a new (correct) value.
    """
    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)

    # Collect figures from each file
    def _collect(path: Path, pattern: re.Pattern) -> list[tuple[float, str]]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        results = []
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in pattern.finditer(line):
                results.append((float(m.group(1)), f"{path.relative_to(REPO_ROOT)}:{lineno}"))
        return results

    readme_figs = _collect(README_PATH, _OOS_ACCURACY_RE)
    signals_figs = _collect(SIGNALS_PY_PATH, _DISCLAIMER_RE)
    doc_figs = (
        _collect(MODEL_PERF_DOC_PATH, _TABLE_ACCURACY_RE) + _collect(MODEL_PERF_DOC_PATH, _INLINE_ACCURACY_RE)
        if MODEL_PERF_DOC_PATH.exists()
        else []
    )

    all_figs = readme_figs + signals_figs + doc_figs
    if len(all_figs) < 2:
        return  # not enough figures to compare — individual tests handle this

    violations: list[str] = []
    for i, (val_a, loc_a) in enumerate(all_figs):
        for val_b, loc_b in all_figs[i + 1 :]:
            delta = abs(val_a - val_b)
            if delta > TOLERANCE_PP:
                violations.append(f"  {loc_a} = {val_a:.2f}%  vs  {loc_b} = {val_b:.2f}%  (delta={delta:.1f}pp)")

    if violations:
        pytest.fail(
            f"\nAccuracy figures across live-claim files differ by more than "
            f"{TOLERANCE_PP}pp from each other.\n"
            f"Ground truth (advanced_oos_meta.json): {ground_truth:.2f}%\n"
            "Update all files to match the JSON after each model retrain:\n\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate D7 — ml/saved_models/ sidecar completeness
# ---------------------------------------------------------------------------


def test_oos_meta_sidecar_completeness() -> None:
    """
    advanced_oos_meta.json must contain all fields required by the deployment
    gate in api/trading.py and the accuracy gate in this test suite.

    Missing fields cause silent failures: the deployment gate may pass with
    a default value of 0.0 accuracy, allowing a broken model into production.
    """
    meta = _load_oos_meta()
    REQUIRED_FIELDS = {
        "oos_accuracy",  # primary accuracy figure (0–1 scale)
        "sharpe_gate",  # gate result dict with gate_passed key
        "oos_n",  # number of OOS bars used for evaluation
        "feature_count",  # number of features in the trained model
        "model_file",  # filename of the serialised model
        "trained_at",  # ISO-8601 timestamp of training run
        "ci_mode",  # False for production models
    }
    missing = REQUIRED_FIELDS - set(meta.keys())
    assert not missing, (
        f"advanced_oos_meta.json is missing required field(s): {sorted(missing)}\n"
        "Re-run the training script to regenerate the file with all required fields."
    )


def test_oos_accuracy_is_realistic() -> None:
    """
    The OOS accuracy must be in a realistic range for a financial ML model.

    Values below 50% indicate the model is worse than random (likely a data
    bug).  Values above 75% indicate overfitting or data leakage.  Either
    condition should block deployment.
    """
    meta = _load_oos_meta()
    accuracy = _accuracy_pct_from_meta(meta)

    assert accuracy >= 50.0, (
        f"OOS accuracy ({accuracy:.2f}%) is below 50% — worse than random.\n"
        "Check for data bugs, label errors, or feature leakage in the training pipeline."
    )
    assert accuracy <= 75.0, (
        f"OOS accuracy ({accuracy:.2f}%) exceeds 75% — likely overfitting or data leakage.\n"
        "Verify the train/test split is clean and there is no look-ahead bias."
    )


# ---------------------------------------------------------------------------
# Informational: print current accuracy figures (always passes)
# ---------------------------------------------------------------------------


def test_print_current_accuracy_figures() -> None:
    """
    Informational: print the current accuracy figures from all sources.

    This test always passes.  Its output in the CI log makes it easy to see
    at a glance whether the figures are in sync after a retrain.
    """
    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)

    def _collect_first(path: Path, pattern: re.Pattern) -> str:
        if not path.exists():
            return "file not found"
        for line in path.read_text(encoding="utf-8").splitlines():
            m = pattern.search(line)
            if m:
                return f"{float(m.group(1)):.2f}%"
        return "no figure found"

    readme_fig = _collect_first(README_PATH, _OOS_ACCURACY_RE)
    signals_fig = _collect_first(SIGNALS_PY_PATH, _DISCLAIMER_RE)
    doc_fig = _collect_first(MODEL_PERF_DOC_PATH, _TABLE_ACCURACY_RE)

    print(
        f"\n--- Accuracy figure audit ---\n"
        f"  advanced_oos_meta.json  : {ground_truth:.2f}%  (ground truth)\n"
        f"  README.md               : {readme_fig}\n"
        f"  api/signals.py          : {signals_fig}\n"
        f"  docs/model_performance  : {doc_fig}\n"
        f"  Tolerance               : ±{TOLERANCE_PP}pp\n"
        f"-----------------------------"
    )
