#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate H: WORDMAP.json.example schema validation.
#
# WORDMAP.json.example is the reference file that operators copy to WORDMAP.json.
# If it becomes malformed or loses required structure the scorer silently falls
# back to built-in keywords, which can mask misconfiguration.
#
# This gate validates:
#   1. WORDMAP.json.example is valid JSON.
#   2. It contains the required top-level key ``nuclear_risk``.
#   3. Each category under ``nuclear_risk`` is a dict of str → float.
#   4. All severity floats are in the valid range [0.0, 10.0].
#   5. No category is empty (a category with zero keywords is likely a mistake).
#   6. Each category name matches the allowed pattern (lowercase, underscores).
#   7. Each keyword string is non-empty and reasonably short (≤ 200 chars).
#   8. The example contains at least MIN_CATEGORIES risk categories and
#      MIN_KEYWORDS total keywords (guards against accidental truncation).
#
# Exits 0 on pass, 1 on failure.
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = REPO_ROOT / "WORDMAP.json.example"

MIN_CATEGORIES = 5
MIN_KEYWORDS = 20
CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_KEYWORD_LENGTH = 200


def main() -> int:  # noqa: C901
    violations: list[str] = []

    if not EXAMPLE_PATH.exists():
        print(f"[gate-h] FAIL  {EXAMPLE_PATH.name} not found")
        return 1

    # ── Rule 1: Valid JSON ────────────────────────────────────────────────────
    try:
        data = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[gate-h] FAIL  {EXAMPLE_PATH.name} is not valid JSON: {exc}")
        return 1

    # ── Rule 2: Required top-level key ────────────────────────────────────────
    if "nuclear_risk" not in data:
        violations.append(
            "missing required top-level key `nuclear_risk`"
        )
        # Can't continue structural checks without this key
        _report(violations)
        return 1

    nuclear_risk = data["nuclear_risk"]

    if not isinstance(nuclear_risk, dict):
        violations.append(
            f"`nuclear_risk` must be a JSON object, got {type(nuclear_risk).__name__}"
        )
        _report(violations)
        return 1

    total_keywords = 0

    for category, keywords in nuclear_risk.items():
        # ── Rule 6: category name format ─────────────────────────────────────
        if not CATEGORY_PATTERN.match(category):
            violations.append(
                f"category name `{category}` must be lowercase with underscores only"
            )

        # ── Rule 3: keywords must be dict[str, float] ─────────────────────────
        if not isinstance(keywords, dict):
            violations.append(
                f"category `{category}`: expected a JSON object, "
                f"got {type(keywords).__name__}"
            )
            continue

        # ── Rule 5: no empty categories ───────────────────────────────────────
        if not keywords:
            violations.append(f"category `{category}` has no keywords")
            continue

        for kw, weight in keywords.items():
            # ── Rule 7: keyword string validation ─────────────────────────────
            if not isinstance(kw, str) or not kw.strip():
                violations.append(
                    f"category `{category}`: keyword must be a non-empty string, "
                    f"got {kw!r}"
                )
                continue
            if len(kw) > MAX_KEYWORD_LENGTH:
                violations.append(
                    f"category `{category}`: keyword `{kw[:40]}...` exceeds "
                    f"{MAX_KEYWORD_LENGTH} characters"
                )

            # ── Rule 3 + 4: weight must be float in [0.0, 10.0] ───────────────
            if not isinstance(weight, (int, float)):
                violations.append(
                    f"category `{category}`, keyword `{kw}`: "
                    f"weight must be a number, got {type(weight).__name__}"
                )
            elif not (0.0 <= float(weight) <= 10.0):
                violations.append(
                    f"category `{category}`, keyword `{kw}`: "
                    f"weight {weight} is outside valid range [0.0, 10.0]"
                )

            total_keywords += 1

    # ── Rule 8: minimum size guards ──────────────────────────────────────────
    n_categories = len(nuclear_risk)
    if n_categories < MIN_CATEGORIES:
        violations.append(
            f"`nuclear_risk` has only {n_categories} categories "
            f"(minimum {MIN_CATEGORIES}); possible accidental truncation"
        )
    if total_keywords < MIN_KEYWORDS:
        violations.append(
            f"`nuclear_risk` has only {total_keywords} keywords "
            f"(minimum {MIN_KEYWORDS}); possible accidental truncation"
        )

    if violations:
        _report(violations)
        return 1

    print(
        f"[gate-h] PASS  {EXAMPLE_PATH.name}: "
        f"{n_categories} categories, {total_keywords} keywords, "
        "all weights in [0.0, 10.0]"
    )
    return 0


def _report(violations: list[str]) -> None:
    print(f"[gate-h] FAIL  {EXAMPLE_PATH.name} schema violations:\n")
    for v in violations:
        print(f"  ✗ {v}")
    print(f"\n  {len(violations)} violation(s).")


if __name__ == "__main__":
    sys.exit(main())
