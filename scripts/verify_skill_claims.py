#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/verify_skill_claims.py — check the custom skills against the codebase.

`.claude/skills/README.md` said every factual claim in the custom skills "was
verified against the codebase by an assertion script (26 checks)" and told the
reader to "re-run that verification after any refactor that moves the cited
lines". **The script was not in the repository**, so the claim could not be
re-run and the instruction could not be followed — a verification asserted with
no artifact behind it, which is the shape `hopefx-dead-controls` is about.

This is that script, written for real. It checks the claims that are mechanical
enough to check: constants, defaults, environment variable names, counts, and
whether cited symbols still exist. It cannot check prose, and does not pretend
to: the count it prints is the number of assertions it actually ran.

A skill citing a stale constant is worse than no skill, because it is believed.

Usage:
    python scripts/verify_skill_claims.py           # human report
    python scripts/verify_skill_claims.py --json    # machine-readable

Exit codes: 0 = every claim held, 1 = at least one claim is stale.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SKILLS = REPO_ROOT / ".claude" / "skills"


class Checks:
    """Collects results instead of raising, so one stale claim does not hide the rest."""

    def __init__(self) -> None:
        self.results: list[dict] = []

    def check(self, skill: str, claim: str, ok: bool, detail: str = "") -> None:
        self.results.append({"skill": skill, "claim": claim, "ok": bool(ok), "detail": detail})

    def source(self, rel: str) -> str:
        """The file's **executable** text: docstrings and comments removed.

        The first version of this script matched raw source, and four checks
        came back "STALE" against code that was correct — because each fixed
        file carries a comment quoting the defect it fixed
        (``# if orchestrator._started and not ...``). That is F255, the
        analyzer rule that scanned prose as code, reproduced in a script
        written to check that F255 was fixed.

        Reuses the analyzer's own helpers rather than a new regex, so there is
        one definition of "this line is prose" in the repository.
        """
        path = REPO_ROOT / rel
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8")

        from security.code_analyzer import _build_docstring_lines, _strip_string_literals

        lines = text.splitlines()
        docstring_lines = _build_docstring_lines(lines)
        out: list[str] = []
        for number, line in enumerate(lines, start=1):
            if number in docstring_lines:
                out.append("")
                continue
            hash_at = _strip_string_literals(line).find("#")
            out.append(line[:hash_at] if hash_at != -1 else line)
        return "\n".join(out)

    def raw_source(self, rel: str) -> str:
        """The file as written, prose included — for claims about documentation."""
        path = REPO_ROOT / rel
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @property
    def failures(self) -> list[dict]:
        return [r for r in self.results if not r["ok"]]


def _skill_text(name: str) -> str:
    path = SKILLS / name / "SKILL.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ── Every custom skill must exist and be discoverable ────────────────────────

CUSTOM_SKILLS = (
    "hopefx-money-precision",
    "hopefx-invariants",
    "hopefx-fix-bridge",
    "hopefx-dead-controls",
)


def check_skill_files(c: Checks) -> None:
    for name in CUSTOM_SKILLS:
        path = SKILLS / name / "SKILL.md"
        c.check(name, "SKILL.md exists", path.exists(), str(path.relative_to(REPO_ROOT)))
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        c.check(name, "frontmatter names the directory", f"name: {name}" in text)
        c.check(
            name, "frontmatter has a description", "description:" in text.split("---")[1] if "---" in text else False
        )


# ── hopefx-invariants ────────────────────────────────────────────────────────


def check_invariants(c: Checks) -> None:
    skill = "hopefx-invariants"
    text = _skill_text(skill)

    from invariants.registry import registry_summary

    summary = registry_summary()

    claimed = re.search(r"\*\*(\d+) predicates across (\d+) modules\*\*", text)
    if claimed:
        c.check(
            skill,
            f"predicate count is {claimed.group(1)}",
            summary["predicates"] == int(claimed.group(1)),
            f"actual {summary['predicates']}",
        )
        c.check(
            skill,
            f"module count is {claimed.group(2)}",
            summary["modules"] == int(claimed.group(2)),
            f"actual {summary['modules']}",
        )
    else:
        c.check(skill, "SKILL.md states a predicate count", False, "no '<n> predicates across <m> modules' found")

    # Resolve the default by calling the resolver, not by matching its source.
    # The first version grepped for `HOPEFX_INVARIANT_MODE", "monitor"` and
    # reported the claim stale — the default is real, it just arrives through
    # `_DEFAULT_MODE = MODE_MONITOR`. A text match tests how the code is
    # written; this tests what it does.
    import os as _os

    from invariants.enforcement import current_mode

    _previous = _os.environ.pop("HOPEFX_INVARIANT_MODE", None)
    try:
        resolved = current_mode()
    finally:
        if _previous is not None:
            _os.environ["HOPEFX_INVARIANT_MODE"] = _previous
    c.check(
        skill,
        "HOPEFX_INVARIANT_MODE defaults to 'monitor'",
        resolved == "monitor",
        f"resolved to {resolved!r}",
    )

    enforcement = c.source("invariants/enforcement.py")
    c.check(skill, "enforcement.py is the decision layer", "def _safe(" in enforcement)


# ── hopefx-money-precision ───────────────────────────────────────────────────


def check_money_precision(c: Checks) -> None:
    skill = "hopefx-money-precision"
    oms = c.source("execution/oms.py")
    c.check(skill, "execution/oms.py exists", bool(oms))
    c.check(skill, "the OMS still uses Decimal", "Decimal" in oms)

    # tol=0.01 is a stated risk boundary that must never be widened.
    enforcement = c.source("invariants/enforcement.py")
    ledger = c.source("invariants/payments.py") + enforcement
    c.check(
        skill,
        "the reconciliation tolerance is still 0.01",
        "tol: float = 0.01" in ledger or "tol=0.01" in ledger,
        "a widened tolerance is a silent risk change",
    )

    risk_manager = c.source("risk/manager.py")
    c.check(skill, "risk/manager.py is still float-based", bool(risk_manager) and "Decimal(" not in risk_manager)


# ── hopefx-fix-bridge ────────────────────────────────────────────────────────


def check_fix_bridge(c: Checks) -> None:
    skill = "hopefx-fix-bridge"
    bridge = c.source("brokers/ibkr_fix_bridge.py")
    c.check(skill, "brokers/ibkr_fix_bridge.py exists", bool(bridge))
    if not bridge:
        return

    c.check(skill, "is_paper still keys off ports 4002/7497", "4002" in bridge and "7497" in bridge)
    c.check(
        skill,
        "IBKR_FIX_PORT default is 4002 (paper)",
        'IBKR_FIX_PORT", "4002"' in bridge or '"IBKR_FIX_PORT", 4002' in bridge,
    )
    c.check(skill, "IBKR_FIX_STORE_PATH is still the sequence-number store", "IBKR_FIX_STORE_PATH" in bridge)
    c.check(skill, "latency_threshold_ms is still a configured limit", "latency_threshold_ms" in bridge)


# ── hopefx-dead-controls ─────────────────────────────────────────────────────


def check_dead_controls(c: Checks) -> None:
    """The catalogue quotes pre-fix code deliberately. What must hold is that
    each control is now wired — the fixed state, not the historical quote."""
    skill = "hopefx-dead-controls"

    engine = c.source("execution/engine.py")
    c.check(
        skill,
        "F84: the data-layer gate no longer depends on _started",
        "_started and not" not in engine,
        "reintroducing the conjunct switches the gate off again",
    )

    alert_engine = c.source("notifications/alert_engine.py")
    c.check(
        skill,
        "F159: send_alert no longer delegates by identity comparison",
        "singleton is not self" not in alert_engine,
    )

    coverage = c.source("scripts/invariant_coverage.py")
    c.check(skill, "F176: the coverage report does not claim FULL COVERAGE", "FULL COVERAGE ✅" not in coverage)
    c.check(
        skill,
        "F176: the report labels the matrix as DECLARED",
        "DECLARED" in c.raw_source("scripts/invariant_coverage.py"),
    )

    orchestrator = c.source("risk/orchestrator.py")
    c.check(
        skill,
        "F81: activate_hedge_mode reports whether the hedge opened",
        'async def activate_hedge_mode(self, symbol: str = "XAU_USD") -> bool:' in orchestrator,
    )
    c.check(
        skill,
        "F252: deactivate_hedge_mode no longer clears unconditionally",
        "self._hedge_positions.clear()" not in orchestrator,
    )

    scorer = c.source("news/nuclear_wordmap_scorer.py")
    c.check(skill, "F80: the wordmap matches on word boundaries", "_compile_terms" in scorer)

    analyzer = c.source("security/code_analyzer.py")
    c.check(skill, "F255: the nan_leak rule consults the docstring exemption", "not is_test and not in_doc" in analyzer)

    # The gate the catalogue points at must still be a gate.
    try:
        from security.code_analyzer import scan_codebase

        findings = scan_codebase()
        c.check(skill, "the repo still scans to zero analyzer findings", len(findings) == 0, f"{len(findings)} found")
    except Exception as exc:  # pragma: no cover - reported, not swallowed
        c.check(skill, "the analyzer runs", False, f"{type(exc).__name__}: {exc}")


# ── Cross-cutting: no skill may cite a file that no longer exists ────────────

_PATH_RE = re.compile(r"`([a-z_][a-z0-9_/]*\.(?:py|md|json|yaml|yml))(?::\d+)?`", re.IGNORECASE)


def check_cited_paths(c: Checks) -> None:
    for name in CUSTOM_SKILLS:
        text = _skill_text(name)
        for rel in sorted(set(_PATH_RE.findall(text))):
            if rel.startswith((".claude/", "references/", "tests/")) or "/" not in rel:
                continue
            c.check(name, f"cited path exists: {rel}", (REPO_ROOT / rel).exists())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify the custom skills' claims against the codebase")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    c = Checks()
    for fn in (
        check_skill_files,
        check_invariants,
        check_money_precision,
        check_fix_bridge,
        check_dead_controls,
        check_cited_paths,
    ):
        fn(c)

    if args.json:
        print(json.dumps({"checks": c.results, "failed": len(c.failures)}, indent=2))
        return 1 if c.failures else 0

    print("HOPEFX custom-skill claim verification\n" + "=" * 56)
    current = None
    for r in c.results:
        if r["skill"] != current:
            current = r["skill"]
            print(f"\n{current}")
        mark = "  ok  " if r["ok"] else "STALE "
        detail = f"  ({r['detail']})" if r["detail"] and not r["ok"] else ""
        print(f"  {mark} {r['claim']}{detail}")
    print("\n" + "=" * 56)
    print(f"{len(c.results)} claims checked, {len(c.failures)} stale")
    if c.failures:
        print("A skill citing a stale constant is worse than no skill — it is believed.")
    return 1 if c.failures else 0


if __name__ == "__main__":
    sys.exit(main())
