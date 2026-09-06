# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The vendor adapters — the only code in this repository that talks to a model.

The gateway existed before this module and nothing reached a vendor through it:
routing, budget, fall-through and audit were all built around a `Provider`
protocol that only tests implemented, while `api/brain.py` and
`brain/llm_agent.py` called Anthropic, OpenAI and Ollama inline. Controls that
are real and bypassed are this audit's signature defect, so the adapters live
here and the callers were moved onto them.

Two decisions carry most of the weight:

**The reason code.** `chain.should_fall_through` obeys it exactly. A 401 is
mapped to `provider_unavailable` and DOES fall through -- a leg that cannot
authenticate cannot serve, and a second vendor can answer the same question. A
400 is mapped to `bad_request` and does NOT -- the request is malformed and
every leg will reject it identically, so retrying launders one failure into a
slower one. An exception this module does not recognise is `adapter_error`,
never a guessed "timeout": guessing retryable turns one bug into three calls.

**Pricing errs high.** An unpriced model is charged at the highest known rate
rather than at zero. A ceiling that under-counts is not a ceiling, and the worst
case of over-estimating is a call refused early -- which is the safe direction
for a control that exists to stop money leaving.

No adapter returns, logs, or embeds its credential. Failures carry the vendor's
status and our reason code, never the key that authenticated the request.
"""

from __future__ import annotations

import json as _json
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final

import httpx

from ai.gateway.client import ProviderError

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS: Final = 2048

# HTTP status boundaries, named so the mapping below reads as the decision it is.
_TOO_MANY_REQUESTS: Final = 429
_SERVER_ERROR: Final = 500
_CLIENT_ERROR: Final = 400
_AUTH_FAILURES: Final = (401, 403)

#: USD per million tokens: (input, output). Rates are data and go stale; the
#: catalogue in docs/ai/MODEL_CATALOGUE.md carries the review date, and an
#: unpriced model is charged at the highest rate here rather than at zero.
PRICING: Final[dict[str, tuple[float, float]]] = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
    "gpt-5.5": (10.0, 30.0),
    "gemini-3.1-pro": (2.50, 10.0),
    "gemini-3.5-flash": (0.30, 2.50),
    "text-embedding-3-large": (0.13, 0.0),
    "gemini-embedding": (0.15, 0.0),
}

#: Providers billed by someone else's hardware. Local inference has no vendor
#: bill, so charging it against a spend ceiling would refuse calls that cost
#: nothing.
FREE_PROVIDERS: Final[frozenset[str]] = frozenset({"ollama"})


@dataclass(frozen=True)
class EmbeddingResult:
    """What the gateway reads off an embeddings answer."""

    vectors: list[list[float]]
    tokens_in: int = 0
    cost_usd: float = 0.0
    dimensions: int = 0


@dataclass(frozen=True)
class StreamChunk:
    """One piece of an answer that is still arriving.

    Text and usage travel together because the vendors interleave them: OpenAI
    sends usage in a final frame with no content, Anthropic sends input tokens
    first and output tokens last. Summing both fields across the stream gives
    the same numbers `AdapterResult` carries, which is what the budget charges
    and the audit records — a streamed call must cost what a buffered one costs.
    """

    text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class AdapterResult:
    """What the gateway reads off a provider's answer."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


# ── reason mapping ────────────────────────────────────────────────────────────


def reason_for_status(status: int) -> str:
    """Map an HTTP status to a reason code `should_fall_through` understands."""
    if status == _TOO_MANY_REQUESTS:
        return "rate_limited"
    if status >= _SERVER_ERROR:
        return "server_error"
    if status in _AUTH_FAILURES:
        # A credential fault is a leg that cannot serve, not an answer about the
        # question. Falling through reaches a vendor that can answer it.
        return "provider_unavailable"
    if status >= _CLIENT_ERROR:
        return "bad_request"
    return "server_error"


def reason_for_exception(exc: BaseException) -> str:
    """Map a transport exception to a reason code.

    Anything unrecognised is `adapter_error`, which does NOT fall through. An
    exception this module has not been taught is not evidence that retrying is
    safe.
    """
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.TransportError):
        return "connection_error"
    return "adapter_error"


def estimate_cost(model: str, *, tokens_in: int, tokens_out: int, provider: str = "") -> float:
    """USD for a call. Unpriced models are charged high, never free."""
    if provider in FREE_PROVIDERS:
        return 0.0
    rates = PRICING.get(model)
    if rates is None:
        # Conservative: the highest rate we know of. Under-counting spend is the
        # failure mode that matters; over-counting only refuses a call early.
        rates = (
            max(rate[0] for rate in PRICING.values()),
            max(rate[1] for rate in PRICING.values()),
        )
        logger.warning(
            "ai.gateway.adapters: %r is not in PRICING; charging at the highest known rate. "
            "Add it to PRICING and to docs/ai/MODEL_CATALOGUE.md.",
            model,
        )
    return (tokens_in / 1_000_000) * rates[0] + (tokens_out / 1_000_000) * rates[1]


def _raise_for_status(response: Any, *, provider: str, model: str) -> None:
    status = int(getattr(response, "status_code", 0) or 0)
    if status >= _CLIENT_ERROR:
        # The vendor's body can echo the request; the status and our reason code
        # are enough to act on, and neither can carry the key.
        raise ProviderError(reason_for_status(status), provider=provider, model=model)


def _sse_payloads(lines: Iterator[str]) -> Iterator[dict]:
    """Decode `data:` frames from an SSE body, skipping what is not one.

    Keep-alive comments (`: ping`), blank separators, `event:` names and the
    OpenAI `[DONE]` sentinel are all normal traffic. A truncated or malformed
    frame is skipped rather than raised on: losing one delta is a worse answer,
    losing the whole answer to a stray byte is an outage.
    """
    for raw in lines:
        line = (raw or "").strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if not body or body == "[DONE]":
            if body == "[DONE]":
                return
            continue
        try:
            payload = _json.loads(body)
        except ValueError:
            logger.debug("ai.gateway.adapters: skipped a malformed stream frame")
            continue
        if isinstance(payload, dict):
            yield payload


def _openai_stream_body(model: str, prompt: str) -> dict:
    """The streaming request body every OpenAI-format vendor takes.

    `stream_options.include_usage` is the only way usage arrives at all on this
    format — without it the final frame has no token counts and a streamed call
    would be charged zero, which is a spend ceiling that stops seeing spend.
    """
    return {
        "model": model,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def _openai_stream_chunks(payloads: Iterator[dict]) -> Iterator[StreamChunk]:
    """Decode OpenAI-format deltas. Shared by OpenAI and every compatible vendor."""
    for payload in payloads:
        choices = payload.get("choices") or []
        if choices:
            text = str((choices[0].get("delta", {}) or {}).get("content") or "")
            if text:
                yield StreamChunk(text=text)
        usage = payload.get("usage") or {}
        if usage:
            yield StreamChunk(
                tokens_in=int(usage.get("prompt_tokens", 0) or 0),
                tokens_out=int(usage.get("completion_tokens", 0) or 0),
            )


def _require_streamed(saw_text: bool, *, provider: str, model: str) -> None:
    """A stream that yielded no text is the streaming form of an empty answer.

    `_require_text` guards the buffered path for the same reason: an empty
    completion would be scanned clean, cached, charged for and shown to an
    operator as though the model had answered.
    """
    if not saw_text:
        raise ProviderError("empty_completion", provider=provider, model=model)


def _require_text(text: str, *, provider: str, model: str) -> str:
    if not text.strip():
        # An empty completion would be cached, charged for, and acted on as if
        # it were a decision.
        raise ProviderError("empty_completion", provider=provider, model=model)
    return text


# ── adapters ──────────────────────────────────────────────────────────────────


class _HttpAdapter:
    """Shared transport handling so each vendor only owns its own shapes."""

    provider: str = ""

    #: Whether this vendor can be handed an image. Defaults to False so a new
    #: adapter is skipped for vision rather than silently handed a prompt about
    #: a picture it cannot see — the same fail-closed default the tool bus uses
    #: for an unregistered tool. Opting in is one line; opting out by omission
    #: would be a confident answer about nothing.
    supports_images: bool = False

    #: Whether this vendor can hand its answer back in pieces. False by default
    #: for the same reason `supports_images` is: a vendor that has not been
    #: taught the wire format should be left on the buffered path, where it
    #: works, rather than handed a streaming request and asked to cope. The
    #: gateway degrades to `complete()` for these rather than skipping the leg.
    supports_streaming: bool = False

    def _stream_lines(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict,
        timeout_s: float,
        model: str,
    ) -> Iterator[str]:
        """Yield response lines, mapping failures the way `_post` does.

        A stream can fail in two places rather than one: on the status, like any
        request, and part-way through the body, after the status said 200. The
        second is the interesting case — without this it surfaces as a SHORT
        ANSWER rather than as an error, and a short answer gets scanned, cached,
        charged for and rendered as though the model had finished speaking.
        """
        try:
            with httpx.stream("POST", url, headers=headers, json=json, timeout=timeout_s) as response:
                _raise_for_status(response, provider=self.provider, model=model)
                yield from response.iter_lines()
        except ProviderError:
            raise
        except Exception as exc:
            reason = reason_for_exception(exc)
            # Not chained with `from exc`: the vendor exception's string can
            # contain the request headers, and those carry the key.
            logger.warning("ai.gateway.adapters: %s stream failed (%s)", self.provider, reason)
            raise ProviderError(reason, provider=self.provider, model=model) from None

    def _post(self, url: str, *, headers: dict[str, str], json: dict, timeout_s: float, model: str) -> Any:
        try:
            response = httpx.post(url, headers=headers, json=json, timeout=timeout_s)
        except ProviderError:
            raise
        except Exception as exc:
            reason = reason_for_exception(exc)
            # Deliberately not chained with `from exc`: the vendor exception's
            # string can contain the request headers, and those carry the key.
            logger.warning("ai.gateway.adapters: %s transport failure (%s)", self.provider, reason)
            raise ProviderError(reason, provider=self.provider, model=model) from None
        _raise_for_status(response, provider=self.provider, model=model)
        return response

    def embed(self, *, model: str, texts: list[str], timeout_s: float) -> EmbeddingResult:
        """Vendors without an embeddings API report a leg that cannot serve.

        `provider_unavailable` rather than an error, so the chain moves to a
        vendor that CAN embed instead of failing the request -- which is what
        api/brain.py used to do by hand, with an inline `if OPENAI_API_KEY`.
        """
        raise ProviderError("provider_unavailable", provider=self.provider, model=model)

    #: A cheap, side-effect-free endpoint that proves the credential works.
    probe_url: str = ""

    def probe_headers(self) -> dict[str, str]:
        return {}

    def probe(self, *, timeout_s: float = 5.0) -> tuple[bool, str]:
        """(reachable, detail). A real request, not a config read.

        `GET /models/health` used to answer `provider_call: not_performed` --
        a health check that never checked. What it costs is one list call; what
        it buys is the difference between "a key is set" and "the key works".
        """
        if not self.probe_url:
            return False, f"{self.provider} exposes no probe endpoint"
        try:
            response = httpx.get(self.probe_url, headers=self.probe_headers(), timeout=timeout_s)
        except Exception as exc:
            # The vendor exception can echo request headers; report our reason.
            return False, f"{self.provider} unreachable ({reason_for_exception(exc)})"
        status = int(getattr(response, "status_code", 0) or 0)
        if status == HTTPStatus.OK:
            return True, ""
        return False, f"{self.provider} returned HTTP {status} ({reason_for_status(status)})"


def _require_vectors(vectors: list[list[float]], *, provider: str, model: str) -> list[list[float]]:
    if not vectors or not any(vectors):
        # A zero-length vector poisons every similarity search that reads it,
        # silently, and long after the call that produced it.
        raise ProviderError("empty_completion", provider=provider, model=model)
    return vectors


class AnthropicAdapter(_HttpAdapter):
    provider = "anthropic"
    url = "https://api.anthropic.com/v1/messages"
    probe_url = "https://api.anthropic.com/v1/models"
    supports_images = True
    supports_streaming = True

    def probe_headers(self) -> dict[str, str]:
        return {"x-api-key": os.getenv("ANTHROPIC_API_KEY", ""), "anthropic-version": "2023-06-01"}

    @staticmethod
    def _content_blocks(prompt: str, images: tuple[Any, ...]) -> Any:
        """Anthropic's message content: a bare string, or a block array.

        The image block goes BEFORE the text block — that is the order the API
        expects, and the order that reads correctly to the model ("here is an
        image; now here is what I want you to do with it").

        With no images this returns the plain string the text path has always
        sent, so nothing about non-vision calls changes.
        """
        if not images:
            return prompt
        blocks: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": img.media_type, "data": img.data_b64},
            }
            for img in images
        ]
        blocks.append({"type": "text", "text": prompt})
        return blocks

    def complete(self, *, model: str, prompt: str, timeout_s: float, images: tuple[Any, ...] = ()) -> AdapterResult:
        response = self._post(
            self.url,
            headers={
                "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "messages": [{"role": "user", "content": self._content_blocks(prompt, images)}],
            },
            timeout_s=timeout_s,
            model=model,
        )
        data = response.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) or [] if block.get("type") == "text")
        usage = data.get("usage", {}) or {}
        tokens_in = int(usage.get("input_tokens", 0) or 0)
        tokens_out = int(usage.get("output_tokens", 0) or 0)
        return AdapterResult(
            text=_require_text(text, provider=self.provider, model=model),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=estimate_cost(model, tokens_in=tokens_in, tokens_out=tokens_out, provider=self.provider),
        )

    def stream(
        self, *, model: str, prompt: str, timeout_s: float, images: tuple[Any, ...] = ()
    ) -> Iterator[StreamChunk]:
        """Anthropic SSE: `message_start` carries input tokens, `content_block_delta`
        carries text, `message_delta` carries output tokens at the end."""
        lines = self._stream_lines(
            self.url,
            headers={
                "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "messages": [{"role": "user", "content": self._content_blocks(prompt, images)}],
                "stream": True,
            },
            timeout_s=timeout_s,
            model=model,
        )
        saw_text = False
        for payload in _sse_payloads(lines):
            kind = payload.get("type")
            if kind == "message_start":
                usage = (payload.get("message", {}) or {}).get("usage", {}) or {}
                yield StreamChunk(tokens_in=int(usage.get("input_tokens", 0) or 0))
            elif kind == "content_block_delta":
                text = str((payload.get("delta", {}) or {}).get("text", "") or "")
                if text:
                    saw_text = True
                    yield StreamChunk(text=text)
            elif kind == "message_delta":
                usage = payload.get("usage", {}) or {}
                yield StreamChunk(tokens_out=int(usage.get("output_tokens", 0) or 0))
        _require_streamed(saw_text, provider=self.provider, model=model)


class OpenAIAdapter(_HttpAdapter):
    provider = "openai"
    url = "https://api.openai.com/v1/chat/completions"
    probe_url = "https://api.openai.com/v1/models"
    supports_images = True
    supports_streaming = True

    def probe_headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}"}

    @staticmethod
    def _content_blocks(prompt: str, images: tuple[Any, ...]) -> Any:
        """OpenAI's content array, which is NOT Anthropic's.

        The two differ in a way that is easy to get wrong by copying: OpenAI
        takes `{"type": "image_url", "image_url": {"url": "data:<mime>;base64,<b64>"}}`,
        a data URI in a nested object, where Anthropic takes a `source` object
        with the media type and raw base64 as separate fields. Sending either
        vendor the other's shape is a rejected request at cost.
        """
        if not images:
            return prompt
        blocks: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{img.media_type};base64,{img.data_b64}"},
            }
            for img in images
        ]
        blocks.append({"type": "text", "text": prompt})
        return blocks

    def complete(self, *, model: str, prompt: str, timeout_s: float, images: tuple[Any, ...] = ()) -> AdapterResult:
        response = self._post(
            self.url,
            headers={
                "authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "messages": [{"role": "user", "content": self._content_blocks(prompt, images)}],
            },
            timeout_s=timeout_s,
            model=model,
        )
        data = response.json()
        choices = data.get("choices") or []
        text = (choices[0].get("message", {}) or {}).get("content", "") if choices else ""
        usage = data.get("usage", {}) or {}
        tokens_in = int(usage.get("prompt_tokens", 0) or 0)
        tokens_out = int(usage.get("completion_tokens", 0) or 0)
        return AdapterResult(
            text=_require_text(text or "", provider=self.provider, model=model),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=estimate_cost(model, tokens_in=tokens_in, tokens_out=tokens_out, provider=self.provider),
        )

    def stream(
        self, *, model: str, prompt: str, timeout_s: float, images: tuple[Any, ...] = ()
    ) -> Iterator[StreamChunk]:
        body = _openai_stream_body(model, prompt)
        if images:
            body["messages"] = [{"role": "user", "content": self._content_blocks(prompt, images)}]
        lines = self._stream_lines(
            self.url,
            headers={
                "authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
                "content-type": "application/json",
            },
            json=body,
            timeout_s=timeout_s,
            model=model,
        )
        saw_text = False
        for chunk in _openai_stream_chunks(_sse_payloads(lines)):
            saw_text = saw_text or bool(chunk.text)
            yield chunk
        _require_streamed(saw_text, provider=self.provider, model=model)

    def embed(self, *, model: str, texts: list[str], timeout_s: float) -> EmbeddingResult:
        response = self._post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
                "content-type": "application/json",
            },
            json={"model": model, "input": texts},
            timeout_s=timeout_s,
            model=model,
        )
        data = response.json()
        vectors = [list(item.get("embedding") or []) for item in data.get("data") or []]
        vectors = _require_vectors(vectors, provider=self.provider, model=model)
        tokens_in = int((data.get("usage") or {}).get("prompt_tokens", 0) or 0)
        return EmbeddingResult(
            vectors=vectors,
            tokens_in=tokens_in,
            cost_usd=estimate_cost(model, tokens_in=tokens_in, tokens_out=0, provider=self.provider),
            dimensions=len(vectors[0]),
        )


class GoogleAdapter(_HttpAdapter):
    provider = "google"
    probe_url = "https://generativelanguage.googleapis.com/v1beta/models"
    supports_images = True
    supports_streaming = True

    def probe_headers(self) -> dict[str, str]:
        return {"x-goog-api-key": os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")}

    @staticmethod
    def _parts(prompt: str, images: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Gemini's `parts` array — a third distinct shape.

        `inline_data` with `mime_type` and `data`, where Anthropic uses
        `source`/`media_type` and OpenAI uses a data URI. Image first, for the
        same reason as the others.
        """
        parts: list[dict[str, Any]] = [
            {"inline_data": {"mime_type": img.media_type, "data": img.data_b64}} for img in images
        ]
        parts.append({"text": prompt})
        return parts

    def complete(self, *, model: str, prompt: str, timeout_s: float, images: tuple[Any, ...] = ()) -> AdapterResult:
        key = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
        response = self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "content-type": "application/json"},
            json={"contents": [{"parts": self._parts(prompt, images)}]},
            timeout_s=timeout_s,
            model=model,
        )
        data = response.json()
        candidates = data.get("candidates") or []
        parts = ((candidates[0].get("content", {}) or {}).get("parts") or []) if candidates else []
        text = "".join(part.get("text", "") for part in parts)
        usage = data.get("usageMetadata", {}) or {}
        tokens_in = int(usage.get("promptTokenCount", 0) or 0)
        tokens_out = int(usage.get("candidatesTokenCount", 0) or 0)
        return AdapterResult(
            text=_require_text(text, provider=self.provider, model=model),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=estimate_cost(model, tokens_in=tokens_in, tokens_out=tokens_out, provider=self.provider),
        )

    def stream(
        self, *, model: str, prompt: str, timeout_s: float, images: tuple[Any, ...] = ()
    ) -> Iterator[StreamChunk]:
        """Gemini SSE. A different endpoint and `alt=sse`, otherwise the same
        candidates/parts shape the buffered path reads."""
        key = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
        lines = self._stream_lines(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse",
            headers={"x-goog-api-key": key, "content-type": "application/json"},
            json={"contents": [{"parts": self._parts(prompt, images)}]},
            timeout_s=timeout_s,
            model=model,
        )
        saw_text = False
        for payload in _sse_payloads(lines):
            candidates = payload.get("candidates") or []
            if candidates:
                parts = (candidates[0].get("content", {}) or {}).get("parts") or []
                text = "".join(str(part.get("text", "") or "") for part in parts)
                if text:
                    saw_text = True
                    yield StreamChunk(text=text)
            usage = payload.get("usageMetadata") or {}
            if usage:
                yield StreamChunk(
                    tokens_in=int(usage.get("promptTokenCount", 0) or 0),
                    tokens_out=int(usage.get("candidatesTokenCount", 0) or 0),
                )
        _require_streamed(saw_text, provider=self.provider, model=model)


class OllamaAdapter(_HttpAdapter):
    provider = "ollama"

    @property
    def probe_url(self) -> str:  # type: ignore[override]
        return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/tags"

    supports_streaming = True

    def stream(self, *, model: str, prompt: str, timeout_s: float) -> Iterator[StreamChunk]:
        """Ollama speaks newline-delimited JSON rather than SSE — one object per
        line, each with a `response` fragment, the last one carrying `done`."""
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        lines = self._stream_lines(
            f"{base}/api/generate",
            headers={"content-type": "application/json"},
            json={"model": model, "prompt": prompt, "stream": True},
            timeout_s=timeout_s,
            model=model,
        )
        saw_text = False
        for raw in lines:
            line = (raw or "").strip()
            if not line:
                continue
            try:
                payload = _json.loads(line)
            except ValueError:
                logger.debug("ai.gateway.adapters: skipped a malformed ollama stream line")
                continue
            text = str(payload.get("response", "") or "")
            if text:
                saw_text = True
            # Local inference has no vendor bill, so token counts are reported
            # for the audit and cost stays zero — the same rule `complete` uses.
            yield StreamChunk(
                text=text,
                tokens_in=int(payload.get("prompt_eval_count", 0) or 0),
                tokens_out=int(payload.get("eval_count", 0) or 0),
            )
        _require_streamed(saw_text, provider=self.provider, model=model)

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> AdapterResult:
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        response = self._post(
            f"{base}/api/generate",
            headers={"content-type": "application/json"},
            json={"model": model, "prompt": prompt, "stream": False},
            timeout_s=timeout_s,
            model=model,
        )
        data = response.json()
        return AdapterResult(
            text=_require_text(str(data.get("response", "")), provider=self.provider, model=model),
            # Local inference has no vendor bill. Charging it against a spend
            # ceiling would refuse calls that cost nothing.
            cost_usd=0.0,
        )

    def embed(self, *, model: str, texts: list[str], timeout_s: float) -> EmbeddingResult:
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        vectors: list[list[float]] = []
        for text in texts:
            response = self._post(
                f"{base}/api/embeddings",
                headers={"content-type": "application/json"},
                json={"model": model, "prompt": text},
                timeout_s=timeout_s,
                model=model,
            )
            vectors.append(list(response.json().get("embedding") or []))
        return EmbeddingResult(
            vectors=_require_vectors(vectors, provider=self.provider, model=model),
            cost_usd=0.0,
            dimensions=len(vectors[0]) if vectors else 0,
        )


class OpenAICompatibleAdapter(_HttpAdapter):
    """Every vendor that speaks the OpenAI wire format, from one table.

    Moonshot (Kimi), Qwen, DeepSeek, Mistral, Groq, xAI, OpenRouter and Together
    all serve `POST {base}/chat/completions` and `GET {base}/models` with a
    bearer key, so they differ only in host and credential. Writing eight
    near-identical adapters would be eight places for the same bug.

    Subclasses set `provider`; the base URL and key come from
    `ai/gateway/vendors.py`, which lets a deployment point a vendor at its
    regional host without a code change.
    """

    provider = ""

    #: Every vendor in this table serves the OpenAI streaming format, so they
    #: inherit it rather than each re-implementing it — the same reason they
    #: share `complete`.
    supports_streaming = True

    def stream(self, *, model: str, prompt: str, timeout_s: float) -> Iterator[StreamChunk]:
        lines = self._stream_lines(
            f"{self._base}/chat/completions",
            headers={
                "authorization": f"Bearer {self._key()}",
                "content-type": "application/json",
            },
            json=_openai_stream_body(model, prompt),
            timeout_s=timeout_s,
            model=model,
        )
        saw_text = False
        for chunk in _openai_stream_chunks(_sse_payloads(lines)):
            saw_text = saw_text or bool(chunk.text)
            yield chunk
        _require_streamed(saw_text, provider=self.provider, model=model)

    @property
    def _base(self) -> str:
        from ai.gateway.vendors import resolve_base_url

        return resolve_base_url(self.provider)

    def _key(self) -> str:
        from ai.gateway.vendors import api_key

        return api_key(self.provider)

    @property
    def probe_url(self) -> str:  # type: ignore[override]
        return f"{self._base}/models"

    def probe_headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._key()}"}

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> AdapterResult:
        response = self._post(
            f"{self._base}/chat/completions",
            headers={
                "authorization": f"Bearer {self._key()}",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout_s=timeout_s,
            model=model,
        )
        data = response.json()
        choices = data.get("choices") or []
        text = (choices[0].get("message", {}) or {}).get("content", "") if choices else ""
        usage = data.get("usage", {}) or {}
        tokens_in = int(usage.get("prompt_tokens", 0) or 0)
        tokens_out = int(usage.get("completion_tokens", 0) or 0)
        return AdapterResult(
            text=_require_text(text or "", provider=self.provider, model=model),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            # An unpriced model is charged at the highest known rate, never
            # free. Adding a vendor must not be a way to spend money the
            # budget cannot see.
            cost_usd=estimate_cost(model, tokens_in=tokens_in, tokens_out=tokens_out, provider=self.provider),
        )


def _openai_compatible_adapters() -> dict[str, type[_HttpAdapter]]:
    """One adapter class per row of the vendor table, built from the table.

    Generated rather than hand-written so `OPENAI_COMPATIBLE`, `CREDENTIAL_ENV`
    and `_ADAPTERS` cannot disagree about which vendors exist — a disagreement
    that would show up as a chain leg that is configurable and uncallable.
    """
    from ai.gateway.vendors import OPENAI_COMPATIBLE

    return {
        name: type(
            f"{name.capitalize()}Adapter",
            (OpenAICompatibleAdapter,),
            {"provider": name},
        )
        for name in OPENAI_COMPATIBLE
    }


_ADAPTERS: Final[dict[str, type[_HttpAdapter]]] = {
    "anthropic": AnthropicAdapter,
    "openai": OpenAIAdapter,
    "google": GoogleAdapter,
    "ollama": OllamaAdapter,
    **_openai_compatible_adapters(),
}


def build_providers() -> dict[str, Any]:
    """One adapter per credentialed vendor.

    A vendor with no credential is omitted rather than offered and failed: the
    gateway SKIPS a leg whose provider is absent, so an unconfigured deployment
    reads as unconfigured instead of as a failing one.
    """
    from ai.gateway import providers as reachability

    return {name: cls() for name, cls in _ADAPTERS.items() if reachability.is_credentialed(name)}


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "FREE_PROVIDERS",
    "PRICING",
    "AdapterResult",
    "EmbeddingResult",
    "StreamChunk",
    "AnthropicAdapter",
    "GoogleAdapter",
    "OllamaAdapter",
    "OpenAICompatibleAdapter",
    "OpenAIAdapter",
    "build_providers",
    "estimate_cost",
    "reason_for_exception",
    "reason_for_status",
]
