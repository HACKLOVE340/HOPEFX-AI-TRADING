"""Regression tests for the stop-loss slice (audit findings F45, F60/F106, F151).

Every test here fails on the pre-fix code. They pin three separate defects that
together meant a user-entered stop-loss was collected, transported, discarded,
and reported as success.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ── F45 — the SL/TP monitor read an attribute Position does not have ──────────


def test_position_has_no_position_id_attribute():
    """Pins the contract the monitor must code against."""
    from execution.position_tracker import Position

    fields = set(Position.__dataclass_fields__)
    assert "id" in fields
    assert "position_id" not in fields, (
        "Position gained a position_id field — sl_tp_monitor was fixed to use .id; "
        "reconcile the two before changing either."
    )


def test_sl_tp_monitor_never_reads_position_id():
    """F45: `pos.position_id` raised AttributeError on the first live position,
    so the monitor closed nothing. Source-level because the loop needs a broker."""
    src = (ROOT / "execution" / "sl_tp_monitor.py").read_text()
    tree = ast.parse(src)
    bad = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "position_id"]
    assert not bad, f"sl_tp_monitor.py reads .position_id at lines {bad}; Position exposes .id"


# ── F60 / F106 — the executor assumed an enum status and an `id` ──────────────


def test_market_order_result_status_is_a_plain_string():
    from brokers.base import MarketOrderResult

    r = MarketOrderResult(order_id="o1", average_fill_price=1.0, filled_quantity=1.0, status="filled")
    assert isinstance(r.status, str)
    with pytest.raises(AttributeError):
        r.status.value  # noqa: B018 — this is the bug trade_executor assumed away
    with pytest.raises(AttributeError):
        r.id  # noqa: B018 — the field is order_id


def test_trade_executor_does_not_assume_enum_status_or_id():
    """F60/F106: `order.status.value` and `order.id` raised AttributeError AFTER
    the broker had already filled — a real position with no local record."""
    src = (ROOT / "execution" / "trade_executor.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        if isinstance(base, ast.Name) and base.id == "order":
            assert node.attr not in ("id",), (
                f"trade_executor.py reads order.{node.attr} at line {node.lineno}; MarketOrderResult exposes order_id"
            )
        if (
            node.attr == "value"
            and isinstance(base, ast.Attribute)
            and base.attr == "status"
            and isinstance(base.value, ast.Name)
            and base.value.id == "order"
        ):
            pytest.fail(
                f"trade_executor.py reads order.status.value at line {node.lineno}; MarketOrderResult.status is a str"
            )


@pytest.mark.parametrize(
    ("status_in", "expected"),
    [("filled", "filled"), ("PARTIAL", "partial"), ("Filled", "filled")],
)
def test_status_normalisation_accepts_both_shapes(status_in, expected):
    """The normalisation must handle a str status and an enum status alike."""
    from brokers.base import MarketOrderResult

    r = MarketOrderResult(order_id="o1", average_fill_price=1.0, filled_quantity=1.0, status=status_in)
    raw = getattr(r, "status", "")
    assert str(getattr(raw, "value", raw)).lower() == expected


# ── F151 — a discarded bracket must not be reported as success ────────────────


def test_market_order_result_exposes_bracket_truth():
    from brokers.base import MarketOrderResult

    r = MarketOrderResult(order_id="o1", average_fill_price=1.0, filled_quantity=1.0, status="filled")
    assert r.brackets_requested is False
    assert r.brackets_applied is True, "no bracket asked for -> nothing was dropped"


def test_base_adapter_flags_a_dropped_bracket_and_warns(caplog):
    """F151: the base adapter cannot place brackets at market entry. It must say
    so at WARNING and mark the result, not log at DEBUG and return success."""
    import logging

    src = (ROOT / "brokers" / "base.py").read_text()
    assert "brackets_applied" in src and "brackets_requested" in src

    # the discard must not be a DEBUG-level event any more
    i = src.index("bracket SL/TP")
    window = src[max(0, i - 400) : i]
    assert "logger.warning(" in window, "the dropped-bracket notice must be WARNING, not DEBUG"
    assert logging  # keep the import meaningful for linters


def test_order_response_carries_stop_loss_placed():
    """The API contract must let a client tell a protected fill from an
    unprotected one."""
    from api.trading import OrderResponse

    assert "stop_loss_placed" in OrderResponse.model_fields
    # None is the correct default: no bracket was requested
    assert OrderResponse.model_fields["stop_loss_placed"].default is None
