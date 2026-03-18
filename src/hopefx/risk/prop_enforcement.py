from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Dict
from dataclasses import dataclass

import structlog
from sqlalchemy import select, and_

from hopefx.config.settings import settings
from hopefx.database.models import PropChallenge, Trade, AuditLog
from hopefx.events.bus import event_bus
from hopefx.events.schemas import Event, EventType, RiskViolation

logger = structlog.get_logger()


@dataclass
class PropBreach:
    rule: str
    severity: str  # warning, violation, termination
    current_value: Decimal
    limit_value: Decimal
    timestamp: datetime
    auto_action: Optional[str] = None  # close_positions, disable_trading, etc.


class PropEnforcementEngine:
    """Automated prop firm rule enforcement with real-time monitoring."""

    def __init__(self) -> None:
        self._active_challenges: Dict[str, PropChallenge] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Rule configurations by firm
        self._firm_rules = {
            "ftmo": {
                "daily_loss_limit": Decimal("0.05"),
                "total_loss_limit": Decimal("0.10"),
                "profit_target": Decimal("0.10"),
                "min_trading_days": 4,
                "max_trading_days": 30,
                "required_stop_loss": True,
                "no_weekend_holding": False,
                "max_position_size": Decimal("50"),  # lots
            },
            "mff": {
                "daily_loss_limit": Decimal("0.05"),
                "total_loss_limit": Decimal("0.12"),
                "profit_target": Decimal("0.08"),
                "min_trading_days": 5,
                "max_trading_days": 35,
                "required_stop_loss": False,
                "no_weekend_holding": True,
                "max_position_size": Decimal("100"),
            }
        }

    async def start(self) -> None:
        """Start enforcement monitoring."""
        self._running = True
        event_bus.subscribe(EventType.ORDER_FILL, self._on_trade)
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("prop_enforcement.started")

    async def stop(self) -> None:
        """Stop enforcement."""
        self._running = False
        if self._monitoring_task:
            self._monitoring_task.cancel()
        logger.info("prop_enforcement.stopped")

    async def register_challenge(self, challenge: PropChallenge) -> None:
        """Register new prop challenge for monitoring."""
        self._active_challenges[challenge.id] = challenge
        logger.info(
            "prop_enforcement.challenge_registered",
            challenge_id=challenge.id,
            firm=challenge.firm,
            account_size=float(challenge.account_size)
        )

    async def _on_trade(self, event: Event) -> None:
        """Process trade for prop compliance."""
        if not isinstance(event.payload, any):  # OrderFill
            return

        fill = event.payload
        
        # Find if this trade belongs to a prop challenge
        for challenge in self._active_challenges.values():
            if await self._is_challenge_trade(challenge, fill):
                await self._update_challenge_metrics(challenge, fill)
                await self._check_compliance(challenge)

    async def _is_challenge_trade(self, challenge: PropChallenge, fill) -> bool:
        """Check if trade belongs to challenge."""
        # Match by broker account ID or metadata
        return False  # Implementation depends on broker integration

    async def _update_challenge_metrics(self, challenge: PropChallenge, fill) -> None:
        """Update challenge metrics with new trade."""
        # Update equity, P&L, trading days
        # Track peak equity for drawdown
        pass

    async def _check_compliance(self, challenge: PropChallenge) -> List[PropBreach]:
        """Check all compliance rules."""
        breaches = []
        rules = self._firm_rules.get(challenge.firm, self._firm_rules["ftmo"])

        # Daily loss limit
        daily_loss_pct = abs(challenge.daily_pnl) / challenge.account_size
        if daily_loss_pct > rules["daily_loss_limit"]:
            breaches.append(PropBreach(
                rule="daily_loss_limit",
                severity="violation" if daily_loss_pct > rules["daily_loss_limit"] * Decimal("1.2") else "warning",
                current_value=daily_loss_pct,
                limit_value=rules["daily_loss_limit"],
                timestamp=datetime.utcnow(),
                auto_action="close_positions" if daily_loss_pct > rules["daily_loss_limit"] * Decimal("1.5") else None
            ))

        # Total loss limit
        total_loss_pct = abs(challenge.total_pnl) / challenge.account_size
        if total_loss_pct > rules["total_loss_limit"]:
            breaches.append(PropBreach(
                rule="total_loss_limit",
                severity="termination",
                current_value=total_loss_pct,
                limit_value=rules["total_loss_limit"],
                timestamp=datetime.utcnow(),
                auto_action="disable_trading"
            ))

        # Profit target reached
        if challenge.total_pnl / challenge.account_size >= rules["profit_target"]:
            if challenge.trading_days_count >= rules["min_trading_days"]:
                breaches.append(PropBreach(
                    rule="profit_target",
                    severity="success",
                    current_value=challenge.total_pnl / challenge.account_size,
                    limit_value=rules["profit_target"],
                    timestamp=datetime.utcnow(),
                    auto_action="promote_to_funded"
                ))

        # Max trading days
        days_active = (datetime.utcnow() - challenge.start_date).days
        if days_active > rules["max_trading_days"] and challenge.status == "active":
            if challenge.total_pnl / challenge.account_size < rules["profit_target"]:
                breaches.append(PropBreach(
                    rule="max_trading_days",
                    severity="termination",
                    current_value=days_active,
                    limit_value=rules["max_trading_days"],
                    timestamp=datetime.utcnow(),
                    auto_action="challenge_failed"
                ))

        # Process breaches
        for breach in breaches:
            await self._handle_breach(challenge, breach)

        return breaches

    async def _handle_breach(self, challenge: PropChallenge, breach: PropBreach) -> None:
        """Handle compliance breach."""
        logger.warning(
            "prop_enforcement.breach",
            challenge_id=challenge.id,
            rule=breach.rule,
            severity=breach.severity,
            current=float(breach.current_value),
            limit=float(breach.limit_value)
        )

        # Record violation
        challenge.violations.append({
            "rule": breach.rule,
            "severity": breach.severity,
            "timestamp": breach.timestamp.isoformat(),
            "values": {
                "current": float(breach.current_value),
                "limit": float(breach.limit_value)
            }
        })

        # Auto-actions
        if breach.auto_action == "close_positions":
            await self._emergency_close_all(challenge)
        elif breach.auto_action == "disable_trading":
            await self._disable_trading(challenge)
        elif breach.auto_action == "promote_to_funded":
            await self._promote_to_funded(challenge)

        # Publish violation event
        if breach.severity in ["violation", "termination"]:
            await event_bus.publish(
                Event(
                    type=EventType.RISK_VIOLATION,
                    payload=RiskViolation(
                        violation_type=f"prop_{breach.rule}",
                        current_value=float(breach.current_value),
                        limit_value=float(breach.limit_value),
                    ),
                    source="prop_enforcement",
                )
            )

    async def _emergency_close_all(self, challenge: PropChallenge) -> None:
        """Emergency close all positions."""
        # Get all open positions for challenge
        # Market close each
        # Notify user
        logger.error("prop_enforcement.emergency_close", challenge_id=challenge.id)

    async def _disable_trading(self, challenge: PropChallenge) -> None:
        """Disable trading for challenge."""
        challenge.status = "violated"
        # Disable broker connection
        # Notify user
        logger.error("prop_enforcement.trading_disabled", challenge_id=challenge.id)

    async def _promote_to_funded(self, challenge: PropChallenge) -> None:
        """Promote to funded account."""
        challenge.status = "passed"
        # Create funded account
        # Update user profile
        # Notify user
        logger.info("prop_enforcement.challenge_passed", challenge_id=challenge.id)

    async def _monitoring_loop(self) -> None:
        """Periodic monitoring loop."""
        while self._running:
            try:
                # Daily report generation
                await self._generate_daily_reports()
                
                # Check for stale challenges
                await self._check_stale_challenges()
                
                await asyncio.sleep(3600)  # Hourly checks
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("prop_enforcement.monitoring_error", error=str(e))
                await asyncio.sleep(60)

    async def _generate_daily_reports(self) -> None:
        """Generate daily compliance reports."""
        for challenge in self._active_challenges.values():
            if challenge.status != "active":
                continue

            report = {
                "date": datetime.utcnow().isoformat(),
                "challenge_id": challenge.id,
                "equity": float(challenge.current_equity),
                "daily_pnl": float(challenge.daily_pnl),
                "total_pnl": float(challenge.total_pnl),
                "trading_days": challenge.trading_days_count,
                "violations": len(challenge.violations)
            }
            
            # Store report, email to user
            logger.info("prop_enforcement.daily_report", **report)

    async def _check_stale_challenges(self) -> None:
        """Check for challenges needing attention."""
        # Challenges approaching limits
        # Inactive challenges
        pass

    async def generate_ftmo_report(self, challenge_id: str) -> dict:
        """Generate FTMO-compliant trading report."""
        # Detailed trade list
        # Risk metrics
        # Compliance attestation
        pass


# Global instance
prop_enforcement = PropEnforcementEngine()
