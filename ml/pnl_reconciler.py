# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/pnl_reconciler.py
====================
P&L reconciliation gate for the model promotion pipeline.

Compares cumulative realized P&L reported by the broker against the
internal ledger (PositionManager history) and blocks model promotion
when the two diverge beyond a configurable tolerance.

Why this gate exists
--------------------
A model that appears profitable in backtests or OOS evaluation may be
operating on a corrupted ledger — fills that were never confirmed by the
broker, slippage that was not recorded, or a fake account_id that never
connected to a real broker. The reconciliation gate catches this class of
failure before a model is promoted to production.

Gate logic
----------
1. Collect all closed-trade realized P&L from the internal ledger
   (PositionManager._history or a persisted JSON snapshot).
2. Fetch the broker's reported realized P&L for the same window via
   OANDABroker.get_closed_trades() (OANDA v20 /v3/accounts/{id}/trades).
3. Compute the absolute divergence:
       divergence = |ledger_pnl - broker_pnl|
4. Compute the relative divergence (when broker_pnl != 0):
       rel_divergence = divergence / |broker_pnl|
5. Gate passes when BOTH:
       divergence     <= PNL_RECON_ABS_TOLERANCE   (default: 1.00 USD)
       rel_divergence <= PNL_RECON_REL_TOLERANCE   (default: 0.01 = 1%)
6. When the broker is unreachable, the gate falls back to the persisted
   snapshot (data/pnl_reconciliation.json) if it is fresh enough
   (< PNL_RECON_STALE_HOURS hours old).  If no fresh snapshot exists,
   the gate is BLOCKED (fail-safe).

Persistence
-----------
Every successful reconciliation writes a snapshot to
data/pnl_reconciliation.json so the gate can be evaluated offline
(e.g. during CI or when the broker is temporarily unreachable).

Prometheus metrics published
----------------------------
  hopefx_pnl_recon_ledger_total    — ledger cumulative realized P&L
  hopefx_pnl_recon_broker_total    — broker cumulative realized P&L
  hopefx_pnl_recon_divergence      — absolute divergence (USD)
  hopefx_pnl_recon_gate_passed     — 1 when gate passes, 0 otherwise

Environment variables
---------------------
PNL_RECON_ABS_TOLERANCE   — absolute tolerance in USD (default: 1.00)
PNL_RECON_REL_TOLERANCE   — relative tolerance 0–1   (default: 0.01)
PNL_RECON_STALE_HOURS     — max age of cached snapshot (default: 24)
PNL_RECON_SNAPSHOT_PATH   — path to snapshot JSON (default: data/pnl_reconciliation.json)
PNL_RECON_MIN_TRADES      — minimum trades required for gate to be meaningful (default: 10)

Usage
-----
    from ml.pnl_reconciler import PnLReconciler, get_reconciler

    reconciler = get_reconciler()

    # Run a full reconciliation against the live broker
    result = await reconciler.reconcile(broker=oanda_broker_instance)
    if not result.gate_passed:
        raise RuntimeError(f"P&L reconciliation gate BLOCKED: {result.reason}")

    # Check gate from persisted snapshot (no broker call)
    result = reconciler.check_gate()
    if not result.gate_passed:
        raise RuntimeError(f"P&L reconciliation gate BLOCKED: {result.reason}")
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_ABS_TOLERANCE: float = float(os.getenv("PNL_RECON_ABS_TOLERANCE", "1.00"))
_REL_TOLERANCE: float = float(os.getenv("PNL_RECON_REL_TOLERANCE", "0.01"))
_STALE_HOURS: float = float(os.getenv("PNL_RECON_STALE_HOURS", "24"))
_SNAPSHOT_PATH = Path(os.getenv("PNL_RECON_SNAPSHOT_PATH", "data/pnl_reconciliation.json"))
_MIN_TRADES: int = int(os.getenv("PNL_RECON_MIN_TRADES", "10"))


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class ReconciliationResult:
    """Result of a single P&L reconciliation run."""

    gate_passed: bool
    ledger_pnl: float
    broker_pnl: float
    divergence: float
    rel_divergence: float
    n_ledger_trades: int
    n_broker_trades: int
    abs_tolerance: float
    rel_tolerance: float
    reason: str
    reconciled_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    from_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Prometheus helpers ────────────────────────────────────────────────────────


def _publish_metrics(result: ReconciliationResult) -> None:
    """Publish reconciliation metrics to Prometheus (best-effort)."""
    try:
        from prometheus_client import Gauge

        _ledger = Gauge(
            "hopefx_pnl_recon_ledger_total",
            "Ledger cumulative realized P&L (USD)",
        )
        _broker = Gauge(
            "hopefx_pnl_recon_broker_total",
            "Broker cumulative realized P&L (USD)",
        )
        _div = Gauge(
            "hopefx_pnl_recon_divergence",
            "Absolute P&L divergence between ledger and broker (USD)",
        )
        _gate = Gauge(
            "hopefx_pnl_recon_gate_passed",
            "1 when P&L reconciliation gate passes, 0 otherwise",
        )
        _ledger.set(result.ledger_pnl)
        _broker.set(result.broker_pnl)
        _div.set(result.divergence)
        _gate.set(1.0 if result.gate_passed else 0.0)
    except Exception as exc:
        logger.debug("PnLReconciler: Prometheus publish failed: %s", exc)


# ── PnLReconciler ─────────────────────────────────────────────────────────────


class PnLReconciler:
    """
    Compares internal ledger P&L against broker-reported P&L.

    Designed to be called from the model promotion pipeline before
    a model is promoted to production.  Can also be called from the
    health-check endpoint to surface reconciliation status.
    """

    def __init__(
        self,
        snapshot_path: Path | None = None,
        abs_tolerance: float = _ABS_TOLERANCE,
        rel_tolerance: float = _REL_TOLERANCE,
        stale_hours: float = _STALE_HOURS,
        min_trades: int = _MIN_TRADES,
    ) -> None:
        self._snapshot_path = snapshot_path or _SNAPSHOT_PATH
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._abs_tol = abs_tolerance
        self._rel_tol = rel_tolerance
        self._stale_hours = stale_hours
        self._min_trades = min_trades

    # ── Ledger collection ─────────────────────────────────────────────────────

    def _collect_ledger_pnl(self) -> tuple[float, int]:
        """
        Sum realized P&L from the PositionManager history.

        Returns (total_pnl, n_trades).  Falls back to zero when the
        PositionManager is not initialised (e.g. during offline gate checks).
        """
        try:
            from core.app_state import get_position_manager

            pm = get_position_manager()
            if pm is None:
                return 0.0, 0
            history = list(pm._history)
            total = sum(float(r.realized_pnl) for r in history)
            return round(total, 6), len(history)
        except Exception as exc:
            logger.debug("PnLReconciler: ledger collection failed: %s", exc)
            return 0.0, 0

    # ── Broker collection ─────────────────────────────────────────────────────

    async def _collect_broker_pnl(self, broker: Any) -> tuple[float, int]:
        """
        Fetch realized P&L from the broker's closed-trades endpoint.

        Supports OANDABroker (async) and any broker that exposes
        ``get_closed_trades()`` returning a list of dicts with a
        ``realized_pnl`` key.

        Returns (total_pnl, n_trades).
        """
        if broker is None:
            return 0.0, 0

        # OANDABroker: fetch closed trades from v3 API
        if hasattr(broker, "get_closed_trades"):
            try:
                trades = await broker.get_closed_trades()
                total = sum(float(t.get("realized_pnl", t.get("realizedPL", 0.0))) for t in trades)
                return round(total, 6), len(trades)
            except Exception as exc:
                logger.warning("PnLReconciler: broker.get_closed_trades() failed: %s", exc)
                return 0.0, 0

        # Fallback: try get_account_info for cumulative realized P&L
        if hasattr(broker, "get_account_info"):
            try:
                info = await broker.get_account_info()
                if info is not None:
                    # OANDA AccountInfo has no realized_pnl field directly;
                    # use NAV - balance as a proxy when no trade history available
                    rpnl = getattr(info, "realized_pnl", None)
                    if rpnl is not None:
                        return round(float(rpnl), 6), -1  # -1 = count unknown
            except Exception as exc:
                logger.debug("PnLReconciler: get_account_info fallback failed: %s", exc)

        return 0.0, 0

    # ── Gate evaluation ───────────────────────────────────────────────────────

    def _evaluate(
        self,
        ledger_pnl: float,
        broker_pnl: float,
        n_ledger: int,
        n_broker: int,
        from_cache: bool = False,
    ) -> ReconciliationResult:
        """
        Compute divergence and evaluate the gate.

        Gate passes when:
          abs(ledger_pnl - broker_pnl) <= abs_tolerance
          AND rel_divergence <= rel_tolerance  (when broker_pnl != 0)
          AND n_ledger >= min_trades  (enough data to be meaningful)
        """
        divergence = abs(ledger_pnl - broker_pnl)
        rel_divergence = (divergence / abs(broker_pnl)) if broker_pnl != 0.0 else 0.0

        # Insufficient data — gate is inconclusive, treat as blocked
        if n_ledger < self._min_trades and n_broker < self._min_trades:
            reason = (
                f"P&L reconciliation gate BLOCKED: insufficient trade data "
                f"(ledger={n_ledger}, broker={n_broker}, min={self._min_trades}). "
                f"Accumulate at least {self._min_trades} confirmed fills before promotion."
            )
            return ReconciliationResult(
                gate_passed=False,
                ledger_pnl=ledger_pnl,
                broker_pnl=broker_pnl,
                divergence=divergence,
                rel_divergence=round(rel_divergence, 6),
                n_ledger_trades=n_ledger,
                n_broker_trades=n_broker,
                abs_tolerance=self._abs_tol,
                rel_tolerance=self._rel_tol,
                reason=reason,
                from_cache=from_cache,
            )

        # Absolute tolerance check
        if divergence > self._abs_tol:
            reason = (
                f"P&L reconciliation gate BLOCKED: divergence={divergence:.4f} USD "
                f"> tolerance={self._abs_tol:.4f} USD. "
                f"Ledger={ledger_pnl:.4f}, Broker={broker_pnl:.4f}. "
                f"Investigate fill recording in execution/hopefx_engine.py."
            )
            return ReconciliationResult(
                gate_passed=False,
                ledger_pnl=ledger_pnl,
                broker_pnl=broker_pnl,
                divergence=divergence,
                rel_divergence=round(rel_divergence, 6),
                n_ledger_trades=n_ledger,
                n_broker_trades=n_broker,
                abs_tolerance=self._abs_tol,
                rel_tolerance=self._rel_tol,
                reason=reason,
                from_cache=from_cache,
            )

        # Relative tolerance check (only meaningful when broker_pnl != 0)
        if broker_pnl != 0.0 and rel_divergence > self._rel_tol:
            reason = (
                f"P&L reconciliation gate BLOCKED: relative divergence={rel_divergence:.4%} "
                f"> tolerance={self._rel_tol:.4%}. "
                f"Ledger={ledger_pnl:.4f}, Broker={broker_pnl:.4f}. "
                f"Check for unrecorded fills or slippage discrepancies."
            )
            return ReconciliationResult(
                gate_passed=False,
                ledger_pnl=ledger_pnl,
                broker_pnl=broker_pnl,
                divergence=divergence,
                rel_divergence=round(rel_divergence, 6),
                n_ledger_trades=n_ledger,
                n_broker_trades=n_broker,
                abs_tolerance=self._abs_tol,
                rel_tolerance=self._rel_tol,
                reason=reason,
                from_cache=from_cache,
            )

        reason = (
            f"P&L reconciliation gate passed: divergence={divergence:.4f} USD "
            f"({rel_divergence:.4%}), ledger={ledger_pnl:.4f}, broker={broker_pnl:.4f}, "
            f"n_ledger={n_ledger}, n_broker={n_broker}."
        )
        return ReconciliationResult(
            gate_passed=True,
            ledger_pnl=ledger_pnl,
            broker_pnl=broker_pnl,
            divergence=divergence,
            rel_divergence=round(rel_divergence, 6),
            n_ledger_trades=n_ledger,
            n_broker_trades=n_broker,
            abs_tolerance=self._abs_tol,
            rel_tolerance=self._rel_tol,
            reason=reason,
            from_cache=from_cache,
        )

    # ── Snapshot I/O ──────────────────────────────────────────────────────────

    def _save_snapshot(self, result: ReconciliationResult) -> None:
        """Atomically write the reconciliation snapshot."""
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=self._snapshot_path.parent,
                prefix=".pnl_recon_tmp_",
                suffix=".json",
            )
        except Exception as exc:
            logger.warning("PnLReconciler: snapshot write failed (mkstemp): %s", exc)
            return
        try:
            import os as _os

            with _os.fdopen(tmp_fd, "w") as fh:
                json.dump(result.to_dict(), fh, indent=2)
            Path(tmp_path).replace(self._snapshot_path)
            logger.debug("PnLReconciler: snapshot written to %s", self._snapshot_path)
        except Exception as exc:
            import contextlib

            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()
            logger.warning("PnLReconciler: snapshot write failed: %s", exc)

    def _load_snapshot(self) -> ReconciliationResult | None:
        """
        Load the persisted snapshot if it exists and is not stale.

        Returns None when the snapshot is missing, corrupt, or older than
        _stale_hours.
        """
        if not self._snapshot_path.exists():
            return None
        try:
            data = json.loads(self._snapshot_path.read_text())
            reconciled_at = data.get("reconciled_at", "")
            if reconciled_at:
                ts = datetime.fromisoformat(reconciled_at)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                age_hours = (datetime.now(UTC) - ts).total_seconds() / 3600.0
                if age_hours > self._stale_hours:
                    logger.warning(
                        "PnLReconciler: snapshot is %.1f hours old (max %.1f) — treating as stale",
                        age_hours,
                        self._stale_hours,
                    )
                    return None
            return ReconciliationResult(
                gate_passed=bool(data.get("gate_passed", False)),
                ledger_pnl=float(data.get("ledger_pnl", 0.0)),
                broker_pnl=float(data.get("broker_pnl", 0.0)),
                divergence=float(data.get("divergence", 0.0)),
                rel_divergence=float(data.get("rel_divergence", 0.0)),
                n_ledger_trades=int(data.get("n_ledger_trades", 0)),
                n_broker_trades=int(data.get("n_broker_trades", 0)),
                abs_tolerance=float(data.get("abs_tolerance", self._abs_tol)),
                rel_tolerance=float(data.get("rel_tolerance", self._rel_tol)),
                reason=str(data.get("reason", "")),
                reconciled_at=reconciled_at,
                from_cache=True,
            )
        except Exception as exc:
            logger.warning("PnLReconciler: snapshot load failed: %s", exc)
            return None

    # ── Public API ────────────────────────────────────────────────────────────

    async def reconcile(self, broker: Any = None) -> ReconciliationResult:
        """
        Run a full reconciliation against the live broker.

        Collects ledger P&L from PositionManager history and broker P&L
        from the broker's closed-trades endpoint.  Persists the result to
        the snapshot file and publishes Prometheus metrics.

        Parameters
        ----------
        broker : An OANDABroker instance (or any broker with get_closed_trades).
                 When None, only the ledger is checked against zero.

        Returns
        -------
        ReconciliationResult with gate_passed, divergence, and reason.
        """
        ledger_pnl, n_ledger = self._collect_ledger_pnl()
        broker_pnl, n_broker = await self._collect_broker_pnl(broker)

        result = self._evaluate(ledger_pnl, broker_pnl, n_ledger, n_broker)
        self._save_snapshot(result)
        _publish_metrics(result)

        if result.gate_passed:
            logger.info("PnLReconciler: %s", result.reason)
        else:
            logger.warning("PnLReconciler: %s", result.reason)

        return result

    def check_gate(self) -> ReconciliationResult:
        """
        Check the gate from the persisted snapshot (no broker call).

        Used by the model promotion pipeline when a live broker connection
        is not available.  Returns a BLOCKED result when no fresh snapshot
        exists.

        Returns
        -------
        ReconciliationResult — gate_passed=False when snapshot is missing/stale.
        """
        snapshot = self._load_snapshot()
        if snapshot is not None:
            logger.debug(
                "PnLReconciler.check_gate: using snapshot from %s (gate=%s)",
                snapshot.reconciled_at,
                snapshot.gate_passed,
            )
            return snapshot

        # No fresh snapshot — fail safe
        reason = (
            "P&L reconciliation gate BLOCKED: no fresh reconciliation snapshot found. "
            f"Run reconciler before promoting a model "
            f"(snapshot path: {self._snapshot_path}, max age: {self._stale_hours}h). "
            "Ensure the broker is connected and reconcile() has been called."
        )
        logger.warning("PnLReconciler.check_gate: %s", reason)
        return ReconciliationResult(
            gate_passed=False,
            ledger_pnl=0.0,
            broker_pnl=0.0,
            divergence=0.0,
            rel_divergence=0.0,
            n_ledger_trades=0,
            n_broker_trades=0,
            abs_tolerance=self._abs_tol,
            rel_tolerance=self._rel_tol,
            reason=reason,
        )

    def snapshot_status(self) -> dict[str, Any]:
        """Return the current snapshot as a dict for health-check endpoints."""
        snap = self._load_snapshot()
        if snap is None:
            return {
                "available": False,
                "gate_passed": False,
                "reason": "No reconciliation snapshot available.",
                "snapshot_path": str(self._snapshot_path),
            }
        d = snap.to_dict()
        d["available"] = True
        return d


# ── OANDABroker extension: get_closed_trades ─────────────────────────────────
# Monkey-patched onto OANDABroker at import time so the reconciler can call
# broker.get_closed_trades() without modifying the broker module directly.
# This keeps the broker module focused on order execution.


def _patch_oanda_broker() -> None:
    """Add get_closed_trades() to OANDABroker if not already present."""
    try:
        from brokers.oanda import OANDABroker
    except ImportError:
        return

    if hasattr(OANDABroker, "get_closed_trades"):
        return

    async def get_closed_trades(self, count: int = 500) -> list[dict]:
        """
        Fetch the most recent closed trades from OANDA v20.

        Returns a list of dicts with keys: trade_id, symbol, realized_pnl,
        open_time, close_time, units, open_price, close_price.
        """
        if not self.connected or not self._session:
            return []
        try:
            url = f"{self._base_url}/v3/accounts/{self._account_id}/trades"
            params = {"state": "CLOSED", "count": str(count)}
            async with self._session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
            trades = data.get("trades", [])
            result = []
            for t in trades:
                result.append(
                    {
                        "trade_id": t.get("id", ""),
                        "symbol": t.get("instrument", ""),
                        "realized_pnl": float(t.get("realizedPL", 0.0)),
                        "open_time": t.get("openTime", ""),
                        "close_time": t.get("closeTime", ""),
                        "units": int(t.get("initialUnits", 0)),
                        "open_price": float(t.get("price", 0.0)),
                        "close_price": float(
                            (t.get("closingTransactionIDs") and t.get("averageClosePrice")) or 0.0
                        ),
                    }
                )
            return result
        except Exception as exc:
            logger.warning("OANDABroker.get_closed_trades: %s", exc)
            return []

    OANDABroker.get_closed_trades = get_closed_trades  # type: ignore[attr-defined]
    logger.debug("PnLReconciler: patched OANDABroker.get_closed_trades")


_patch_oanda_broker()


# ── Module-level singleton ────────────────────────────────────────────────────

_reconciler: PnLReconciler | None = None


def get_reconciler() -> PnLReconciler:
    """Return the module-level PnLReconciler singleton."""
    global _reconciler
    if _reconciler is None:
        _reconciler = PnLReconciler()
    return _reconciler
