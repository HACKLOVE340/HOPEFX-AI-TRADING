# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/llm_wrapper.py
=======================
Async LLM call used by HOPEFXBrain for intent analysis and auto-generated code
fixes. **A thin adapter onto `ai.gateway` — it no longer talks to a vendor.**

What it used to be: 173 lines that selected a backend from `LLM_BACKEND`, built
the Anthropic and OpenAI request bodies inline, posted to
api.anthropic.com/v1/messages and api.openai.com/v1/chat/completions, and
retried transient errors with exponential backoff.

Every one of those concerns now lives in the gateway, and three that this module
never had come with it:

* **A spend ceiling**, checked before the request. This module could be called
  in a loop by the self-healer with no limit at all.
* **An audit record** of the model, latency, tokens and cost — with the prompt
  hashed, never stored. The prompts here carry source code from this repository.
* **A second vendor.** The old retry loop retried the SAME backend three times
  with backoff, which is the one thing that does not help when that vendor is
  the thing that is down. The gateway's chain moves to a different vendor.

The public signature is unchanged, so `security/global_fortress.py` and
`security/self_healer.py` did not have to change with it.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

#: Kept for callers and tests that read them. They no longer select a backend —
#: `ai.gateway.chain` does, from platform config, which is what makes the
#: setting a superadmin edits actually take effect (audit D8).
LLM_BACKEND: str = os.getenv("LLM_BACKEND", "anthropic").lower()
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

#: Security analysis responses are short. The gateway caps output centrally;
#: this stays because deployments set it.
MAX_TOKENS = int(os.getenv("LLM_SECURITY_MAX_TOKENS", os.getenv("LLM_MAX_TOKENS", "1024")))

#: Which operator these calls are billed and audited against. Security analysis
#: is machine-initiated, so it gets its own identity rather than borrowing a
#: person's — a self-healer loop must not exhaust an operator's ceiling.
OPERATOR = "security-analysis"

#: Security analysis wants the reasoning tier: it reads code and decides whether
#: something is an attack. A cheaper model that is wrong more often is not
#: cheaper here either.
ROLE = "reasoning"


async def call_llm(prompt: str) -> str:
    """Send *prompt* through the gateway and return the text response.

    Raises:
        RuntimeError: when no vendor in the chain is reachable, or a ceiling
            refused the call. The message names which, so an operator can tell
            "not configured" from "out of budget" — the old code raised the same
            RuntimeError for both.
    """
    from ai.gateway.adapters import build_providers
    from ai.cache.store import STATELESS
    from ai.gateway.client import (
        BudgetExceeded,
        GatewayClient,
        ModelRequest,
        NoProviderAvailable,
    )

    providers = build_providers()
    if not providers:
        raise RuntimeError(
            "No LLM vendor is configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, "
            "GOOGLE_API_KEY or OLLAMA_BASE_URL in your environment."
        )

    client = GatewayClient(providers)
    # STATELESS: this wrapper's answer depends on its prompt and nothing else —
    # no positions, no regime, no config. It is the only caller opted in.
    # api/brain.py and brain/llm_agent.py reason about live market state and
    # stay uncached until they declare what theirs depends on.
    request = ModelRequest(role=ROLE, prompt=prompt, tool_state=STATELESS)
    try:
        response = await asyncio.to_thread(client.call_sync, request, operator=OPERATOR)
    except BudgetExceeded as exc:
        raise RuntimeError(f"Security analysis is over its model budget: {exc}") from None
    except NoProviderAvailable as exc:
        raise RuntimeError(f"No LLM vendor answered: {exc}") from None
    return response.text.strip()


__all__ = ["ANTHROPIC_API_KEY", "LLM_BACKEND", "MAX_TOKENS", "OPENAI_API_KEY", "OPERATOR", "ROLE", "call_llm"]
