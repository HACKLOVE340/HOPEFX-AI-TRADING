# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Generate `GROUP4_VOLUME_INDEX.md` from both Group 4 sources.

    python scripts/group4_index.py --check      # does the committed index match?
    python scripts/group4_index.py --generate   # rewrite it

Retyping 186 + 118 titles is how one gets silently dropped or altered, which is
the exact failure the source's preservation rule forbids. So the index is
generated, and `--check` fails if the committed file has drifted from what the
sources produce — otherwise "generated from the source" is a claim nobody can
verify, and the next person edits the output by hand.

Routing (which group owns each volume) is the one thing here that is *decided*
rather than derived. It lives in :data:`OWNER` and :data:`EXTRA_OWNER`, in this
file, so a routing change is a reviewable diff rather than a silent edit to a
generated document.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parent.parent
INDEX: Final = REPO / "docs" / "ai" / "specs" / "GROUP4_VOLUME_INDEX.md"

sys.path.insert(0, str(REPO))

from scripts.group4_preservation import (
    V2,
    PreservationBroken,
    Section,
    _read,
    v1_chapters,
    v2_sections,
)

#: Which group already owns each volume, and what it covers there. Decided, not
#: derived — see the module docstring.
OWNER: Final[dict[str, tuple[str, str]]] = {
    "I": ("**This document's constitution** — `GROUP4_CONSTITUTION.md`", "T0, binding on all groups"),
    "II": ("Group 1 §4, §14, §57 · Group 0 §14", "runtime, governor, mission control, planning"),
    "III": ("Group 1 §9–§13, §15, §31", "cognition, meta-cognition, uncertainty, calibration"),
    "IV": ("Group 0 §5, §6 · Group 1 §7, §8", "gateway, providers, routing, local models"),
    "V": ("Group 0 §11, §12 · Group 1 §17–§20", "agent registry, teams, protocols, debate"),
    "VI": (
        "Group 0 §16 · Group 1 §25–§28 · Group 3 Ch 8",
        "memory tiers, knowledge graph, decision and failure memory",
    ),
    "VII": ("Group 0 §18 · Group 1 §16, §21 · Group 2 Ch 14", "perception, events, anomaly, awareness"),
    "VIII": (
        "**Group 2 Part VIII, Chapters 28–34** — NEW",
        "no group owned acceleration; now specified in full",
    ),
    "IX": ("Group 1 §33–§36 · Group 2 Ch 10, 23", "authority, pipeline, action registry, audit"),
    "X": ("Group 2 Part III (Ch 8–9) · Ch 15", "containment, HA, recovery, chaos, incident learning"),
    "XI": ("Group 1 §37–§40", "projection, world model, what-if, digital twin"),
    "XII": (
        "Group 1 §21, §22, §50 · Group 0 improvement cycle",
        "operational learning, experimentation, promotion controls",
    ),
    "XIII": ("Group 2 Ch 10, 23 · Group 4 Articles I–XII", "authority tiers, sovereignty, policy, audit"),
    "XIV": ("Group 2 Part IV (Ch 11–13)", "zones, identity, secrets, defensive security, supply chain"),
    "XV": ("Group 1 §41–§44", "research intelligence, incubator, adoption, research memory"),
    "XVI": ("Group 0 capability registry · Group 2 Ch 22, 24", "capability registry, skills, plugins, retirement"),
    "XVII": ("Group 2 Ch 7, 17, 18 · Part VIII", "performance, resources, cost, capacity, energy"),
    "XVIII": ("Group 2 Part VI (Ch 19–20) · Group 1 §12", "evals, agent testing, invariants, continuous verification"),
    "XIX": (
        "Group 3, all 18 chapters · Group 2 Ch 21",
        "interfaces, documentation, versioning, architecture governance",
    ),
    "XX": ("Group 2 Ch 22, 35 · Group 3 Ch 7, 8", "institutional model, debt, adaptive architecture, maturity index"),
}

#: v2 places three blocks outside the twenty volumes.
EXTRA_OWNER: Final[dict[str, tuple[str, str]]] = {
    "AI HUB AND EXPERIENCE ARCHITECTURE": (
        "Group 0 — delivered, 31 sections",
        "presence, workspaces, orchestration, multimodal",
    ),
    "SPECIALIZED TRADING DOMAIN PRESERVATION": (
        "The trading platform itself · `ARCHITECTURE.md`",
        "the existing domain is preserved, not replaced",
    ),
    "FINAL COMPLETENESS CHECKLIST": (
        "**This index** — the checklist is what it verifies",
        "thirteen completeness assertions",
    ),
}

_ROMAN_OF_VOLUME = re.compile(r"VOLUME ([IVX]+) —")


def _roman(volume: str) -> str:
    m = _ROMAN_OF_VOLUME.match(volume)
    return m.group(1) if m else ""


def _statements() -> dict[str, str]:
    """Each v2 section's one-line statement, read from the source."""
    lines = _read(V2).splitlines()
    for start, line in enumerate(lines):
        if line.startswith("=" * 20):
            lines = lines[start + 1 :]
            break
    else:  # pragma: no cover - guarded identically in group4_preservation
        raise PreservationBroken("v2 source has no provenance rule")

    out: dict[str, str] = {}
    for sec in v2_sections():
        for i, line in enumerate(lines):
            if line.strip() != sec.title:
                continue
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt and not nxt.startswith("- ") and nxt != "Mandatory Engineering Requirements":
                out[sec.title] = nxt
            break
    return out


def render() -> str:
    v1 = v1_chapters()
    v2 = v2_sections()
    statement = _statements()

    order: list[str] = []
    for s in v2:
        if s.volume and s.volume not in order:
            order.append(s.volume)

    v1_by_roman: dict[str, list[Section]] = {}
    for c in v1:
        v1_by_roman.setdefault(_roman(c.volume), []).append(c)
    v1_number = {id(c): n for n, c in enumerate(v1, 1)}
    v1_volume_name = {_roman(c.volume): c.volume for c in v1}

    out: list[str] = []
    w = out.append
    w("<!-- Generated by scripts/group4_index.py — do not edit by hand. -->")
    w("<!-- Run `python scripts/group4_index.py --generate` after a source changes. -->")
    w("")
    w("# Group 4 — Volume Index")
    w("")
    w("**Every title from both Group 4 sources, preserved and routed.**")
    w("")
    w("Two sources exist and they do not enumerate the same things:")
    w("")
    w("| Source | Shape | Items |")
    w("|---|---|---:|")
    w(f"| `GROUP4_master_ai_operating_system.txt` (**v1**) | Table of contents only | {len(v1)} numbered chapters |")
    w(
        f"| `GROUP4_master_ai_operating_system_v2_complete.txt` (**v2**) | "
        f"Complete document, a statement under every section | {len(v2)} named sections |"
    )
    w("")
    w("**v2 is not a superset of v1.** It carries substance v1 never had — a statement")
    w("under every section, a Decision Governance section, an AI Hub and Experience")
    w("block, an explicit trading-domain preservation clause — while naming far fewer")
    w("items than v1's 186 chapters. Adopting either alone would drop titles the other")
    w("names, which the source's own opening rule forbids: **ADD AND EXPAND; NEVER")
    w("SILENTLY REMOVE.** So both are listed here, side by side, per volume.")
    w("")
    w("**Generated from both sources**, not retyped, and checked two ways:")
    w("")
    w("- `python scripts/group4_preservation.py` fails if any title from either source")
    w("  stops being listed here.")
    w("- `python scripts/group4_index.py --check` fails if this file has drifted from")
    w("  what the sources produce.")
    w("")
    w("A preservation rule enforced by intention is not enforced.")
    w("")
    w("Routing points at the group that owns each area rather than restating it — the")
    w("same relationship rule Groups 1–3 follow. It is decided in `scripts/group4_index.py`,")
    w("so a routing change is a reviewable diff.")
    w("")
    w("---")
    w("")

    for volume in order:
        roman = _roman(volume)
        w(f"## {volume}")
        w("")
        if roman and v1_volume_name.get(roman, volume) != volume:
            w(f"*v1 titled this volume:* **{v1_volume_name[roman]}**")
            w("")
        owner, covers = OWNER.get(roman) or EXTRA_OWNER.get(volume, ("*Unrouted — assign before building*", ""))
        w(f"**Owner:** {owner}")
        w("")
        if covers:
            w(f"**Covers:** {covers}")
            w("")

        chapters = v1_by_roman.get(roman, [])
        if chapters:
            w(f"**v1 — {len(chapters)} chapters**")
            w("")
            w("| # | Chapter |")
            w("|---:|---|")
            for c in chapters:
                w(f"| {v1_number[id(c)]} | {c.title} |")
            w("")

        sections = [s for s in v2 if s.volume == volume]
        if sections:
            w(f"**v2 — {len(sections)} sections, each with its statement**")
            w("")
            w("| Section | What the source says |")
            w("|---|---|")
            for s in sections:
                w(f"| {s.title} | {statement.get(s.title, '—')} |")
            w("")

    w("---")
    w("")
    w("## Sections v2 places outside the twenty volumes")
    w("")
    w("These have no v1 chapter number and are new in v2. They are listed above under")
    w("their own headings; recorded here so nobody reads the volume list as complete.")
    w("")
    w("| Block | Routed to |")
    w("|---|---|")
    for name, (owner, _covers) in EXTRA_OWNER.items():
        w(f"| {name} | {owner} |")
    w("")
    w("## Preservation")
    w("")
    w("Both sources are preserved verbatim in `docs/ai/specs/`. Volume I is promoted")
    w("to `GROUP4_CONSTITUTION.md` at T0. Volume VIII is specified in full as Group 2")
    w("Part VIII, Chapters 28–34. Everything else routes to the group that owns it.")
    w("")
    w(f"Nothing is removed. All {len(v1) + len(v2)} titles across the two sources are listed here or in")
    w("the constitution, and `scripts/group4_preservation.py` is what makes that a")
    w("statement rather than a promise.")

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true", help="Rewrite the index from the sources")
    parser.add_argument("--check", action="store_true", help="Fail if the committed index has drifted")
    args = parser.parse_args()

    try:
        expected = render()
    except PreservationBroken as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return 2

    if args.generate:
        INDEX.write_text(expected, encoding="utf-8")
        print(f"wrote {INDEX.relative_to(REPO)} ({expected.count(chr(10))} lines)")
        return 0

    actual = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
    if actual == expected:
        print("group4 index: matches the sources")
        return 0
    print(
        "group4 index: DRIFTED from the sources — run scripts/group4_index.py --generate",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
