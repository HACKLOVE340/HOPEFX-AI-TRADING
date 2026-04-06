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

# Max tokens — increased to support full code-generation responses
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))


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
    """Call Anthropic Messages API (async via httpx)."""
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"].strip()


# ── OpenAI backend ────────────────────────────────────────────────────────────


async def _call_openai(prompt: str) -> str:
    """Call OpenAI Chat Completions API (async via httpx)."""
    import httpx

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "system",
                "content": ("You are a cybersecurity analyst for a trading platform. Be concise and technical."),
            },
            {"role": "user", "content": prompt},
        ],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
