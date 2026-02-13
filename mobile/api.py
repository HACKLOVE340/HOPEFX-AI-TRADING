"""
Mobile-Optimized API
"""

from typing import Dict, Any, Optional
from decimal import Decimal


class MobileAPI:
    """Mobile-optimized API endpoints"""

    def __init__(self):
        self.compression_enabled = True

    def get_portfolio_mobile(
        self,
        user_id: str,
        compression: bool = True,
        include_charts: bool = False
    ) -> Dict[str, Any]:
        """Get portfolio data optimized for mobile"""
        return {
            'user_id': user_id,
            'total_value': Decimal('10000.00'),
            'positions': [],
            'compression': compression,
            'charts': include_charts
        }

    def place_order_mobile(
        self,
        user_id: str,
        symbol: str,
        order_type: str,
        side: str,
        quantity: float,
        confirm_required: bool = True
    ) -> Dict[str, Any]:
        """Place order from mobile"""
        return {
            'order_id': f"MOB_ORD_{user_id}_{symbol}",
            'status': 'pending' if confirm_required else 'submitted',
            'symbol': symbol,
            'quantity': quantity
        }
