# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Vendor adapters can hand back an answer in pieces.

Four wire formats, one interface. Anthropic and OpenAI speak SSE with different
event shapes, Google speaks SSE with a third, and Ollama speaks newline-delimited
JSON. Getting any of them subtly wrong shows up as an answer that renders
half-empty, so each one is exercised against a recorded transcript here.

Two properties carry more weight than the parsing:

* **`supports_streaming` is False by default**, so a vendor that has not been
  taught to stream is not handed a streaming request and asked to cope. Same
  fail-closed default as `supports_images`.
* **A stream that dies mid-body is a transport failure**, reported with a reason
  `should_fall_through` understands. It must not surface as an empty answer,
  which would be cached, charged for and acted on as a decision.

These tests fail on the pre-fix tree — no adapter has a `stream` method there.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


class _FakeStream:
    """Stands in for the context manager `httpx.stream` returns."""

    def __init__(self, lines: list[str], *, status: int = 200, explode_at: int | None = None) -> None:
        self._lines = lines
        self.status_code = status
        self._explode_at = explode_at

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def iter_lines(self):
        for i, line in enumerate(self._lines):
            if self._explode_at is not None and i == self._explode_at:
                import httpx

                raise httpx.ReadError("connection reset mid-stream")
            yield line


@pytest.fixture
def wire(monkeypatch):
    """Install a recorded transcript in place of the network."""
    captured: dict[str, Any] = {}

    def install(lines, *, status=200, explode_at=None):
        def fake_stream(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            captured["headers"] = kwargs.get("headers")
            return _FakeStream(lines, status=status, explode_at=explode_at)

        import httpx

        monkeypatch.setattr(httpx, "stream", fake_stream)
        return captured

    return install


def _text(chunks) -> str:
    return "".join(c.text for c in chunks)


# ── the fail-closed default ───────────────────────────────────────────────────


def test_an_adapter_does_not_claim_to_stream_unless_it_was_taught_to():
    from ai.gateway.adapters import _HttpAdapter

    assert _HttpAdapter.supports_streaming is False


def test_the_vendors_that_were_taught_say_so():
    from ai.gateway.adapters import AnthropicAdapter, GoogleAdapter, OllamaAdapter, OpenAIAdapter

    for adapter in (AnthropicAdapter, OpenAIAdapter, GoogleAdapter, OllamaAdapter):
        assert adapter.supports_streaming is True, f"{adapter.__name__} does not stream"


# ── the four wire formats ─────────────────────────────────────────────────────


def test_anthropic_deltas_and_usage(wire, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    wire(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"usage":{"input_tokens":31}}}',
            "",
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Gold is "}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"range-bound."}}',
            'data: {"type":"message_delta","usage":{"output_tokens":12}}',
            'data: {"type":"message_stop"}',
        ]
    )
    from ai.gateway.adapters import AnthropicAdapter

    chunks = list(AnthropicAdapter().stream(model="claude-opus-5", prompt="p", timeout_s=5))
    assert _text(chunks) == "Gold is range-bound."
    assert sum(c.tokens_in for c in chunks) == 31
    assert sum(c.tokens_out for c in chunks) == 12


def test_openai_deltas_and_the_done_sentinel(wire, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = wire(
        [
            'data: {"choices":[{"delta":{"content":"Gold "}}]}',
            'data: {"choices":[{"delta":{"content":"is thin."}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":9}}',
            "data: [DONE]",
            'data: {"choices":[{"delta":{"content":"AFTER THE END"}}]}',
        ]
    )
    from ai.gateway.adapters import OpenAIAdapter

    chunks = list(OpenAIAdapter().stream(model="gpt-5.5", prompt="p", timeout_s=5))
    assert _text(chunks) == "Gold is thin."
    assert "AFTER THE END" not in _text(chunks), "[DONE] did not stop the stream"
    assert sum(c.tokens_out for c in chunks) == 9
    # Usage only arrives if it is asked for.
    assert captured["json"].get("stream") is True
    assert captured["json"].get("stream_options", {}).get("include_usage") is True


def test_google_sse(wire, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    captured = wire(
        [
            'data: {"candidates":[{"content":{"parts":[{"text":"Range "}]}}]}',
            'data: {"candidates":[{"content":{"parts":[{"text":"bound."}]}}],'
            '"usageMetadata":{"promptTokenCount":11,"candidatesTokenCount":4}}',
        ]
    )
    from ai.gateway.adapters import GoogleAdapter

    chunks = list(GoogleAdapter().stream(model="gemini-3.1-pro", prompt="p", timeout_s=5))
    assert _text(chunks) == "Range bound."
    assert sum(c.tokens_in for c in chunks) == 11
    assert "streamGenerateContent" in captured["url"]
    assert "alt=sse" in captured["url"]


def test_ollama_ndjson(wire, monkeypatch):
    captured = wire(
        [
            '{"response":"Local ","done":false}',
            '{"response":"answer.","done":true,"prompt_eval_count":7,"eval_count":3}',
        ]
    )
    from ai.gateway.adapters import OllamaAdapter

    chunks = list(OllamaAdapter().stream(model="llama3", prompt="p", timeout_s=5))
    assert _text(chunks) == "Local answer."
    assert captured["json"].get("stream") is True


def test_an_openai_compatible_vendor_streams_too(wire, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    wire(['data: {"choices":[{"delta":{"content":"hi"}}]}', "data: [DONE]"])
    from ai.gateway.adapters import build_providers

    adapters = build_providers()
    groq = adapters.get("groq")
    if groq is None:
        pytest.skip("groq is not in the vendor table for this deployment")
    assert groq.supports_streaming is True
    assert _text(list(groq.stream(model="llama-3.3-70b", prompt="p", timeout_s=5))) == "hi"


# ── failure has to look like failure ──────────────────────────────────────────


def test_a_stream_that_dies_mid_body_is_a_transport_failure(wire, monkeypatch):
    """Not an empty answer. An empty completion gets cached, charged for and
    acted on as a decision — which is why `_require_text` exists on the
    non-streaming path."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    wire(
        [
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Gold is "}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"never"}}',
        ],
        explode_at=1,
    )
    from ai.gateway.adapters import AnthropicAdapter
    from ai.gateway.client import ProviderError
    from ai.gateway.chain import should_fall_through

    with pytest.raises(ProviderError) as exc:
        list(AnthropicAdapter().stream(model="claude-opus-5", prompt="p", timeout_s=5))
    assert should_fall_through(exc.value.reason), f"{exc.value.reason} does not reach the next leg"


def test_a_rate_limit_on_the_stream_maps_to_the_same_reason_as_a_post(wire, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    wire([], status=429)
    from ai.gateway.adapters import AnthropicAdapter
    from ai.gateway.client import ProviderError

    with pytest.raises(ProviderError) as exc:
        list(AnthropicAdapter().stream(model="claude-opus-5", prompt="p", timeout_s=5))
    assert exc.value.reason == "rate_limited"


def test_a_malformed_line_is_skipped_rather_than_fatal(wire, monkeypatch):
    """A keep-alive comment or a truncated frame must not lose the answer."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    wire(
        [
            ": keep-alive",
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"still "}}',
            "data: {not json at all",
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"here"}}',
        ]
    )
    from ai.gateway.adapters import AnthropicAdapter

    assert _text(list(AnthropicAdapter().stream(model="claude-opus-5", prompt="p", timeout_s=5))) == "still here"


def test_an_empty_stream_is_reported_not_returned(wire, monkeypatch):
    """Zero deltas is the streaming form of `empty_completion`."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    wire(['data: {"type":"message_stop"}'])
    from ai.gateway.adapters import AnthropicAdapter
    from ai.gateway.client import ProviderError

    with pytest.raises(ProviderError) as exc:
        list(AnthropicAdapter().stream(model="claude-opus-5", prompt="p", timeout_s=5))
    assert exc.value.reason == "empty_completion"
