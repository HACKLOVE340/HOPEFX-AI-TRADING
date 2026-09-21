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
        ("GC=F", "XAU/USD"),
        ("SI=F", "XAG/USD"),
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
