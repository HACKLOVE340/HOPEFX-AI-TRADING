# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Every variable `.env.example` documents must be one the code reads.

## The defect this holds

`.env.example` is the only description of this platform's configuration an
operator has. A key in it that nothing reads is not an untidy line — it is an
instruction that silently does nothing, and the file gives no way to tell the
two apart.

Measured on 2026-09-18: **26 of 969 keys appeared nowhere in any source file**,
and they were not random rot. Almost every one was a near-miss of a live name:

    documented (dead)              actually read
    ───────────────────────────────────────────────────────
    RISK_DAILY_LOSS_LIMIT=500      RISK_MAX_DAILY_LOSS_PCT   (a fraction, not dollars)
    RISK_PER_TRADE_PCT=0.01        MAX_RISK_PCT_PER_TRADE
    RISK_MAX_LEVERAGE=10           MAX_LEVERAGE_RATIO
    SELF_HEAL_ENABLED              SELF_HEALER_ENABLED
    SPREAD_SPIKE_THRESHOLD         SPREAD_SPIKE_MULTIPLIER
    SPREAD_WARN_USD                SPREAD_ABS_LIMIT_USD
    TWAP_DURATION_S                TWAP_DEFAULT_SECS

Three of those sat under a heading reading `# Risk limits`, on a money-moving
system, beside the live knobs documented elsewhere in the same file. An operator
halving `RISK_PER_TRADE_PCT` from 0.01 to 0.005 changes nothing — and 0.01 is
also the default of the live `MAX_RISK_PCT_PER_TRADE`, so the number on screen
agrees with the number in force and nothing looks wrong.

That is `.claude/skills/hopefx-dead-controls` in the configuration surface: a
control that exists, is documented accurately as to its intent, and never runs.

## Why a source-text match rather than a reader match

The first version of this check scanned for `os.getenv("X")` and reported 312
undocumented keys and 103 dead ones — both wrong, because this codebase reads
env vars through helpers (`_env_float("EDGE_SELECTOR_MAX_LOT", 0.01)`) and
through declarative tables (`_FeatureDef("FEATURE_COPY_TRADING", ...)`). It very
nearly reported eleven live trading-strategy knobs as dead.

So the rule is deliberately weak in the safe direction: a key must appear as a
literal string SOMEWHERE in the source. That over-counts — a key mentioned only
in a docstring passes — and under-claims nothing. A key that appears nowhere at
all cannot be being read by anything.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Directories with no bearing on what the backend reads.
_SKIP = {".venv", "node_modules", ".git", "static", "dashboard", "htmlcov", ".mypy_cache"}

#: Files that could READ a key. Markdown is deliberately absent: a key named in
#: a document is documented, not read, and including `.md` let seven dead keys
#: through on the first run — `RISK_DAILY_LOSS_LIMIT` among them, which is one of
#: the three this check exists for. "A checker that reads prose is not reading
#: code" (F255/F257) applies to the checker as much as to the thing checked.
_EXT = {".py", ".ts", ".tsx", ".sh", ".yml", ".yaml", ".json", ".template", ".toml", ".tf", ".conf"}

_KEY_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=")


def _declared() -> dict[str, int]:
    out: dict[str, int] = {}
    for n, line in enumerate((REPO / ".env.example").read_text(encoding="utf-8").splitlines(), 1):
        m = _KEY_RE.match(line)
        if m:
            out.setdefault(m.group(1), n)
    return out


def _source_text() -> str:
    parts: list[str] = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in _EXT:
            continue
        if any(s in path.parts for s in _SKIP):
            continue
        if path.name.startswith(".env"):
            continue
        # This file itself. The table above names seven dead keys in order to
        # explain them, and on the first run that table was the only place they
        # appeared — so the checker passed them. F257 in miniature, committed by
        # the checker written to prevent it: `verify_skill_claims.py` failed four
        # correct files for quoting the defect they fixed; this one absolved
        # seven broken lines for the same reason.
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(parts)


def test_no_key_is_documented_that_nothing_mentions():
    declared = _declared()
    blob = _source_text()
    dead = sorted((n, k) for k, n in declared.items() if k not in blob)
    assert not dead, (
        "these .env.example keys appear in no source file, so setting them does nothing:\n"
        + "\n".join(f"  line {n}: {k}" for n, k in dead)
        + "\n\nEither point the line at the name the code really reads, or delete it. "
        "A key an operator can set and that changes nothing is worse than an "
        "undocumented one, because it reads as a control."
    )


def test_no_key_is_declared_twice():
    """Two lines for one key means the second silently wins."""
    seen: dict[str, int] = {}
    dupes: list[str] = []
    for n, line in enumerate((REPO / ".env.example").read_text(encoding="utf-8").splitlines(), 1):
        m = _KEY_RE.match(line)
        if not m:
            continue
        if m.group(1) in seen:
            dupes.append(f"{m.group(1)} (lines {seen[m.group(1)]} and {n})")
        else:
            seen[m.group(1)] = n
    assert not dupes, f"duplicate keys in .env.example: {', '.join(dupes)}"


def test_the_scan_reads_a_real_tree():
    """The sanity floor: a glob that stopped matching would report zero dead keys."""
    declared = _declared()
    assert len(declared) > 500, f"only {len(declared)} keys parsed from .env.example"
    assert "SECURITY_JWT_SECRET" in _source_text()
    assert "RISK_MAX_DAILY_LOSS_PCT" in _source_text(), "the scan is not reaching risk/"
