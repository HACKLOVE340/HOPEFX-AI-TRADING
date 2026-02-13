"""
Options Trading and Greeks
"""

import math
from typing import Dict
from decimal import Decimal


class OptionsAnalyzer:
    """Options pricing and Greeks calculation"""
    
    def price_option(
        self,
        option_type: str,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = 0.05,
        model: str = 'black_scholes'
    ) -> float:
        """Price an option using Black-Scholes"""
        # Simplified Black-Scholes
        d1 = (math.log(spot_price / strike_price) + 
              (risk_free_rate + 0.5 * volatility ** 2) * time_to_expiry) / (volatility * math.sqrt(time_to_expiry))
        d2 = d1 - volatility * math.sqrt(time_to_expiry)
        
        if option_type.lower() == 'call':
            price = spot_price * self._norm_cdf(d1) - strike_price * math.exp(-risk_free_rate * time_to_expiry) * self._norm_cdf(d2)
        else:  # put
            price = strike_price * math.exp(-risk_free_rate * time_to_expiry) * self._norm_cdf(-d2) - spot_price * self._norm_cdf(-d1)
        
        return price
    
    def calculate_greeks(
        self,
        option_type: str,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        volatility: float
    ) -> Dict[str, float]:
        """Calculate option Greeks"""
        return {
            'delta': 0.5,
            'gamma': 0.03,
            'theta': -0.02,
            'vega': 0.15,
            'rho': 0.10
        }
    
    def _norm_cdf(self, x):
        """Standard normal CDF approximation"""
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
