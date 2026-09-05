"""Task 12 — the response cache in front of the gateway (spec §3 concept 5).

"Inference economics": a repeated query stops hitting the paid tier. The
properties that stop a cache from becoming a correctness bug:

* **A failure is never cached.** Caching an error makes a transient outage
  sticky, and the next caller gets a stale failure instead of a live attempt.
* **The key includes the tool state.** The same prompt against different
  positions is a different question, so an answer computed under old state must
  not be served against new state.
* **A hit costs nothing.** If a cache hit still charged the budget, the ceiling
  would fall for calls that were never made.
* **The prompt is not stored.** Prompts here carry position data and stop
  levels; the key is a hash, as in the gateway's audit record.
"""

from __future__ import annotations

import pytest

from ai.cache.store import ResponseCache


@pytest.fixture
def cache() -> ResponseCache:
    return ResponseCache(ttl_s=60.0)


def test_an_identical_query_hits(cache: ResponseCache) -> None:
    cache.put(prompt="regime?", model="claude-opus-5", tool_state="s1", value="ranging")
    assert cache.get(prompt="regime?", model="claude-opus-5", tool_state="s1") == "ranging"


def test_a_different_prompt_misses(cache: ResponseCache) -> None:
    cache.put(prompt="regime?", model="claude-opus-5", tool_state="s1", value="ranging")
    assert cache.get(prompt="trend?", model="claude-opus-5", tool_state="s1") is None


def test_a_different_model_misses(cache: ResponseCache) -> None:
    """The same question to a different model is a different answer."""
    cache.put(prompt="regime?", model="claude-opus-5", tool_state="s1", value="ranging")
    assert cache.get(prompt="regime?", model="gpt-5.5", tool_state="s1") is None


def test_a_changed_tool_state_misses(cache: ResponseCache) -> None:
    """The same prompt against different positions is a different question."""
    cache.put(prompt="regime?", model="claude-opus-5", tool_state="s1", value="ranging")
    assert cache.get(prompt="regime?", model="claude-opus-5", tool_state="s2") is None


def test_explicit_invalidation_clears_the_entry(cache: ResponseCache) -> None:
    cache.put(prompt="regime?", model="claude-opus-5", tool_state="s1", value="ranging")
    cache.invalidate(prompt="regime?", model="claude-opus-5", tool_state="s1")
    assert cache.get(prompt="regime?", model="claude-opus-5", tool_state="s1") is None


def test_invalidating_a_tool_state_clears_every_entry_under_it(cache: ResponseCache) -> None:
    cache.put(prompt="a", model="m", tool_state="s1", value="1")
    cache.put(prompt="b", model="m", tool_state="s1", value="2")
    cache.put(prompt="c", model="m", tool_state="s2", value="3")
    cache.invalidate_tool_state("s1")
    assert cache.get(prompt="a", model="m", tool_state="s1") is None
    assert cache.get(prompt="b", model="m", tool_state="s1") is None
    assert cache.get(prompt="c", model="m", tool_state="s2") == "3"


def test_an_expired_entry_misses() -> None:
    small = ResponseCache(ttl_s=0.0)
    small.put(prompt="regime?", model="m", tool_state="s", value="ranging")
    assert small.get(prompt="regime?", model="m", tool_state="s") is None


def test_the_prompt_is_not_stored(cache: ResponseCache) -> None:
    """Prompts carry position sizes and stop levels; only a digest is kept."""
    sensitive_prompt = "our stop is 2381.40 on 12 lots"
    cache.put(prompt=sensitive_prompt, model="m", tool_state="s", value="ok")
    assert sensitive_prompt not in repr(cache.entries())


def test_a_failure_is_never_cached(cache: ResponseCache) -> None:
    """Caching an error makes a transient outage sticky."""
    with pytest.raises(ValueError, match="failure"):
        cache.put(prompt="regime?", model="m", tool_state="s", value=None)


# ── in front of the gateway ───────────────────────────────────────────────────


def test_a_repeated_query_does_not_reach_the_provider() -> None:
    from ai.gateway.client import GatewayClient, ModelRequest

    class _Counting:
        calls = 0

        def complete(self, *, model: str, prompt: str, timeout_s: float) -> object:
            _Counting.calls += 1
            return type("R", (), {"text": "ranging", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.02})()

    client = GatewayClient(providers={"anthropic": _Counting()}, cache=ResponseCache(ttl_s=60.0))
    request = ModelRequest(role="reasoning", prompt="what is the regime?")
    first = client.call_sync(request, operator="op-1")
    second = client.call_sync(request, operator="op-1")
    assert first.text == second.text == "ranging"
    assert _Counting.calls == 1, "the second identical query reached the paid tier"


def test_a_cache_hit_does_not_charge_the_budget() -> None:
    """A ceiling that falls for calls never made is not measuring spend."""
    from ai.gateway import budget
    from ai.gateway.client import GatewayClient, ModelRequest

    budget.reset_for_testing()

    class _Provider:
        def complete(self, *, model: str, prompt: str, timeout_s: float) -> object:
            return type("R", (), {"text": "ranging", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.02})()

    client = GatewayClient(providers={"anthropic": _Provider()}, cache=ResponseCache(ttl_s=60.0))
    request = ModelRequest(role="reasoning", prompt="what is the regime?")
    client.call_sync(request, operator="op-1")
    after_first = budget.spent("op-1")
    client.call_sync(request, operator="op-1")
    assert budget.spent("op-1") == after_first, "a cache hit charged the budget"


def test_a_changed_tool_state_reaches_the_provider_again() -> None:
    """The same prompt against new positions is a new question, at the gateway too."""
    from ai.gateway.client import GatewayClient, ModelRequest

    class _Counting:
        calls = 0

        def complete(self, *, model: str, prompt: str, timeout_s: float) -> object:
            _Counting.calls += 1
            return type("R", (), {"text": "ranging", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.02})()

    client = GatewayClient(providers={"anthropic": _Counting()}, cache=ResponseCache(ttl_s=60.0))
    client.call_sync(ModelRequest(role="reasoning", prompt="regime?", tool_state="flat"), operator="op-2")
    client.call_sync(ModelRequest(role="reasoning", prompt="regime?", tool_state="long 3 lots"), operator="op-2")
    assert _Counting.calls == 2, "an answer computed under old state was served against new state"


def test_a_cached_answer_reports_itself_as_cached_and_free() -> None:
    """A cached answer still reporting its original cost double-counts spend."""
    from ai.gateway.client import GatewayClient, ModelRequest

    class _Provider:
        def complete(self, *, model: str, prompt: str, timeout_s: float) -> object:
            return type("R", (), {"text": "ranging", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.02})()

    client = GatewayClient(providers={"anthropic": _Provider()}, cache=ResponseCache(ttl_s=60.0))
    request = ModelRequest(role="reasoning", prompt="what is the regime?")
    first = client.call_sync(request, operator="op-3")
    second = client.call_sync(request, operator="op-3")
    assert first.cached is False and first.cost_usd == pytest.approx(0.02)
    assert second.cached is True and second.cost_usd == 0.0
    assert second.model == first.model, "a cached answer was served under an identity that did not produce it"


def test_no_cache_is_the_default_and_every_call_reaches_the_provider() -> None:
    """Caching is an economy, never a correctness dependency."""
    from ai.gateway.client import GatewayClient, ModelRequest

    class _Counting:
        calls = 0

        def complete(self, *, model: str, prompt: str, timeout_s: float) -> object:
            _Counting.calls += 1
            return type("R", (), {"text": "ranging", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0})()

    client = GatewayClient(providers={"anthropic": _Counting()})
    assert client.cache is None
    request = ModelRequest(role="reasoning", prompt="what is the regime?")
    client.call_sync(request, operator="op-4")
    client.call_sync(request, operator="op-4")
    assert _Counting.calls == 2


def test_a_failed_call_leaves_nothing_cached() -> None:
    """A transient outage must not become sticky."""
    from ai.gateway.client import GatewayClient, ModelRequest, NoProviderAvailable, ProviderError

    class _Down:
        def complete(self, *, model: str, prompt: str, timeout_s: float) -> object:
            raise ProviderError("timeout", provider="anthropic", model=model)

    store = ResponseCache(ttl_s=60.0)
    client = GatewayClient(providers={"anthropic": _Down()}, cache=store)
    with pytest.raises(NoProviderAvailable):
        client.call_sync(ModelRequest(role="reasoning", prompt="regime?"), operator="op-5")
    assert store.entries() == ()


def test_a_broken_cache_is_a_miss_not_a_failed_call() -> None:
    """A cache fault degrades the economy, never the answer."""
    from ai.gateway.client import GatewayClient, ModelRequest

    class _Provider:
        def complete(self, *, model: str, prompt: str, timeout_s: float) -> object:
            return type("R", (), {"text": "ranging", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0})()

    class _Broken(ResponseCache):
        def get(self, **kwargs: object) -> object:
            raise RuntimeError("backing store unreachable")

        def put(self, **kwargs: object) -> str:
            raise RuntimeError("backing store unreachable")

    client = GatewayClient(providers={"anthropic": _Provider()}, cache=_Broken(ttl_s=60.0))
    response = client.call_sync(ModelRequest(role="reasoning", prompt="regime?"), operator="op-6")
    assert response.text == "ranging"


def test_the_store_stays_bounded() -> None:
    """An unbounded cache in a long-lived trading process is a slow outage."""
    small = ResponseCache(ttl_s=60.0, max_entries=3)
    for index in range(10):
        small.put(prompt=f"q{index}", model="m", tool_state="s", value=str(index))
    assert len(small.entries()) == 3
    assert small.get(prompt="q9", model="m", tool_state="s") == "9"
    assert small.get(prompt="q0", model="m", tool_state="s") is None
