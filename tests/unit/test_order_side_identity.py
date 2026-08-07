# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_order_side_identity.py
======================================
Round 3 audit, Slice 13 (docs/HARDENING_BACKLOG.md S13-03).

`brokers/__init__.py` **redefines** OrderSide/OrderType/OrderStatus/Order
rather than re-exporting `brokers.base`. Two same-named enums with different
member values are never equal, so a side that crosses that boundary compares
false against every branch it is tested against:

    brokers.OrderSide.BUY       -> <OrderSide.BUY: 'buy'>
    brokers.base.OrderSide.BUY  -> <OrderSide.BUY: 'BUY'>
    equal? False

`hopefx_engine.py` imported the package-level enum and handed it to
`OANDAStream.place_order`, which compares against the `brokers.base` one:

    signed_units = units if side == OrderSide.BUY else -units

A BUY therefore fell through to the `else` and was submitted to OANDA as
**negative units — a SELL**. Longs inverted; shorts were right by accident.

The enum split itself is *not* collapsed here: `brokers.__init__` serialises
`side.value` into API payloads and Redis position keys, and the frontend
compares those against lowercase literals (`side === 'buy'`,
`side === 'long'`). Collapsing the classes would flip those to uppercase and
break the comparisons silently — trading one quiet bug for another. So the
boundary is fixed and guarded instead; see the backlog entry for the migration
this still wants.
"""

from __future__ import annotations

import pytest


def test_the_two_order_side_enums_really_are_incompatible():
    """Pins the hazard itself, so the guards below cannot look pointless.

    If this ever starts failing because the classes were unified, delete it
    along with `_signed_units`' normalisation — but check the frontend's
    lowercase `side` comparisons first.
    """
    from brokers import OrderSide as pkg_side
    from brokers.base import OrderSide as base_side

    assert pkg_side is not base_side
    assert pkg_side.BUY != base_side.BUY, "if these are equal the split is gone"


def test_engine_uses_the_enum_the_stream_compares_against():
    """The regression: the call site must import from `brokers.base`.

    `hopefx_engine` builds the OANDA order kwargs; `OANDAStream` decides
    direction. Both must be talking about the same class.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "hopefx_engine.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    order_side_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and any(a.name == "OrderSide" for a in node.names)
    }
    assert order_side_imports, "hopefx_engine no longer imports OrderSide"
    assert order_side_imports == {"brokers.base"}, (
        f"hopefx_engine imports OrderSide from {order_side_imports}. Only "
        f"brokers.base matches what OANDAStream compares against — anything "
        f"else reverses the direction of every BUY."
    )


@pytest.mark.parametrize(
    ("side", "expected_sign"),
    [
        ("BUY", 1),
        ("buy", 1),
        ("LONG", 1),
        ("SELL", -1),
        ("sell", -1),
        ("SHORT", -1),
    ],
)
def test_signed_units_direction(side, expected_sign):
    """Direction must survive either spelling of either enum."""
    from brokers.oanda_stream import _signed_units

    assert _signed_units(side, 100.0) == pytest.approx(100.0 * expected_sign)


def test_signed_units_accepts_both_order_side_enums():
    """Whichever OrderSide reaches the stream, a BUY stays a BUY."""
    from brokers import OrderSide as pkg_side
    from brokers.base import OrderSide as base_side
    from brokers.oanda_stream import _signed_units

    for enum_cls in (pkg_side, base_side):
        assert _signed_units(enum_cls.BUY, 100.0) > 0, (
            f"a BUY built from {enum_cls.__module__}.OrderSide is sent to OANDA as a SELL"
        )
        assert _signed_units(enum_cls.SELL, 100.0) < 0


def test_unrecognised_side_raises_instead_of_shorting():
    """ "Not BUY" must not mean "SELL".

    Defaulting an unknown side to a short is precisely how the enum split
    turned into a reversed live position instead of a loud failure.
    """
    from brokers.oanda_stream import _signed_units

    with pytest.raises(ValueError, match="Unrecognised order side"):
        _signed_units("sideways", 100.0)
    with pytest.raises(ValueError):
        _signed_units(None, 100.0)


def test_signed_units_ignores_incoming_sign():
    """A SELL of -100 units is still a sell of 100, not a buy."""
    from brokers.oanda_stream import _signed_units

    assert _signed_units("SELL", -100.0) == -100.0
    assert _signed_units("BUY", -100.0) == 100.0
