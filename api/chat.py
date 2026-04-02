# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/chat.py
===========
AI chat endpoint — wraps brain.llm_agent.LLMAgent.chat() behind a REST
route so the dashboard (and any API client) can send free-form messages
and receive AI responses.

Routes
------
POST /api/chat          — send a message, get a response (auth required)
DELETE /api/chat/history — clear conversation history for the session (auth required)

Both routes require a valid JWT bearer token. Without auth, any bot that
discovers the URL can run up OpenAI charges indefinitely.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from datetime import timezone

UTC = timezone.utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["AI Chat"])

# ── request / response models ─────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096, description="User message")
    session_id: str | None = Field(
        None,
        description="Optional session ID for history isolation",
    )


class ChatResponse(BaseModel):
    response: str
    session_id: str | None = None


# ── per-session agent cache ───────────────────────────────────────────────────
# Agents are lightweight (just conversation history + OpenAI client).
# One agent per session_id keeps histories isolated between users/tabs.

_agents: dict[str, object] = {}


def _get_agent(session_id: str | None = None):
    """Return (or create) an LLMAgent for the given session."""
    try:
        from brain.llm_agent import LLMAgent
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LLM agent module unavailable: {exc}",
        ) from exc

    key = session_id or "__default__"
    if key not in _agents:
        _agents[key] = LLMAgent()
    return _agents[key], key


# ── routes ────────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ChatResponse,
    summary="Send a message to the AI assistant",
)
async def ai_chat(
    body: ChatRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Send a free-form message to the HOPEFX AI assistant.

    The assistant maintains conversation history per session_id so
    follow-up questions have full context. If no session_id is provided
    all requests share a single default history per authenticated user.

    Requires a valid JWT bearer token and OPENAI_API_KEY in the environment.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured. Set it in your .env file.",
        )

    # Scope session key to the authenticated user so histories never bleed
    # across accounts even when callers omit session_id.
    session_key = f"{user.sub}:{body.session_id}" if body.session_id else user.sub
    agent, key = _get_agent(session_key)

    try:
        response_text = await agent.chat(body.message)
    except Exception as exc:
        logger.error("LLM chat error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI response failed: {exc}",
        ) from exc

    return ChatResponse(response=response_text, session_id=key)


@router.delete("/history", summary="Clear conversation history for a session")
async def clear_chat_history(
    session_id: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Clear the conversation history for the given session_id (or the
    default session if none is provided). The next message will start
    a fresh conversation. Only clears history owned by the authenticated user.
    """
    key = f"{user.sub}:{session_id}" if session_id else user.sub
    if key in _agents:
        try:
            _agents[key]._history = []
        except Exception as exc:
            logger.debug("Chat history clear failed for session %s: %s", key, exc)
        del _agents[key]
    return {"cleared": True, "session_id": key}


@router.get("/status", summary="AI chat readiness check")
async def chat_status(user: TokenPayload = Depends(get_current_user)):
    """
    Return the readiness state of the AI chat endpoint.

    Checks:
    - OPENAI_API_KEY is configured
    - LLMAgent module is importable
    - OpenAI model name in use
    - Active session count for the authenticated user

    Does not make a live API call — purely a configuration check.
    Any authenticated user may call this.
    """
    from datetime import datetime

    api_key_set = bool(os.getenv("OPENAI_API_KEY", ""))
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    llm_available = False
    llm_error: str | None = None
    try:
        from brain.llm_agent import LLMAgent

        llm_available = True
    except ImportError as exc:
        logger.debug("LLM agent import failed: %s", exc)
        llm_error = "LLM agent unavailable — check server logs"

    # Count active sessions for this user
    user_sessions = [k for k in _agents if k.startswith(f"{user.sub}:") or k == user.sub]

    ready = api_key_set and llm_available

    return {
        "ready": ready,
        "api_key_configured": api_key_set,
        "llm_available": llm_available,
        "model": model,
        "active_sessions": len(user_sessions),
        "max_history_turns": int(os.getenv("CHAT_MAX_HISTORY_TURNS", "20")),
        "error": llm_error,
        "checked_at": datetime.now(UTC).isoformat(),
    }
