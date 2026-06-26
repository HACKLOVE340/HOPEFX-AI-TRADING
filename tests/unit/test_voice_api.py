# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_voice_api.py
============================
Unit tests for api/voice.py — optional cloud TTS/STT endpoints.

Covers:
  - GET  /api/voice/status — reports provider availability from env keys
  - POST /api/voice/tts    — 503 when no provider; 200 audio when key set
  - POST /api/voice/stt    — 503 when no provider; 200 transcript when key set

No real network calls: httpx.AsyncClient.post is patched. The point is that the
routes never move money, always require auth, and degrade to 503 (→ frontend
falls back to Web Speech) when unconfigured.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "unit-test-voice-secret-key-32chars!!!!")

from api.auth import TokenPayload, get_current_user
from api.voice import router as voice_router

pytestmark = pytest.mark.unit


def _client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="voice-user", role="trader")
    app.include_router(voice_router)
    return TestClient(app)


class _FakeResp:
    def __init__(self, status_code: int, content: bytes = b"", payload: dict[str, Any] | None = None):
        self.status_code = status_code
        self.content = content
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture()
def _no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# ── status ──────────────────────────────────────────────────────────────────────
def test_status_no_provider(_no_keys: None) -> None:
    r = _client().get("/api/voice/status")
    assert r.status_code == 200
    body = r.json()
    assert body["tts_available"] is False
    assert body["stt_available"] is False
    assert body["tts_provider"] is None


def test_status_openai(monkeypatch: pytest.MonkeyPatch, _no_keys: None) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    body = _client().get("/api/voice/status").json()
    assert body["tts_available"] is True
    assert body["stt_available"] is True
    assert body["tts_provider"] == "openai"
    assert body["stt_provider"] == "openai"


def test_status_prefers_elevenlabs_for_tts(monkeypatch: pytest.MonkeyPatch, _no_keys: None) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    body = _client().get("/api/voice/status").json()
    assert body["tts_provider"] == "elevenlabs"  # ElevenLabs wins for TTS
    assert body["stt_provider"] == "openai"  # STT is OpenAI-only


# ── tts ───────────────────────────────────────────────────────────────────────
def test_tts_503_without_provider(_no_keys: None) -> None:
    r = _client().post("/api/voice/tts", json={"text": "hello"})
    assert r.status_code == 503


def test_tts_returns_audio_with_key(monkeypatch: pytest.MonkeyPatch, _no_keys: None) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake = AsyncMock(return_value=_FakeResp(200, content=b"ID3audio"))
    with patch("httpx.AsyncClient.post", fake):
        r = _client().post("/api/voice/tts", json={"text": "hello world"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3audio"


def test_tts_provider_error_maps_to_502(monkeypatch: pytest.MonkeyPatch, _no_keys: None) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake = AsyncMock(return_value=_FakeResp(401, content=b""))
    with patch("httpx.AsyncClient.post", fake):
        r = _client().post("/api/voice/tts", json={"text": "hi"})
    assert r.status_code == 502


def test_tts_rejects_empty_text(monkeypatch: pytest.MonkeyPatch, _no_keys: None) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    r = _client().post("/api/voice/tts", json={"text": ""})
    assert r.status_code == 422  # pydantic min_length


# ── stt ───────────────────────────────────────────────────────────────────────
def test_stt_503_without_provider(_no_keys: None) -> None:
    r = _client().post("/api/voice/stt", files={"audio": ("a.webm", b"bytes", "audio/webm")})
    assert r.status_code == 503


def test_stt_returns_transcript_with_key(monkeypatch: pytest.MonkeyPatch, _no_keys: None) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake = AsyncMock(return_value=_FakeResp(200, payload={"text": "buy one lot gold"}))
    with patch("httpx.AsyncClient.post", fake):
        r = _client().post("/api/voice/stt", files={"audio": ("a.webm", b"bytes", "audio/webm")})
    assert r.status_code == 200
    assert r.json()["text"] == "buy one lot gold"


def test_stt_rejects_empty_upload(monkeypatch: pytest.MonkeyPatch, _no_keys: None) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    r = _client().post("/api/voice/stt", files={"audio": ("a.webm", b"", "audio/webm")})
    assert r.status_code == 400
