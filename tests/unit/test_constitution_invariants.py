# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Unit tests for the constitutional invariant library.

Every invariant is tested two ways: it must PASS on valid input and CATCH the
violation on bad input. A checker that can't catch a violation is worse than no
checker, so these tests are the proof it works.
"""

import math

import pytest

from invariants import constitution as c

pytestmark = pytest.mark.unit


# ── order state machine (No State Corruption) ───────────────────────────────────
def test_terminal_order_cannot_transition():
    assert c.verify_order_state_transition("FILLED", "CANCELLED")  # violation
    assert c.verify_order_state_transition("CANCELLED", "NEW")
    assert c.verify_order_state_transition("REJECTED", "FILLED")
    for term in ("FILLED", "CANCELLED", "REJECTED", "EXPIRED"):
        v = c.verify_order_state_transition(term, "NEW")
        assert v and v[0].severity == c.CONSTITUTIONAL


def test_legal_transitions_pass():
    assert c.verify_order_state_transition("NEW", "PARTIALLY_FILLED") == []
    assert c.verify_order_state_transition("PARTIALLY_FILLED", "FILLED") == []
    assert c.verify_order_state_transition("NEW", "CANCELLED") == []
    assert c.verify_order_state_transition("FILLED", "FILLED") == []  # idempotent no-op


def test_illegal_nonterminal_transition_flagged():
    v = c.verify_order_state_transition("NEW", "CREATED")
    assert v and v[0].severity == c.CRITICAL


def test_contradictory_order():
    assert c.verify_order_not_contradictory({"status": "FILLED", "cancelled": True})
    assert c.verify_order_not_contradictory({"quantity": 100, "filled_quantity": 150})  # phantom fill
    assert c.verify_order_not_contradictory({"quantity": 100, "filled_qty": -5})
    assert c.verify_order_not_contradictory({"status": "FILLED", "quantity": 100, "filled_quantity": 100}) == []


def test_duplicate_ids():
    items = [{"id": 1}, {"id": 2}, {"id": 1}]
    v = c.verify_no_duplicate_ids(items)
    assert v and v[0].severity == c.CONSTITUTIONAL
    assert c.verify_no_duplicate_ids([{"id": 1}, {"id": 2}]) == []
    assert c.verify_no_duplicate_ids([{"fill_id": "a"}, {"fill_id": "a"}], id_field="fill_id")


# ── capital & PnL (No Hidden Loss / Capital) ────────────────────────────────────
def test_pnl_reconciliation():
    assert c.verify_pnl_reconciliation(100.0, 50.0, 150.0) == []
    assert c.verify_pnl_reconciliation(100.0, 50.0, 140.0)  # mismatch
    v = c.verify_pnl_reconciliation(100.0, float("nan"), 150.0)
    assert v and v[0].severity == c.CONSTITUTIONAL


def test_capital_conservation():
    assert c.verify_capital_conservation(60.0, 30.0, 10.0, 100.0) == []
    assert c.verify_capital_conservation(60.0, 30.0, 20.0, 100.0)  # 110 != 100
    assert c.verify_capital_conservation(60.0, 30.0, float("inf"), 100.0)


def test_capital_equation():
    # 1000 + 200 + 50 - 100 - 10 = 1140
    assert c.verify_capital_equation(1000, 200, 50, 100, 10, 1140) == []
    assert c.verify_capital_equation(1000, 200, 50, 100, 10, 9999)  # broken → fraud/bug


def test_negative_balance():
    assert c.verify_no_negative_balance(0.0) == []
    assert c.verify_no_negative_balance(100.0) == []
    v = c.verify_no_negative_balance(-0.01)
    assert v and v[0].severity == c.CRITICAL


# ── risk limits (No Hidden Risk) ────────────────────────────────────────────────
def test_within_limit():
    assert c.verify_within_limit(5.0, 10.0, "daily_loss") == []
    v = c.verify_within_limit(15.0, 10.0, "daily_loss")
    assert v and v[0].severity == c.CRITICAL
    assert c.verify_within_limit(float("nan"), 10.0, "x")[0].severity == c.CONSTITUTIONAL


# ── market data (No Data Corruption) ────────────────────────────────────────────
def test_tick_validation():
    assert c.verify_tick(2650.5, 100) == []
    assert c.verify_tick(0, 100)  # price must be > 0
    assert c.verify_tick(-1, 100)
    assert c.verify_tick(2650.5, -5)  # volume must be >= 0
    assert c.verify_tick(2650.5, 100, ts=1000, now=10)  # future-dated
    assert c.verify_tick(2650.5, 100, ts=10, now=1000) == []


def test_spread_integrity():
    assert c.verify_spread(2650.0, 2650.5) == []  # bid <= ask
    assert c.verify_spread(2651.0, 2650.0)  # crossed book
    assert c.verify_spread(float("nan"), 2650.0)


# ── numeric integrity (No Silent Failure) ───────────────────────────────────────
def test_finite():
    assert c.verify_finite(1.5, "x") == []
    assert c.verify_finite(float("nan"), "x")
    assert c.verify_finite(float("inf"), "x")
    assert c.verify_finite(math.inf, "x")[0].severity == c.CRITICAL
    assert c.verify_finite("a string", "x") == []  # non-numeric is not this check's concern


# ── human control (No Loss Of Human Control) ────────────────────────────────────
class _GoodKill:
    def trigger(self): ...
    def is_active(self):
        return False


class _NoEngageKill:
    def is_active(self):
        return False


def test_human_control():
    assert c.verify_human_control(_GoodKill()) == []
    assert c.verify_human_control(None)[0].severity == c.CONSTITUTIONAL
    assert c.verify_human_control(_NoEngageKill())[0].severity == c.CONSTITUTIONAL


# ── aggregate ───────────────────────────────────────────────────────────────────
def test_summarize_gates_on_constitutional_and_critical():
    clean = c.summarize([])
    assert clean["ok"] is True
    bad = c.summarize(c.verify_pnl_reconciliation(1, 1, 999))
    assert bad["ok"] is False
    assert bad["counts"][c.CONSTITUTIONAL] == 1
