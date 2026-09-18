"""Task 7's last mile — real vendor adapters, and one door for every model call.

The gateway existed but nothing reached a vendor through it: routing, budget,
fall-through and audit were all in place around a `Provider` protocol that only
tests implemented. Meanwhile `api/brain.py` and `brain/llm_agent.py` still
called Anthropic, OpenAI and Ollama inline -- so the controls were real and
bypassed, which is this audit's signature defect wearing the fix's clothes.

Two things decide whether an adapter is honest:

* **The reason code it raises.** `chain.should_fall_through` obeys it exactly,
  so mapping a malformed request to "timeout" would retry a request every leg
  will reject identically, and mapping an outage to "bad_request" would strand
  a working second vendor. The mapping is asserted, not assumed.
* **What it never returns.** The key that authenticates the call must not reach
  the response, the exception message, or a log line.
"""

from __future__ import annotations

import httpx
import pytest

from ai.gateway import adapters
from ai.gateway.client import ProviderError


class _Response:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


# ── reason codes drive fall-through, so they are asserted ────────────────────


@pytest.mark.parametrize(
    ("status", "reason", "falls_through"),
    [
        (429, "rate_limited", True),
        (500, "server_error", True),
        (503, "server_error", True),
        (401, "provider_unavailable", True),
        (403, "provider_unavailable", True),
        (400, "bad_request", False),
        (422, "bad_request", False),
    ],
)
def test_http_status_maps_to_the_right_reason(status: int, reason: str, falls_through: bool) -> None:
    """A credential fault is a leg that cannot serve; a malformed request is an answer.

    401 falls through because a second vendor CAN answer the same question. 400
    does not, because it will be rejected identically -- retrying it launders one
    failure into a slower one.
    """
    from ai.gateway.chain import should_fall_through

    mapped = adapters.reason_for_status(status)
    assert mapped == reason
    assert should_fall_through(mapped) is falls_through


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (httpx.ConnectTimeout("t"), "timeout"),
        (httpx.ReadTimeout("t"), "timeout"),
        (httpx.ConnectError("c"), "connection_error"),
        (httpx.RemoteProtocolError("p"), "connection_error"),
    ],
)
def test_transport_exceptions_map_to_retryable_reasons(exc: Exception, reason: str) -> None:
    from ai.gateway.chain import should_fall_through

    mapped = adapters.reason_for_exception(exc)
    assert mapped == reason
    assert should_fall_through(mapped) is True


def test_an_unrecognised_exception_does_not_pretend_to_be_a_timeout() -> None:
    """Guessing "retryable" for an unknown fault is how a bug becomes three calls."""
    assert adapters.reason_for_exception(ValueError("something else")) == "adapter_error"


# ── the credential never leaves ───────────────────────────────────────────────


def test_a_failure_message_never_carries_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-ant-do-not-leak"  # pragma: allowlist secret
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

    def _post(*_a, **_kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(adapters.httpx, "post", _post)

    with pytest.raises(ProviderError) as raised:
        adapters.AnthropicAdapter().complete(model="claude-opus-5", prompt="hi", timeout_s=1.0)
    assert secret not in str(raised.value)
    assert raised.value.reason == "connection_error"


# ── the adapters parse what their vendor actually returns ─────────────────────


def test_the_anthropic_adapter_reads_content_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")  # pragma: allowlist secret
    monkeypatch.setattr(
        adapters.httpx,
        "post",
        lambda *_a, **_kw: _Response(
            200,
            {
                "content": [{"type": "text", "text": "ranging"}, {"type": "thinking", "text": "ignored"}],
                "usage": {"input_tokens": 11, "output_tokens": 5},
            },
        ),
    )
    result = adapters.AnthropicAdapter().complete(model="claude-opus-5", prompt="regime?", timeout_s=5.0)
    assert result.text == "ranging"
    assert (result.tokens_in, result.tokens_out) == (11, 5)


def test_the_ollama_adapter_reads_its_own_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(adapters.httpx, "post", lambda *_a, **_kw: _Response(200, {"response": "ranging"}))
    result = adapters.OllamaAdapter().complete(model="llama3", prompt="regime?", timeout_s=5.0)
    assert result.text == "ranging"
    assert result.cost_usd == 0.0, "local inference has no vendor bill"


def test_an_empty_completion_is_a_failure_not_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty string would be cached, charged for, and acted on as a decision."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")  # pragma: allowlist secret
    monkeypatch.setattr(adapters.httpx, "post", lambda *_a, **_kw: _Response(200, {"content": [], "usage": {}}))
    with pytest.raises(ProviderError) as raised:
        adapters.AnthropicAdapter().complete(model="claude-opus-5", prompt="regime?", timeout_s=5.0)
    assert raised.value.reason == "empty_completion"


# ── pricing must not under-count ──────────────────────────────────────────────


def test_a_priced_model_is_charged_at_its_rate() -> None:
    cost = adapters.estimate_cost("claude-opus-5", tokens_in=1_000_000, tokens_out=0)
    assert cost == pytest.approx(adapters.PRICING["claude-opus-5"][0])


def test_an_unpriced_model_is_charged_conservatively_not_free() -> None:
    """Charging 0.00 for an unpriced model makes the ceiling stop measuring spend.

    The safe direction for a money control is to over-estimate: the worst case
    is a call refused early, not a budget silently exceeded.
    """
    cost = adapters.estimate_cost("some-new-model", tokens_in=1_000_000, tokens_out=0)
    assert cost > 0
    assert cost >= max(rate[0] for rate in adapters.PRICING.values())


def test_local_inference_is_free_at_any_size() -> None:
    assert adapters.estimate_cost("llama3", tokens_in=10_000_000, tokens_out=10_000_000, provider="ollama") == 0.0


# ── only credentialed vendors are offered to the gateway ─────────────────────


def test_build_providers_offers_only_what_is_credentialed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert adapters.build_providers() == {}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")  # pragma: allowlist secret
    built = adapters.build_providers()
    assert set(built) == {"anthropic"}
    assert hasattr(built["anthropic"], "complete")


def test_an_adapter_bug_behaves_the_same_however_it_surfaces() -> None:
    """One fault, one behaviour.

    `GatewayClient` catches an unexpected adapter exception and advances to the
    next leg. The same bug wrapped in a ProviderError must do the same thing --
    otherwise whether the chain continues depends on how the adapter happened to
    report its own crash.
    """
    from ai.gateway.chain import should_fall_through

    assert should_fall_through("adapter_error") is True


# ── embeddings go through the same door ───────────────────────────────────────


def test_the_openai_adapter_embeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")  # pragma: allowlist secret
    monkeypatch.setattr(
        adapters.httpx,
        "post",
        lambda *_a, **_kw: _Response(
            200,
            {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}], "usage": {"prompt_tokens": 4}},
        ),
    )
    result = adapters.OpenAIAdapter().embed(model="text-embedding-3-large", texts=["a", "b"], timeout_s=5.0)
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert result.dimensions == 2


def test_an_embedding_adapter_refuses_an_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero-length vector silently poisons every similarity search that reads it."""
    monkeypatch.setenv("OPENAI_API_KEY", "k")  # pragma: allowlist secret
    monkeypatch.setattr(adapters.httpx, "post", lambda *_a, **_kw: _Response(200, {"data": []}))
    with pytest.raises(ProviderError) as raised:
        adapters.OpenAIAdapter().embed(model="text-embedding-3-large", texts=["a"], timeout_s=5.0)
    assert raised.value.reason == "empty_completion"


def test_anthropic_has_no_embeddings_api_and_says_so() -> None:
    """Reported as "this leg cannot serve", so the chain moves on rather than failing."""
    with pytest.raises(ProviderError) as raised:
        adapters.AnthropicAdapter().embed(model="claude-opus-5", texts=["a"], timeout_s=5.0)
    assert raised.value.reason == "provider_unavailable"

    from ai.gateway.chain import should_fall_through

    assert should_fall_through(raised.value.reason) is True


def test_embeddings_are_charged_and_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    """The budget and the record are the point of routing embeddings here at all."""
    from ai.gateway import audit, budget
    from ai.gateway.client import GatewayClient

    budget.reset_for_testing()
    audit.reset_for_testing()

    class _Embedder:
        def embed(self, *, model: str, texts: list[str], timeout_s: float) -> object:
            return adapters.EmbeddingResult(
                vectors=[[0.1] * 3 for _ in texts], tokens_in=7, cost_usd=0.25, dimensions=3
            )

    client = GatewayClient(providers={"openai": _Embedder()})
    result = client.embed_sync(["a", "b"], operator="op-embed")

    assert result.dimensions == 3
    assert len(result.vectors) == 2
    assert budget.spent("op-embed") == pytest.approx(0.25)
    record = audit.records()[-1]
    assert record["role"] == "embedding"
    assert record["served_by"] == "openai"
    assert "prompt" not in record and record["prompt_sha256"]
