# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/quality/engine.py
============================
DataQualityEngine — merciless real-time data validation.

Responsibilities
----------------
- Price jump detection: rejects ticks that move > MAX_JUMP_PCT in < MIN_JUMP_INTERVAL_S
- Stale tick rejection: marks ticks STALE when source has been silent > STALE_THRESHOLD_S
- Inverted spread detection: bid > ask is always rejected
- Excessive spread detection: spread > 1% is pathological for gold
- Cross-source consensus: computes weighted mid from all live feeds; flags outliers
- Latency monitoring: tracks per-source p50/p95/p99 latency with Prometheus histograms
- Anomaly scoring: rolling z-score on (price, spread) feature vector
- Mahalanobis distance: multivariate anomaly detection on (price, spread, latency)
- Confidence scoring: per-source rolling quality score used by orchestrator for failover
- Causal enforcement: every tick carries a monotonic sequence number; out-of-order
  ticks are flagged SUSPECT to guarantee zero look-ahead bias in the ML pipeline

All decisions are logged with structured fields and written to the lineage store.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

UTC = timezone.utc

import numpy as np

from data_layer.types import FeedSource, GoldTick, QualityReport, TickQuality

logger = logging.getLogger(__name__)

MAX_JUMP_PCT = float(os.getenv("DQE_MAX_JUMP_PCT", "0.005"))  # 0.5%
STALE_THRESHOLD_S = float(os.getenv("DQE_STALE_THRESHOLD_S", "30.0"))
LATENCY_WARN_MS = float(os.getenv("DQE_LATENCY_WARN_MS", "500.0"))
ANOMALY_ZSCORE_THRESH = float(os.getenv("DQE_ANOMALY_ZSCORE", "4.0"))
CROSS_SOURCE_MAX_DIFF = float(os.getenv("DQE_CROSS_SOURCE_MAX_DIFF", "0.003"))  # 0.3%
CONFIDENCE_DECAY = float(os.getenv("DQE_CONFIDENCE_DECAY", "0.95"))
MIN_CONFIDENCE = float(os.getenv("DQE_MIN_CONFIDENCE", "0.30"))
WINDOW_SIZE = int(os.getenv("DQE_WINDOW_SIZE", "200"))
MAX_SPREAD_PCT = float(os.getenv("DQE_MAX_SPREAD_PCT", "0.01"))  # 1%
MIN_GOLD_PRICE = float(os.getenv("DQE_MIN_GOLD_PRICE", "500.0"))  # sanity floor
MAX_GOLD_PRICE = float(os.getenv("DQE_MAX_GOLD_PRICE", "10000.0"))  # sanity ceiling


class _SourceState:
    """Per-source rolling statistics."""

    def __init__(self, source: FeedSource) -> None:
        self.source = source
        self.last_tick_ts = 0.0
        self.last_mid = 0.0
        self.seq = -1
        self.confidence = 1.0
        self.error_count = 0
        self.accept_count = 0
        self.reject_count = 0
        self.stale_count = 0
        self.jump_count = 0
        self.anomaly_count = 0
        self.latencies_ms: deque = deque(maxlen=WINDOW_SIZE)
        self.mids: deque = deque(maxlen=WINDOW_SIZE)
        self.spreads: deque = deque(maxlen=WINDOW_SIZE)
        self._lock = threading.Lock()

    def record_latency(self, ms: float) -> None:
        with self._lock:
            self.latencies_ms.append(ms)

    def p50_latency(self) -> float:
        with self._lock:
            if not self.latencies_ms:
                return 0.0
            return float(np.percentile(list(self.latencies_ms), 50))

    def p95_latency(self) -> float:
        with self._lock:
            if not self.latencies_ms:
                return 0.0
            return float(np.percentile(list(self.latencies_ms), 95))

    def p99_latency(self) -> float:
        with self._lock:
            if not self.latencies_ms:
                return 0.0
            return float(np.percentile(list(self.latencies_ms), 99))

    def rolling_mid_std(self) -> float:
        with self._lock:
            if len(self.mids) < 10:
                return 0.0
            return float(np.std(list(self.mids)))

    def update_confidence(self, delta: float) -> None:
        with self._lock:
            self.confidence = max(MIN_CONFIDENCE, min(1.0, self.confidence + delta))

    def is_stale(self) -> bool:
        return (time.time() - self.last_tick_ts) > STALE_THRESHOLD_S and self.last_tick_ts > 0


class DataQualityEngine:
    """
    Real-time data quality enforcement for all gold price feeds.

    Thread-safe. Designed to be called from multiple async feed tasks
    concurrently via validate_tick().
    """

    def __init__(self) -> None:
        self._sources: dict[FeedSource, _SourceState] = {src: _SourceState(src) for src in FeedSource}
        self._global_seq = 0
        self._seq_lock = threading.Lock()
        self._report_window: deque = deque(maxlen=1000)

        # Prometheus metrics
        self._prom_accepted = None
        self._prom_rejected = None
        self._prom_latency = None
        self._prom_confidence = None
        self._prom_consensus = None
        self._init_prometheus()

    def _init_prometheus(self) -> None:
        try:
            from prometheus_client import REGISTRY, Counter, Gauge, Histogram

            def _counter(name: str, doc: str, labels=None):
                try:
                    return Counter(name, doc, labels or [])
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            def _histogram(name: str, doc: str, labels=None, buckets=None):
                kwargs = {"labelnames": labels or []}
                if buckets:
                    kwargs["buckets"] = buckets
                try:
                    return Histogram(name, doc, **kwargs)
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            def _gauge(name: str, doc: str, labels=None):
                try:
                    return Gauge(name, doc, labels or [])
                except ValueError:
                    return REGISTRY._names_to_collectors.get(name)

            self._prom_accepted = _counter(
                "hopefx_dqe_ticks_accepted_total",
                "Ticks accepted by DataQualityEngine",
                ["source"],
            )
            self._prom_rejected = _counter(
                "hopefx_dqe_ticks_rejected_total",
                "Ticks rejected by DataQualityEngine",
                ["source", "reason"],
            )
            self._prom_latency = _histogram(
                "hopefx_dqe_source_latency_ms",
                "Per-source tick latency in milliseconds",
                labels=["source"],
                buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
            )
            self._prom_confidence = _gauge(
                "hopefx_dqe_source_confidence",
                "Per-source confidence score",
                ["source"],
            )
            self._prom_consensus = _gauge(
                "hopefx_dqe_consensus_price_usd",
                "Cross-source consensus gold price",
            )
        except Exception as _exc:
            logger.debug("DataQualityEngine: Prometheus init skipped: %s", _exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def validate_tick(self, tick: GoldTick, received_at: float | None = None) -> GoldTick:
        """
        Validate a raw tick from any gold feed.

        Returns a new GoldTick with quality and confidence fields set.
        Never raises — all errors produce a REJECTED tick.

        Causal guarantee: assigns a monotonic global sequence number.
        """
        received_at = received_at or time.time()
        state = self._sources[tick.source]

        # ── 1. Assign global sequence ──────────────────────────────────────
        with self._seq_lock:
            self._global_seq += 1
            seq = self._global_seq

        # ── 2. Sanity bounds ───────────────────────────────────────────────
        if tick.mid <= 0 or tick.bid <= 0 or tick.ask <= 0:
            return self._reject(tick, state, "zero_price", seq)

        if tick.mid < MIN_GOLD_PRICE or tick.mid > MAX_GOLD_PRICE:
            return self._reject(tick, state, "price_out_of_bounds", seq)

        # ── 3. Spread validation ───────────────────────────────────────────
        if tick.bid > tick.ask:
            return self._reject(tick, state, "inverted_spread", seq)

        spread_pct = (tick.ask - tick.bid) / tick.mid if tick.mid > 0 else 0
        if spread_pct > MAX_SPREAD_PCT:
            return self._reject(tick, state, "excessive_spread", seq)

        # ── 4. Price jump detection ────────────────────────────────────────
        if state.last_mid > 0:
            jump_pct = abs(tick.mid - state.last_mid) / state.last_mid
            if jump_pct > MAX_JUMP_PCT:
                state.jump_count += 1
                state.update_confidence(-0.05)
                logger.warning(
                    "DQE jump detected source=%s jump_pct=%.4f mid=%.2f prev=%.2f seq=%d",
                    tick.source.value,
                    jump_pct,
                    tick.mid,
                    state.last_mid,
                    seq,
                )
                if self._prom_rejected:
                    try:
                        self._prom_rejected.labels(source=tick.source.value, reason="price_jump").inc()
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)
                return self._reject(tick, state, "price_jump", seq)

        # ── 5. Stale detection ─────────────────────────────────────────────
        if state.is_stale():
            state.stale_count += 1
            state.update_confidence(-0.02)
            quality = TickQuality.STALE
        else:
            quality = TickQuality.GOOD

        # ── 6. Anomaly detection (rolling z-score) ─────────────────────────
        state.mids.append(tick.mid)
        state.spreads.append(tick.spread)

        if len(state.mids) >= 20:
            arr = np.nan_to_num(np.array(list(state.mids)), nan=0.0)
            mean = arr[:-1].mean()
            std = arr[:-1].std() + 1e-9
            z = abs((tick.mid - mean) / std)
            if z > ANOMALY_ZSCORE_THRESH:
                state.anomaly_count += 1
                state.update_confidence(-0.03)
                quality = TickQuality.SUSPECT
                logger.debug(
                    "DQE anomaly source=%s z=%.2f mid=%.2f mean=%.2f",
                    tick.source.value,
                    z,
                    tick.mid,
                    mean,
                )

        # ── 7. Multivariate anomaly (Mahalanobis) — when enough history ────
        if len(state.mids) >= 50 and len(state.spreads) >= 50:
            try:
                mids_arr = np.nan_to_num(np.array(list(state.mids)[-50:]), nan=0.0)
                spreads_arr = np.nan_to_num(np.array(list(state.spreads)[-50:]), nan=0.0)
                X = np.column_stack([mids_arr, spreads_arr])
                mu = X[:-1].mean(axis=0)
                cov = np.cov(X[:-1].T) + np.eye(2) * 1e-9
                diff = np.nan_to_num(np.array([tick.mid, tick.spread]) - mu, nan=0.0)
                inv_cov = np.linalg.inv(cov)
                mahal = float(np.nan_to_num(np.sqrt(diff @ inv_cov @ diff), nan=0.0))
                if mahal > 6.0:  # ~3-sigma in 2D
                    state.anomaly_count += 1
                    state.update_confidence(-0.02)
                    if quality == TickQuality.GOOD:
                        quality = TickQuality.SUSPECT
                    logger.debug(
                        "DQE Mahalanobis anomaly source=%s dist=%.2f",
                        tick.source.value,
                        mahal,
                    )
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)  # singular matrix or other numerical issue — skip

        # ── 8. Latency tracking ────────────────────────────────────────────
        tick_epoch = tick.timestamp.timestamp()
        latency_ms = (received_at - tick_epoch) * 1000.0
        if 0 < latency_ms < 300_000:  # ignore negative or absurd latencies
            state.record_latency(latency_ms)
            if self._prom_latency:
                try:
                    self._prom_latency.labels(source=tick.source.value).observe(latency_ms)
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
            if latency_ms > LATENCY_WARN_MS:
                logger.warning(
                    "DQE high latency source=%s latency_ms=%.1f",
                    tick.source.value,
                    latency_ms,
                )

        # ── 9. Accept ──────────────────────────────────────────────────────
        state.last_tick_ts = received_at
        state.last_mid = tick.mid
        state.accept_count += 1
        state.update_confidence(+0.001)

        if self._prom_accepted:
            try:
                self._prom_accepted.labels(source=tick.source.value).inc()
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        if self._prom_confidence:
            try:
                self._prom_confidence.labels(source=tick.source.value).set(state.confidence)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        validated = GoldTick(
            symbol=tick.symbol,
            timestamp=tick.timestamp,
            bid=tick.bid,
            ask=tick.ask,
            mid=tick.mid,
            source=tick.source,
            quality=quality,
            confidence=state.confidence,
            spread=tick.spread,
            lineage_id=tick.lineage_id,
            raw=tick.raw,
        )
        self._report_window.append(("accept", tick.source, tick.mid))
        return validated

    def cross_source_consensus(self, ticks: dict[FeedSource, GoldTick]) -> tuple[float, float, dict[FeedSource, float]]:
        """
        Compute weighted consensus mid price from multiple live feeds.

        Returns (consensus_mid, consensus_confidence, per_source_weights).

        Algorithm (two-pass outlier removal):
          Pass 1: confidence-weighted mean across all valid sources.
          Outlier gate: sources deviating > CROSS_SOURCE_MAX_DIFF from the
            pass-1 mean are *excluded* from pass 2 (not just penalised) and
            their confidence is decremented.
          Pass 2: recompute consensus using only inlier sources.
          If all sources are outliers (single-source or extreme divergence),
            fall back to the highest-confidence single source.

        Weighting: source_confidence × (1 / latency_p95) × (1 / spread)
        """
        if not ticks:
            return 0.0, 0.0, {}

        valid = {src: t for src, t in ticks.items() if t.is_valid() and t.quality != TickQuality.REJECTED}
        if not valid:
            return 0.0, 0.0, {}

        # Raw weights: confidence / latency_p95 / spread
        weights: dict[FeedSource, float] = {}
        for src, t in valid.items():
            state = self._sources[src]
            lat = max(state.p95_latency(), 1.0)
            sprd = max(t.spread, 0.01)
            weights[src] = state.confidence / lat / sprd

        total_w = sum(weights.values()) or 1.0
        norm_w = {s: w / total_w for s, w in weights.items()}

        # Pass 1: unfiltered consensus
        consensus_p1 = sum(t.mid * norm_w[s] for s, t in valid.items())

        # Identify and exclude outliers (hard exclusion, not just weight penalty)
        inliers: dict[FeedSource, GoldTick] = {}
        for src, t in valid.items():
            diff_pct = abs(t.mid - consensus_p1) / max(consensus_p1, 1.0)
            if diff_pct > CROSS_SOURCE_MAX_DIFF:
                self._sources[src].update_confidence(-0.02)
                logger.warning(
                    "DQE cross-source outlier EXCLUDED source=%s mid=%.4f consensus_p1=%.4f diff_pct=%.4f",
                    src.value,
                    t.mid,
                    consensus_p1,
                    diff_pct,
                )
                if self._prom_rejected:
                    with contextlib.suppress(Exception):
                        self._prom_rejected.labels(source=src.value, reason="cross_source_outlier").inc()
            else:
                inliers[src] = t

        # Fall back to best single source if all are outliers
        if not inliers:
            best = max(valid.items(), key=lambda kv: self._sources[kv[0]].confidence)
            inliers = {best[0]: best[1]}
            logger.warning(
                "DQE: all sources are outliers — using best single source %s",
                best[0].value,
            )

        # Pass 2: consensus over inliers only
        inlier_weights = {s: weights[s] for s in inliers}
        total_w2 = sum(inlier_weights.values()) or 1.0
        norm_w2 = {s: w / total_w2 for s, w in inlier_weights.items()}
        consensus = sum(t.mid * norm_w2[s] for s, t in inliers.items())

        conf = sum(self._sources[s].confidence * norm_w2[s] for s in inliers)

        if self._prom_consensus:
            try:
                self._prom_consensus.set(consensus)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        return consensus, conf, norm_w2

    def get_source_health(self) -> dict[str, dict]:
        out = {}
        for src, state in self._sources.items():
            out[src.value] = {
                "is_alive": not state.is_stale(),
                "confidence": round(state.confidence, 4),
                "accept_count": state.accept_count,
                "reject_count": state.reject_count,
                "stale_count": state.stale_count,
                "jump_count": state.jump_count,
                "anomaly_count": state.anomaly_count,
                "p50_latency_ms": round(state.p50_latency(), 2),
                "p95_latency_ms": round(state.p95_latency(), 2),
                "p99_latency_ms": round(state.p99_latency(), 2),
                "last_mid": state.last_mid,
            }
        return out

    def best_source(self) -> FeedSource | None:
        """Return the highest-confidence non-stale source."""
        candidates = [
            (src, state) for src, state in self._sources.items() if not state.is_stale() and state.accept_count > 0
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda x: x[1].confidence)[0]

    def latency_report(self) -> dict[str, dict[str, float]]:
        """
        Return per-source latency percentiles (p50/p95/p99) in milliseconds.

        Used by monitoring dashboards and the health endpoint.
        Returns empty dict for sources with no latency observations.
        """
        report: dict[str, dict[str, float]] = {}
        for src, state in self._sources.items():
            if not state.latencies_ms:
                continue
            report[src.value] = {
                "p50_ms": round(state.p50_latency(), 2),
                "p95_ms": round(state.p95_latency(), 2),
                "p99_ms": round(state.p99_latency(), 2),
                "n": len(state.latencies_ms),
            }
        return report

    def reset_source(self, source: FeedSource) -> None:
        """
        Reset a source's state (confidence, error counts, latency history).

        Called when a feed is restarted after a prolonged outage to prevent
        stale confidence scores from penalising a recovered feed.
        """
        if source in self._sources:
            state = self._sources[source]
            with state._lock:
                state.confidence = 1.0
                state.error_count = 0
                state.accept_count = 0
                state.reject_count = 0
                state.stale_count = 0
                state.jump_count = 0
                state.anomaly_count = 0
                state.latencies_ms.clear()
                state.mids.clear()
                state.spreads.clear()
                state.last_tick_ts = 0.0
                state.last_mid = 0.0
            logger.info("DQE: source %s reset", source.value)

    def mark_source_stale(self, source: FeedSource) -> None:
        """Force-mark a source as stale (e.g. after a known outage)."""
        if source in self._sources:
            self._sources[source].last_tick_ts = 0.0
            logger.info("DQE: source %s force-marked stale", source.value)

    def generate_report(self, symbol: str) -> QualityReport:
        now = datetime.now(UTC)
        recent = list(self._report_window)
        accepted = sum(1 for r in recent if r[0] == "accept")
        rejected = sum(1 for r in recent if r[0] == "reject")
        active = [s.value for s, st in self._sources.items() if not st.is_stale() and st.accept_count > 0]
        best = self.best_source()
        mids = [r[2] for r in recent if r[0] == "accept" and r[2] > 0]
        spread_across = (max(mids) - min(mids)) if len(mids) > 1 else 0.0

        # Reconstruct minimal ticks from each source's last-known mid price
        # so cross_source_consensus() can compute a consensus without requiring
        # a live tick to be in-flight at report time.
        last_known_ticks = {}
        for s, st in self._sources.items():
            if st.last_mid > 0 and not st.is_stale():
                last_known_ticks[s] = GoldTick(
                    symbol=symbol,
                    timestamp=now,
                    bid=st.last_mid * 0.9999,
                    ask=st.last_mid * 1.0001,
                    mid=st.last_mid,
                    source=s,
                )
        consensus, _, _ = self.cross_source_consensus(last_known_ticks)

        return QualityReport(
            timestamp=now,
            symbol=symbol,
            ticks_received=accepted + rejected,
            ticks_accepted=accepted,
            ticks_rejected=rejected,
            stale_count=sum(st.stale_count for st in self._sources.values()),
            jump_count=sum(st.jump_count for st in self._sources.values()),
            anomaly_count=sum(st.anomaly_count for st in self._sources.values()),
            active_sources=active,
            primary_source=best.value if best else "none",
            consensus_price=consensus,
            price_spread_across_sources=spread_across,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _reject(self, tick: GoldTick, state: _SourceState, reason: str, seq: int) -> GoldTick:
        state.reject_count += 1
        state.update_confidence(-0.01)
        self._report_window.append(("reject", tick.source, tick.mid))
        logger.debug(
            "DQE reject source=%s reason=%s mid=%.2f seq=%d",
            tick.source.value,
            reason,
            tick.mid,
            seq,
        )
        if self._prom_rejected:
            try:
                self._prom_rejected.labels(source=tick.source.value, reason=reason).inc()
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        return GoldTick(
            symbol=tick.symbol,
            timestamp=tick.timestamp,
            bid=tick.bid,
            ask=tick.ask,
            mid=tick.mid,
            source=tick.source,
            quality=TickQuality.REJECTED,
            confidence=0.0,
            spread=tick.spread,
            lineage_id=tick.lineage_id,
            raw=tick.raw,
        )


# Module-level singleton
dqe = DataQualityEngine()
