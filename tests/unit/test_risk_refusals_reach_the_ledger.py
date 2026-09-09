# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A ledger nobody writes to is a dead control.

`ai/ledger/decisions.py` is well tested and, on its own, proves nothing: Group 3
Chapter 7's KPI is *ledger coverage of automated decisions*, and a schema with no
callers has zero coverage while every unit test passes. That is the F176 shape
this repository keeps finding, and building the ledger without a caller would be
committing it inside the module meant to record it.

`risk/manager.py::_zero_sizing` is the right first caller and not an arbitrary
one. It is the single funnel every sizing refusal passes through — halted,
daily-drawdown, `data_quality:unmeasured` — and those refusals are the clearest
evidence in this repository that governance worked. §E12 turned a gate that
scored missing data as perfect into one that refuses; until now the only record
of a refusal was a WARNING line.

## The rule this must never break

**Recording must never change what the money path decides.** A ledger write that
raised would turn a refusal into a crash, which is strictly worse than the
defect it documents. So the call is wrapped — and wrapped LOUDLY, at ERROR,
because `except Exception: pass` on this path is how the alert failures in F248
went unnoticed for as long as they did. The ledger is a record, not a control:
losing an entry must not stop a refusal, and must not be silent either.
"""

from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.unit

from ai.ledger import decisions
from risk.manager import RiskConfig, RiskManager


@pytest.fixture(autouse=True)
def _clean():
    decisions.reset_for_testing()
    yield
    decisions.reset_for_testing()


def _manager(tmp_path) -> RiskManager:
    return RiskManager(
        config=RiskConfig(max_drawdown_pct=0.10, max_position_size_pct=0.02),
        initial_balance=1_000_000.0,
        halt_state_file=tmp_path / "halt.json",
    )


def _refused_sizing(tmp_path):
    """The real §E12 refusal: no orchestrator, so data quality is unmeasured."""
    return _manager(tmp_path).calculate_position_size(
        symbol="XAU_USD",
        signal_strength=0.9,
        probability=0.62,
        direction="long",
        entry_price=3300.0,
        stop_loss_price=3280.0,
        take_profit_price=3360.0,
        account_equity=1_000_000.0,
    )


class TestARefusalBecomesALedgerEntry:
    def test_the_refusal_still_happens(self, tmp_path) -> None:
        # Asserted first: if the ledger ever changes this, the wiring is the bug.
        result = _refused_sizing(tmp_path)
        assert result.quantity == 0.0
        assert result.reason == "data_quality:unmeasured"

    def test_it_is_recorded(self, tmp_path) -> None:
        _refused_sizing(tmp_path)
        refusals = decisions.entries(refused_only=True)
        assert refusals, "the money path refused a trade and the ledger has no record of it"

    def test_the_entry_names_the_control_that_refused(self, tmp_path) -> None:
        _refused_sizing(tmp_path)
        entry = decisions.entries(refused_only=True)[-1]
        assert entry.refused_by == "data_quality:unmeasured"
        assert entry.chosen is None

    def test_the_entry_carries_the_real_authority_tier(self, tmp_path) -> None:
        _refused_sizing(tmp_path)
        entry = decisions.entries(refused_only=True)[-1]
        assert entry.authority_tier == "execute"
        assert entry.actor_kind == "system"

    def test_the_symbol_is_in_the_evidence(self, tmp_path) -> None:
        _refused_sizing(tmp_path)
        entry = decisions.entries(refused_only=True)[-1]
        assert entry.evidence.get("symbol") == "XAU_USD"


class TestRecordingNeverChangesWhatTheMoneyPathDecides:
    def test_a_broken_ledger_does_not_break_a_refusal(self, tmp_path, monkeypatch) -> None:
        """The property that matters more than the record itself."""

        def _explode(**_kwargs):
            raise RuntimeError("ledger backend is down")

        monkeypatch.setattr(decisions, "refuse", _explode)
        result = _refused_sizing(tmp_path)
        assert result.quantity == 0.0
        assert result.reason == "data_quality:unmeasured"

    def test_and_it_says_so_loudly(self, tmp_path, monkeypatch, caplog) -> None:
        # `except Exception: pass` on this path is how F248's alert failures went
        # unnoticed. A lost governance entry is reported at ERROR.
        def _explode(**_kwargs):
            raise RuntimeError("ledger backend is down")

        monkeypatch.setattr(decisions, "refuse", _explode)
        with caplog.at_level(logging.ERROR):
            _refused_sizing(tmp_path)
        assert any(r.levelno >= logging.ERROR for r in caplog.records), (
            "a governance record was lost and nothing said so"
        )

    def test_an_approved_trade_writes_no_refusal(self, tmp_path) -> None:
        class _Tick:
            confidence = 0.95

        class _Orch:
            def get_latest_tick(self, symbol: str = "XAU_USD"):
                return _Tick()

            def get_ml_features(self) -> dict:
                return {}

        manager = RiskManager(
            config=RiskConfig(max_drawdown_pct=0.10, max_position_size_pct=0.02),
            initial_balance=1_000_000.0,
            halt_state_file=tmp_path / "halt.json",
            orchestrator=_Orch(),
        )
        result = manager.calculate_position_size(
            symbol="XAU_USD",
            signal_strength=0.9,
            probability=0.62,
            direction="long",
            entry_price=3300.0,
            stop_loss_price=3280.0,
            take_profit_price=3360.0,
            account_equity=1_000_000.0,
        )
        assert result.quantity > 0
        assert decisions.entries(refused_only=True) == [], "an approved trade was recorded as a refusal"
