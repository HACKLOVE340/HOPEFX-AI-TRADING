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

import logging
import os
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

    def probe_headers(self) -> dict[str, str]:
        return {"x-api-key": os.getenv("ANTHROPIC_API_KEY", ""), "anthropic-version": "2023-06-01"}

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> AdapterResult:
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
                "messages": [{"role": "user", "content": prompt}],
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


class OpenAIAdapter(_HttpAdapter):
    provider = "openai"
    url = "https://api.openai.com/v1/chat/completions"
    probe_url = "https://api.openai.com/v1/models"

    def probe_headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}"}

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> AdapterResult:
        response = self._post(
            self.url,
            headers={
                "authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
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
            cost_usd=estimate_cost(model, tokens_in=tokens_in, tokens_out=tokens_out, provider=self.provider),
        )

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

    def probe_headers(self) -> dict[str, str]:
        return {"x-goog-api-key": os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")}

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> AdapterResult:
        key = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
        response = self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "content-type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
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


class OllamaAdapter(_HttpAdapter):
    provider = "ollama"

    @property
    def probe_url(self) -> str:  # type: ignore[override]
        return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/tags"

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
