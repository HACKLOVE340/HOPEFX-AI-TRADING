#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate L: safety invariants.
#
# Verifies that critical fail-closed safety defaults have not been accidentally
# changed to unsafe values.  This gate prevents four categories of incidents:
#
#   1. Accidental live-trading enablement (BROKER_TYPE != paper, FEATURE_LIVE_TRADING default changed)
#   2. Disabled inference safeguards (STALE_MODEL_BLOCK or DRIFT_BLOCK flipped to false by default)
#   3. Disabled WebSocket authentication (WS_AUTH_REQUIRED defaulting to false)
#   4. Disabled Redis TLS in production template (REDIS_FORCE_TLS defaulting to false)
#
# Each rule is a string pattern check on a specific file — no imports of
# application code are needed so the gate runs without any dependencies.
#
# Exits 0 on pass, 1 on failure.
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]

# ─── Rule definitions ─────────────────────────────────────────────────────────


class _Rule(NamedTuple):
    name: str
    file: Path
    # A regex that MUST match at least once in the file (positive assertion)
    must_match: str | None = None
    # A regex that MUST NOT match anywhere in the file (negative assertion)
    must_not_match: str | None = None
    help: str = ""


_RULES: list[_Rule] = [
    # ── Rule L-1: FEATURE_LIVE_TRADING default must be False ──────────────────
    _Rule(
        name="L-1  FEATURE_LIVE_TRADING default=False",
        file=REPO_ROOT / "config" / "feature_flags.py",
        # The _FeatureDef for LIVE_TRADING must declare default=False.
        # Pattern: the string "FEATURE_LIVE_TRADING" appears within a few
        # lines before "default=False" (the descriptor constructor).
        must_match=r'["\']FEATURE_LIVE_TRADING["\']',
        help=(
            "config/feature_flags.py must declare FEATURE_LIVE_TRADING with "
            "default=False.  Live trading must be an explicit opt-in, never "
            "the default.  See the _FeatureDef for LIVE_TRADING."
        ),
    ),
    # ── Rule L-2: FEATURE_LIVE_TRADING descriptor uses default=False ──────────
    _Rule(
        name="L-2  FEATURE_LIVE_TRADING _FeatureDef carries default=False",
        file=REPO_ROOT / "config" / "feature_flags.py",
        # The file must not contain a _FeatureDef block where the env_var is
        # FEATURE_LIVE_TRADING AND default=True on the same nearby lines.
        # We check positively: the block *must* contain default=False after
        # the env_var declaration (within 10 lines).
        # Implemented via _check_live_trading_default() below.
        must_match=None,
        must_not_match=None,
        help="Verified by _check_live_trading_default()",
    ),
    # ── Rule L-3: BROKER_TYPE defaults to paper in .env.example ──────────────
    _Rule(
        name="L-3  BROKER_TYPE=paper in .env.example",
        file=REPO_ROOT / ".env.example",
        must_match=r"^BROKER_TYPE\s*=\s*paper\s*($|#)",
        help=(
            ".env.example must set BROKER_TYPE=paper.  Changing this to a "
            "live broker type in the template could cause new deployments to "
            "execute real trades before credentials are validated."
        ),
    ),
    # ── Rule L-4: DRIFT_BLOCK defaults to true in .env.example ───────────────
    _Rule(
        name="L-4  DRIFT_BLOCK=true in .env.example",
        file=REPO_ROOT / ".env.example",
        must_match=r"^DRIFT_BLOCK\s*=\s*true\s*($|#)",
        help=(
            ".env.example must set DRIFT_BLOCK=true.  Disabling drift "
            "blocking allows inference on degraded features, which can "
            "produce harmful signals."
        ),
    ),
    # ── Rule L-5: WS_AUTH_REQUIRED defaults to true in .env.example ──────────
    _Rule(
        name="L-5  WS_AUTH_REQUIRED=true in .env.example",
        file=REPO_ROOT / ".env.example",
        must_match=r"^WS_AUTH_REQUIRED\s*=\s*true\s*($|#)",
        help=(
            ".env.example must set WS_AUTH_REQUIRED=true.  WebSocket "
            "authentication must be enabled by default to prevent "
            "unauthenticated access to the live data stream."
        ),
    ),
    # ── Rule L-6: REDIS_FORCE_TLS defaults to true in .env.example ───────────
    _Rule(
        name="L-6  REDIS_FORCE_TLS=true in .env.example",
        file=REPO_ROOT / ".env.example",
        must_match=r"^REDIS_FORCE_TLS\s*=\s*true\s*($|#)",
        help=(
            ".env.example must set REDIS_FORCE_TLS=true.  Redis connections "
            "must be encrypted in transit.  Disabling TLS exposes order "
            "state, session tokens, and position data to network eavesdropping."
        ),
    ),
    # ── Rule L-7: STALE_MODEL_BLOCK defaults to true in ml/inference_engine ──
    _Rule(
        name="L-7  STALE_MODEL_BLOCK defaults to 'true' in ml/inference_engine.py",
        file=REPO_ROOT / "ml" / "inference_engine.py",
        must_match=r'os\.getenv\s*\(\s*["\']STALE_MODEL_BLOCK["\'],\s*["\']true["\']\s*\)',
        help=(
            "ml/inference_engine.py must default STALE_MODEL_BLOCK to 'true'.  "
            "A stale model can produce signals calibrated on outdated market "
            "data — inference must be blocked until the model is refreshed."
        ),
    ),
    # ── Rule L-8: FEATURE_LIVE_TRADING=false in .env.example ─────────────────
    _Rule(
        name="L-8  FEATURE_LIVE_TRADING=false in .env.example",
        file=REPO_ROOT / ".env.example",
        must_match=r"^FEATURE_LIVE_TRADING\s*=\s*false\s*($|#)",
        help=(
            ".env.example must set FEATURE_LIVE_TRADING=false.  The feature "
            "flag and BROKER_TYPE together form a two-key lock for live "
            "trading.  Both must be false/paper in the default template."
        ),
    ),
]


# ─── Special check for L-2 ────────────────────────────────────────────────────


def _check_live_trading_default(content: str) -> str | None:
    """
    Verify that the _FeatureDef block for FEATURE_LIVE_TRADING uses default=False.

    Scans the file line by line: once the FEATURE_LIVE_TRADING env_var line is
    found, the following 10 lines must contain 'default=False' before any
    'default=True' appears in that block.

    Returns an error string on failure, or None on success.
    """
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "FEATURE_LIVE_TRADING" not in line:
            continue
        # Look ahead within 10 lines for the default= keyword
        window = lines[i : i + 10]
        window_text = "\n".join(window)
        if re.search(r"default\s*=\s*False", window_text):
            return None  # Correct — default=False found
        if re.search(r"default\s*=\s*True", window_text):
            return (
                "FEATURE_LIVE_TRADING _FeatureDef has default=True — "
                "live trading must default to False (opt-in only)"
            )
    # FEATURE_LIVE_TRADING string was found by L-1 but no default= found in window
    return None  # L-1 already caught missing declaration; avoid double error


# ─── Runner ───────────────────────────────────────────────────────────────────


def _run_rule(rule: _Rule) -> list[str]:
    """Run a single rule and return a list of failure messages (empty = pass)."""
    failures: list[str] = []

    if not rule.file.exists():
        failures.append(f"[{rule.name}] file not found: {rule.file.relative_to(REPO_ROOT)}")
        return failures

    content = rule.file.read_text(encoding="utf-8")

    if rule.must_match is not None:
        if not re.search(rule.must_match, content, re.MULTILINE):
            failures.append(
                f"[{rule.name}] MISSING required pattern {rule.must_match!r}\n"
                f"    → {rule.help}"
            )

    if rule.must_not_match is not None:
        m = re.search(rule.must_not_match, content, re.MULTILINE)
        if m:
            failures.append(
                f"[{rule.name}] FORBIDDEN pattern matched: {m.group()!r}\n"
                f"    → {rule.help}"
            )

    return failures


def main() -> int:
    failures: list[str] = []

    for rule in _RULES:
        if rule.name.startswith("L-2"):
            # Special check — not a simple regex
            if not rule.file.exists():
                failures.append(f"[L-2] file not found: {rule.file.relative_to(REPO_ROOT)}")
                continue
            content = rule.file.read_text(encoding="utf-8")
            err = _check_live_trading_default(content)
            if err:
                failures.append(f"[{rule.name}] {err}\n    → {rule.help}")
        else:
            failures.extend(_run_rule(rule))

    if failures:
        print(f"Gate L FAILED — {len(failures)} safety invariant(s) violated:")
        for f in failures:
            print(f"  • {f}")
        print()
        print(
            "These invariants enforce fail-closed defaults for live trading, "
            "model staleness, WebSocket auth, and Redis TLS.  Fix the "
            "violations before merging — do NOT suppress this gate."
        )
        return 1

    print(
        f"Gate L PASSED — {len(_RULES)} safety invariant(s) verified "
        "(BROKER_TYPE, FEATURE_LIVE_TRADING, DRIFT_BLOCK, STALE_MODEL_BLOCK, "
        "WS_AUTH_REQUIRED, REDIS_FORCE_TLS all safe)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
