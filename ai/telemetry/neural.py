# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The "neural engine" indicator, bound to whether a model is actually reachable.

The specification lists a neural engine indicator among what the platform
already has. It was not in this repository — and the tempting version of it is
a light that pulses whenever the page is open, which is the zero CPU gauge
wearing different clothes. It would say "thinking" on a deployment with no
credential configured.

So the status is derived from three facts and nothing else:

* which vendors this deployment can actually reach (`available_providers`),
* which of their circuit breakers are open (`ai/gateway/breakers.py`),
* whether any call has ever succeeded.

`offline` when nothing is reachable, `degraded` when some legs are broken,
`ready` otherwise — and `last_success_at` stays None rather than becoming
"just now" when nothing has succeeded.
"""

from __future__ import annotations

from typing import Any


def neural_engine(
    *,
    providers: frozenset[str] | set[str] | None = None,
    open_breakers: tuple[str, ...] | list[str] | None = None,
    last_success_at: float | None = None,
) -> dict[str, Any]:
    """Model-layer state, derived from real configuration rather than animation."""
    if providers is None:
        from ai.gateway.client import GatewayClient

        providers = GatewayClient().available_providers()
    if open_breakers is None:
        from ai.gateway import breakers

        open_breakers = tuple(
            name for name, state in breakers.status().items() if str(state.get("state", "")).lower() == "open"
        )

    configured = sorted(providers)
    broken = sorted(set(open_breakers) & set(configured))
    reachable = [p for p in configured if p not in broken]

    reasons: list[str] = []
    if not configured:
        status = "offline"
        reasons.append("no provider is configured, so no model can be reached")
    elif not reachable:
        status = "offline"
        reasons.append("every configured provider has an open circuit breaker")
    elif broken:
        status = "degraded"
        reasons.append(f"{len(broken)} of {len(configured)} providers have an open breaker")
    else:
        status = "ready"

    if last_success_at is None:
        reasons.append("no successful call has been recorded in this process")

    return {
        "status": status,
        "providers": configured,
        "reachable": reachable,
        "open_breakers": broken,
        "last_success_at": last_success_at,
        "reason": "; ".join(reasons),
    }


__all__ = ["neural_engine"]
