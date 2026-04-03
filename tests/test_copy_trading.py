# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for social/copy_trading.py.

Tests use the real CopyTradingEngine from the production module — no mocks.
"""

from decimal import Decimal

import pytest

from social.copy_trading import CopyRelationship, CopyTradingEngine, RiskLimitExceededError


class TestCopyRelationship:
    """CopyRelationship dataclass behaves correctly."""

    def test_defaults(self):
        rel = CopyRelationship(follower_id="f1", leader_id="l1")
        assert rel.copy_ratio == 1.0
        assert rel.is_active is True
        assert rel.max_allocation is None

    def test_custom_ratio(self):
        rel = CopyRelationship(follower_id="f1", leader_id="l1", copy_ratio=0.5)
        assert rel.copy_ratio == 0.5

    def test_max_allocation_stored(self):
        rel = CopyRelationship(
            follower_id="f1",
            leader_id="l1",
            max_allocation=Decimal(5000),
        )
        assert rel.max_allocation == Decimal(5000)


class TestCopyTradingEngine:
    """CopyTradingEngine manages relationships and propagates trades."""

    def _engine(self):
        return CopyTradingEngine()

    # ── Relationship management ──────────────────────────────────────────────

    def test_start_copying_creates_relationship(self):
        engine = self._engine()
        rel = engine.start_copying("follower-1", "leader-1", copy_ratio=0.5)
        assert isinstance(rel, CopyRelationship)
        assert rel.follower_id == "follower-1"
        assert rel.leader_id == "leader-1"
        assert rel.copy_ratio == 0.5
        assert rel.is_active is True

    def test_stop_copying_deactivates(self):
        engine = self._engine()
        engine.start_copying("follower-1", "leader-1")
        result = engine.stop_copying("follower-1", "leader-1")
        assert result is True
        rels = engine.get_active_relationships("follower-1", as_follower=True)
        assert len(rels) == 0

    def test_stop_copying_nonexistent_returns_false(self):
        engine = self._engine()
        result = engine.stop_copying("nobody", "nobody")
        assert result is False

    def test_get_active_relationships_as_follower(self):
        engine = self._engine()
        engine.start_copying("f1", "l1")
        engine.start_copying("f1", "l2")
        engine.start_copying("f2", "l1")
        rels = engine.get_active_relationships("f1", as_follower=True)
        assert len(rels) == 2
        leaders = {r.leader_id for r in rels}
        assert leaders == {"l1", "l2"}

    def test_get_active_relationships_as_leader(self):
        engine = self._engine()
        engine.start_copying("f1", "l1")
        engine.start_copying("f2", "l1")
        rels = engine.get_active_relationships("l1", as_follower=False)
        assert len(rels) == 2

    def test_inactive_relationship_excluded(self):
        engine = self._engine()
        engine.start_copying("f1", "l1")
        engine.stop_copying("f1", "l1")
        rels = engine.get_active_relationships("f1", as_follower=True)
        assert len(rels) == 0

    # ── Trade synchronisation ────────────────────────────────────────────────

    def test_sync_trade_propagates_to_followers(self):
        engine = self._engine()
        engine.start_copying("f1", "leader-1")
        engine.start_copying("f2", "leader-1")
        result = engine.sync_trade("TRADE_001", "leader-1")
        assert len(result) == 2
        follower_ids = set(result.values())
        assert follower_ids == {"f1", "f2"}

    def test_sync_trade_no_followers(self):
        engine = self._engine()
        result = engine.sync_trade("TRADE_001", "leader-nobody")
        assert result == {}

    def test_sync_trade_skips_inactive(self):
        engine = self._engine()
        engine.start_copying("f1", "l1")
        engine.stop_copying("f1", "l1")
        result = engine.sync_trade("T1", "l1")
        assert result == {}

    def test_sync_trade_copy_ids_unique(self):
        engine = self._engine()
        engine.start_copying("f1", "l1")
        engine.start_copying("f2", "l1")
        result = engine.sync_trade("T1", "l1")
        copy_ids = list(result.keys())
        assert len(copy_ids) == len(set(copy_ids))

    # ── copy_trade proportional sizing ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_copy_trade_proportional(self):
        engine = self._engine()
        leader_trade = {
            "symbol": "XAUUSD",
            "side": "buy",
            "quantity": 1.0,
            "price": 2000.0,
        }
        follower_config = {
            "follower_id": "follower-1",
            "leader_id": "leader-1",
            "copy_ratio": 0.5,
            "max_position_size": 0.5,
        }
        copied = await engine.copy_trade(
            leader_trade=leader_trade,
            follower_config=follower_config,
            follower_balance=50_000,
        )
        assert copied["symbol"] == "XAUUSD"
        assert copied["quantity"] == pytest.approx(0.25, rel=1e-3)

    @pytest.mark.asyncio
    async def test_copy_trade_full_ratio_same_balance(self):
        engine = self._engine()
        leader_trade = {
            "symbol": "EURUSD",
            "side": "buy",
            "quantity": 1.0,
            "price": 1.08,
        }
        follower_config = {
            "follower_id": "f1",
            "copy_ratio": 1.0,
            "max_position_size": 1.0,
        }
        copied = await engine.copy_trade(
            leader_trade=leader_trade,
            follower_config=follower_config,
            follower_balance=100_000,
        )
        assert copied["quantity"] == pytest.approx(1.0, rel=1e-3)

    @pytest.mark.asyncio
    async def test_risk_limits_raise_exception(self):
        engine = self._engine()
        large_trade = {
            "symbol": "XAUUSD",
            "quantity": 10.0,
            "side": "buy",
            "price": 2000.0,
        }
        follower_config = {
            "follower_id": "follower-1",
            "copy_ratio": 1.0,
            "max_position_size": 0.001,  # very tight limit
        }
        with pytest.raises(RiskLimitExceededError):
            await engine.copy_trade(
                leader_trade=large_trade,
                follower_config=follower_config,
                follower_balance=100_000,
            )

    # ── Leaderboard ──────────────────────────────────────────────────────────

    def test_leaderboard_ranking_order(self):
        engine = self._engine()
        traders = [
            {"id": "trader-1", "return": 0.25, "sharpe": 1.5, "followers": 10},
            {"id": "trader-2", "return": 0.15, "sharpe": 2.0, "followers": 5},
            {"id": "trader-3", "return": 0.30, "sharpe": 1.2, "followers": 20},
        ]
        leaderboard = engine.calculate_leaderboard(traders)
        assert len(leaderboard) == 3
        assert leaderboard[0]["rank"] == 1
        assert leaderboard[1]["rank"] == 2
        assert leaderboard[2]["rank"] == 3

    def test_leaderboard_rank_1_has_highest_score(self):
        engine = self._engine()
        traders = [
            {"id": "a", "return": 0.10, "sharpe": 1.0, "followers": 1},
            {"id": "b", "return": 0.50, "sharpe": 3.0, "followers": 100},
        ]
        leaderboard = engine.calculate_leaderboard(traders)
        assert leaderboard[0]["id"] == "b"

    def test_leaderboard_empty_input(self):
        engine = self._engine()
        result = engine.calculate_leaderboard([])
        assert result == []

    def test_leaderboard_single_trader(self):
        engine = self._engine()
        result = engine.calculate_leaderboard([{"id": "solo", "return": 0.2, "sharpe": 1.5, "followers": 3}])
        assert len(result) == 1
        assert result[0]["rank"] == 1
