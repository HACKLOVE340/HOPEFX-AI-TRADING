"""Regression tests for the api/brain.py raw-LLM endpoints.

Locks in three fixes:

1. **API-key leak.** ``_detect_llm_backend()`` returns (backend, api_key), but
   /brain/health, /brain/complete and /brain/embed unpacked it as
   (backend, model) — so /brain/health returned the raw ANTHROPIC/OPENAI API
   key to the browser as the "model" field, and /brain/complete passed the key
   as the OpenAI model name (failing every call with a 502).

2. **Anthropic support.** The platform's primary backend is Anthropic
   (generate-strategy and chat both use it via LLMAgent), yet the raw
   endpoints only had openai/ollama branches — with ANTHROPIC_API_KEY set
   they returned 503 "No LLM backend configured".

3. **Honest fallbacks.** Anthropic has no embeddings API; /brain/embed now
   falls through to OpenAI/Ollama or 503s with an accurate message.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import TokenPayload, get_current_user

SECRET_KEY = "sk-ant-VERY-SECRET-KEY-do-not-leak"  # pragma: allowlist secret


@pytest.fixture()
def client() -> TestClient:
    from api.brain import router as brain_router

    app = FastAPI()
    _user = TokenPayload(sub="test-user", role="trader")
    app.dependency_overrides[get_current_user] = lambda: _user
    app.include_router(brain_router)
    return TestClient(app, raise_server_exceptions=False)


class TestRuntimeDetection:
    def test_anthropic_key_maps_to_model_name_not_key(self, monkeypatch):
        from api.brain import _detect_llm_runtime

        monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        backend, model = _detect_llm_runtime()
        assert backend == "anthropic"
        assert model and SECRET_KEY not in model

    def test_openai_key_maps_to_model_name_not_key(self, monkeypatch):
        from api.brain import _detect_llm_runtime

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", SECRET_KEY)
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        backend, model = _detect_llm_runtime()
        assert backend == "openai"
        assert model and SECRET_KEY not in model

    def test_ollama_fallback_when_no_cloud_keys(self, monkeypatch):
        from api.brain import _detect_llm_runtime

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
        backend, model = _detect_llm_runtime()
        assert backend == "ollama"
        assert model

    def test_no_backend_when_nothing_configured(self, monkeypatch):
        from api.brain import _detect_llm_runtime

        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_BASE_URL", "LLM_BACKEND"):
            monkeypatch.delenv(var, raising=False)
        assert _detect_llm_runtime() == (None, None)


class TestHealthNeverLeaksKey:
    def test_health_response_does_not_contain_api_key(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        # Whatever the probe outcome (network may be unavailable), the key
        # must never appear anywhere in the response.
        resp = client.get("/api/brain/health")
        assert resp.status_code == 200
        assert SECRET_KEY not in resp.text
        data = resp.json()
        assert data["backend"] == "anthropic"
        assert data["model"] and SECRET_KEY not in str(data["model"])

    def test_health_no_backend_gives_actionable_detail(self, client, monkeypatch):
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_BASE_URL", "LLM_BACKEND"):
            monkeypatch.delenv(var, raising=False)
        resp = client.get("/api/brain/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert "ANTHROPIC_API_KEY" in (data["detail"] or "")


class TestCompleteAnthropicBranch:
    def test_complete_uses_anthropic_when_configured(self, client, monkeypatch):
        import api.brain as brain_mod

        monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)

        class _FakeResp:
            status_code = 200

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {
                    "content": [{"type": "text", "text": "hello from claude"}],
                    "usage": {"input_tokens": 3, "output_tokens": 5},
                }

        class _FakeAsyncClient:
            def __init__(self, *a, **k): ...

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, **kwargs):
                # the key goes in the header, never as the model
                assert kwargs["json"]["model"] and SECRET_KEY not in kwargs["json"]["model"]
                assert kwargs["headers"]["x-api-key"] == SECRET_KEY
                return _FakeResp()

        import httpx

        with (
            patch.object(brain_mod, "_detect_llm_runtime", return_value=("anthropic", "claude-sonnet-4-6")),
            patch.object(httpx, "AsyncClient", _FakeAsyncClient),
        ):
            resp = client.post("/api/brain/complete", json={"prompt": "hi"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "hello from claude"
        assert data["backend"] == "anthropic"
        assert SECRET_KEY not in resp.text

    def test_complete_503_mentions_all_backends(self, client, monkeypatch):
        import api.brain as brain_mod

        with patch.object(brain_mod, "_detect_llm_runtime", return_value=(None, None)):
            resp = client.post("/api/brain/complete", json={"prompt": "hi"})
        assert resp.status_code == 503
        assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


class TestEmbedAnthropicFallback:
    def test_embed_anthropic_without_embedding_backend_503s_accurately(self, client, monkeypatch):
        import api.brain as brain_mod

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        with patch.object(brain_mod, "_detect_llm_runtime", return_value=("anthropic", "claude-sonnet-4-6")):
            resp = client.post("/api/brain/embed", json={"input": "text"})
        assert resp.status_code == 503
        assert "no embeddings API" in resp.json()["detail"]
