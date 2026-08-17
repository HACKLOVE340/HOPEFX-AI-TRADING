# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/voice.py
============
Optional **cloud** voice endpoints — server-side text-to-speech (TTS) and
speech-to-text (STT) behind an API key. The frontend uses the browser-native
Web Speech API by default and only calls these when ``GET /api/voice/status``
reports a cloud provider is configured; otherwise it falls back to Web Speech.

This is purely an I/O convenience layer: it moves no money and places no orders.
Spoken trading *commands* are parsed and confirmed in the browser and routed
through the existing, invariant-gated ``/api/trading`` endpoints — never here.

Routes
------
GET  /api/voice/status  — which cloud providers (if any) are configured (auth)
POST /api/voice/tts     — text -> audio bytes (auth; 503 when no provider)
POST /api/voice/stt     — audio file -> transcript (auth; 503 when no provider)

Providers (selected automatically by which key is set):
  - TTS: ElevenLabs (``ELEVENLABS_API_KEY``) or OpenAI (``OPENAI_API_KEY``)
  - STT: OpenAI Whisper (``OPENAI_API_KEY``)

Every route requires a valid JWT bearer token so anonymous callers cannot run up
provider charges.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from core.ai_quota import ai_quota

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["Voice"])

# Upper bound on inputs so a misbehaving client cannot send huge payloads to a
# metered provider. Generous enough for normal chat/alert text and short clips.
_MAX_TTS_CHARS = 2000
_MAX_STT_BYTES = 10 * 1024 * 1024  # 10 MB

_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
_OPENAI_STT_URL = "https://api.openai.com/v1/audio/transcriptions"
_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# ElevenLabs "Rachel" — a stable default public voice id.
_ELEVENLABS_DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"

_HTTP_TIMEOUT = 30.0


# ── models ────────────────────────────────────────────────────────────────────
class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=_MAX_TTS_CHARS)
    voice: str | None = Field(None, max_length=64, description="Provider voice id/name")


class VoiceStatus(BaseModel):
    tts_available: bool
    stt_available: bool
    tts_provider: str | None = None
    stt_provider: str | None = None


# ── provider selection (read env lazily so tests can monkeypatch) ───────────────
def _elevenlabs_key() -> str:
    return (os.getenv("ELEVENLABS_API_KEY") or "").strip()


def _openai_key() -> str:
    return (os.getenv("OPENAI_API_KEY") or "").strip()


def _tts_provider() -> str | None:
    if _elevenlabs_key():
        return "elevenlabs"
    if _openai_key():
        return "openai"
    return None


def _stt_provider() -> str | None:
    return "openai" if _openai_key() else None


# ── routes ──────────────────────────────────────────────────────────────────────
@router.get("/status", response_model=VoiceStatus)
async def voice_status(_user: TokenPayload = Depends(get_current_user)) -> VoiceStatus:
    """Report which cloud voice providers are configured. The frontend uses this
    to decide whether to call the cloud routes or fall back to Web Speech."""
    tts = _tts_provider()
    stt = _stt_provider()
    return VoiceStatus(
        tts_available=tts is not None,
        stt_available=stt is not None,
        tts_provider=tts,
        stt_provider=stt,
    )


@router.post("/tts")
async def tts(
    req: TTSRequest,
    _user: TokenPayload = Depends(ai_quota(feature="voice")),
) -> Response:
    """Synthesize ``req.text`` to speech and return the audio bytes. Returns 503
    when no cloud provider is configured so the client falls back to Web Speech."""
    provider = _tts_provider()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No cloud TTS provider configured; use browser Web Speech instead.",
        )

    import httpx

    try:
        if provider == "elevenlabs":
            voice_id = (req.voice or _ELEVENLABS_DEFAULT_VOICE).strip()
            url = _ELEVENLABS_TTS_URL.format(voice_id=voice_id)
            headers = {"xi-api-key": _elevenlabs_key(), "accept": "audio/mpeg"}
            payload = {"text": req.text, "model_id": "eleven_turbo_v2"}
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=payload)
        else:  # openai
            headers = {"Authorization": f"Bearer {_openai_key()}"}
            payload = {"model": "tts-1", "voice": (req.voice or "alloy"), "input": req.text}
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(_OPENAI_TTS_URL, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("Cloud TTS request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cloud TTS provider request failed.",
        ) from None

    if resp.status_code != 200:
        logger.warning("Cloud TTS provider %s returned %s", provider, resp.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Cloud TTS provider error ({resp.status_code}).",
        )
    return Response(content=resp.content, media_type="audio/mpeg")


@router.post("/stt")
async def stt(
    audio: UploadFile = File(...),
    _user: TokenPayload = Depends(ai_quota(feature="voice")),
) -> dict[str, str]:
    """Transcribe an uploaded audio clip to text via OpenAI Whisper. Returns 503
    when no provider is configured so the client falls back to Web Speech."""
    provider = _stt_provider()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No cloud STT provider configured; use browser Web Speech instead.",
        )

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio upload.")
    if len(data) > _MAX_STT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio clip too large.",
        )

    import httpx

    try:
        headers = {"Authorization": f"Bearer {_openai_key()}"}
        files = {"file": (audio.filename or "audio.webm", data, audio.content_type or "audio/webm")}
        form = {"model": "whisper-1"}
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(_OPENAI_STT_URL, headers=headers, data=form, files=files)
    except httpx.HTTPError as exc:
        logger.warning("Cloud STT request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cloud STT provider request failed.",
        ) from None

    if resp.status_code != 200:
        logger.warning("Cloud STT provider returned %s", resp.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Cloud STT provider error ({resp.status_code}).",
        )
    try:
        text = str(resp.json().get("text", "")).strip()
    except (ValueError, AttributeError):
        text = ""
    return {"text": text}
