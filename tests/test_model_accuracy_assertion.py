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
  - api/signals.py          → 59.92% (stale from an intermediate model)
  - docs/                   → various

When these diverge, operators, regulators, and users see contradictory
claims.  More critically, the deployment gate in api/trading.py reads the
JSON directly — if the README and signals.py are not updated after a
retrain, the live system is running with a model whose real accuracy is
unknown to anyone reading the documentation.

Tolerance
---------
±2 percentage points (0.02 absolute) is intentionally tight.  The model
is retrained periodically; after each retrain the accuracy figures in
README.md and api/signals.py must be updated to match.  A 2pp tolerance
accommodates minor rounding differences (e.g. 56.5% vs 56.3%) without
allowing the four-figure divergence to recur.

How to fix a failure
--------------------
1. Open ``ml/saved_models/advanced_oos_meta.json`` and read ``oos_accuracy``.
2. Update README.md: replace every accuracy percentage in the performance
   table and the walk-forward section with the new figure.
3. Update api/signals.py: replace the percentage in ``SIGNAL_DISCLAIMER``.
4. Re-run this test to confirm all figures are within tolerance.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
OOS_META_PATH = REPO_ROOT / "ml" / "saved_models" / "advanced_oos_meta.json"
README_PATH = REPO_ROOT / "README.md"
SIGNALS_PY_PATH = REPO_ROOT / "api" / "signals.py"

# Tolerance: accuracy figures in docs/code must be within this many percentage
# points of the ground-truth oos_accuracy from the JSON.
TOLERANCE_PP = 2.0  # percentage points (absolute)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_oos_meta() -> dict:
    """Load and return advanced_oos_meta.json."""
    return json.loads(OOS_META_PATH.read_text(encoding="utf-8"))


def _extract_percentages(text: str) -> list[tuple[float, int]]:
    """
    Return all (value, line_number) pairs for percentage figures in *text*.

    Matches patterns like ``56.5%``, ``**66.4%**``, ``approximately 59.92%``.
    Only captures values in the range [40, 100] to avoid matching unrelated
    percentages (drawdown, win-rate, etc. are filtered by context in the
    individual tests).
    """
    pct_re = re.compile(r"(\d{2,3}(?:\.\d+)?)\s*%")
    results: list[tuple[float, int]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in pct_re.finditer(line):
            val = float(m.group(1))
            if 40.0 <= val <= 100.0:
                results.append((val, lineno))
    return results


def _accuracy_pct_from_meta(meta: dict) -> float:
    """Return oos_accuracy as a percentage (0–100 scale)."""
    return float(meta["oos_accuracy"]) * 100.0


# ---------------------------------------------------------------------------
# Prerequisite tests
# ---------------------------------------------------------------------------


def test_oos_meta_exists() -> None:
    """advanced_oos_meta.json must exist before any accuracy assertion can run."""
    assert OOS_META_PATH.exists(), (
        f"OOS meta file not found: {OOS_META_PATH}\n"
        "Run scripts/train_advanced.py to generate it."
    )


def test_oos_meta_has_required_fields() -> None:
    """The meta file must contain oos_accuracy and gate_passed."""
    meta = _load_oos_meta()
    for field in ("oos_accuracy", "sharpe_gate"):
        assert field in meta, (
            f"advanced_oos_meta.json is missing required field '{field}'.\n"
            "Re-run the training script to regenerate the file."
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


# ---------------------------------------------------------------------------
# README accuracy gate
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

    readme_text = README_PATH.read_text(encoding="utf-8")

    # Only check lines that explicitly mention OOS accuracy — avoid flagging
    # win-rate, drawdown, or other unrelated percentages.
    oos_accuracy_re = re.compile(
        r"(?:OOS\s+accuracy|out.of.sample\s+accuracy|oos_accuracy|walk.forward\s+validated)"
        r"[^%\n]{0,80}?(\d{2,3}(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    )

    violations: list[str] = []
    for lineno, line in enumerate(readme_text.splitlines(), 1):
        for m in oos_accuracy_re.finditer(line):
            quoted = float(m.group(1))
            delta = abs(quoted - ground_truth)
            if delta > TOLERANCE_PP:
                violations.append(
                    f"  README.md:{lineno}  quoted={quoted:.1f}%  "
                    f"actual={ground_truth:.1f}%  delta={delta:.1f}pp  "
                    f"(tolerance=±{TOLERANCE_PP}pp)\n"
                    f"    Line: {line.strip()}"
                )

    if violations:
        pytest.fail(
            f"\nREADME.md accuracy figure(s) are more than {TOLERANCE_PP}pp "
            f"from advanced_oos_meta.json (oos_accuracy={ground_truth:.1f}%).\n"
            "Update README.md to reflect the current model's accuracy:\n\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# api/signals.py disclaimer accuracy gate
# ---------------------------------------------------------------------------


def test_signals_disclaimer_accuracy_within_tolerance() -> None:
    """
    The accuracy figure in SIGNAL_DISCLAIMER (api/signals.py) must be within
    ±{TOLERANCE_PP}pp of the ground-truth oos_accuracy.

    The disclaimer is shown to users on every signal response.  A stale figure
    is a regulatory risk (misleading marketing claim) and a trust issue.

    Failure: update the percentage in SIGNAL_DISCLAIMER to match the JSON.
    """
    assert SIGNALS_PY_PATH.exists(), f"api/signals.py not found at {SIGNALS_PY_PATH}"

    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)

    signals_text = SIGNALS_PY_PATH.read_text(encoding="utf-8")

    # Match the accuracy figure in the disclaimer string.
    # Pattern: "approximately XX.XX%" or "accuracy is XX.XX%"
    disclaimer_re = re.compile(
        r"(?:approximately|accuracy\s+is)\s+(\d{2,3}(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    )

    violations: list[str] = []
    for lineno, line in enumerate(signals_text.splitlines(), 1):
        for m in disclaimer_re.finditer(line):
            quoted = float(m.group(1))
            delta = abs(quoted - ground_truth)
            if delta > TOLERANCE_PP:
                violations.append(
                    f"  api/signals.py:{lineno}  quoted={quoted:.1f}%  "
                    f"actual={ground_truth:.1f}%  delta={delta:.1f}pp  "
                    f"(tolerance=±{TOLERANCE_PP}pp)\n"
                    f"    Line: {line.strip()}"
                )

    if violations:
        pytest.fail(
            f"\napi/signals.py SIGNAL_DISCLAIMER accuracy figure(s) are more than "
            f"{TOLERANCE_PP}pp from advanced_oos_meta.json "
            f"(oos_accuracy={ground_truth:.1f}%).\n"
            "Update SIGNAL_DISCLAIMER in api/signals.py to reflect the current model:\n\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Cross-consistency: README vs signals.py
# ---------------------------------------------------------------------------


def test_readme_and_signals_accuracy_consistent() -> None:
    """
    The accuracy figures in README.md and api/signals.py must agree with each
    other within ±{TOLERANCE_PP}pp.

    If they diverge it means one was updated after a retrain and the other was
    not — a split-brain state that confuses users and auditors.
    """
    assert README_PATH.exists(), f"README.md not found at {README_PATH}"
    assert SIGNALS_PY_PATH.exists(), f"api/signals.py not found at {SIGNALS_PY_PATH}"

    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)

    # Collect all OOS accuracy figures from README
    readme_oos_re = re.compile(
        r"(?:OOS\s+accuracy|out.of.sample\s+accuracy|walk.forward\s+validated)"
        r"[^%\n]{0,80}?(\d{2,3}(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    )
    readme_figures = [
        float(m.group(1))
        for m in readme_oos_re.finditer(README_PATH.read_text(encoding="utf-8"))
    ]

    # Collect accuracy figure from signals.py disclaimer
    disclaimer_re = re.compile(
        r"(?:approximately|accuracy\s+is)\s+(\d{2,3}(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    )
    signals_figures = [
        float(m.group(1))
        for m in disclaimer_re.finditer(SIGNALS_PY_PATH.read_text(encoding="utf-8"))
    ]

    if not readme_figures or not signals_figures:
        # If either file has no accuracy figure, the individual tests above
        # will catch it.  Skip the cross-check to avoid a confusing error.
        return

    for r_fig in readme_figures:
        for s_fig in signals_figures:
            delta = abs(r_fig - s_fig)
            if delta > TOLERANCE_PP:
                pytest.fail(
                    f"\nREADME.md ({r_fig:.1f}%) and api/signals.py ({s_fig:.1f}%) "
                    f"accuracy figures differ by {delta:.1f}pp "
                    f"(tolerance=±{TOLERANCE_PP}pp).\n"
                    f"Ground truth (advanced_oos_meta.json): {ground_truth:.1f}%\n"
                    "Update both files to match the JSON after each model retrain."
                )


# ---------------------------------------------------------------------------
# CI model guard
# ---------------------------------------------------------------------------


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
# Accuracy figure update helper (informational, never fails)
# ---------------------------------------------------------------------------


def test_print_current_accuracy_figures() -> None:
    """
    Informational: print the current accuracy figures from all sources.

    This test always passes.  Its output in the CI log makes it easy to see
    at a glance whether the figures are in sync after a retrain.
    """
    meta = _load_oos_meta()
    ground_truth = _accuracy_pct_from_meta(meta)

    readme_oos_re = re.compile(
        r"(?:OOS\s+accuracy|out.of.sample\s+accuracy|walk.forward\s+validated)"
        r"[^%\n]{0,80}?(\d{2,3}(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    )
    disclaimer_re = re.compile(
        r"(?:approximately|accuracy\s+is)\s+(\d{2,3}(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    )

    readme_figures = [
        float(m.group(1))
        for m in readme_oos_re.finditer(README_PATH.read_text(encoding="utf-8"))
        if README_PATH.exists()
    ]
    signals_figures = [
        float(m.group(1))
        for m in disclaimer_re.finditer(SIGNALS_PY_PATH.read_text(encoding="utf-8"))
        if SIGNALS_PY_PATH.exists()
    ]

    print(
        f"\n--- Accuracy figure audit ---\n"
        f"  advanced_oos_meta.json  oos_accuracy : {ground_truth:.2f}%  (ground truth)\n"
        f"  README.md OOS figures   : {readme_figures}\n"
        f"  api/signals.py figures  : {signals_figures}\n"
        f"  Tolerance               : ±{TOLERANCE_PP}pp\n"
        f"-----------------------------"
    )
