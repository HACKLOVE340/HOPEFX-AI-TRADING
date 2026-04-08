# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/llm_wrapper.py
=======================
Async LLM API wrapper used by HOPEFXBrain for intent analysis and
auto-generated code fixes.

Supports two backends (selected via LLM_BACKEND env var):
  - "anthropic"  → Claude 3.5 Sonnet (default; strong reasoning for security analysis and code generation)
  - "openai"     → GPT-4o-mini

Raises RuntimeError when called without a configured API key.
Set ANTHROPIC_API_KEY or OPENAI_API_KEY before use.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

# ── Backend selection ─────────────────────────────────────────────────────────
LLM_BACKEND: str = os.getenv("LLM_BACKEND", "anthropic").lower()
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

# Model identifiers
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "o4-mini")

# OpenAI reasoning models require max_completion_tokens and no temperature param.
_OPENAI_REASONING_MODELS: frozenset[str] = frozenset({"o1", "o1-mini", "o3", "o3-mini", "o4-mini"})

# Security analysis responses are short — keep token limit low for cost/latency.
# Use LLM_SECURITY_MAX_TOKENS to override; falls back to LLM_MAX_TOKENS for
# deployments that share a single token-limit setting.
MAX_TOKENS = int(os.getenv("LLM_SECURITY_MAX_TOKENS", os.getenv("LLM_MAX_TOKENS", "1024")))

# Retry configuration for transient upstream errors (429, 529, 503)
_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
_RETRY_BASE_DELAY: float = float(os.getenv("LLM_RETRY_BASE_DELAY", "1.0"))  # seconds


async def call_llm(prompt: str) -> str:
    """
    Send *prompt* to the configured LLM backend and return the text response.

    Raises:
        RuntimeError: When no API key is configured for the selected backend.
        httpx.HTTPStatusError / openai.APIError: On upstream API failures.
    """
    if LLM_BACKEND == "anthropic" and ANTHROPIC_API_KEY:
        return await _call_anthropic(prompt)
    if LLM_BACKEND == "openai" and OPENAI_API_KEY:
        return await _call_openai(prompt)
    raise RuntimeError(
        f"LLM backend '{LLM_BACKEND}' is not configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment."
    )


# ── Anthropic backend ─────────────────────────────────────────────────────────


async def _call_anthropic(prompt: str) -> str:
    """Call Anthropic Messages API with exponential backoff retry."""
    import httpx

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["content"][0]["text"].strip()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (429, 503, 529):
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "Anthropic transient error %d — retry %d/%d in %.1fs", status, attempt, _MAX_RETRIES, delay
                )
                await asyncio.sleep(delay)
                continue
            raise
        except httpx.ConnectError as exc:
            last_exc = exc
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning("Anthropic connection error — retry %d/%d in %.1fs: %s", attempt, _MAX_RETRIES, delay, exc)
            await asyncio.sleep(delay)

    raise RuntimeError(f"Anthropic call failed after {_MAX_RETRIES} retries") from last_exc


# ── OpenAI backend ────────────────────────────────────────────────────────────


async def _call_openai(prompt: str) -> str:
    """Call OpenAI Chat Completions API with exponential backoff retry.

    Reasoning models (o-series) require ``max_completion_tokens`` instead of
    ``max_tokens`` and do not accept a ``temperature`` parameter.
    """
    import httpx

    is_reasoning = OPENAI_MODEL in _OPENAI_REASONING_MODELS
    payload: dict = {
        "model": OPENAI_MODEL,
        "max_completion_tokens" if is_reasoning else "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "system",
                "content": "You are a cybersecurity analyst for a trading platform. Be concise and technical.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    if not is_reasoning:
        payload["temperature"] = 0.2

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (429, 500, 503):
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("OpenAI transient error %d — retry %d/%d in %.1fs", status, attempt, _MAX_RETRIES, delay)
                await asyncio.sleep(delay)
                continue
            raise
        except httpx.ConnectError as exc:
            last_exc = exc
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning("OpenAI connection error — retry %d/%d in %.1fs: %s", attempt, _MAX_RETRIES, delay, exc)
            await asyncio.sleep(delay)

    raise RuntimeError(f"OpenAI call failed after {_MAX_RETRIES} retries") from last_exc
