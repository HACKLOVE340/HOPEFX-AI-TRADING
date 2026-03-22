"""
Institutional-grade slippage models for realistic backtesting.
"""

import random
from decimal import Decimal
from enum import Enum
from typing import Literal

import numpy as np

from src.domain.enums import OrderType, TradeDirection
from src.domain.models import Order


class SlippageModel(Enum):
    """Slippage model types."""
    FIXED = "fixed"
    VARIABLE = "variable"
    VOLATILITY_BASED = "volatility_based"
    VOLUME_WEIGHTED = "volume_weighted"
    LOGARITHMIC = "logarithmic"  # Institutional standard


class SlippageSimulator:
    """
    Realistic slippage simulation for backtesting.
    
    Models based on:
    - Fixed: Constant slippage in bps
    - Variable: Random slippage with mean/std
    - Volatility-based: Scales with market volatility
    - Volume-weighted: Scales with order size relative to volume
    - Logarithmic: Log-scaling for large orders (institutional standard)
    """
    
    def __init__(
        self,
        model: SlippageModel = SlippageModel.VARIABLE,
        base_slippage_bps: float = 1.0,
        volatility_factor: float = 0.5,
        volume_factor: float = 1.0
    ):
        self.model = model
        self.base_slippage_bps = base_slippage_bps
        self.volatility_factor = volatility_factor
        self.volume_factor = volume_factor
    
    def apply_slippage(
        self,
        order: Order,
        base_price: Decimal,
        volatility: float = 0.0,
        volume_24h: float = 0.0,
        market_impact_model: Literal["square_root", "linear"] = "square_root"
    ) -> Decimal:
        """
        Apply slippage to order price.
        
        Args:
            order: Order to execute
            base_price: Current market price
            volatility: Annualized volatility (0-1)
            volume_24h: 24h trading volume
            market_impact_model: Market impact model
        
        Returns:
            Executed price with slippage
        """
        slippage_pct = self._calculate_slippage(
            order, volatility, volume_24h, market_impact_model
        )
        
        # Apply directionally
        if order.direction == TradeDirection.LONG:
            # Buy at higher price
            executed_price = base_price * (Decimal("1") + Decimal(str(slippage_pct)))
        else:
            # Sell at lower price
            executed_price = base_price * (Decimal("1") - Decimal(str(slippage_pct)))
        
        return executed_price.quantize(Decimal("0.00001"))
    
    def _calculate_slippage(
        self,
        order: Order,
        volatility: float,
        volume_24h: float,
        market_impact_model: str
    ) -> float:
        """Calculate slippage percentage."""
        base = self.base_slippage_bps / 10000  # Convert to pct
        
        if self.model == SlippageModel.FIXED:
            return base
        
        elif self.model == SlippageModel.VARIABLE:
            # Random slippage with normal distribution
            return random.gauss(base, base * 0.5)
        
        elif self.model == SlippageModel.VOLATILITY_BASED:
            # Scale with volatility
            vol_component = volatility * self.volatility_factor
            return base * (1 + vol_component)
        
        elif self.model == SlippageModel.VOLUME_WEIGHTED:
            # Scale with order size / volume
            if volume_24h > 0:
                participation_rate = float(order.quantity) / volume_24h
                return base * (1 + participation_rate * self.volume_factor)
            return base
        
        elif self.model == SlippageModel.LOGARITHMIC:
            # Institutional model: log-scaling for size
            # Based on square-root market impact model
            if market_impact_model == "square_root":
                # Impact ~ sqrt(order_size / volume)
                if volume_24h > 0:
                    participation = float(order.quantity) / volume_24h
                    impact = np.sqrt(participation) * self.volatility_factor
                    return base + impact
                return base
            else:
                # Linear impact
                if volume_24h > 0:
                    participation = float(order.quantity) / volume_24h
                    return base * (1 + participation)
                return base
        
        return base
    
    def estimate_market_impact(
        self,
        order_size: float,
        daily_volume: float,
        volatility: float,
        spread_bps: float = 1.0
    ) -> float:
        """
        Estimate permanent market impact using square-root law.
        
        Reference: Almgren et al. "Direct Estimation of Equity Market Impact"
        """
        if daily_volume == 0:
            return 0.0
        
        participation_rate = order_size / daily_volume
        
        # Square-root formula: I = sigma * sqrt(participation)
        impact = volatility * np.sqrt(participation_rate)
        
        # Add temporary impact (spread)
        total_impact = (spread_bps / 10000) + impact
        
        return total_impact
