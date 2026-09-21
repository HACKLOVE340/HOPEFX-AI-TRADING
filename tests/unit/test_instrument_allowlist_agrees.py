"""
tests/unit/test_instrument_allowlist_agrees.py
==============================================
The deployed terminal offered ETH/USD in its symbol dropdown and answered

    Symbol 'ETHUSD' is not in the permitted instrument list.

Four lists of instruments existed and none of them agreed:

  1. ``frontend/src/pages/Trading.tsx`` — what the UI lets you select.
  2. ``api/auth.py::ALLOWED_SYMBOLS``  — what ``validate_order_symbol`` enforces
     (default included ETHUSD).
  3. ``api/server.py::_ALLOWED_SYMBOLS`` — what the order routes enforce
     (its own hardcoded literal, which did **not** include ETHUSD).
  4. ``.env.example``                  — what a deployment actually copies into
     its ``.env``; also missing ETHUSD, which is why production rejected it.

So the instrument was permitted by one gate and refused by another, and the
gate a real deployment ran was the refusing one. This is the writer/reader
divergence again, in configuration rather than code.

These tests pin the invariant that matters: **a symbol the UI offers must be
accepted by every gate that can see it.** They deliberately read the shipped
default and the shipped ``.env.example`` rather than the process environment,
because the process environment in CI is not what a deployment runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _canonical(sym: str) -> str:
    from utils.symbol import canonical

    return canonical(sym)


def _env_example_allowed() -> frozenset[str]:
    """The ALLOWED_SYMBOLS value a fresh deployment copies from .env.example."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    matches = [line.split("=", 1)[1] for line in text.splitlines() if line.startswith("ALLOWED_SYMBOLS=")]
    assert matches, ".env.example no longer defines ALLOWED_SYMBOLS"
    assert len(matches) == 1, f"ALLOWED_SYMBOLS defined {len(matches)} times in .env.example"

    from api.auth import parse_allowed_symbols

    return parse_allowed_symbols(matches[0])


def _ui_symbols() -> list[str]:
    """The instruments the trading terminal puts in its dropdown."""
    src = (ROOT / "frontend/src/pages/Trading.tsx").read_text(encoding="utf-8")
    # Strip comments first — prose in this repo has matched source scans five
    # times now, and the file's comments name symbols.
    code = re.sub(r"/\*[\s\S]*?\*/", "", src)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    m = re.search(r"const\s+SYMBOLS\s*=\s*\[([^\]]*)\]", code)
    assert m, "Could not find the SYMBOLS array in Trading.tsx"
    symbols = re.findall(r"'([^']+)'", m.group(1))
    assert symbols, "SYMBOLS array parsed as empty — the regex has gone stale"
    return symbols


# ── The shipped defaults agree with each other ────────────────────────────────


def test_server_and_auth_enforce_the_same_default_allowlist():
    """api/server.py must not carry its own copy of the literal."""
    src = (ROOT / "api/server.py").read_text(encoding="utf-8")
    code = re.sub(r"^\s*#.*$", "", src, flags=re.M)

    # The old divergent literal, or any second hardcoded instrument list.
    assert "XAUUSD,EURUSD" not in code, (
        "api/server.py has re-grown a hardcoded ALLOWED_SYMBOLS default. "
        "Import DEFAULT_ALLOWED_SYMBOLS from api.auth instead — the two copies "
        "drifted on ETHUSD and shipped two different gates."
    )
    assert "DEFAULT_ALLOWED_SYMBOLS" in code


def test_env_example_matches_the_code_default():
    from api.auth import DEFAULT_ALLOWED_SYMBOLS, parse_allowed_symbols

    assert _env_example_allowed() == parse_allowed_symbols(DEFAULT_ALLOWED_SYMBOLS), (
        ".env.example and api/auth.DEFAULT_ALLOWED_SYMBOLS disagree. A deployment "
        "runs the .env.example copy, so this divergence is what users hit."
    )


# ── Every instrument the UI offers is actually permitted ──────────────────────


@pytest.mark.parametrize("ui_symbol", _ui_symbols())
def test_every_symbol_the_terminal_offers_is_permitted(ui_symbol):
    from api.auth import DEFAULT_ALLOWED_SYMBOLS, parse_allowed_symbols

    canonical = _canonical(ui_symbol)
    shipped_default = parse_allowed_symbols(DEFAULT_ALLOWED_SYMBOLS)

    assert canonical in shipped_default, (
        f"Trading.tsx offers {ui_symbol!r} (canonical {canonical!r}) but the code "
        f"default does not permit it. Selecting it returns 400."
    )
    assert canonical in _env_example_allowed(), (
        f"Trading.tsx offers {ui_symbol!r} (canonical {canonical!r}) but "
        f".env.example does not permit it — this is the exact ETHUSD failure."
    )


def test_ethusd_specifically_is_permitted():
    """The reported failure, pinned by name so a rename cannot quietly drop it."""
    from api.auth import DEFAULT_ALLOWED_SYMBOLS, parse_allowed_symbols

    assert "ETHUSD" in parse_allowed_symbols(DEFAULT_ALLOWED_SYMBOLS)
    assert "ETHUSD" in _env_example_allowed()


# ── Parsing is forgiving of the way people actually write env vars ────────────


def test_spaces_after_commas_do_not_silently_disable_an_instrument():
    """`XAUUSD, ETHUSD` used to yield the member " ETHUSD", matching nothing."""
    from api.auth import parse_allowed_symbols

    assert parse_allowed_symbols("XAUUSD, ETHUSD") == frozenset({"XAUUSD", "ETHUSD"})
    assert parse_allowed_symbols("xauusd,ethusd") == frozenset({"XAUUSD", "ETHUSD"})
    assert parse_allowed_symbols("XAUUSD,,ETHUSD,") == frozenset({"XAUUSD", "ETHUSD"})


def test_an_empty_allowlist_permits_nothing_rather_than_everything():
    """Fail closed: a blank or missing value must not become a wildcard."""
    from api.auth import parse_allowed_symbols

    assert parse_allowed_symbols("") == frozenset()
    assert parse_allowed_symbols(None) == frozenset()
    assert parse_allowed_symbols("   ") == frozenset()
