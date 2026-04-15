# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
execution/tca_recorder.py
=========================
Post-trade Transaction Cost Analysis (TCA) recorder.

Captures the expected price at signal generation time vs the actual fill
price, aggregates slippage statistics per broker/session/instrument, and
exposes a reporting API for the dashboard and compliance audit.

What this solves
----------------
Without TCA, there is no way to:
  - Measure actual slippage vs expected
  - Detect broker routing issues (systematic fill quality degradation)
  - Prove best execution to regulators
  - Identify which sessions/instruments have the worst fill quality

Architecture
------------
TCARecorder.record_signal(symbol, side, signal_price, quantity, model_version)
    Called by the signal layer at signal generation time.
    Stores the expected price and timestamp.

TCARecorder.record_fill(request_id, fill_price, filled_quantity, broker, latency_ms)
    Called by the execution engine after every fill.
    Computes slippage vs the stored signal price.
    Persists the TCA record to Redis (for cross-pod aggregation) and DB.

TCARecorder.get_report(...)
    Returns aggregated slippage statistics per broker/session/instrument.

TCARecorder.get_fill_quality_alert(...)
    Returns True if slippage for a broker/instrument exceeds the alert threshold.

Usage
-----
    from execution.tca_recorder import get_tca_recorder

    recorder = get_tca_recorder()

    # At signal generation time (before routing):
    recorder.record_signal(
        request_id="req_abc123",
        symbol="XAU_USD",
        side="BUY",
        signal_price=2001.50,
        quantity=1.0,
        model_version="advanced_oos_v4",
    )

    # After fill (in execution engine):
    recorder.record_fill(
        request_id="req_abc123",
        fill_price=2001.85,
        filled_quantity=1.0,
        broker="oanda",
        latency_ms=42.3,
    )

    # Reporting:
    report = recorder.get_report(broker="oanda", last_n=500)
    logger.info(report.mean_slippage_bps)   # e.g. 1.8 bps
    logger.info(report.p95_slippage_bps)    # e.g. 4.2 bps

Configuration (env vars)
------------------------
TCA_ALERT_THRESHOLD_BPS   — slippage alert threshold in bps (default: 5.0)
TCA_ALERT_WINDOW          — rolling window for alert evaluation (default: 100)
TCA_PERSIST_REDIS         — persist records to Redis (default: true)
TCA_PERSIST_DB            — persist records to DB via outbox (default: true)
TCA_MAX_MEMORY_RECORDS    — max in-memory records per instrument (default: 10000)
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc

import numpy as np

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
TCA_ALERT_THRESHOLD_BPS: float = float(os.getenv("TCA_ALERT_THRESHOLD_BPS", "5.0"))
TCA_ALERT_WINDOW: int = int(os.getenv("TCA_ALERT_WINDOW", "100"))
TCA_PERSIST_REDIS: bool = os.getenv("TCA_PERSIST_REDIS", "true").lower() == "true"
TCA_PERSIST_DB: bool = os.getenv("TCA_PERSIST_DB", "true").lower() == "true"
TCA_MAX_MEMORY_RECORDS: int = int(os.getenv("TCA_MAX_MEMORY_RECORDS", "10000"))


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class TCARecord:
    """Single trade TCA record: signal price vs actual fill price."""

    request_id: str
    symbol: str
    side: str  # BUY | SELL
    signal_price: float  # Price at signal generation time
    fill_price: float  # Actual fill price
    filled_quantity: float
    broker: str
    latency_ms: float
    model_version: str
    session: str  # e.g. "london", "new_york", "asia"
    signal_time: datetime
    fill_time: datetime

    @property
    def slippage_bps(self) -> float:
        """
        Slippage in basis points: (fill_price - signal_price) / signal_price × 10000.

        Positive = paid more than expected (adverse for BUY, favourable for SELL).
        Negative = paid less than expected (favourable for BUY, adverse for SELL).
        """
        if self.signal_price <= 0:
            return 0.0
        raw = (self.fill_price - self.signal_price) / self.signal_price * 10_000
        # Normalise: adverse slippage is always positive
        return raw if self.side == "BUY" else -raw

    @property
    def slippage_usd(self) -> float:
        """Slippage in USD for this fill."""
        return abs(self.fill_price - self.signal_price) * self.filled_quantity

    @property
    def signal_to_fill_ms(self) -> float:
        """Time from signal generation to fill in milliseconds."""
        return (self.fill_time - self.signal_time).total_seconds() * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "symbol": self.symbol,
            "side": self.side,
            "signal_price": self.signal_price,
            "fill_price": self.fill_price,
            "filled_quantity": self.filled_quantity,
            "slippage_bps": round(self.slippage_bps, 4),
            "slippage_usd": round(self.slippage_usd, 4),
            "broker": self.broker,
            "latency_ms": round(self.latency_ms, 2),
            "signal_to_fill_ms": round(self.signal_to_fill_ms, 2),
            "model_version": self.model_version,
            "session": self.session,
            "signal_time": self.signal_time.isoformat(),
            "fill_time": self.fill_time.isoformat(),
        }


@dataclass
class TCAReport:
    """Aggregated TCA statistics for a broker/instrument/session slice."""

    broker: str
    symbol: str | None
    session: str | None
    n_trades: int
    mean_slippage_bps: float
    median_slippage_bps: float
    p95_slippage_bps: float
    p99_slippage_bps: float
    std_slippage_bps: float
    total_slippage_usd: float
    mean_latency_ms: float
    p95_latency_ms: float
    mean_signal_to_fill_ms: float
    adverse_fill_rate: float  # fraction of fills with slippage > 0
    price_improvement_rate: float  # fraction of fills with slippage < 0
    alert_triggered: bool
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def summary(self) -> str:
        return (
            f"TCA [{self.broker}/{self.symbol or 'all'}/{self.session or 'all'}] "
            f"n={self.n_trades} | "
            f"slippage: mean={self.mean_slippage_bps:.2f}bps "
            f"p95={self.p95_slippage_bps:.2f}bps | "
            f"latency: mean={self.mean_latency_ms:.1f}ms | "
            f"adverse={self.adverse_fill_rate:.1%} | "
            f"{'⚠ ALERT' if self.alert_triggered else 'OK'}"
        )


# ── TCA Recorder ──────────────────────────────────────────────────────────────


class TCARecorder:
    """
    Post-trade TCA recorder.

    Records signal-time price vs actual fill price for every trade,
    aggregates slippage statistics, and alerts on fill quality degradation.
    """

    def __init__(self) -> None:
        # Pending signals: request_id → signal metadata
        self._pending: dict[str, dict[str, Any]] = {}

        # Completed records: keyed by (broker, symbol) for fast aggregation
        self._records: dict[str, deque[TCARecord]] = defaultdict(lambda: deque(maxlen=TCA_MAX_MEMORY_RECORDS))
        # Flat list for cross-slice queries
        self._all_records: deque[TCARecord] = deque(maxlen=TCA_MAX_MEMORY_RECORDS * 10)

        # Rolling slippage window per broker for alert evaluation
        self._broker_slippage: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=TCA_ALERT_WINDOW))

    # ── Public API ────────────────────────────────────────────────────────────

    def record_signal(
        self,
        request_id: str,
        symbol: str,
        side: str,
        signal_price: float,
        quantity: float,
        model_version: str = "unknown",
    ) -> None:
        """
        Record the expected price at signal generation time.

        Must be called BEFORE the order is routed to the broker.
        The request_id links this signal record to the subsequent fill.
        """
        self._pending[request_id] = {
            "symbol": symbol,
            "side": side,
            "signal_price": signal_price,
            "quantity": quantity,
            "model_version": model_version,
            "signal_time": datetime.now(UTC),
        }

    def record_fill(
        self,
        request_id: str,
        fill_price: float,
        filled_quantity: float,
        broker: str = "unknown",
        latency_ms: float = 0.0,
    ) -> TCARecord | None:
        """
        Record the actual fill price and compute slippage vs signal price.

        Returns the TCARecord if a matching signal was found, None otherwise.
        """
        signal = self._pending.pop(request_id, None)
        if signal is None:
            logger.debug(
                "TCARecorder: no pending signal for request_id=%s — "
                "record_signal() must be called before record_fill()",
                request_id,
            )
            return None

        fill_time = datetime.now(UTC)
        session = self._get_session(fill_time)

        record = TCARecord(
            request_id=request_id,
            symbol=signal["symbol"],
            side=signal["side"],
            signal_price=signal["signal_price"],
            fill_price=fill_price,
            filled_quantity=filled_quantity,
            broker=broker,
            latency_ms=latency_ms,
            model_version=signal["model_version"],
            session=session,
            signal_time=signal["signal_time"],
            fill_time=fill_time,
        )

        # Store in memory
        key = f"{broker}:{signal['symbol']}"
        self._records[key].append(record)
        self._all_records.append(record)
        self._broker_slippage[broker].append(record.slippage_bps)

        # Log every fill
        logger.info(
            "TCA: %s %s %s | signal=%.4f fill=%.4f slippage=%.2fbps "
            "slippage_usd=%.2f latency=%.1fms broker=%s session=%s",
            signal["side"],
            signal["symbol"],
            request_id,
            signal["signal_price"],
            fill_price,
            record.slippage_bps,
            record.slippage_usd,
            latency_ms,
            broker,
            session,
        )

        # Alert check
        self._check_alert(broker, record)

        # Persist
        self._persist(record)

        return record

    def get_report(
        self,
        broker: str | None = None,
        symbol: str | None = None,
        session: str | None = None,
        last_n: int = 500,
    ) -> TCAReport | None:
        """
        Return aggregated TCA statistics for the given slice.

        Parameters
        ----------
        broker  : Filter by broker name. None = all brokers.
        symbol  : Filter by instrument. None = all instruments.
        session : Filter by trading session. None = all sessions.
        last_n  : Use only the most recent N records.
        """
        records = self._filter_records(broker, symbol, session, last_n)
        if not records:
            return None

        slippages = np.array([r.slippage_bps for r in records])
        latencies = np.array([r.latency_ms for r in records])
        s2f = np.array([r.signal_to_fill_ms for r in records])
        total_slip_usd = sum(r.slippage_usd for r in records)

        mean_slip = float(np.mean(slippages))
        rolling_mean = float(np.mean(list(self._broker_slippage.get(broker or "", [])) or [mean_slip]))
        alert = rolling_mean > TCA_ALERT_THRESHOLD_BPS

        report = TCAReport(
            broker=broker or "all",
            symbol=symbol,
            session=session,
            n_trades=len(records),
            mean_slippage_bps=mean_slip,
            median_slippage_bps=float(np.median(slippages)),
            p95_slippage_bps=float(np.percentile(slippages, 95)),
            p99_slippage_bps=float(np.percentile(slippages, 99)),
            std_slippage_bps=float(np.std(slippages)),
            total_slippage_usd=total_slip_usd,
            mean_latency_ms=float(np.mean(latencies)),
            p95_latency_ms=float(np.percentile(latencies, 95)),
            mean_signal_to_fill_ms=float(np.mean(s2f)),
            adverse_fill_rate=float(np.mean(slippages > 0)),
            price_improvement_rate=float(np.mean(slippages < 0)),
            alert_triggered=alert,
        )
        logger.info(report.summary())
        return report

    def get_all_reports(self, last_n: int = 500) -> list[TCAReport]:
        """Return per-broker TCA reports for all brokers with recent fills."""
        brokers = {r.broker for r in self._all_records}
        return [r for b in brokers if (r := self.get_report(broker=b, last_n=last_n))]

    def get_recent_records(self, n: int = 100) -> list[dict[str, Any]]:
        """Return the N most recent TCA records as dicts."""
        records = list(self._all_records)[-n:]
        return [r.to_dict() for r in reversed(records)]

    def is_fill_quality_degraded(self, broker: str) -> bool:
        """
        Return True if the rolling mean slippage for a broker exceeds the alert threshold.

        Used by the execution engine to flag broker routing issues.
        """
        window = list(self._broker_slippage.get(broker, []))
        if len(window) < 10:
            return False
        return float(np.mean(window)) > TCA_ALERT_THRESHOLD_BPS

    # ── Internal ──────────────────────────────────────────────────────────────

    def _filter_records(
        self,
        broker: str | None,
        symbol: str | None,
        session: str | None,
        last_n: int,
    ) -> list[TCARecord]:
        """Filter records by broker/symbol/session and return last_n."""
        records = list(self._all_records)
        if broker:
            records = [r for r in records if r.broker == broker]
        if symbol:
            records = [r for r in records if r.symbol == symbol]
        if session:
            records = [r for r in records if r.session == session]
        return records[-last_n:]

    def _check_alert(self, broker: str, record: TCARecord) -> None:
        """Fire an alert if rolling mean slippage exceeds threshold."""
        window = list(self._broker_slippage[broker])
        if len(window) < 10:
            return
        rolling_mean = float(np.mean(window))
        if rolling_mean > TCA_ALERT_THRESHOLD_BPS:
            logger.warning(
                "TCA ALERT: broker=%s rolling mean slippage=%.2fbps > threshold=%.2fbps "
                "(window=%d trades) — possible routing issue",
                broker,
                rolling_mean,
                TCA_ALERT_THRESHOLD_BPS,
                len(window),
            )
            self._fire_alert(broker, rolling_mean, record)

    def _fire_alert(self, broker: str, mean_slippage_bps: float, record: TCARecord) -> None:
        """Publish a TCA alert to the outbox and alert engine."""
        try:
            from core.outbox import write_outbox_event_standalone

            write_outbox_event_standalone(
                event_type="TCA_SLIPPAGE_ALERT",
                channel="hopefx:tca",
                payload={
                    "broker": broker,
                    "symbol": record.symbol,
                    "mean_slippage_bps": mean_slippage_bps,
                    "threshold_bps": TCA_ALERT_THRESHOLD_BPS,
                    "window": TCA_ALERT_WINDOW,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except (RuntimeError, ConnectionError, OSError, ValueError) as exc:
            logger.debug("TCA alert outbox write failed: %s", exc)

    def _persist(self, record: TCARecord) -> None:
        """Persist TCA record to Redis and/or DB."""
        if TCA_PERSIST_REDIS:
            self._persist_redis(record)
        if TCA_PERSIST_DB:
            self._persist_db(record)

    def _persist_redis(self, record: TCARecord) -> None:
        """Write TCA record to Redis sorted set (score = fill timestamp)."""
        try:
            import asyncio

            from cache.redis_client import get_redis

            async def _write() -> None:
                redis = await get_redis()
                if redis is None:
                    return
                import json

                key = f"hopefx:tca:{record.broker}:{record.symbol}"
                score = record.fill_time.timestamp()
                await redis.zadd(key, {json.dumps(record.to_dict()): score})
                # Keep only last 10,000 records per broker/symbol
                await redis.zremrangebyrank(key, 0, -10_001)

            try:
                loop = asyncio.get_running_loop()
                _t = loop.create_task(_write(), name="tca_redis_write")
                _t.add_done_callback(lambda _: None)
            except RuntimeError:
                ...  # nosec B110
        except (RuntimeError, AttributeError) as exc:
            logger.debug("TCA Redis persist failed: %s", exc)

    def _persist_db(self, record: TCARecord) -> None:
        """Write TCA record to DB via transactional outbox."""
        try:
            from core.outbox import write_outbox_event_standalone

            write_outbox_event_standalone(
                event_type="TCA_RECORD",
                channel="hopefx:tca",
                payload=record.to_dict(),
            )
        except (RuntimeError, ConnectionError, OSError, ValueError) as exc:
            logger.debug("TCA DB persist failed: %s", exc)

    @staticmethod
    def _get_session(dt: datetime) -> str:
        """Classify a UTC datetime into a trading session."""
        hour = dt.hour
        if 7 <= hour < 16:
            return "london"
        if 13 <= hour < 22:
            return "new_york"
        if 0 <= hour < 9:
            return "asia"
        return "off_hours"


# ── Module-level singleton ────────────────────────────────────────────────────

_tca_recorder: TCARecorder | None = None


def get_tca_recorder() -> TCARecorder:
    """Return the module-level TCARecorder singleton."""
    global _tca_recorder
    if _tca_recorder is None:
        _tca_recorder = TCARecorder()
    return _tca_recorder
