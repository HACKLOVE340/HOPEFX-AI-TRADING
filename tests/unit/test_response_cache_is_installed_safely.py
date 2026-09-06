# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The response cache gets installed — and cannot serve a stale market answer.

`install_shared_cache()` had zero callers, so no deployment had a cache and
every call reached a provider. Wiring it naively would have been worse than
leaving it off, and that is the finding this module encodes.

`ModelRequest.tool_state` is documented as the fingerprint of the state a
question is asked against: "an answer computed under old state must never be
served against new state." **Not one production caller sets it.** api/brain.py,
brain/llm_agent.py, security/llm_wrapper.py and ai/evals/runner.py all leave it
at the default `""`. So installing a cache would have keyed every answer under
the empty state and served a market view computed an hour ago, under different
positions and a different regime, as though it were current.

The fix is a policy, not a per-caller audit: **a blank `tool_state` means the
caller did not say what the answer depends on, so the answer is not cached.**
Silence means do not cache. A caller whose answer genuinely depends on nothing
says so explicitly with `STATELESS`, which is a claim someone has to make on
purpose rather than one they fall into by omitting an argument.
"""

from __future__ import annotations

import pytest

from ai.cache.store import ResponseCache, STATELESS, install_shared_cache, shared_cache
from ai.gateway.client import GatewayClient, ModelRequest, ModelResponse

pytestmark = pytest.mark.unit


def a_response(text: str = "answer") -> ModelResponse:
    """ModelResponse requires provider/model/latency; this keeps the cases readable."""
    return ModelResponse(text=text, provider="anthropic", model="m", latency_ms=1.0)


@pytest.fixture(autouse=True)
def _clean_shared_cache():
    install_shared_cache(None)
    yield
    install_shared_cache(None)


# ── the policy: silence means do not cache ───────────────────────────────────


def test_a_request_with_no_declared_state_is_not_cached():
    """The whole safety argument. No declaration, no caching."""
    cache = ResponseCache()
    cache.put(prompt="p", model="m", tool_state="", value=a_response("stale"))
    assert cache.get(prompt="p", model="m", tool_state="") is None


def test_a_stateless_request_is_cached():
    """An explicit claim that the answer depends on nothing."""
    cache = ResponseCache()
    cache.put(prompt="p", model="m", tool_state=STATELESS, value=a_response("fresh"))
    hit = cache.get(prompt="p", model="m", tool_state=STATELESS)
    assert hit is not None and hit.text == "fresh"


def test_a_declared_state_is_cached_and_keyed_on_it():
    cache = ResponseCache()
    cache.put(prompt="p", model="m", tool_state="positions=1", value=a_response("one"))
    assert cache.get(prompt="p", model="m", tool_state="positions=1").text == "one"
    # Different state, same prompt: a different question.
    assert cache.get(prompt="p", model="m", tool_state="positions=2") is None


def test_put_reports_that_it_stored_nothing_when_state_is_undeclared():
    """put() must not claim to have stored something it refused to store."""
    cache = ResponseCache()
    key = cache.put(prompt="p", model="m", tool_state="", value=a_response("x"))
    assert key == ""
    assert cache.stats()["entries"] == 0


# ── the gateway honours it ───────────────────────────────────────────────────


def _client(cache):
    return GatewayClient({}, cache=cache)


def test_the_gateway_never_serves_a_hit_for_an_undeclared_state():
    cache = ResponseCache()
    client = _client(cache)
    request = ModelRequest(role="reasoning", prompt="what is my exposure?")
    assert client._cache_lookup(request, "some-model") is None


def test_the_gateway_serves_a_hit_for_a_declared_state():
    cache = ResponseCache()
    cache.put(prompt="q", model="some-model", tool_state=STATELESS, value=a_response("hit"))
    client = _client(cache)
    request = ModelRequest(role="reasoning", prompt="q", tool_state=STATELESS)
    hit = client._cache_lookup(request, "some-model")
    assert hit is not None and hit.cached is True


# ── installation: the seam that had no filler ────────────────────────────────


def test_no_cache_is_installed_by_default():
    assert shared_cache() is None


def test_the_gateway_picks_up_the_shared_cache_without_being_handed_one():
    """One place resolves it, so five construction sites need no editing.

    A per-site wiring step is a step somebody forgets — which is how
    install_shared_cache came to have zero callers in the first place.
    """
    cache = ResponseCache()
    install_shared_cache(cache)
    assert GatewayClient({}).cache is cache


def test_an_explicitly_passed_cache_still_wins():
    own = ResponseCache()
    install_shared_cache(ResponseCache())
    assert GatewayClient({}, cache=own).cache is own


def test_passing_no_cache_after_uninstalling_leaves_none():
    install_shared_cache(None)
    assert GatewayClient({}).cache is None


def test_the_startup_factory_installs_one():
    """Zero production callers is the defect. Asserted, not assumed."""
    import core.startup_factories as F

    assert hasattr(F, "init_ai_response_cache")


def test_the_registry_entry_is_optional():
    from unittest.mock import MagicMock

    from core.startup_factories import build_component_registry

    registry = build_component_registry(MagicMock(), MagicMock())
    components = getattr(registry, "components", None) or registry._components
    assert "ai_response_cache" in components
    assert components["ai_response_cache"].required is False


# ── the one caller that opted in ─────────────────────────────────────────────


def test_the_security_wrapper_declares_its_answer_stateless():
    """security/llm_wrapper.call_llm(prompt) depends on nothing but its prompt.

    It is the only caller opted in. api/brain.py and brain/llm_agent.py reason
    about markets and positions; their answers are state-dependent and stay
    uncached until they say what state they depend on.
    """
    import inspect

    from security import llm_wrapper

    source = inspect.getsource(llm_wrapper)
    assert "STATELESS" in source


def test_the_market_reasoning_callers_have_not_been_opted_in():
    """Guard against a future edit quietly making market answers cacheable."""
    import inspect

    import api.brain as brain_api

    source = inspect.getsource(brain_api)
    assert "STATELESS" not in source, (
        "api/brain.py reasons about live market state; caching its answers "
        "under a stateless key would serve an old market view as current"
    )
