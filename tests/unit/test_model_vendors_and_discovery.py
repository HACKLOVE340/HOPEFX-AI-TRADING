# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""More vendors than three, and a model list that is discovered rather than typed.

Owner requirement, 2026-09-06: "what about Kimi, what about Qwen and other
models... make sure this app can accept external API ... and it pops up all the
model."

Two separate gaps, and they are worth naming separately because only one of them
was a real limitation:

* **Local models were never limited to one.** Ollama is a *runner*, not a model:
  it already serves Qwen, DeepSeek, Mistral, Gemma, Phi and Llama, and
  `LOCAL_MODEL_NAMES` already takes a list. Nothing needed widening there.
* **Hosted vendors were limited to three** — Anthropic, OpenAI, Google. Moonshot
  (Kimi), DeepSeek, Alibaba's Qwen, Mistral, Groq, xAI and OpenRouter were all
  unreachable, and every one of them speaks the OpenAI wire format, so the
  absence was a missing table rather than a missing integration.
* **The model list was hard-coded.** A superadmin picking a model chose from
  whatever was committed in `DEFAULT_CHAINS`, so a vendor shipping a new model
  meant a code change. Discovery asks the vendor.

The safety property under all of it: an unpriced model is charged at the highest
known rate, never free (`estimate_cost`), so adding vendors cannot quietly
widen spend. That is asserted here rather than assumed, because it is the one
way this change could cost money.
"""

from __future__ import annotations

import pytest

from ai.gateway import discovery, vendors
from ai.gateway.adapters import PRICING, estimate_cost

pytestmark = pytest.mark.unit


# ── the vendor table ─────────────────────────────────────────────────────────


def test_the_vendors_the_owner_named_are_present():
    assert "moonshot" in vendors.OPENAI_COMPATIBLE, "Kimi is Moonshot's API"
    assert "qwen" in vendors.OPENAI_COMPATIBLE, "Qwen is Alibaba's DashScope API"


def test_every_vendor_declares_what_it_needs_to_be_reachable():
    for name, vendor in vendors.OPENAI_COMPATIBLE.items():
        assert vendor.name == name, f"{name} disagrees with its own key"
        assert vendor.base_url.startswith("https://"), f"{name} must be https"
        assert not vendor.base_url.endswith("/"), f"{name} base_url has a trailing slash"
        assert vendor.key_env.endswith("_API_KEY"), f"{name} key env is oddly named"
        assert vendor.label, f"{name} has no human label for the settings UI"


def test_a_regional_endpoint_can_be_overridden_without_a_code_change(monkeypatch):
    """Moonshot, DashScope and others publish different hosts per region."""
    vendor = vendors.OPENAI_COMPATIBLE["moonshot"]
    monkeypatch.setenv(vendor.base_url_env, "https://api.moonshot.cn/v1")
    assert vendors.resolve_base_url("moonshot") == "https://api.moonshot.cn/v1"


def test_base_url_falls_back_to_the_committed_default(monkeypatch):
    vendor = vendors.OPENAI_COMPATIBLE["qwen"]
    monkeypatch.delenv(vendor.base_url_env, raising=False)
    assert vendors.resolve_base_url("qwen") == vendor.base_url


def test_an_unknown_vendor_is_refused_not_guessed():
    with pytest.raises(KeyError):
        vendors.resolve_base_url("not-a-vendor")


# ── they reach the gateway's credential and adapter registries ───────────────


def test_every_vendor_is_credentialable():
    from ai.gateway import providers

    for name, vendor in vendors.OPENAI_COMPATIBLE.items():
        assert name in providers.CREDENTIAL_ENV, f"{name} is not in CREDENTIAL_ENV"
        assert vendor.key_env in providers.CREDENTIAL_ENV[name]


def test_every_vendor_has_an_adapter():
    from ai.gateway.adapters import _ADAPTERS

    for name in vendors.OPENAI_COMPATIBLE:
        assert name in _ADAPTERS, f"{name} is in the vendor table but has no adapter"


def test_a_vendor_adapter_reports_its_own_provider_name():
    from ai.gateway.adapters import _ADAPTERS

    for name in vendors.OPENAI_COMPATIBLE:
        assert _ADAPTERS[name]().provider == name


def test_a_vendor_probe_url_is_the_models_listing(monkeypatch):
    from ai.gateway.adapters import _ADAPTERS

    monkeypatch.delenv(vendors.OPENAI_COMPATIBLE["deepseek"].base_url_env, raising=False)
    adapter = _ADAPTERS["deepseek"]()
    assert adapter.probe_url == vendors.OPENAI_COMPATIBLE["deepseek"].base_url + "/models"


# ── the money property ───────────────────────────────────────────────────────


def test_a_new_vendors_unpriced_model_is_charged_high_never_free():
    """Adding vendors must not be a way to spend money the budget cannot see."""
    highest_in = max(rate[0] for rate in PRICING.values())
    cost = estimate_cost("kimi-k2-0905-preview", tokens_in=1_000_000, tokens_out=0, provider="moonshot")
    assert cost == pytest.approx(highest_in)
    assert cost > 0.0


def test_no_new_vendor_is_treated_as_free_inference():
    from ai.gateway.adapters import FREE_PROVIDERS

    assert frozenset({"ollama"}) == FREE_PROVIDERS, (
        "only on-hardware inference has no vendor bill; a hosted vendor marked free would spend against no ceiling"
    )


# ── discovery: ask the vendor instead of hard-coding ─────────────────────────


def test_discovery_reads_the_openai_models_payload():
    payload = {"data": [{"id": "kimi-k2-0905-preview"}, {"id": "moonshot-v1-8k"}]}
    assert discovery.parse_models("moonshot", payload) == ("kimi-k2-0905-preview", "moonshot-v1-8k")


def test_discovery_reads_the_ollama_tags_payload():
    payload = {"models": [{"name": "qwen2.5:32b"}, {"name": "llama3:latest"}]}
    assert discovery.parse_models("ollama", payload) == ("qwen2.5:32b", "llama3:latest")


def test_discovery_of_a_malformed_payload_is_empty_not_an_exception():
    """A vendor changing its shape must not take down the settings page."""
    assert discovery.parse_models("moonshot", {"unexpected": True}) == ()
    assert discovery.parse_models("moonshot", []) == ()
    assert discovery.parse_models("ollama", {"models": [{"no_name": 1}]}) == ()


def test_discovery_skips_an_uncredentialed_vendor(monkeypatch):
    """No key means "not configured", which is not the same as "no models"."""
    monkeypatch.delenv(vendors.OPENAI_COMPATIBLE["groq"].key_env, raising=False)
    result = discovery.list_models("groq", fetch=lambda url, headers: pytest.fail("must not call out"))
    assert result.configured is False
    assert result.models == ()
    assert result.error is None


def test_discovery_returns_what_the_vendor_lists(monkeypatch):
    monkeypatch.setenv(vendors.OPENAI_COMPATIBLE["moonshot"].key_env, "sk-test")  # pragma: allowlist secret
    seen: dict[str, object] = {}

    def fetch(url: str, headers: dict[str, str]) -> dict:
        seen["url"] = url
        seen["auth"] = headers.get("authorization", "")
        return {"data": [{"id": "kimi-k2-0905-preview"}]}

    result = discovery.list_models("moonshot", fetch=fetch)
    assert result.configured is True
    assert result.models == ("kimi-k2-0905-preview",)
    assert str(seen["url"]).endswith("/models")
    assert seen["auth"] == "Bearer sk-test"  # pragma: allowlist secret


def test_a_vendor_that_errors_reports_the_reason_and_no_models(monkeypatch):
    monkeypatch.setenv(vendors.OPENAI_COMPATIBLE["xai"].key_env, "sk-test")  # pragma: allowlist secret

    def fetch(url: str, headers: dict[str, str]) -> dict:
        raise TimeoutError("took too long")

    result = discovery.list_models("xai", fetch=fetch)
    assert result.configured is True
    assert result.models == ()
    assert result.error and "timeout" in result.error.lower()


def test_the_error_never_echoes_the_key(monkeypatch):
    """A vendor exception can quote the request headers; those carry the key."""
    key = "sk-super-secret-value"  # pragma: allowlist secret
    monkeypatch.setenv(vendors.OPENAI_COMPATIBLE["deepseek"].key_env, key)

    def fetch(url: str, headers: dict[str, str]) -> dict:
        raise RuntimeError(f"401 with authorization={headers['authorization']}")

    result = discovery.list_models("deepseek", fetch=fetch)
    assert key not in (result.error or "")


def test_discover_all_covers_every_known_provider(monkeypatch):
    for vendor in vendors.OPENAI_COMPATIBLE.values():
        monkeypatch.delenv(vendor.key_env, raising=False)
    results = discovery.discover_all(fetch=lambda url, headers: {"data": []})
    for name in vendors.OPENAI_COMPATIBLE:
        assert name in results, f"{name} missing from discovery"
    assert "ollama" in results, "the local runner must appear alongside the hosted vendors"
