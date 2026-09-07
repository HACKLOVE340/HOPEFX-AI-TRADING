# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Voice — §11's voice agent: recognition, synthesis, turn management. Read-only.

## It reports configuration, never credentials

The providers behind `api/voice.py` are configured with API keys. "Is
ElevenLabs available" is answerable without any of them leaving the process,
and it has to be: an agent result lands in department memory and is fenced back
into a model later, so a key that reached one of these dictionaries would have
several onward paths and no way back.

So `voice_status` reads whether each key is *set* and returns a boolean. There
is no code path here that can put a key value into a result, which is a stronger
property than remembering to redact one.

## It cannot speak

Every action is read-only. A voice agent that could synthesise on its own
initiative is a system that can talk to somebody who did not ask it to, and that
is a different risk tier and a different review — `ConversationTurn` on the
frontend decides when the AI speaks, from a user gesture.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _default_keys() -> dict[str, str]:
    from api.voice import _elevenlabs_key, _openai_key

    return {"elevenlabs": _elevenlabs_key(), "openai": _openai_key()}


def voice_status(*, keys: Callable[[], dict[str, str]] | None = None, **_: Any) -> dict[str, Any]:
    """Which synthesis and recognition providers this deployment can reach.

    Booleans only. The values are read to test for emptiness and are never
    placed in the returned structure.
    """
    try:
        configured = (keys or _default_keys)()
    except Exception as exc:
        logger.info("ai.departments.voice: provider configuration unreadable: %s", exc)
        return {"available": False, "reason": str(exc)}

    return {
        "available": True,
        # `bool(...)` at the boundary, so no branch below can carry a value.
        "providers": {name: bool(value and value.strip()) for name, value in configured.items()},
        "fallback": "Web Speech in the browser, when no provider is configured.",
    }


def turn_policy(**_: Any) -> dict[str, Any]:
    """The turn-taking rules this deployment actually enforces (§17).

    Described from the rules `frontend/src/hub/conversation.ts` implements, not
    from what a voice assistant usually does. Reporting a policy nothing
    enforces would be a description of a different system, and an operator
    reading it would plan around behaviour they do not have.
    """
    return {
        "available": True,
        "rules": [
            "Barge-in cancels synthesis immediately — not at the end of the sentence.",
            "Listening outranks speaking: if both are true the user has interrupted.",
            "An interruption is remembered, so the next turn knows it was cut off.",
            "Muting changes the audio, never the transcript.",
            "Disposal stops the microphone; capture never outlives the surface.",
        ],
        "enforced_by": "frontend/src/hub/conversation.ts",
    }


__all__ = ["turn_policy", "voice_status"]
