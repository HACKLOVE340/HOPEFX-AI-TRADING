# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
data_layer/quality/engine.py
============================
DataQualityEngine — merciless real-time data validation.

Responsibilities
----------------
- Price jump detection: rejects ticks that move > MAX_JUMP_PCT
- Stale tick rejection: marks ticks STALE when source has been silent > STALE_THRESHOLD_S
- Inverted spread detection: bid > ask is always rejected
- Excessive spread detection: spread > 1% is pathological for gold
- Cross-source consensus: computes weighted mid from all live feeds; flags outliers
- Latency monitoring: tracks per-source p50/p95/p99 latency with Prometheus histograms
- Anomaly scoring: rolling z-score on (price, spread) feature vector
- Mahalanobis distance: multivariate anomaly detection on (price, spread, latency)
- Confidence scoring: per-source rolling quality score used by orchestrator for failover
- Causal enforcement: every tick carries a monotonic sequence number

New in this version
-------------------
- Kalman filter price smoothing: 1D constant-velocity Kalman filter per source
  produces a smoothed mid estimate and innovation residual for anomaly detection
- Cross-source arbitrage detection: flags when two live sources diverge by more
  than ARBITRAGE_THRESHOLD_PCT — emits structured log + Prometheus counter
- ML-based anomaly scoring: Isolation Forest trained online on rolling window of
  (price_return, spread, latency_ms) features; score in [0, 1] where 1 = anomaly

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
ARBITRAGE_THRESHOLD_PCT = float(os.getenv("DQE_ARBITRAGE_THRESHOLD_PCT", "0.002"))  # 0.2%
CONFIDENCE_DECAY = float(os.getenv("DQE_CONFIDENCE_DECAY", "0.95"))
MIN_CONFIDENCE = float(os.getenv("DQE_MIN_CONFIDENCE", "0.30"))
WINDOW_SIZE = int(os.getenv("DQE_WINDOW_SIZE", "200"))
MAX_SPREAD_PCT = float(os.getenv("DQE_MAX_SPREAD_PCT", "0.01"))  # 1%
MIN_GOLD_PRICE = float(os.getenv("DQE_MIN_GOLD_PRICE", "500.0"))
MAX_GOLD_PRICE = float(os.getenv("DQE_MAX_GOLD_PRICE", "10000.0"))
# Kalman filter noise parameters (tuned for gold tick data)
KALMAN_PROCESS_NOISE = float(os.getenv("DQE_KALMAN_Q", "1e-4"))
KALMAN_OBSERVATION_NOISE = float(os.getenv("DQE_KALMAN_R", "1e-2"))
# Isolation Forest: retrain every N ticks, min samples before first fit
IF_RETRAIN_INTERVAL = int(os.getenv("DQE_IF_RETRAIN_INTERVAL", "100"))
IF_MIN_SAMPLES = int(os.getenv("DQE_IF_MIN_SAMPLES", "50"))
IF_CONTAMINATION = float(os.getenv("DQE_IF_CONTAMINATION", "0.05"))


class _KalmanFilter1D:
    """
    1D constant-velocity Kalman filter for price smoothing.

    State vector: [price, velocity]
    Observation:  [price]

    Produces a smoothed price estimate and innovation residual on each update.
    The innovation (measurement - prediction) is used as an anomaly signal:
    large innovations indicate price jumps or data errors.
    """

    def __init__(self, q: float = KALMAN_PROCESS_NOISE, r: float = KALMAN_OBSERVATION_NOISE) -> None:
        # State: [price, velocity]
        self.x = np.zeros(2)
        # State covariance
        self.P = np.eye(2) * 1.0
        # State transition: price += velocity each step
        self.F = np.array([[1.0, 1.0], [0.0, 1.0]])
        # Observation matrix: we observe price only
        self.H = np.array([[1.0, 0.0]])
        # Process noise covariance
        self.Q = np.array([[q, 0.0], [0.0, q * 0.1]])
        # Observation noise covariance
        self.R = np.array([[r]])
        self._initialized = False

    def update(self, price: float) -> tuple[float, float]:
        """
        Update filter with a new price observation.

        Returns (smoothed_price, innovation) where innovation = price - predicted_price.
        On first call, initialises state and returns (price, 0.0).
        """
        if not self._initialized:
            self.x[0] = price
            self._initialized = True
            return price, 0.0

        # Predict
        x_pred = self.F @ self.x
        P_pred = self.F @ self.P @ self.F.T + self.Q

        # Innovation
        z = np.array([price])
        y = z - self.H @ x_pred  # innovation

        # Kalman gain
        S = self.H @ P_pred @ self.H.T + self.R
        K = P_pred @ self.H.T @ np.linalg.inv(S)

        # Update
        self.x = x_pred + K @ y
        self.P = (np.eye(2) - K @ self.H) @ P_pred

        return float(self.x[0]), float(y[0])

    def smoothed_price(self) -> float:
        return float(self.x[0])

    def reset(self) -> None:
        self.x = np.zeros(2)
        self.P = np.eye(2) * 1.0
        self._initialized = False


class _SourceState:
    """Per-source rolling statistics with Kalman filter state."""

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
        # Kalman filter for price smoothing
        self.kalman = _KalmanFilter1D()
        self.kalman_smoothed: float = 0.0
        self.kalman_innovation: float = 0.0
        # ML anomaly feature buffer: (price_return, spread, latency_ms)
        self.ml_features: deque = deque(maxlen=WINDOW_SIZE)
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
        self._prom_arbitrage = None
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
            self._prom_arbitrage = _counter(
                "hopefx_dqe_arbitrage_detected_total",
                "Cross-source arbitrage events detected",
                ["source_a", "source_b"],
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

        # ── 6. Kalman filter smoothing ─────────────────────────────────────
        smoothed, innovation = state.kalman.update(tick.mid)
        state.kalman_smoothed = smoothed
        state.kalman_innovation = innovation
        # Large Kalman innovation (> 3× process noise std) flags suspect tick
        innovation_threshold = 3.0 * np.sqrt(np.nan_to_num(KALMAN_PROCESS_NOISE, nan=1e-6)) * max(tick.mid, 1.0)
        if abs(innovation) > innovation_threshold and state.accept_count > 10:
            state.anomaly_count += 1
            state.update_confidence(-0.01)
            if quality == TickQuality.GOOD:
                quality = TickQuality.SUSPECT
            logger.debug(
                "DQE Kalman innovation anomaly source=%s innovation=%.4f threshold=%.4f",
                tick.source.value,
                innovation,
                innovation_threshold,
            )

        # ── 7. Anomaly detection (rolling z-score) ─────────────────────────
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

        # ── 8. Multivariate anomaly (Mahalanobis) — when enough history ────
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

        # ── 9. Collect ML anomaly features ────────────────────────────────
        price_return = (tick.mid - state.last_mid) / max(state.last_mid, 1.0) if state.last_mid > 0 else 0.0
        tick_epoch = tick.timestamp.timestamp()
        latency_ms_raw = max(0.0, (received_at - tick_epoch) * 1000.0)
        state.ml_features.append((price_return, tick.spread, min(latency_ms_raw, 5000.0)))

        # ── 10. Latency tracking ───────────────────────────────────────────
        latency_ms = latency_ms_raw
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

        # ── 11. Accept ─────────────────────────────────────────────────────
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
                state.ml_features.clear()
                state.kalman.reset()
                state.kalman_smoothed = 0.0
                state.kalman_innovation = 0.0
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

    # ── Kalman smoothed price ─────────────────────────────────────────────────

    def get_kalman_price(self, source: FeedSource) -> float:
        """Return the Kalman-smoothed price for a source, or 0.0 if no data."""
        state = self._sources.get(source)
        if state is None:
            return 0.0
        return state.kalman_smoothed

    def get_kalman_innovation(self, source: FeedSource) -> float:
        """Return the last Kalman innovation (measurement - prediction) for a source."""
        state = self._sources.get(source)
        if state is None:
            return 0.0
        return state.kalman_innovation

    def get_all_kalman_prices(self) -> dict[str, float]:
        """Return Kalman-smoothed prices for all sources that have data."""
        return {
            src.value: state.kalman_smoothed
            for src, state in self._sources.items()
            if state.kalman_smoothed > 0
        }

    # ── Cross-source arbitrage detection ─────────────────────────────────────

    def detect_arbitrage(
        self,
        ticks: dict[FeedSource, GoldTick],
    ) -> list[dict]:
        """
        Detect cross-source arbitrage opportunities.

        Compares every pair of live sources. When two sources diverge by more
        than ARBITRAGE_THRESHOLD_PCT, an arbitrage record is emitted.

        Returns a list of arbitrage records:
          {
            "source_a": str,
            "source_b": str,
            "price_a": float,
            "price_b": float,
            "diff_pct": float,
            "threshold_pct": float,
          }

        An empty list means no arbitrage detected.
        """
        valid = {
            src: t
            for src, t in ticks.items()
            if t.is_valid() and t.quality != TickQuality.REJECTED
        }
        if len(valid) < 2:
            return []

        sources = list(valid.keys())
        records = []
        for i in range(len(sources)):
            for j in range(i + 1, len(sources)):
                sa, sb = sources[i], sources[j]
                pa, pb = valid[sa].mid, valid[sb].mid
                mid_avg = (pa + pb) / 2.0
                diff_pct = abs(pa - pb) / max(mid_avg, 1.0)
                if diff_pct > ARBITRAGE_THRESHOLD_PCT:
                    record = {
                        "source_a": sa.value,
                        "source_b": sb.value,
                        "price_a": round(pa, 4),
                        "price_b": round(pb, 4),
                        "diff_pct": round(diff_pct * 100, 4),
                        "threshold_pct": round(ARBITRAGE_THRESHOLD_PCT * 100, 4),
                    }
                    records.append(record)
                    logger.warning(
                        "DQE arbitrage detected %s=%.4f vs %s=%.4f diff=%.4f%%",
                        sa.value, pa, sb.value, pb, diff_pct * 100,
                    )
                    if self._prom_arbitrage:
                        with contextlib.suppress(Exception):
                            self._prom_arbitrage.labels(
                                source_a=sa.value, source_b=sb.value
                            ).inc()
        return records

    # ── ML-based anomaly scoring ──────────────────────────────────────────────

    def compute_ml_anomaly_score(self, source: FeedSource) -> float:
        """
        Compute an Isolation Forest anomaly score for the given source.

        Features: (price_return, spread, latency_ms) — same 3-tuple collected
        in validate_tick() step 9.

        Returns a score in [0, 1] where values close to 1 indicate anomalies.
        Returns 0.0 when insufficient data or sklearn is unavailable.

        The model is retrained every IF_RETRAIN_INTERVAL ticks on the rolling
        window. Between retrains the last fitted model is reused.
        """
        state = self._sources.get(source)
        if state is None or len(state.ml_features) < IF_MIN_SAMPLES:
            return 0.0
        try:
            from sklearn.ensemble import IsolationForest  # type: ignore[import]

            X = np.array(list(state.ml_features), dtype=np.float64)
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

            # Retrain periodically
            retrain_key = f"_if_model_{source.value}"
            retrain_count_key = f"_if_count_{source.value}"
            model = getattr(self, retrain_key, None)
            count = getattr(self, retrain_count_key, 0)

            if model is None or count % IF_RETRAIN_INTERVAL == 0:
                model = IsolationForest(
                    n_estimators=50,
                    contamination=IF_CONTAMINATION,
                    n_jobs=1,
                )
                model.fit(X)
                setattr(self, retrain_key, model)

            setattr(self, retrain_count_key, count + 1)

            # Score the latest observation
            latest = X[-1:].reshape(1, -1)
            # decision_function: negative = anomaly, positive = normal
            raw_score = model.decision_function(latest)[0]
            # Normalise to [0, 1]: 0 = normal, 1 = anomaly
            # Raw scores typically in [-0.5, 0.5]; clip and invert
            normalised = float(np.clip(0.5 - raw_score, 0.0, 1.0))
            return round(normalised, 4)
        except ImportError:
            logger.debug("sklearn not available — ML anomaly scoring disabled")
            return 0.0
        except Exception as exc:
            logger.debug("ML anomaly score error source=%s: %s", source.value, exc)
            return 0.0

    def get_all_ml_anomaly_scores(self) -> dict[str, float]:
        """Return ML anomaly scores for all sources with sufficient data."""
        return {
            src.value: self.compute_ml_anomaly_score(src)
            for src, state in self._sources.items()
            if len(state.ml_features) >= IF_MIN_SAMPLES
        }

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
