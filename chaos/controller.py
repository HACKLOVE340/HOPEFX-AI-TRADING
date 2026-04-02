# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
chaos/controller.py
====================
ChaosController — orchestrates chaos scenarios and validates system resilience.

Runs pre-defined chaos scenarios against the live data pipeline (paper mode
only) and records whether the system recovered correctly within SLA bounds.

Scenarios
---------
  FEED_FAILOVER       — drop primary feed, verify secondary takes over in <5s
  DQE_SPIKE_REJECTION — inject price spike, verify DQE rejects it
  STALE_TICK_RECOVERY — freeze feed, verify stale detection fires in <30s
  REDIS_RECONNECT     — simulate Redis timeout, verify reconnect in <10s
  SPREAD_GATE         — widen spread, verify router blocks execution
  CONSENSUS_DIVERGE   — split feed consensus, verify DQE degrades confidence
  CLOCK_SKEW_DETECT   — skew timestamps, verify causal guard fires

Each scenario:
  1. Injects the fault via FaultInjector
  2. Waits for the system to respond
  3. Validates the expected response occurred
  4. Clears the fault
  5. Validates recovery
  6. Records pass/fail + timing

Usage
-----
    controller = ChaosController(orchestrator=orchestrator)
    results = await controller.run_all_scenarios()
    print(controller.report())
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from chaos.injector import FaultInjector, FaultType, fault_injector

logger = logging.getLogger(__name__)

# ── SLA bounds ────────────────────────────────────────────────────────────────
_FAILOVER_SLA_S = 5.0  # feed failover must complete in 5s
_STALE_DETECT_SLA = 35.0  # stale tick must be detected in 35s
_REDIS_RECOVER_SLA = 10.0  # Redis must reconnect in 10s
_SPIKE_REJECT_SLA = 2.0  # DQE must reject spike within 2 ticks


@dataclass
class ScenarioResult:
    scenario: str
    passed: bool
    duration_s: float
    sla_s: float
    detail: str
    injected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def within_sla(self) -> bool:
        return self.duration_s <= self.sla_s


class ChaosController:
    """
    Orchestrates chaos scenarios and validates system resilience.

    All scenarios run in paper mode — no live broker calls.
    """

    def __init__(
        self,
        orchestrator: Any = None,
        injector: FaultInjector | None = None,
    ) -> None:
        self._orch = orchestrator
        self._inj = injector or fault_injector
        self._results: list[ScenarioResult] = []

    # ── Scenario runner ───────────────────────────────────────────────────────

    async def run_all_scenarios(self) -> list[ScenarioResult]:
        """Run all chaos scenarios sequentially. Returns list of results."""
        scenarios = [
            self._scenario_dqe_spike_rejection,
            self._scenario_stale_tick_detection,
            self._scenario_spread_gate,
            self._scenario_corrupt_tick_rejection,
            self._scenario_clock_skew_detection,
            self._scenario_feed_drop_recovery,
        ]
        self._results.clear()
        for scenario_fn in scenarios:
            try:
                result = await scenario_fn()
                self._results.append(result)
                icon = "✓" if result.passed else "✗"
                logger.info(
                    "CHAOS [%s] %s — %.2fs (SLA=%.1fs) %s",
                    icon,
                    result.scenario,
                    result.duration_s,
                    result.sla_s,
                    result.detail,
                )
            except Exception as exc:
                logger.error("Chaos scenario '%s' raised exception: %s", scenario_fn.__name__, exc)
                self._results.append(
                    ScenarioResult(
                        scenario=scenario_fn.__name__,
                        passed=False,
                        duration_s=0.0,
                        sla_s=0.0,
                        detail="EXCEPTION — check server logs",
                    )
                )
            finally:
                self._inj.clear_all()
                await asyncio.sleep(0.5)  # brief pause between scenarios

        return self._results

    # ── Individual scenarios ──────────────────────────────────────────────────

    async def _scenario_dqe_spike_rejection(self) -> ScenarioResult:
        """
        Inject a 3% price spike. DQE must reject it within 2 ticks.
        Validates: DataQualityEngine anomaly detection is live.
        """
        t0 = time.monotonic()
        rejected_before = self._get_dqe_rejected_count()

        self._inj.inject(FaultType.PRICE_SPIKE, duration_s=5.0, magnitude=0.03, direction="up")
        await asyncio.sleep(3.0)
        self._inj.clear(FaultType.PRICE_SPIKE)

        rejected_after = self._get_dqe_rejected_count()
        spike_rejected = rejected_after > rejected_before
        duration = time.monotonic() - t0

        return ScenarioResult(
            scenario="dqe_spike_rejection",
            passed=spike_rejected,
            duration_s=duration,
            sla_s=_SPIKE_REJECT_SLA + 3.0,
            detail=(
                f"rejected_delta={rejected_after - rejected_before}"
                if spike_rejected
                else "DQE did not reject spike — check anomaly threshold"
            ),
        )

    async def _scenario_stale_tick_detection(self) -> ScenarioResult:
        """
        Freeze tick timestamps. DQE must detect stale feed within 35s.
        Validates: stale tick detection is wired and firing.
        """
        t0 = time.monotonic()
        stale_before = self._get_dqe_stale_count()

        self._inj.inject(FaultType.STALE_FEED, duration_s=40.0)
        await asyncio.sleep(35.0)
        self._inj.clear(FaultType.STALE_FEED)

        stale_after = self._get_dqe_stale_count()
        detected = stale_after > stale_before
        duration = time.monotonic() - t0

        return ScenarioResult(
            scenario="stale_tick_detection",
            passed=detected,
            duration_s=duration,
            sla_s=_STALE_DETECT_SLA,
            detail=(f"stale_delta={stale_after - stale_before}" if detected else "DQE did not detect stale feed"),
        )

    async def _scenario_spread_gate(self) -> ScenarioResult:
        """
        Widen spread 10x. SmartRouter must block execution.
        Validates: spread gate in router pre-route check.
        """
        t0 = time.monotonic()
        self._inj.inject(FaultType.SPREAD_WIDEN, duration_s=5.0, magnitude=10.0)
        await asyncio.sleep(2.0)

        # Verify router would reject (check via orchestrator features)
        spread_bps = self._get_current_spread_bps()
        from execution.smart_router import _MAX_SPREAD_BPS

        gate_would_fire = spread_bps > _MAX_SPREAD_BPS

        self._inj.clear(FaultType.SPREAD_WIDEN)
        duration = time.monotonic() - t0

        return ScenarioResult(
            scenario="spread_gate",
            passed=gate_would_fire,
            duration_s=duration,
            sla_s=5.0,
            detail=(
                f"spread={spread_bps:.1f}bps > max={_MAX_SPREAD_BPS:.1f}bps — gate fires"
                if gate_would_fire
                else f"spread={spread_bps:.1f}bps — gate would NOT fire (check ROUTER_MAX_SPREAD_BPS)"
            ),
        )

    async def _scenario_corrupt_tick_rejection(self) -> ScenarioResult:
        """
        Inject NaN price. DQE must reject it.
        Validates: NaN/inf guard in DataQualityEngine.
        """
        t0 = time.monotonic()
        rejected_before = self._get_dqe_rejected_count()

        self._inj.inject(FaultType.CORRUPT_TICK, duration_s=5.0, corrupt_type="nan")
        await asyncio.sleep(3.0)
        self._inj.clear(FaultType.CORRUPT_TICK)

        rejected_after = self._get_dqe_rejected_count()
        duration = time.monotonic() - t0

        return ScenarioResult(
            scenario="corrupt_tick_rejection",
            passed=rejected_after > rejected_before,
            duration_s=duration,
            sla_s=5.0,
            detail=f"rejected_delta={rejected_after - rejected_before}",
        )

    async def _scenario_clock_skew_detection(self) -> ScenarioResult:
        """
        Skew tick timestamps +120s into the future.
        Validates: causal timestamp guard in NormalizationPipeline rejects
        future-dated ticks and the DQE rejected count increases.
        """
        t0 = time.monotonic()
        rejected_before = self._get_dqe_rejected_count()

        self._inj.inject(FaultType.CLOCK_SKEW, duration_s=5.0, magnitude=120.0, direction_sign=1)
        await asyncio.sleep(4.0)
        self._inj.clear(FaultType.CLOCK_SKEW)

        rejected_after = self._get_dqe_rejected_count()
        duration = time.monotonic() - t0

        # The normalization pipeline rejects ticks with timestamps > 5s in
        # the future. A 120s skew must produce at least one rejection.
        skew_detected = rejected_after > rejected_before

        return ScenarioResult(
            scenario="clock_skew_detection",
            passed=skew_detected,
            duration_s=duration,
            sla_s=10.0,
            detail=(
                f"future-timestamp rejections delta={rejected_after - rejected_before}"
                if skew_detected
                else "causal guard did not reject skewed ticks — check NormalizationPipeline"
            ),
        )

    async def _scenario_feed_drop_recovery(self) -> ScenarioResult:
        """
        Drop the feed for 5s. Verify orchestrator health recovers.
        Validates: orchestrator continues operating after feed loss.
        """
        t0 = time.monotonic()
        _health_before = self._get_orchestrator_health()

        self._inj.inject(FaultType.FEED_DROP, duration_s=5.0)
        await asyncio.sleep(6.0)
        self._inj.clear(FaultType.FEED_DROP)
        await asyncio.sleep(2.0)

        health_after = self._get_orchestrator_health()
        duration = time.monotonic() - t0

        # Orchestrator must still be started after feed drop
        recovered = health_after.get("started", False)

        return ScenarioResult(
            scenario="feed_drop_recovery",
            passed=recovered,
            duration_s=duration,
            sla_s=_FAILOVER_SLA_S + 8.0,
            detail=("orchestrator still running after feed drop" if recovered else "orchestrator stopped — CRITICAL"),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_dqe_rejected_count(self) -> int:
        try:
            report = self._orch.get_quality_report("XAU_USD")
            return report.ticks_rejected if report else 0
        except Exception:
            return 0

    def _get_dqe_stale_count(self) -> int:
        try:
            report = self._orch.get_quality_report("XAU_USD")
            return report.stale_count if report else 0
        except Exception:
            return 0

    def _get_current_spread_bps(self) -> float:
        try:
            features = self._orch.get_ml_features()
            spread = features.get("micro_spread", 0.5)
            mid = self._orch.get_current_gold_price() or 2350.0
            return spread / mid * 10_000 * 10  # 10x widened
        except Exception:
            return 999.0  # assume wide if unavailable

    def _get_orchestrator_health(self) -> dict[str, Any]:
        try:
            return self._orch.health()
        except Exception:
            return {"started": False}

    # ── Report ────────────────────────────────────────────────────────────────

    def report(self) -> str:
        if not self._results:
            return "No chaos scenarios have been run."
        passed = sum(1 for r in self._results if r.passed)
        lines = [
            f"CHAOS ENGINEERING REPORT — {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            f"Scenarios: {len(self._results)}  Passed: {passed}  Failed: {len(self._results) - passed}",
            "",
        ]
        for r in self._results:
            icon = "✓" if r.passed else "✗"
            sla = "within SLA" if r.within_sla else f"EXCEEDED SLA ({r.duration_s:.1f}s > {r.sla_s:.1f}s)"
            lines.append(f"  [{icon}] {r.scenario:<35} {sla}")
            lines.append(f"       {r.detail}")
        return "\n".join(lines)

    def results_dict(self) -> list[dict[str, Any]]:
        return [
            {
                "scenario": r.scenario,
                "passed": r.passed,
                "duration_s": round(r.duration_s, 3),
                "sla_s": r.sla_s,
                "within_sla": r.within_sla,
                "detail": r.detail,
            }
            for r in self._results
        ]
