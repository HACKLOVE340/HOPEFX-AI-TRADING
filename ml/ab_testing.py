# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ML A/B Testing Manager — champion/challenger model evaluation framework.

Allows side-by-side comparison of two model variants (control vs challenger)
with configurable traffic split.  Results are stored in the database and
exposed via the superadmin ML dashboard.

Usage
-----
    from ml.ab_testing import get_ab_test_manager

    mgr = get_ab_test_manager()
    tests = mgr.list_tests()            # → list of test dicts
    mgr.create_test("xgb_v2", 0.2)      # 20% traffic to challenger
    mgr.record_result("test_id", "challenger", correct=True, pnl=12.5)
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc


class ABTest:
    def __init__(
        self,
        test_id: str,
        name: str,
        control: str,
        challenger: str,
        traffic_split: float = 0.20,
        status: str = "active",
        started_at: str | None = None,
    ) -> None:
        self.test_id = test_id
        self.name = name
        self.control = control
        self.challenger = challenger
        self.traffic_split = traffic_split
        self.status = status
        self.started_at = started_at or datetime.now(UTC).isoformat()
        self.finished_at: str | None = None

        # Running metrics
        self._results: dict[str, list[dict]] = {"control": [], "challenger": []}
        self._lock = threading.Lock()

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_result(
        self,
        variant: str,
        *,
        correct: bool,
        pnl: float = 0.0,
        confidence: float = 0.5,
    ) -> None:
        if variant not in ("control", "challenger"):
            return
        with self._lock:
            self._results[variant].append(
                {
                    "correct": correct,
                    "pnl": pnl,
                    "confidence": confidence,
                    "ts": datetime.now(UTC).isoformat(),
                }
            )

    # ── Metrics ───────────────────────────────────────────────────────────────

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            metrics: dict[str, Any] = {}
            for variant in ("control", "challenger"):
                records = self._results[variant]
                n = len(records)
                if n == 0:
                    metrics[variant] = {"n": 0, "accuracy": None, "avg_pnl": None}
                    continue
                accuracy = sum(1 for r in records if r["correct"]) / n
                avg_pnl = sum(r["pnl"] for r in records) / n
                avg_conf = sum(r["confidence"] for r in records) / n
                metrics[variant] = {
                    "n": n,
                    "accuracy": round(accuracy, 4),
                    "avg_pnl": round(avg_pnl, 4),
                    "avg_confidence": round(avg_conf, 4),
                }
            # Statistical significance (chi-square on correct/incorrect)
            if metrics["control"]["n"] > 10 and metrics["challenger"]["n"] > 10:
                metrics["significance"] = self._chi2_pvalue()
            return metrics

    def _chi2_pvalue(self) -> float | None:
        try:
            from scipy.stats import chi2_contingency
            import numpy as np

            c_corr  = sum(1 for r in self._results["control"]    if r["correct"])
            ch_corr = sum(1 for r in self._results["challenger"]  if r["correct"])
            c_n  = len(self._results["control"])
            ch_n = len(self._results["challenger"])
            c_wrong  = c_n  - c_corr
            ch_wrong = ch_n - ch_corr
            table = np.array([[c_corr, c_wrong], [ch_corr, ch_wrong]])
            if table.min() < 5:
                return None  # too few observations for chi2
            _, p, _, _ = chi2_contingency(table)
            return round(float(p), 4)
        except Exception:
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.test_id,
            "name": self.name,
            "status": self.status,
            "control": self.control,
            "challenger": self.challenger,
            "traffic_split": self.traffic_split,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metrics": self.get_metrics(),
        }


class ABTestManager:
    """
    Manages ML champion/challenger A/B tests.

    Tests are stored in-memory and optionally persisted to the SystemEvent
    table so they survive restarts.
    """

    def __init__(self) -> None:
        self._tests: dict[str, ABTest] = {}
        self._lock = threading.Lock()
        self._load_from_db()

    # ── Query ─────────────────────────────────────────────────────────────────

    def list_tests(self, active_only: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            tests = list(self._tests.values())

        result = [t.to_dict() for t in tests if not active_only or t.status == "active"]

        # Also pull historical tests from DB
        try:
            from database.connection import get_db_manager

            db_mgr = get_db_manager()
            if db_mgr:
                with db_mgr.session() as db:
                    from database.models import SystemEvent

                    rows = (
                        db.query(SystemEvent)
                        .filter(SystemEvent.event_type == "ab_test")
                        .order_by(SystemEvent.created_at.desc())
                        .limit(20)
                        .all()
                    )
                    in_memory_ids = {t["id"] for t in result}
                    for r in rows:
                        if str(r.id) not in in_memory_ids:
                            meta = r.metadata or {}
                            result.append(
                                {
                                    "id": str(r.id),
                                    "name": r.component or "unknown",
                                    "status": r.status or "completed",
                                    "control": meta.get("control", "baseline"),
                                    "challenger": meta.get("challenger", "variant"),
                                    "traffic_split": meta.get("traffic_split", 0.5),
                                    "started_at": r.created_at.isoformat() if r.created_at else None,
                                    "finished_at": meta.get("finished_at"),
                                    "metrics": meta.get("metrics", {}),
                                }
                            )
        except Exception as exc:
            logger.debug("ABTestManager.list_tests db: %s", exc)

        return result

    def get_test(self, test_id: str) -> ABTest | None:
        with self._lock:
            return self._tests.get(test_id)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create_test(
        self,
        challenger_model: str,
        traffic_split: float = 0.20,
        control_model: str = "advanced_oos",
        name: str | None = None,
    ) -> ABTest:
        test_id = str(uuid.uuid4())
        test_name = name or f"{control_model}_vs_{challenger_model}"
        test = ABTest(
            test_id=test_id,
            name=test_name,
            control=control_model,
            challenger=challenger_model,
            traffic_split=float(traffic_split),
        )
        with self._lock:
            self._tests[test_id] = test
        self._persist_test(test)
        logger.info("ABTest created: %s (%s)", test_id, test_name)
        return test

    def stop_test(self, test_id: str, winner: str | None = None) -> bool:
        with self._lock:
            test = self._tests.get(test_id)
            if test is None or test.status != "active":
                return False
            test.status = "completed"
            test.finished_at = datetime.now(UTC).isoformat()
        self._persist_test(test)
        logger.info("ABTest %s stopped (winner=%s)", test_id, winner)
        return True

    def record_result(
        self,
        test_id: str,
        variant: str,
        *,
        correct: bool,
        pnl: float = 0.0,
        confidence: float = 0.5,
    ) -> None:
        test = self.get_test(test_id)
        if test:
            test.record_result(variant, correct=correct, pnl=pnl, confidence=confidence)

    # ── Route traffic ─────────────────────────────────────────────────────────

    def route(self, test_id: str) -> str:
        """
        Route a single request to control or challenger.

        Returns 'challenger' with probability == traffic_split, else 'control'.
        """
        import random

        test = self.get_test(test_id)
        if test is None or test.status != "active":
            return "control"
        return "challenger" if random.random() < test.traffic_split else "control"

    # ── Persistence ───────────────────────────────────────────────────────────

    def _persist_test(self, test: ABTest) -> None:
        try:
            from database.connection import get_db_manager

            db_mgr = get_db_manager()
            if not db_mgr:
                return
            with db_mgr.session() as db:
                from database.models import SystemEvent

                row = SystemEvent(
                    id=test.test_id,
                    event_type="ab_test",
                    component=test.name,
                    status=test.status,
                    metadata={
                        "control": test.control,
                        "challenger": test.challenger,
                        "traffic_split": test.traffic_split,
                        "finished_at": test.finished_at,
                        "metrics": test.get_metrics(),
                    },
                )
                db.merge(row)
                db.commit()
        except Exception as exc:
            logger.debug("ABTestManager._persist_test: %s", exc)

    def _load_from_db(self) -> None:
        try:
            from database.connection import get_db_manager

            db_mgr = get_db_manager()
            if not db_mgr:
                return
            with db_mgr.session() as db:
                from database.models import SystemEvent

                rows = (
                    db.query(SystemEvent)
                    .filter(SystemEvent.event_type == "ab_test", SystemEvent.status == "active")
                    .all()
                )
                for r in rows:
                    meta = r.metadata or {}
                    test = ABTest(
                        test_id=str(r.id),
                        name=r.component or "unknown",
                        control=meta.get("control", "baseline"),
                        challenger=meta.get("challenger", "variant"),
                        traffic_split=float(meta.get("traffic_split", 0.2)),
                        status="active",
                        started_at=r.created_at.isoformat() if r.created_at else None,
                    )
                    with self._lock:
                        self._tests[test.test_id] = test
        except Exception as exc:
            logger.debug("ABTestManager._load_from_db: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: ABTestManager | None = None
_manager_lock = threading.Lock()


def get_ab_test_manager() -> ABTestManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ABTestManager()
    return _manager
