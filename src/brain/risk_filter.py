"""Final risk gate before execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.brain.sizing_engine import SizeRecommendation
from src.risk.kill_switch import kill_switch


@dataclass
class RiskDecision:
    approved: bool
    size: Any  # Modified size or original
    reject_reason: str | None = None


class RiskFilter:
    """Final risk checks."""
    
    def evaluate(
        self,
        signal: Any,
        size: SizeRecommendation,
        current_positions: list[Any],
        daily_pnl: float,
        daily_limit: float = -2000.0
    ) -> RiskDecision:
        """Final go/no-go decision."""
        
        # Kill switch
        if kill_switch.is_killed():
            return RiskDecision(False, None, "KILL_SWITCH_ACTIVE")
        
        # Daily loss limit
        if daily_pnl < daily_limit:
            return RiskDecision(False, None, "DAILY_LIMIT_REACHED")
        
        # Position concentration
        total_exposure = sum(p.size for p in current_positions)
        if total_exposure + size.quantity > size.portfolio_value * Decimal("0.2"):
            # Reduce size instead of reject
            reduced = size.portfolio_value * Decimal("0.2") - total_exposure
            if reduced > 0:
                return RiskDecision(True, reduced, "SIZE_REDUCED_CONCENTRATION")
            return RiskDecision(False, None, "MAX_CONCENTRATION")
        
        # Correlation check (don't add to correlated positions)
        # ... implementation
        
        return RiskDecision(True, size.quantity, None)
