# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/llm_wrapper.py
=======================
Async LLM API wrapper used by HOPEFXBrain for intent analysis and
auto-generated code fixes.

Supports two backends (selected via LLM_BACKEND env var):
  - "anthropic"  → Claude 3 Haiku (fast, cheap, good for security analysis)
  - "openai"     → GPT-4o-mini (fallback)

Falls back to a stub response when no API key is configured so the
system degrades gracefully in dev/test environments.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── Backend selection ─────────────────────────────────────────────────────────
LLM_BACKEND: str = os.getenv("LLM_BACKEND", "anthropic").lower()
ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")

# Model identifiers
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Max tokens for security analysis responses (keep short → fast + cheap)
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "512"))


async def call_llm(prompt: str) -> str:
    """
    Send *prompt* to the configured LLM backend and return the text response.

    Never raises — on any error returns a safe fallback string so the
    HOPEFXBrain loop continues uninterrupted.
    """
    try:
        if LLM_BACKEND == "anthropic" and ANTHROPIC_API_KEY:
            return await _call_anthropic(prompt)
        elif LLM_BACKEND == "openai" and OPENAI_API_KEY:
            return await _call_openai(prompt)
        else:
            logger.warning(
                "LLM backend '%s' not configured — using stub response", LLM_BACKEND
            )
            return _stub_response(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM call failed: %s", exc)
        return _stub_response(prompt)


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
                "content": (
                    "You are a cybersecurity analyst for a trading platform. "
                    "Be concise and technical."
                ),
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


# ── Stub (no API key configured) ─────────────────────────────────────────────

def _stub_response(prompt: str) -> str:
    """
    Deterministic stub used when no LLM backend is available.
    Returns a safe, parseable string so downstream code never breaks.
    """
    prompt_lower = prompt.lower()
    if "intent" in prompt_lower or "attack" in prompt_lower:
        return "probe"
    if "rewrite" in prompt_lower or "fix" in prompt_lower or "secure" in prompt_lower:
        return (
            "# Auto-fix stub (configure LLM_BACKEND + API key for real fixes)\n"
            "# Original code requires manual security review."
        )
    return "analysis_unavailable"
