# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
market_data/validation.py
==========================
Market data validation — FIA 3.1 Market Data Reasonability Checks.

Enhancements:
  - Rolling 30-day price bounds (IQR-based adaptive min/max)
  - Volume sanity check (IQR-based outlier detection on rolling window)
  - Rejection wiring: per-reason counters exposed via get_rejection_stats()
  - Cross-source divergence check (multi-feed consensus validation)
  - Bid/ask spread sanity (absolute and bps bounds)
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

UTC = timezone.utc

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_PRICE_HISTORY_SIZE = 43200  # ~30 days at 1-min bars
_VOLUME_WINDOW_SIZE = 500


class DataQualityIssue(Enum):
    STALE_DATA = "stale_data"
    PRICE_JUMP = "price_jump"
    PRICE_OUT_OF_BOUNDS = "price_out_of_bounds"
    ZERO_VOLUME = "zero_volume"
    VOLUME_OUTLIER = "volume_outlier"
    NEGATIVE_SPREAD = "negative_spread"
    SPREAD_TOO_WIDE = "spread_too_wide"
    MISSING_FIELDS = "missing_fields"
    OUTSIDE_HOURS = "outside_hours"
    CROSS_SOURCE_DIVERGENCE = "cross_source_divergence"


@dataclass
class ValidationResult:
    is_valid: bool
    quality_score: float
    issues: list[dict]
    timestamp: datetime
    rejection_reason: str | None = None


@dataclass
class _RollingBounds:
    _prices: deque = field(default_factory=lambda: deque(maxlen=_PRICE_HISTORY_SIZE))

    def update(self, price: float) -> None:
        self._prices.append(price)

    def iqr_bounds(self) -> tuple[float, float]:
        if len(self._prices) < 30:
            return 0.0, float("inf")
        arr = np.array(self._prices)
        q1, q3 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
        iqr = q3 - q1
        return q1 - 3 * iqr, q3 + 3 * iqr


class MarketDataValidator:
    """
    Real-time market data validation with rolling adaptive bounds.

    Features
    --------
    - Rolling 30-day price bounds (IQR)
    - Volume sanity via IQR on a rolling window
    - Bid/ask spread sanity (absolute and bps)
    - Cross-source divergence check
    - Per-reason rejection counters via get_rejection_stats()
    """

    MAX_SPREAD_BPS: float = 500.0
    MAX_SPREAD_ABS: float = 10.0
    MAX_SOURCE_DIVERGENCE: float = 0.005

    def __init__(
        self,
        max_staleness_seconds: int = 5,
        max_price_jump_pct: float = 0.02,
        min_volume: float = 0.0,
        reference_prices: dict[str, float] | None = None,
    ) -> None:
        self.max_staleness = timedelta(seconds=max_staleness_seconds)
        self.max_price_jump = max_price_jump_pct
        self.min_volume = min_volume
        self.reference_prices: dict[str, float] = reference_prices or {}
        self.last_valid_data: dict[str, datetime] = {}
        self.quality_history: list[ValidationResult] = []

        self._price_bounds: dict[str, _RollingBounds] = {}
        self._volume_window: dict[str, deque] = {}

        self._rejection_counts: dict[str, int] = {
            issue.value: 0 for issue in DataQualityIssue
        }
        self._accepted_count: int = 0
        self._total_count: int = 0

    def validate_tick(self, tick: dict, symbol: str) -> ValidationResult:
        """Validate a single tick against all quality checks."""
        self._total_count += 1
        issues: list[dict] = []
        checks_passed = 0
        total_checks = 7

        # 1. Staleness
        tick_time = self._parse_timestamp(tick.get("timestamp"))
        if tick_time is not None:
            age = datetime.now(UTC) - tick_time
            if age > self.max_staleness:
                issues.append(self._issue(
                    DataQualityIssue.STALE_DATA, "high",
                    f"Data is {age.total_seconds():.1f}s old (max {self.max_staleness.total_seconds()}s)",
                ))
            else:
                checks_passed += 1
        else:
            checks_passed += 1

        # 2. Price jump vs last known
        current_price = float(
            tick.get("price") or tick.get("close") or tick.get("mid") or 0.0
        )
        if current_price > 0 and symbol in self.reference_prices:
            ref = self.reference_prices[symbol]
            if ref > 0:
                jump = abs(current_price - ref) / ref
                if jump > self.max_price_jump:
                    issues.append(self._issue(
                        DataQualityIssue.PRICE_JUMP, "critical",
                        f"Price jump {jump:.2%} > max {self.max_price_jump:.2%}",
                        current=current_price, reference=ref,
                    ))
                else:
                    checks_passed += 1
            else:
                checks_passed += 1
        else:
            checks_passed += 1

        # 3. Rolling 30-day price bounds (IQR)
        if current_price > 0:
            bounds = self._price_bounds.setdefault(symbol, _RollingBounds())
            lo, hi = bounds.iqr_bounds()
            if lo > 0 and (current_price < lo or current_price > hi):
                issues.append(self._issue(
                    DataQualityIssue.PRICE_OUT_OF_BOUNDS, "critical",
                    f"Price {current_price:.2f} outside 30-day IQR bounds [{lo:.2f}, {hi:.2f}]",
                    price=current_price, lower=lo, upper=hi,
                ))
            else:
                checks_passed += 1
                bounds.update(current_price)
        else:
            checks_passed += 1

        # 4. Volume sanity (IQR-based)
        volume = float(tick.get("volume") or 0.0)
        if volume < self.min_volume and self.min_volume > 0:
            issues.append(self._issue(
                DataQualityIssue.ZERO_VOLUME, "medium",
                f"Volume {volume} below minimum {self.min_volume}",
            ))
        else:
            vol_window = self._volume_window.setdefault(
                symbol, deque(maxlen=_VOLUME_WINDOW_SIZE)
            )
            if volume > 0 and len(vol_window) >= 50:
                arr = np.array(vol_window)
                q1, q3 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
                iqr = q3 - q1
                upper = q3 + 5 * iqr
                if iqr > 0 and volume > upper:
                    issues.append(self._issue(
                        DataQualityIssue.VOLUME_OUTLIER, "low",
                        f"Volume {volume:.0f} exceeds IQR upper bound {upper:.0f}",
                        volume=volume, iqr_upper=upper,
                    ))
                else:
                    checks_passed += 1
                    vol_window.append(volume)
            else:
                checks_passed += 1
                if volume > 0:
                    vol_window.append(volume)

        # 5. Bid/ask spread sanity
        bid = float(tick.get("bid") or 0.0)
        ask = float(tick.get("ask") or 0.0)
        if bid > 0 and ask > 0:
            if ask <= bid:
                issues.append(self._issue(
                    DataQualityIssue.NEGATIVE_SPREAD, "critical",
                    f"Negative/zero spread: bid={bid}, ask={ask}",
                    bid=bid, ask=ask,
                ))
            else:
                spread = ask - bid
                mid = (bid + ask) / 2.0
                spread_bps = (spread / mid * 10_000.0) if mid > 0 else 0.0
                if spread_bps > self.MAX_SPREAD_BPS or spread > self.MAX_SPREAD_ABS:
                    issues.append(self._issue(
                        DataQualityIssue.SPREAD_TOO_WIDE, "high",
                        f"Spread {spread:.4f} ({spread_bps:.1f} bps) exceeds limits",
                        spread=spread, spread_bps=spread_bps,
                    ))
                else:
                    checks_passed += 1
        else:
            checks_passed += 1

        # 6. Required fields
        has_price = any(k in tick for k in ("price", "close", "bid", "ask", "mid"))
        if has_price:
            checks_passed += 1
        else:
            issues.append(self._issue(
                DataQualityIssue.MISSING_FIELDS, "high",
                "Missing required price fields",
            ))

        # 7. Trading hours (forex 24/5 — flag weekends only)
        if tick_time is not None and not self._is_trading_hours(tick_time, symbol):
            issues.append(self._issue(
                DataQualityIssue.OUTSIDE_HOURS, "low",
                "Data outside normal trading hours",
            ))
        else:
            checks_passed += 1

        quality_score = checks_passed / total_checks
        critical = [i for i in issues if i["severity"] == "critical"]
        is_valid = len(critical) == 0 and quality_score >= 0.8

        if is_valid and current_price > 0:
            self.reference_prices[symbol] = current_price
            self.last_valid_data[symbol] = datetime.now(UTC)

        primary_reason: str | None = None
        if not is_valid:
            for iss in issues:
                reason = iss["type"]
                self._rejection_counts[reason] = self._rejection_counts.get(reason, 0) + 1
                if primary_reason is None and iss["severity"] == "critical":
                    primary_reason = reason
            if primary_reason is None and issues:
                primary_reason = issues[0]["type"]
        else:
            self._accepted_count += 1

        result = ValidationResult(
            is_valid=is_valid,
            quality_score=quality_score,
            issues=issues,
            timestamp=datetime.now(UTC),
            rejection_reason=primary_reason,
        )
        self.quality_history.append(result)

        if critical:
            logger.warning(
                "Market data critical issues [%s]: %s",
                symbol,
                [i["message"] for i in critical],
            )

        return result

    def validate_cross_source(
        self,
        prices: dict[str, float],
        symbol: str,
    ) -> ValidationResult:
        """Check that prices from multiple sources agree within MAX_SOURCE_DIVERGENCE."""
        self._total_count += 1
        vals = [v for v in prices.values() if v > 0]
        if len(vals) < 2:
            self._accepted_count += 1
            return ValidationResult(
                is_valid=True, quality_score=1.0, issues=[],
                timestamp=datetime.now(UTC),
            )

        mean_price = sum(vals) / len(vals)
        max_dev = max(abs(v - mean_price) / mean_price for v in vals)
        if max_dev > self.MAX_SOURCE_DIVERGENCE:
            reason = DataQualityIssue.CROSS_SOURCE_DIVERGENCE.value
            self._rejection_counts[reason] = self._rejection_counts.get(reason, 0) + 1
            return ValidationResult(
                is_valid=False, quality_score=0.5,
                issues=[self._issue(
                    DataQualityIssue.CROSS_SOURCE_DIVERGENCE, "high",
                    f"Cross-source divergence {max_dev:.3%} > {self.MAX_SOURCE_DIVERGENCE:.3%}",
                    sources=prices, mean=mean_price, max_deviation=max_dev,
                )],
                timestamp=datetime.now(UTC),
                rejection_reason=reason,
            )

        self._accepted_count += 1
        return ValidationResult(
            is_valid=True, quality_score=1.0, issues=[],
            timestamp=datetime.now(UTC),
        )

    def validate_ohlc(self, data: pd.DataFrame, symbol: str) -> ValidationResult:
        """Validate an OHLCV DataFrame for internal consistency and gaps."""
        issues: list[dict] = []

        nan_pct = float(
            np.nan_to_num(
                data.isnull().sum().sum() / max(len(data) * len(data.columns), 1),
                nan=0.0,
            )
        )
        if nan_pct > 0.05:
            issues.append(self._issue(
                DataQualityIssue.MISSING_FIELDS, "high",
                f"{nan_pct:.1%} NaN values in OHLCV data",
            ))

        for col in ("high", "low", "close", "open"):
            if col not in data.columns:
                issues.append(self._issue(
                    DataQualityIssue.MISSING_FIELDS, "critical",
                    f"Missing required column: {col}",
                ))
                break
        else:
            invalid = (
                (data["high"] < data["low"])
                | (data["close"] > data["high"])
                | (data["close"] < data["low"])
                | (data["open"] > data["high"])
                | (data["open"] < data["low"])
            )
            if invalid.any():
                issues.append(self._issue(
                    DataQualityIssue.PRICE_JUMP, "critical",
                    f"{int(invalid.sum())} bars with invalid OHLC relationships",
                ))

        if isinstance(data.index, pd.DatetimeIndex) and len(data) > 2:
            expected_freq = pd.infer_freq(data.index)
            if expected_freq:
                gaps = data.index.to_series().diff() > pd.Timedelta(expected_freq) * 2
                if gaps.any():
                    issues.append(self._issue(
                        DataQualityIssue.STALE_DATA, "medium",
                        f"{int(gaps.sum())} time gaps detected in OHLCV data",
                    ))

        if "volume" in data.columns and len(data) >= 50:
            vols = data["volume"].dropna()
            if len(vols) >= 50:
                q1, q3 = float(vols.quantile(0.25)), float(vols.quantile(0.75))
                iqr = q3 - q1
                if iqr > 0:
                    outliers = vols[vols > q3 + 5 * iqr]
                    if len(outliers) > 0:
                        issues.append(self._issue(
                            DataQualityIssue.VOLUME_OUTLIER, "low",
                            f"{len(outliers)} volume outliers (>Q3+5×IQR) in OHLCV data",
                        ))

        critical = [i for i in issues if i["severity"] == "critical"]
        quality_score = max(0.0, 1.0 - len(issues) * 0.15)
        return ValidationResult(
            is_valid=len(critical) == 0,
            quality_score=quality_score,
            issues=issues,
            timestamp=datetime.now(UTC),
        )

    def get_rejection_stats(self) -> dict[str, Any]:
        """Return per-reason rejection counts for Prometheus / health endpoints."""
        total = self._total_count
        accepted = self._accepted_count
        rejected = total - accepted
        return {
            "total": total,
            "accepted": accepted,
            "rejected": rejected,
            "acceptance_rate": round(accepted / total, 4) if total > 0 else 1.0,
            "by_reason": dict(self._rejection_counts),
        }

    def get_quality_report(self) -> dict[str, Any]:
        """Return a summary quality report from recent validation history."""
        if not self.quality_history:
            return {"message": "No validation history"}
        recent = self.quality_history[-100:]
        return {
            "total_validations": len(self.quality_history),
            "average_quality_score": round(
                float(np.mean([r.quality_score for r in recent])), 4
            ),
            "valid_rate": round(float(np.mean([r.is_valid for r in recent])), 4),
            "critical_issues_count": sum(
                len([i for i in r.issues if i["severity"] == "critical"])
                for r in recent
            ),
            "rejection_stats": self.get_rejection_stats(),
            "last_updated": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _issue(
        issue_type: DataQualityIssue,
        severity: str,
        message: str,
        **extra: Any,
    ) -> dict:
        d: dict[str, Any] = {
            "type": issue_type.value,
            "severity": severity,
            "message": message,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        d.update(extra)
        return d

    @staticmethod
    def _parse_timestamp(ts: Any) -> datetime | None:
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=UTC)
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except ValueError:
                return None
        return None

    @staticmethod
    def _is_trading_hours(dt: datetime, symbol: str) -> bool:
        """Return False only on weekends (forex is 24/5)."""
        return dt.weekday() < 5
