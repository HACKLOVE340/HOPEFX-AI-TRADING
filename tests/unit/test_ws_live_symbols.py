# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Symbol normalisation for the live WebSocket tick stream."""

from __future__ import annotations

import pytest

from api.ws_live import _to_slash


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Regression: these five were absent from the hand-written alias table,
        # so their ticks were published as "USDCHF" while the Trade page looked
        # up prices['USD/CHF'] — the tile read "No feed" on a healthy feed.
        ("USDCHF", "USD/CHF"),
        ("AUDUSD", "AUD/USD"),
        ("USDCAD", "USD/CAD"),
        ("NZDUSD", "NZD/USD"),
        ("XPTUSD", "XPT/USD"),
        # Forms that already worked and must keep working.
        ("XAUUSD", "XAU/USD"),
        ("BTCUSD", "BTC/USD"),
        # GC=F/SI=F are gold/silver FUTURES, not spot. Relabelling them under
        # the spot slash symbol would be the exact undisclosed-instrument-
        # substitution defect closed elsewhere by ce72406 and, on this file,
        # by the ws_live-specific fix (see
        # tests/unit/test_gold_futures_not_served_as_spot.py::TestWsLiveSlashSymbolMap).
        # They have no pair structure to infer, so — like any other futures
        # or index code with no pair structure (see "US30" below) — they
        # fall through unchanged rather than being resolved to a spot symbol.
        ("GC=F", "GC=F"),
        ("SI=F", "SI=F"),
        ("EURUSD=X", "EUR/USD"),
        # Rule-derived forms, so a new symbol needs no edit here.
        ("BTC-USD", "BTC/USD"),
        ("XAUUSD=X", "XAU/USD"),
        # Already normalised — must not be mangled.
        ("XAU/USD", "XAU/USD"),
        # Indices have no pair structure; inventing a slash would be wrong.
        ("US30", "US30"),
        ("NAS100", "NAS100"),
        ("USOIL", "USOIL"),
        ("", ""),
    ],
)
def test_to_slash(raw, expected):
    assert _to_slash(raw) == expected
