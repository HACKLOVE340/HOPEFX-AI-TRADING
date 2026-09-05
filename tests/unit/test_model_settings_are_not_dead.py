"""D8 — the model settings must drive the model that is actually called.

`llm_provider`, `llm_model`, `llm_fallback_provider`, `llm_fallback_model` and
`llm_embedding_model` appeared in exactly three places: the form in
frontend/src/pages/settings/PlatformConfiguration.tsx, the PlatformConfigBody
fields in api/superadmin/_shared.py, and the defaults dict in
api/superadmin/platform.py. `GET`/`PATCH /platform/config` round-tripped them
into the config store and **no runtime code read any of them**. The real
selection was `api/brain.py::_detect_llm_backend`, which reads environment
variables and never consults the store.

So a superadmin could open Platform Configuration, set the primary and fallback
model, save, and change nothing at all. The fallback did not exist as behaviour
either: api/brain.py turned one provider failure into a 502 without trying a
second leg.
"""

from __future__ import annotations

import subprocess

import pytest

from ai.gateway import chain as gateway_chain

_SETTING_KEYS = (
    "llm_provider",
    "llm_model",
    "llm_fallback_provider",
    "llm_fallback_model",
    "llm_embedding_model",
)

#: Files that may mention a setting without being a consumer of it: the form,
#: the request body, and the defaults dict are the declaration sites.
_DECLARATION_SITES = {
    "api/superadmin/platform.py",
    "api/superadmin/_shared.py",
}


def test_every_llm_setting_has_a_runtime_consumer() -> None:
    """A setting nothing reads is a lie told to the operator."""
    orphaned: list[str] = []
    for key in _SETTING_KEYS:
        out = subprocess.run(
            ["git", "grep", "-l", key, "--", "*.py"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        consumers = [path for path in out if not path.startswith("tests/") and path not in _DECLARATION_SITES]
        if not consumers:
            orphaned.append(key)
    assert not orphaned, f"declared, stored, and never read: {orphaned}"


# ── the chain is data, not code ───────────────────────────────────────────────


def test_the_configured_model_is_the_model_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gateway_chain,
        "_stored_config",
        lambda: {"llm_provider": "anthropic", "llm_model": "claude-opus-5"},
    )
    legs = gateway_chain.resolve_chain("reasoning")
    assert legs[0].model == "claude-opus-5"
    assert legs[0].provider == "anthropic"


def test_changing_the_setting_changes_the_resolved_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The D8 defect, inverted: the setting must actually move the needle."""
    monkeypatch.setattr(gateway_chain, "_stored_config", lambda: {"llm_provider": "openai", "llm_model": "gpt-5.5"})
    assert gateway_chain.resolve_chain("reasoning")[0].model == "gpt-5.5"


def test_defaults_apply_when_nothing_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway_chain, "_stored_config", dict)
    legs = gateway_chain.resolve_chain("reasoning")
    assert legs, "an unconfigured deployment must still resolve a chain"
    assert legs[0].model == gateway_chain.DEFAULT_CHAINS["reasoning"][0].model


def test_the_committed_defaults_are_not_two_years_stale() -> None:
    """gpt-4o and claude-3-5-sonnet-20241022 were the defaults in Sept 2026."""
    from api.superadmin.platform import _PLATFORM_CONFIG_DEFAULTS

    stale = {"gpt-4o", "claude-3-5-sonnet-20241022", "gpt-4", "gpt-3.5-turbo"}
    for key in ("llm_model", "llm_fallback_model", "brain_model"):
        assert _PLATFORM_CONFIG_DEFAULTS.get(key) not in stale, (
            f"{key} still defaults to {_PLATFORM_CONFIG_DEFAULTS.get(key)!r}"
        )


# ── a fallback that is a chain, not a field ───────────────────────────────────


def test_the_reasoning_chain_spans_more_than_one_vendor() -> None:
    """A same-vendor fallback shares the primary's control plane and status page.

    In the incident a fallback exists for -- the primary vendor unreachable --
    both legs fail together, which makes the fallback decorative. Vendor
    diversity is the property that makes it real.
    """
    vendors = {leg.provider for leg in gateway_chain.DEFAULT_CHAINS["reasoning"]}
    assert len(vendors) >= 2, f"reasoning chain is single-vendor: {vendors}"


def test_local_inference_is_never_the_primary_reasoning_leg() -> None:
    """The owner's requirement: hosted primary, local optional and opt-in."""
    assert gateway_chain.DEFAULT_CHAINS["reasoning"][0].provider != "ollama"
    for role, legs in gateway_chain.DEFAULT_CHAINS.items():
        assert legs[0].provider != "ollama", f"{role} defaults to local inference"


def test_every_role_resolves_a_chain() -> None:
    for role in ("reasoning", "fast", "vision", "embedding"):
        assert gateway_chain.resolve_chain(role), role


def test_an_unknown_role_is_refused_not_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown model role"):
        gateway_chain.resolve_chain("nonsense")


# ── fall-through semantics ────────────────────────────────────────────────────


@pytest.mark.parametrize("reason", ["connection_error", "timeout", "rate_limited", "server_error", "overloaded"])
def test_transport_failures_fall_through(reason: str) -> None:
    assert gateway_chain.should_fall_through(reason) is True


@pytest.mark.parametrize("reason", ["guardrail_rejected", "refusal", "budget_exceeded", "bad_request"])
def test_answers_do_not_fall_through(reason: str) -> None:
    """Retrying a refusal on another vendor launders a failure into a different one."""
    assert gateway_chain.should_fall_through(reason) is False
