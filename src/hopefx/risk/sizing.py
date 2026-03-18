from __future__ import annotations

from decimal import Decimal

import structlog

from hopefx.config.settings import settings

logger = structlog.get_logger()


class PositionSizer:
    """ATR-based position sizing."""

    def calculate(
        self,
        equity: Decimal,
        risk_per_trade: Decimal,
        stop_loss: Decimal,  # in price terms
        symbol: str,
        atr: Decimal | None = None,
    ) -> Decimal:
        """Calculate position size based on risk."""
        if stop_loss <= 0:
            logger.error("risk.invalid_stop_loss", stop_loss=stop_loss)
            return Decimal("0")

        # Risk amount in currency
        risk_amount = equity * risk_per_trade

        # Position size = Risk Amount / Stop Loss Distance
        # For XAUUSD, 1 pip = 0.01, but price is in dollars
        position_size = risk_amount / stop_loss

        # Apply leverage limits
        max_notional = equity * Decimal(str(settings.default_leverage))
        if position_size * Decimal("2000") > max_notional:  # Approximate XAUUSD price
            position_size = max_notional / Decimal("2000")

        # Round to standard lot sizes
        return Decimal(str(round(float(position_size), 2)))
