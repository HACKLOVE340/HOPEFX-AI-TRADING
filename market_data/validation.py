# market_data/validator.py
"""
Market Data Validation - FIA 3.1 Market Data Reasonability Checks
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class DataQualityIssue(Enum):
    STALE_DATA = "stale_data"
    PRICE_JUMP = "price_jump"
    ZERO_VOLUME = "zero_volume"
    NEGATIVE_SPREAD = "negative_spread"
    MISSING_FIELDS = "missing_fields"
    OUTSIDE_HOURS = "outside_hours"

@dataclass
class ValidationResult:
    is_valid: bool
    quality_score: float  # 0.0 to 1.0
    issues: List[Dict]
    timestamp: datetime

class MarketDataValidator:
    """
    Real-time market data validation
    Prevents trading on stale, incomplete, or aberrant data
    """
    
    def __init__(
        self,
        max_staleness_seconds: int = 5,
        max_price_jump_pct: float = 0.02,  # 2% max jump
        min_volume: float = 1.0,
        reference_prices: Optional[Dict[str, float]] = None
    ):
        self.max_staleness = timedelta(seconds=max_staleness_seconds)
        self.max_price_jump = max_price_jump_pct
        self.min_volume = min_volume
        self.reference_prices = reference_prices or {}
        self.last_valid_data: Dict[str, datetime] = {}
        self.quality_history: List[ValidationResult] = []
    
    def validate_tick(self, tick: Dict, symbol: str) -> ValidationResult:
        """
        Validate single tick data
        FIA 3.1: Market Data Reasonability Checks
        """
        issues = []
        checks_passed = 0
        total_checks = 6
        
        # 1. Staleness check
        tick_time = tick.get('timestamp')
        if tick_time:
            if isinstance(tick_time, (int, float)):
                tick_time = datetime.fromtimestamp(tick_time)
            age = datetime.now() - tick_time
            if age > self.max_staleness:
                issues.append({
                    'type': DataQualityIssue.STALE_DATA.value,
                    'severity': 'high',
                    'message': f'Data is {age.total_seconds()}s old (max {self.max_staleness.total_seconds()}s)',
                    'timestamp': datetime.now().isoformat()
                })
            else:
                checks_passed += 1
        
        # 2. Price jump check
        current_price = tick.get('price') or tick.get('close')
        if current_price and symbol in self.reference_prices:
            ref_price = self.reference_prices[symbol]
            jump = abs(current_price - ref_price) / ref_price
            if jump > self.max_price_jump:
                issues.append({
                    'type': DataQualityIssue.PRICE_JUMP.value,
                    'severity': 'critical',
                    'message': f'Price jump of {jump:.2%} detected (max {self.max_price_jump:.2%})',
                    'current': current_price,
                    'reference': ref_price
                })
            else:
                checks_passed += 1
        
        # 3. Volume check
        volume = tick.get('volume', 0)
        if volume < self.min_volume:
            issues.append({
                'type': DataQualityIssue.ZERO_VOLUME.value,
                'severity': 'medium',
                'message': f'Volume {volume} below minimum {self.min_volume}'
            })
        else:
            checks_passed += 1
        
        # 4. Spread check (if bid/ask available)
        bid = tick.get('bid')
        ask = tick.get('ask')
        if bid and ask:
            if ask <= bid:
                issues.append({
                    'type': DataQualityIssue.NEGATIVE_SPREAD.value,
                    'severity': 'critical',
                    'message': f'Negative spread: bid={bid}, ask={ask}'
                })
            else:
                checks_passed += 1
        
        # 5. Required fields check
        required = ['timestamp', 'price']  # or 'close', 'bid/ask'
        has_price = any(k in tick for k in ['price', 'close', 'bid', 'ask'])
        if has_price and 'timestamp' in tick:
            checks_passed += 1
        else:
            issues.append({
                'type': DataQualityIssue.MISSING_FIELDS.value,
                'severity': 'high',
                'message': f'Missing required fields. Has price: {has_price}'
            })
        
        # 6. Trading hours check (simplified)
        if tick_time and not self._is_trading_hours(tick_time, symbol):
            issues.append({
                'type': DataQualityIssue.OUTSIDE_HOURS.value,
                'severity': 'low',
                'message': 'Data outside normal trading hours'
            })
        else:
            checks_passed += 1
        
        # Calculate quality score
        quality_score = checks_passed / total_checks
        
        # Update reference price if valid
        is_valid = len([i for i in issues if i['severity'] == 'critical']) == 0
        if is_valid and current_price:
            self.reference_prices[symbol] = current_price
            self.last_valid_data[symbol] = datetime.now()
        
        result = ValidationResult(
            is_valid=is_valid and quality_score >= 0.8,
            quality_score=quality_score,
            issues=issues,
            timestamp=datetime.now()
        )
        
        self.quality_history.append(result)
        
        # Log critical issues
        critical_issues = [i for i in issues if i['severity'] == 'critical']
        if critical_issues:
            logger.critical(f"Critical data quality issues for {symbol}: {critical_issues}")
        
        return result
    
    def _is_trading_hours(self, dt: datetime, symbol: str) -> bool:
        """Check if datetime is within trading hours for symbol"""
        # Simplified - would check forex market hours
        return True  # Forex is 24/5
    
    def validate_ohlc(self, data: pd.DataFrame, symbol: str) -> ValidationResult:
        """Validate OHLCV dataframe"""
        issues = []
        
        # Check for NaN values
        nan_pct = data.isnull().sum().sum() / (len(data) * len(data.columns))
        if nan_pct > 0.05:  # More than 5% NaN
            issues.append({
                'type': 'excessive_nan',
                'severity': 'high',
                'message': f'{nan_pct:.1%} NaN values in data'
            })
        
        # Check for price consistency
        invalid_ohlc = (
            (data['high'] < data['low']) |
            (data['close'] > data['high']) |
            (data['close'] < data['low']) |
            (data['open'] > data['high']) |
            (data['open'] < data['low'])
        )
        if invalid_ohlc.any():
            issues.append({
                'type': 'invalid_ohlc',
                'severity': 'critical',
                'message': f'{invalid_ohlc.sum()} invalid OHLC relationships'
            })
        
        # Check for gaps
        if isinstance(data.index, pd.DatetimeIndex):
            expected_freq = pd.infer_freq(data.index)
            if expected_freq:
                gaps = data.index.to_series().diff() > pd.Timedelta(expected_freq) * 2
                if gaps.any():
                    issues.append({
                        'type': 'data_gaps',
                        'severity': 'medium',
                        'message': f'{gaps.sum()} gaps in data detected'
                    })
        
        quality_score = 1.0 - (len(issues) * 0.2)
        is_valid = len([i for i in issues if i['severity'] == 'critical']) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            quality_score=max(0, quality_score),
            issues=issues,
            timestamp=datetime.now()
        )
    
    def get_quality_report(self) -> Dict:
        """Generate data quality report"""
        if not self.quality_history:
            return {'message': 'No validation history'}
        
        recent = self.quality_history[-100:]  # Last 100 validations
        
        return {
            'total_validations': len(self.quality_history),
            'average_quality_score': np.mean([r.quality_score for r in recent]),
            'valid_rate': np.mean([r.is_valid for r in recent]),
            'critical_issues_count': sum(
                len([i for i in r.issues if i['severity'] == 'critical']) 
                for r in recent
            ),
            'last_updated': datetime.now().isoformat()
        }
