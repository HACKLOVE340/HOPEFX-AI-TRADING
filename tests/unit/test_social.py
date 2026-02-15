"""
Tests for the social trading module.
"""

import pytest
from decimal import Decimal
from datetime import datetime

from social.copy_trading import CopyTradingEngine, CopyRelationship
from social.leaderboards import LeaderboardManager, LeaderboardEntry
from social.performance import PerformanceTracker, PerformanceMetric


class TestCopyRelationship:
    """Tests for CopyRelationship class."""
    
    def test_copy_relationship_creation(self):
        """Test creating a copy relationship."""
        relationship = CopyRelationship(
            follower_id='user_1',
            leader_id='user_2',
            copy_ratio=0.5
        )
        
        assert relationship.follower_id == 'user_1'
        assert relationship.leader_id == 'user_2'
        assert relationship.copy_ratio == 0.5
        assert relationship.is_active is True
        assert relationship.started_at is not None
    
    def test_copy_relationship_defaults(self):
        """Test default values for copy relationship."""
        relationship = CopyRelationship('f1', 'l1')
        
        assert relationship.copy_ratio == 1.0
        assert relationship.max_allocation is None
        assert relationship.max_per_trade is None


class TestCopyTradingEngine:
    """Tests for CopyTradingEngine class."""
    
    def test_engine_initialization(self):
        """Test CopyTradingEngine initialization."""
        engine = CopyTradingEngine()
        
        assert engine is not None
        assert len(engine.relationships) == 0
    
    def test_start_copying(self):
        """Test starting copy relationship."""
        engine = CopyTradingEngine()
        
        relationship = engine.start_copying(
            follower_id='follower_1',
            leader_id='leader_1',
            copy_ratio=0.75
        )
        
        assert relationship is not None
        assert relationship.follower_id == 'follower_1'
        assert relationship.leader_id == 'leader_1'
        assert relationship.copy_ratio == 0.75
        assert 'follower_1_leader_1' in engine.relationships
    
    def test_start_copying_with_limits(self):
        """Test starting copy relationship with allocation limits."""
        engine = CopyTradingEngine()
        
        relationship = engine.start_copying(
            follower_id='f1',
            leader_id='l1',
            copy_ratio=1.0,
            max_allocation=Decimal('10000'),
            max_per_trade=Decimal('500')
        )
        
        assert relationship.max_allocation == Decimal('10000')
        assert relationship.max_per_trade == Decimal('500')
    
    def test_stop_copying(self):
        """Test stopping copy relationship."""
        engine = CopyTradingEngine()
        
        engine.start_copying('f1', 'l1')
        result = engine.stop_copying('f1', 'l1')
        
        assert result is True
        assert engine.relationships['f1_l1'].is_active is False
    
    def test_stop_copying_nonexistent(self):
        """Test stopping non-existent relationship."""
        engine = CopyTradingEngine()
        
        result = engine.stop_copying('f1', 'l1')
        
        assert result is False
    
    def test_sync_trade(self):
        """Test synchronizing a trade to followers."""
        engine = CopyTradingEngine()
        
        engine.start_copying('f1', 'l1')
        engine.start_copying('f2', 'l1')
        engine.start_copying('f3', 'l2')  # Different leader
        
        copied_trades = engine.sync_trade('trade_123', 'l1')
        
        assert len(copied_trades) == 2
        assert 'COPY_trade_123_f1' in copied_trades
        assert 'COPY_trade_123_f2' in copied_trades
    
    def test_sync_trade_inactive_relationship(self):
        """Test that inactive relationships don't receive synced trades."""
        engine = CopyTradingEngine()
        
        engine.start_copying('f1', 'l1')
        engine.stop_copying('f1', 'l1')
        
        copied_trades = engine.sync_trade('trade_123', 'l1')
        
        assert len(copied_trades) == 0
    
    def test_get_active_relationships_as_follower(self):
        """Test getting active relationships as follower."""
        engine = CopyTradingEngine()
        
        engine.start_copying('f1', 'l1')
        engine.start_copying('f1', 'l2')
        engine.start_copying('f2', 'l1')
        
        relationships = engine.get_active_relationships('f1', as_follower=True)
        
        assert len(relationships) == 2
    
    def test_get_active_relationships_as_leader(self):
        """Test getting active relationships as leader."""
        engine = CopyTradingEngine()
        
        engine.start_copying('f1', 'l1')
        engine.start_copying('f2', 'l1')
        engine.start_copying('f3', 'l2')
        
        relationships = engine.get_active_relationships('l1', as_follower=False)
        
        assert len(relationships) == 2


class TestLeaderboardEntry:
    """Tests for LeaderboardEntry class."""
    
    def test_entry_creation(self):
        """Test creating a leaderboard entry."""
        entry = LeaderboardEntry(
            user_id='user_1',
            score=Decimal('1000.50'),
            rank=1
        )
        
        assert entry.user_id == 'user_1'
        assert entry.score == Decimal('1000.50')
        assert entry.rank == 1
    
    def test_entry_default_rank(self):
        """Test default rank for entry."""
        entry = LeaderboardEntry('user_1', Decimal('100'))
        
        assert entry.rank == 0


class TestLeaderboardManager:
    """Tests for LeaderboardManager class."""
    
    def test_manager_initialization(self):
        """Test LeaderboardManager initialization."""
        manager = LeaderboardManager()
        
        assert manager is not None
        assert len(manager.leaderboards) == 0
    
    def test_update_leaderboard_new_category(self):
        """Test updating leaderboard creates new category."""
        manager = LeaderboardManager()
        
        manager.update_leaderboard('pnl', 'user_1', Decimal('500'))
        
        assert 'pnl' in manager.leaderboards
        assert len(manager.leaderboards['pnl']) == 1
    
    def test_update_leaderboard_ranking(self):
        """Test that leaderboard is correctly ranked."""
        manager = LeaderboardManager()
        
        manager.update_leaderboard('pnl', 'user_a', Decimal('100'))
        manager.update_leaderboard('pnl', 'user_b', Decimal('300'))
        manager.update_leaderboard('pnl', 'user_c', Decimal('200'))
        
        leaderboard = manager.get_leaderboard('pnl')
        
        assert leaderboard[0].user_id == 'user_b'
        assert leaderboard[0].rank == 1
        assert leaderboard[1].user_id == 'user_c'
        assert leaderboard[1].rank == 2
        assert leaderboard[2].user_id == 'user_a'
        assert leaderboard[2].rank == 3
    
    def test_update_existing_entry(self):
        """Test updating existing entry."""
        manager = LeaderboardManager()
        
        manager.update_leaderboard('pnl', 'user_1', Decimal('100'))
        manager.update_leaderboard('pnl', 'user_1', Decimal('500'))
        
        leaderboard = manager.get_leaderboard('pnl')
        
        assert len(leaderboard) == 1
        assert leaderboard[0].score == Decimal('500')
    
    def test_get_leaderboard_with_limit(self):
        """Test getting leaderboard with limit."""
        manager = LeaderboardManager()
        
        for i in range(10):
            manager.update_leaderboard('pnl', f'user_{i}', Decimal(i * 100))
        
        top_5 = manager.get_leaderboard('pnl', limit=5)
        
        assert len(top_5) == 5
        assert top_5[0].score == Decimal('900')  # Highest score
    
    def test_get_leaderboard_nonexistent(self):
        """Test getting non-existent leaderboard."""
        manager = LeaderboardManager()
        
        leaderboard = manager.get_leaderboard('nonexistent')
        
        assert leaderboard == []
    
    def test_get_user_rank(self):
        """Test getting user's rank."""
        manager = LeaderboardManager()
        
        manager.update_leaderboard('pnl', 'user_1', Decimal('300'))
        manager.update_leaderboard('pnl', 'user_2', Decimal('100'))
        manager.update_leaderboard('pnl', 'user_3', Decimal('200'))
        
        rank = manager.get_user_rank('pnl', 'user_3')
        
        assert rank == 2
    
    def test_get_user_rank_not_found(self):
        """Test getting rank for user not in leaderboard."""
        manager = LeaderboardManager()
        
        rank = manager.get_user_rank('pnl', 'nonexistent')
        
        assert rank == 0


class TestPerformanceMetric:
    """Tests for PerformanceMetric class."""
    
    def test_metric_creation(self):
        """Test creating a performance metric."""
        metric = PerformanceMetric('user_1', 'monthly')
        
        assert metric.user_id == 'user_1'
        assert metric.period == 'monthly'
        assert metric.total_return == Decimal('0.0')
        assert metric.total_trades == 0
        assert metric.updated_at is not None


class TestPerformanceTracker:
    """Tests for PerformanceTracker class."""
    
    def test_tracker_initialization(self):
        """Test PerformanceTracker initialization."""
        tracker = PerformanceTracker()
        
        assert tracker is not None
        assert len(tracker.metrics) == 0
    
    def test_record_trade(self):
        """Test recording a trade."""
        tracker = PerformanceTracker()
        
        tracker.record_trade('user_1', Decimal('100'))
        
        metric = tracker.get_performance('user_1')
        
        assert metric.total_trades == 1
        assert metric.total_return == Decimal('100')
    
    def test_record_multiple_trades(self):
        """Test recording multiple trades."""
        tracker = PerformanceTracker()
        
        tracker.record_trade('user_1', Decimal('100'))
        tracker.record_trade('user_1', Decimal('-50'))
        tracker.record_trade('user_1', Decimal('200'))
        
        metric = tracker.get_performance('user_1')
        
        assert metric.total_trades == 3
        assert metric.total_return == Decimal('250')
    
    def test_get_performance_nonexistent(self):
        """Test getting performance for non-existent user."""
        tracker = PerformanceTracker()
        
        metric = tracker.get_performance('nonexistent')
        
        assert metric.user_id == 'nonexistent'
        assert metric.total_trades == 0
    
    def test_calculate_win_rate(self):
        """Test win rate calculation."""
        tracker = PerformanceTracker()
        
        win_rate = tracker.calculate_win_rate('user_1', 7, 10)
        
        assert win_rate == Decimal('70.0')
    
    def test_calculate_win_rate_zero_trades(self):
        """Test win rate with zero trades."""
        tracker = PerformanceTracker()
        
        win_rate = tracker.calculate_win_rate('user_1', 0, 0)
        
        assert win_rate == Decimal('0.0')
    
    def test_record_trade_with_period(self):
        """Test recording trades with different periods."""
        tracker = PerformanceTracker()
        
        tracker.record_trade('user_1', Decimal('100'), period='daily')
        tracker.record_trade('user_1', Decimal('200'), period='monthly')
        
        daily = tracker.get_performance('user_1', 'daily')
        monthly = tracker.get_performance('user_1', 'monthly')
        
        assert daily.total_return == Decimal('100')
        assert monthly.total_return == Decimal('200')
