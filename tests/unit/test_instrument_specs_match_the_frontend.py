# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_instrument_specs_match_the_frontend.py
======================================================
F5-01 — two instrument tables, and they had already drifted.

``api/trading.py::_SYMBOL_CATALOGUE`` is the server's instrument spec, served at
``GET /api/trading/symbols``. The risk calculator did not read it: it carried its
own hardcoded ``SYMBOLS`` map of pip and contract sizes and sized positions from
that.

**Since fixed** — ``useInstrumentSpecs`` now fetches the catalogue and the server
is the authority. What remains on the client is ``BUILTIN_SPECS``, the offline
default used when that call fails, and it is what this test checks. A fallback
nobody verifies is just a second opinion.

They disagreed on ETH/USD — ``0.01`` on the client against ``0.1`` on the
server, a factor of ten.

**What that did, stated precisely rather than alarmingly.** The sizing formula
is

    stopPips       = stopDist / pipSize
    pipValuePerLot = pipSize * contractSize
    lotSize        = riskAmount / (stopPips * pipValuePerLot)

``pipSize`` cancels, so **lot size and max loss were correct**. What was wrong
were the two figures displayed beside them — the pip count and the pip value —
both out by 10×. A trader reading "stop distance: 10,000 pips" on a $100 stop
would reasonably conclude the tool was broken, or worse, believe it.

This is the S13-01 duplication pattern, which has now produced a defect in every
duplicated pair found in this codebase. The copy is allowed to exist as an
offline default; it is not allowed to disagree.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from api.trading import _SYMBOL_CATALOGUE

pytestmark = pytest.mark.unit

_SPECS_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "hooks" / "useInstrumentSpecs.ts"


def _frontend_symbols() -> dict[str, dict[str, float]]:
    """Parse the offline fallback table out of useInstrumentSpecs.ts.

    The calculator now reads ``GET /api/trading/symbols`` at runtime, so the
    server is the authority. This table remains as the offline default when that
    call fails — which is exactly why it still has to agree with the catalogue:
    a fallback nobody checks is a second opinion, and S13-01's record is that
    every duplicated pair here has already produced a defect.
    """
    src = _SPECS_TS.read_text(encoding="utf-8")
    block = re.search(r"BUILTIN_SPECS[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert block, "BUILTIN_SPECS not found in useInstrumentSpecs.ts — re-check F5-01"

    out: dict[str, dict[str, float]] = {}
    for line in block.group(1).split("\n"):
        key = re.search(r"'([A-Z]{3}/[A-Z]{3})':", line)
        if not key:
            continue
        fields = dict(re.findall(r"(\w+):\s*([\d.]+)", line))
        out[key.group(1).replace("/", "")] = {k: ast.literal_eval(v) for k, v in fields.items()}
    assert out, "parsed no symbols out of useInstrumentSpecs.ts"
    return out


@pytest.mark.parametrize("symbol", sorted(_frontend_symbols()))
def test_pip_size_matches_the_server(symbol):
    fe = _frontend_symbols()[symbol]
    be = _SYMBOL_CATALOGUE.get(symbol)
    if be is None:
        pytest.skip(f"{symbol} is offered by the calculator but absent from the server catalogue")

    assert fe["pipSize"] == be["pip_size"], (
        f"{symbol}: the risk calculator uses pipSize={fe['pipSize']} while the "
        f"server catalogue says {be['pip_size']}. Pip counts and pip values "
        f"shown to the trader are wrong by a factor of "
        f"{be['pip_size'] / fe['pipSize']:g} (F5-01)."
    )


@pytest.mark.parametrize("symbol", sorted(_frontend_symbols()))
def test_contract_size_matches_the_server(symbol):
    fe = _frontend_symbols()[symbol]
    be = _SYMBOL_CATALOGUE.get(symbol)
    if be is None:
        pytest.skip(f"{symbol} is offered by the calculator but absent from the server catalogue")

    assert fe["contractSize"] == be["lot_size"], (
        f"{symbol}: the risk calculator uses contractSize={fe['contractSize']} "
        f"while the server catalogue says lot_size={be['lot_size']}. Contract "
        f"size does NOT cancel in the sizing formula — the suggested position "
        f"is wrong by a factor of {be['lot_size'] / fe['contractSize']:g} (F5-01)."
    )


def test_gold_is_not_quoted_with_fx_conventions():
    """The specific confusion the backend audit already hit once (S3): gold's
    contract is 100 oz with a $0.01 pip, not FX's 100,000 units at 0.0001."""
    fe = _frontend_symbols()["XAUUSD"]
    assert fe["pipSize"] == 0.01
    assert fe["contractSize"] == 100
    assert _SYMBOL_CATALOGUE["XAUUSD"]["pip_size"] == 0.01
    assert _SYMBOL_CATALOGUE["XAUUSD"]["lot_size"] == 100


def test_the_calculator_only_offers_symbols_the_server_knows():
    """A symbol the calculator offers but the server has never heard of would
    size against numbers nothing else in the system agrees with."""
    unknown = sorted(set(_frontend_symbols()) - set(_SYMBOL_CATALOGUE))
    assert unknown == [], (
        f"the risk calculator offers {unknown}, absent from the server's "
        f"instrument catalogue — nothing validates those pip and contract sizes"
    )
