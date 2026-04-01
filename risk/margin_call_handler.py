# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk/margin_call_handler.py
============================
Automated margin call handler.

Responds to broker margin calls with a prioritised action sequence:
  1. Log and alert immediately
  2. Close highest-risk / most-leveraged positions first
  3. Inject additional equity if available (internal transfers)
  4. Notify risk manager and operators
  5. Suspend trading if margin call cannot be resolved

Hooks into: risk/orchestrator.py, brokers/, core/event_bus.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

UTC = timezone.utc
logger = logging.getLogger(__name__)


class MarginCallAction(Enum):
    """Actions taken in response to a margin call."""
    DETECTED = "detected"
    ALERTING = "alerting"
    CLOSING_POSITIONS = "closing_positions"
    INJECTING_EQUITY = "injecting_equity"
    SUSPENDED = "suspended"
    RESOLVED = "resolved"
    FAILED = "failed"


@dataclass
class MarginCallEvent:
    """A margin call event from a broker."""
    broker_name: str
    account_id: str
    margin_deficit_usd: float
    """How much additional margin is required."""
    equity_usd: float
    """Current equity."""
    maintenance_margin_usd: float
    """Maintenance margin required."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarginCallResponse:
    """Actions taken in response to a margin call."""
    event: MarginCallEvent
    actions_taken: list[str] = field(default_factory=list)
    positions_closed: list[str] = field(default_factory=list)
    equity_injected_usd: float = 0.0
    resolved: bool = False
    suspended: bool = False
    final_status: str = ""
    resolved_at: datetime | None = None


class MarginCallHandler:
    """
    Automated margin call response handler.

    Prioritises position closure by risk-adjusted notional value and
    coordinates with broker APIs to reduce margin deficit.
    """

    def __init__(
        self,
        max_equity_injection_usd: float = 0.0,
        auto_close_enabled: bool = True,
        alert_callbacks: list[Callable[[MarginCallEvent], None]] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        max_equity_injection_usd : float
            Maximum equity transfer per margin call. 0 = no injection.
        auto_close_enabled : bool
            Whether to automatically close positions. Default True.
        alert_callbacks : list of callables
            Functions to call with MarginCallEvent on detection.
        """
        self.max_equity_injection_usd = max_equity_injection_usd
        self.auto_close_enabled = auto_close_enabled
        self._alert_callbacks = alert_callbacks or []
        self._history: list[MarginCallResponse] = []

    def handle(
        self,
        event: MarginCallEvent,
        open_positions: list[dict[str, Any]] | None = None,
        broker_close_fn: Callable[[str, float], bool] | None = None,
    ) -> MarginCallResponse:
        """
        Handle a margin call event with a prioritised response sequence.

        Parameters
        ----------
        event : MarginCallEvent
            The incoming margin call.
        open_positions : list of dicts, optional
            Each dict: {symbol, notional_usd, pnl_usd, leverage}.
            Used to select which positions to close.
        broker_close_fn : callable, optional
            Function(symbol, quantity) -> bool.
            Called to close positions. If None, closure is logged only.

        Returns
        -------
        MarginCallResponse
        """
        response = MarginCallResponse(event=event)
        response.actions_taken.append(
            f"[{datetime.now(UTC).isoformat()}] Margin call detected: "
            f"broker={event.broker_name}, deficit=${event.margin_deficit_usd:,.0f}"
        )

        logger.warning(
            "MARGIN CALL: %s account=%s deficit=$%.2f equity=$%.2f",
            event.broker_name, event.account_id,
            event.margin_deficit_usd, event.equity_usd,
        )

        # Step 1: Alert
        for cb in self._alert_callbacks:
            try:
                cb(event)
            except Exception as exc:
                logger.error("Margin call alert callback failed: %s", exc)
        response.actions_taken.append(f"Alerts sent to {len(self._alert_callbacks)} callbacks")

        remaining_deficit = event.margin_deficit_usd

        # Step 2: Close positions (highest leverage / worst PnL first)
        if self.auto_close_enabled and open_positions:
            sorted_positions = sorted(
                open_positions,
                key=lambda p: (
                    -float(p.get("leverage", 1.0)),
                    float(p.get("pnl_usd", 0.0)),
                ),
            )

            for pos in sorted_positions:
                if remaining_deficit <= 0:
                    break
                symbol = str(pos.get("symbol", "UNKNOWN"))
                notional = float(pos.get("notional_usd", 0.0))
                margin_released = notional * float(pos.get("margin_pct", 0.02))

                success = True
                if broker_close_fn is not None:
                    try:
                        success = broker_close_fn(symbol, notional)
                    except Exception as exc:
                        logger.error("Failed to close %s: %s", symbol, exc)
                        success = False

                if success:
                    response.positions_closed.append(symbol)
                    remaining_deficit -= margin_released
                    response.actions_taken.append(
                        f"Closed {symbol}: margin released=${margin_released:,.0f}"
                    )
                    logger.info("Margin call: closed %s, released $%.2f", symbol, margin_released)

        # Step 3: Equity injection if still in deficit
        if remaining_deficit > 0 and self.max_equity_injection_usd > 0:
            injection = min(remaining_deficit, self.max_equity_injection_usd)
            response.equity_injected_usd = injection
            remaining_deficit -= injection
            response.actions_taken.append(f"Equity injection: ${injection:,.0f}")
            logger.info("Margin call: injected $%.2f equity", injection)

        # Step 4: Determine resolution
        if remaining_deficit <= 0:
            response.resolved = True
            response.resolved_at = datetime.now(UTC)
            response.final_status = MarginCallAction.RESOLVED.value
            response.actions_taken.append("Margin call RESOLVED")
            logger.info("Margin call resolved for %s", event.broker_name)
        else:
            # Cannot resolve — suspend trading
            response.suspended = True
            response.final_status = MarginCallAction.SUSPENDED.value
            response.actions_taken.append(
                f"TRADING SUSPENDED: remaining deficit=${remaining_deficit:,.0f}"
            )
            logger.critical(
                "Margin call UNRESOLVED — trading suspended for %s. "
                "Remaining deficit: $%.2f",
                event.broker_name, remaining_deficit,
            )

        self._history.append(response)
        return response

    def history(self) -> list[dict[str, Any]]:
        """Return serialisable history of margin call responses."""
        return [
            {
                "broker": r.event.broker_name,
                "account": r.event.account_id,
                "deficit_usd": r.event.margin_deficit_usd,
                "timestamp": r.event.timestamp.isoformat(),
                "resolved": r.resolved,
                "suspended": r.suspended,
                "positions_closed": r.positions_closed,
                "equity_injected": r.equity_injected_usd,
                "actions_taken": r.actions_taken,
            }
            for r in self._history
        ]

    def register_alert_callback(self, cb: Callable[[MarginCallEvent], None]) -> None:
        """Register an alert callback (e.g. send email, Slack, PagerDuty)."""
        self._alert_callbacks.append(cb)


# Module-level singleton
margin_call_handler = MarginCallHandler()
