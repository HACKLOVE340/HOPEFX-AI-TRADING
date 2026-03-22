from __future__ import annotations

from decimal import Decimal
from typing import Protocol, Optional

import structlog

from hopefx.config.settings import settings
from hopefx.events.schemas import TickData

logger = structlog.get_logger()


class TickValidator(Protocol):
    """Protocol for tick validation strategies."""

    def validate(self, tick: TickData) -> bool:
        ...


class XAUUSDValidator:
    """XAUUSD specific validation rules."""

    def __init__(self) -> None:
        self._last_valid_tick: Optional[TickData] = None
        self._price_deviation_threshold = Decimal("0.05")  # 5% max deviation
        self._validation_count = 0
        self._rejection_count = 0

    def validate(self, tick: TickData) -> bool:
        """Validate XAUUSD tick."""
        self._validation_count += 1
        
        # Basic sanity checks
        if tick.bid <= 0 or tick.ask <= 0:
            self._rejection_count += 1
            logger.warning("validation.invalid_price", bid=tick.bid, ask=tick.ask)
            return False

        if tick.spread <= 0:
            self._rejection_count += 1
            logger.warning("validation.negative_spread", spread=tick.spread)
            return False

        if tick.spread > settings.xauusd_spread_threshold:
            self._rejection_count += 1
            logger.warning(
                "validation.excessive_spread",
                spread=tick.spread,
                threshold=settings.xauusd_spread_threshold
            )
            return False

        # Price continuity check
        if self._last_valid_tick:
            mid = tick.mid
            last_mid = self._last_valid_tick.mid

            if last_mid > 0:
                deviation = abs(mid - last_mid) / last_mid
                if deviation > self._price_deviation_threshold:
                    self._rejection_count += 1
                    logger.warning(
                        "validation.price_jump",
                        deviation=float(deviation),
                        last_price=last_mid,
                        current_price=mid
                    )
                    return False

        self._last_valid_tick = tick
        return True

    def get_stats(self) -> dict[str, float | int]:
        """Return validation statistics."""
        return {
            "total": self._validation_count,
            "rejected": self._rejection_count,
            "rejection_rate": (
                self._rejection_count / self._validation_count if self._validation_count > 0 else 0
            ),
        }


class MultiLayerValidator:
    """Composite validator with multiple validation layers."""

    def __init__(self) -> None:
        self._validators: list[TickValidator] = []
        self._rejection_count = 0
        self._total_count = 0

    def add_validator(self, validator: TickValidator) -> None:
        """Add validation layer."""
        self._validators.append(validator)

    def validate(self, tick: TickData) -> bool:
        """Run all validators."""
        self._total_count += 1

        for validator in self._validators:
            if not validator.validate(tick):
                self._rejection_count += 1
                if self._total_count > 0:
                    rejection_rate = self._rejection_count / self._total_count
                    if rejection_rate > 0.1:  # Alert if >10% rejected
                        logger.error(
                            "validation.high_rejection_rate",
                            rate=rejection_rate,
                            rejected=self._rejection_count,
                            total=self._total_count
                        )
                return False

        return True

    def get_stats(self) -> dict[str, float | int]:
        """Return validation statistics."""
        return {
            "total": self._total_count,
            "rejected": self._rejection_count,
            "rejection_rate": (
                self._rejection_count / self._total_count if self._total_count > 0 else 0
            ),
        }
