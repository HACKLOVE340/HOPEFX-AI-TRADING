# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The single entry point for every model call.

Routing, timeouts, fall-through, budget and audit live here so that no caller
has to get them right individually. Before this, `api/brain.py` selected a
backend from environment variables, built the request inline, and turned any
failure into a 502 -- no second leg, no ceiling, and no record of what was
spent or which model answered.

Two rules are worth stating because they are easy to get backwards:

* **Budget is checked before the request is issued.** A ceiling enforced after
  the money is spent is a report, not a limit.
* **A refusal is an answer.** Transport failures advance to the next leg;
  guardrail rejections, refusals, budget denials and our own 4xx do not.
  Retrying a guardrail rejection on a second vendor defeats the guardrail, and
  retrying a budget denial defeats the ceiling. `ai.gateway.chain` owns that
  predicate; this module obeys it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ai.gateway import audit, budget
from ai.gateway.chain import ChainLeg, resolve_chain, should_fall_through
from ai.guardrails.input import screen_input
from ai.guardrails.output import validate_output

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 60.0


class GatewayError(RuntimeError):
    """Base for every gateway failure."""


class BudgetExceeded(GatewayError):
    """A ceiling refused the call before it was issued."""


class NoProviderAvailable(GatewayError):
    """Every leg of the chain failed, or none could be reached."""


class ProviderError(GatewayError):
    """One leg failed. `reason` decides whether the next leg is tried."""

    def __init__(self, reason: str, *, provider: str = "", model: str = "") -> None:
        super().__init__(f"{provider or 'provider'} failed: {reason}")
        self.reason, self.provider, self.model = reason, provider, model


@dataclass(frozen=True)
class ModelRequest:
    role: str = "reasoning"
    prompt: str = ""
    timeout_s: float = DEFAULT_TIMEOUT_S
    estimated_usd: float = 0.0

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("a model request needs a prompt")


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str
    latency_ms: float
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: tuple[dict[str, Any], ...] = field(default_factory=tuple)


class Provider(Protocol):
    """What the gateway needs from a vendor adapter."""

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> Any: ...


class GatewayClient:
    """Routes a request along its role's chain and records what happened."""

    def __init__(self, providers: dict[str, Provider] | None = None) -> None:
        self._providers = providers if providers is not None else {}

    def available_providers(self) -> frozenset[str]:
        """Vendors this deployment can actually reach.

        A chain leg whose vendor is absent is SKIPPED rather than counted as a
        failed attempt: a missing credential is a deployment fact, not a
        provider outage, and conflating them would make an unconfigured
        deployment look like a failing one.
        """
        return frozenset(self._providers)

    def call_sync(self, request: ModelRequest, *, operator: str) -> ModelResponse:
        """Issue `request`, falling through the chain as the rules allow."""
        # Input screening happens before anything is spent or sent. A guardrail
        # violation is an ANSWER, not a transport failure: it is raised, never
        # retried on a second vendor, because retrying it would defeat the
        # guardrail. `chain.should_fall_through` encodes the same rule.
        screen_input(request.prompt)

        allowed, reason = budget.check(operator, request.estimated_usd)
        if not allowed:
            # Audited before raising: a refused call is still a call someone
            # made, and the ceiling working is worth being able to show.
            audit.record_call(
                operator=operator,
                role=request.role,
                prompt=request.prompt,
                attempts=[{"provider": None, "reason": "budget_exceeded", "detail": reason}],
                served_by=None,
                model=None,
                latency_ms=0.0,
                cost_usd=0.0,
                tokens_in=0,
                tokens_out=0,
            )
            raise BudgetExceeded(reason)

        attempts: list[dict[str, Any]] = []
        started = time.perf_counter()

        for leg in resolve_chain(request.role):
            provider = self._providers.get(leg.provider)
            if provider is None:
                attempts.append({"provider": leg.provider, "reason": "no_credentials", "skipped": True})
                continue
            try:
                result = provider.complete(model=leg.model, prompt=request.prompt, timeout_s=request.timeout_s)
            except ProviderError as exc:
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": exc.reason})
                if should_fall_through(exc.reason):
                    logger.info("ai.gateway: %s failed (%s); trying the next leg", leg.provider, exc.reason)
                    continue
                self._audit(request, operator, attempts, None, None, started, 0.0, 0, 0)
                raise
            except Exception as exc:  # an adapter bug must not look like a refusal
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": "adapter_error"})
                logger.exception("ai.gateway: adapter raised for %s: %s", leg.provider, exc)
                continue

            latency_ms = (time.perf_counter() - started) * 1000
            cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
            tokens_in = int(getattr(result, "tokens_in", 0) or 0)
            tokens_out = int(getattr(result, "tokens_out", 0) or 0)
            attempts.append({"provider": leg.provider, "model": leg.model, "reason": "served"})
            budget.charge(operator, cost)
            self._audit(request, operator, attempts, leg, leg.model, started, cost, tokens_in, tokens_out)
            return ModelResponse(
                text=str(getattr(result, "text", "")),
                provider=leg.provider,
                model=leg.model,
                latency_ms=latency_ms,
                cost_usd=cost,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                attempts=tuple(attempts),
            )

        self._audit(request, operator, attempts, None, None, started, 0.0, 0, 0)
        tried = ", ".join(f"{a['provider']}={a['reason']}" for a in attempts) or "no legs"
        raise NoProviderAvailable(f"no model served role {request.role!r}: {tried}")

    def call_structured(
        self,
        request: ModelRequest,
        *,
        operator: str,
        required: dict[str, tuple[type, ...]] | None = None,
        ranges: dict[str, tuple[float, float]] | None = None,
    ) -> dict[str, Any]:
        """Issue `request` and validate the response before any caller sees it.

        Validation is not coercion: a response the model did not produce in the
        requested shape raises GuardrailViolation, and the caller's fallback to
        a deterministic answer is the safe result. The gateway does NOT retry a
        validation failure on the next leg -- the model answered, it just did
        not answer in the contract.
        """
        response = self.call_sync(request, operator=operator)
        return validate_output(response.text, required=required, ranges=ranges)

    def _audit(
        self,
        request: ModelRequest,
        operator: str,
        attempts: list[dict[str, Any]],
        leg: ChainLeg | None,
        model: str | None,
        started: float,
        cost: float,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        audit.record_call(
            operator=operator,
            role=request.role,
            prompt=request.prompt,
            attempts=attempts,
            served_by=leg.provider if leg else None,
            model=model,
            latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "BudgetExceeded",
    "GatewayClient",
    "GatewayError",
    "ModelRequest",
    "ModelResponse",
    "NoProviderAvailable",
    "Provider",
    "ProviderError",
]
