"""
Tests for the mobile module.
"""

import pytest
from decimal import Decimal
from datetime import datetime

from mobile.api import MobileAPI
from mobile.push_notifications import PushNotificationManager


class TestMobileAPI:
    """Tests for MobileAPI class."""
    
    def test_mobile_api_initialization(self):
        """Test MobileAPI initialization."""
        api = MobileAPI()
        
        assert api is not None
        assert api.compression_enabled is True
    
    def test_get_portfolio_mobile(self):
        """Test getting mobile portfolio data."""
        api = MobileAPI()
        
        result = api.get_portfolio_mobile('user_1')
        
        assert result['user_id'] == 'user_1'
        assert 'total_value' in result
        assert 'positions' in result
        assert result['compression'] is True
    
    def test_get_portfolio_mobile_with_charts(self):
        """Test getting portfolio with charts."""
        api = MobileAPI()
        
        result = api.get_portfolio_mobile('user_1', include_charts=True)
        
        assert result['charts'] is True
    
    def test_get_portfolio_mobile_no_compression(self):
        """Test getting portfolio without compression."""
        api = MobileAPI()
        
        result = api.get_portfolio_mobile('user_1', compression=False)
        
        assert result['compression'] is False
    
    def test_place_order_mobile(self):
        """Test placing mobile order."""
        api = MobileAPI()
        
        result = api.place_order_mobile(
            user_id='user_1',
            symbol='EUR/USD',
            order_type='market',
            side='buy',
            quantity=1000.0
        )
        
        assert 'order_id' in result
        assert result['symbol'] == 'EUR/USD'
        assert result['quantity'] == 1000.0
    
    def test_place_order_mobile_confirm_required(self):
        """Test order requires confirmation by default."""
        api = MobileAPI()
        
        result = api.place_order_mobile(
            user_id='user_1',
            symbol='BTC/USD',
            order_type='limit',
            side='sell',
            quantity=0.5
        )
        
        assert result['status'] == 'pending'
    
    def test_place_order_mobile_no_confirm(self):
        """Test order without confirmation."""
        api = MobileAPI()
        
        result = api.place_order_mobile(
            user_id='user_1',
            symbol='BTC/USD',
            order_type='market',
            side='buy',
            quantity=0.5,
            confirm_required=False
        )
        
        assert result['status'] == 'submitted'
    
    def test_order_id_format(self):
        """Test order ID contains user and symbol."""
        api = MobileAPI()
        
        result = api.place_order_mobile(
            user_id='user_123',
            symbol='ETH/USD',
            order_type='market',
            side='buy',
            quantity=1.0
        )
        
        assert 'user_123' in result['order_id']
        assert 'ETH/USD' in result['order_id']


class TestPushNotificationManager:
    """Tests for PushNotificationManager class."""
    
    def test_manager_initialization(self):
        """Test PushNotificationManager initialization."""
        manager = PushNotificationManager()
        
        assert manager is not None
        assert manager.fcm_enabled is False
        assert manager.apns_enabled is False
    
    def test_send_notification(self, capsys):
        """Test sending a notification."""
        manager = PushNotificationManager()
        
        result = manager.send_notification(
            user_id='user_1',
            title='Test Title',
            body='Test body message'
        )
        
        assert result is True
        
        captured = capsys.readouterr()
        assert 'Test Title' in captured.out
        assert 'user_1' in captured.out
    
    def test_send_notification_with_category(self, capsys):
        """Test sending notification with category."""
        manager = PushNotificationManager()
        
        result = manager.send_notification(
            user_id='user_1',
            title='Trade Alert',
            body='Your order was filled',
            category='trade'
        )
        
        assert result is True
    
    def test_send_notification_with_data(self, capsys):
        """Test sending notification with data payload."""
        manager = PushNotificationManager()
        
        result = manager.send_notification(
            user_id='user_1',
            title='Price Update',
            body='BTC price changed',
            data={'price': 50000, 'change': 2.5}
        )
        
        assert result is True
    
    def test_send_price_alert(self, capsys):
        """Test sending price alert."""
        manager = PushNotificationManager()
        
        result = manager.send_price_alert(
            user_id='user_1',
            symbol='BTC/USD',
            price=50000.0,
            direction='above'
        )
        
        assert result is True
        
        captured = capsys.readouterr()
        assert 'BTC/USD' in captured.out
    
    def test_send_price_alert_below(self, capsys):
        """Test sending price alert for below threshold."""
        manager = PushNotificationManager()
        
        result = manager.send_price_alert(
            user_id='user_1',
            symbol='ETH/USD',
            price=3000.0,
            direction='below'
        )
        
        assert result is True
