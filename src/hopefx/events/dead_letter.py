from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any

import structlog

from hopefx.events.schemas import Event

logger = structlog.get_logger()


class DeadLetterQueue:
    """Store and retry failed events with exponential backoff and jitter."""

    def __init__(
        self,
        max_retries: int = 5,
        base_delay: int = 60,
        max_delay: int = 3600
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        
        self._failed_events: Dict[str, dict] = {}
        self._permanent_failures: List[dict] = []
        self._retry_task: Optional[asyncio.Task] = None
        self._metrics: dict = {
            "retried": 0,
            "succeeded": 0,
            "permanent_failures": 0
        }

    async def start(self) -> None:
        """Start retry processor."""
        self._retry_task = asyncio.create_task(self._retry_loop())
        logger.info("dlq.started")

    async def stop(self) -> None:
        """Stop retry processor."""
        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass

    async def enqueue(
        self,
        event: Event,
        error: str,
        handler: Callable[[Event], Any],
        context: Optional[dict] = None
    ) -> None:
        """Add failed event to DLQ."""
        event_id = f"{event.id}:{event.type.value}"
        
        # Get current attempt count
        existing = self._failed_events.get(event_id)
        attempt = existing['attempts'] + 1 if existing else 1

        if attempt > self.max_retries:
            await self._permanent_failure(event, error, attempt, context)
            return

        # Calculate next retry with exponential backoff and jitter
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        jitter = random.uniform(0, 0.1 * delay)  # 10% jitter
        next_retry = datetime.utcnow().timestamp() + delay + jitter

        self._failed_events[event_id] = {
            'event': event,
            'error': error,
            'handler': handler,
            'attempts': attempt,
            'first_failure': existing['first_failure'] if existing else datetime.utcnow(),
            'next_retry': next_retry,
            'context': context or {},
            'error_history': existing['error_history'] + [error] if existing else [error]
        }

        logger.warning(
            "dlq.enqueued",
            event_id=event_id,
            attempt=attempt,
            next_retry=datetime.fromtimestamp(next_retry).isoformat()
        )

    async def _retry_loop(self) -> None:
        """Process retry queue."""
        while True:
            try:
                now = datetime.utcnow().timestamp()
                
                # Find ready events
                ready = [
                    (eid, data) for eid, data in self._failed_events.items()
                    if data['next_retry'] <= now
                ]

                for event_id, data in ready:
                    # Remove from queue (will re-add if fails)
                    del self._failed_events[event_id]
                    
                    # Attempt retry
                    try:
                        await data['handler'](data['event'])
                        self._metrics['succeeded'] += 1
                        self._metrics['retried'] += 1
                        
                        logger.info(
                            "dlq.retry_succeeded",
                            event_id=event_id,
                            attempts=data['attempts']
                        )
                        
                    except Exception as e:
                        # Re-enqueue with incremented attempt
                        await self.enqueue(
                            data['event'],
                            str(e),
                            data['handler'],
                            data['context']
                        )
                        self._metrics['retried'] += 1

                # Clean up old permanent failures
                await self._cleanup_permanent_failures()

                await asyncio.sleep(5)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("dlq.loop_error", error=str(e))
                await asyncio.sleep(10)

    async def _permanent_failure(
        self,
        event: Event,
        error: str,
        attempts: int,
        context: Optional[dict]
    ) -> None:
        """Handle permanent failure."""
        failure_record = {
            'event': event.model_dump(),
            'final_error': error,
            'attempts': attempts,
            'error_history': context.get('error_history', []) if context else [],
            'first_failure': context.get('first_failure', datetime.utcnow()).isoformat() if context else datetime.utcnow().isoformat(),
            'final_failure': datetime.utcnow().isoformat(),
            'handler_name': context.get('handler', lambda: None).__name__ if context else 'unknown'
        }

        self._permanent_failures.append(failure_record)
        self._metrics['permanent_failures'] += 1

        # Immediate alert
        await self._alert_ops(failure_record)

        logger.error(
            "dlq.permanent_failure",
            event_id=event.id,
            attempts=attempts,
            error=error
        )

    async def _alert_ops(self, failure_record: dict) -> None:
        """Alert operations team."""
        # Send to PagerDuty/Slack
        # Create incident ticket
        pass

    async def manual_retry(self, event_id: str) -> bool:
        """Manually trigger immediate retry."""
        for eid, data in list(self._failed_events.items()):
            if eid.startswith(event_id):
                data['next_retry'] = datetime.utcnow().timestamp()
                return True
        
        # Check permanent failures
        for failure in self._permanent_failures:
            if failure['event']['id'] == event_id:
                # Re-enqueue
                event = Event(**failure['event'])
                # Need to reconstruct handler - this is simplified
                return False
        
        return False

    async def get_metrics(self) -> dict:
        """DLQ metrics for monitoring."""
        now = datetime.utcnow().timestamp()
        
        pending = sum(
            1 for data in self._failed_events.values()
            if data['next_retry'] > now
        )
        
        ready = sum(
            1 for data in self._failed_events.values()
            if data['next_retry'] <= now
        )

        avg_attempts = sum(
            d['attempts'] for d in self._failed_events.values()
        ) / len(self._failed_events) if self._failed_events else 0

        oldest_failure = min(
            (d['first_failure'] for d in self._failed_events.values()),
            default=None
        )

        return {
            'pending_retries': pending,
            'ready_to_retry': ready,
            'total_queued': len(self._failed_events),
            'permanent_failures': len(self._permanent_failures),
            'avg_attempts': avg_attempts,
            'metrics': self._metrics,
            'oldest_failure_seconds': (
                (datetime.utcnow() - oldest_failure).total_seconds()
                if oldest_failure else None
            )
        }

    async def archive_permanent_failures(self, storage: Any) -> int:
        """Archive permanent failures to cold storage."""
        archived = 0
        cutoff = datetime.utcnow() - timedelta(days=30)

        for failure in list(self._permanent_failures):
            failure_time = datetime.fromisoformat(failure['final_failure'])
            if failure_time < cutoff:
                await storage.store(
                    f"dlq:{failure['event']['id']}",
                    failure
                )
                self._permanent_failures.remove(failure)
                archived += 1

        return archived

    async def _cleanup_permanent_failures(self) -> None:
        """Remove very old permanent failures."""
        cutoff = datetime.utcnow() - timedelta(days=90)
        self._permanent_failures = [
            f for f in self._permanent_failures
            if datetime.fromisoformat(f['final_failure']) > cutoff
        ]


# Global instance
dead_letter_queue = DeadLetterQueue()
