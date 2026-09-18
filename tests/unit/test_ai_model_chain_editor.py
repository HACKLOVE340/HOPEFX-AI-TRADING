"""Task 14 — the chain editor must drive the chain, end to end.

D8 inverted. The old settings were declared, stored, and read by nothing: a
superadmin could set the primary and fallback model, save, and change nothing.
Task 6c fixed that for the single `reasoning` primary/fallback pair. This is the
rest of it -- an ordered chain per role, plus the optional local leg -- and the
same rule applies: an editor whose output no runtime code reads is a worse lie
than no editor, because it looks like control.

The properties that keep the local leg honest are asserted here too, because
they are the owner's decision (plan Part 1A.5) and not a default anyone should
be able to drift:

* local inference is **off by default**;
* when enabled it joins **last**, never as a primary -- capability drops
  sharply, and a silent promotion to primary would degrade every answer;
* the one exception is the explicit `local_only` privacy mode, for a deployment
  that must not egress prompts at all.
"""

from __future__ import annotations

import pytest

from ai.gateway import chain as gateway_chain


def _stub(monkeypatch: pytest.MonkeyPatch, config: dict) -> None:
    monkeypatch.setattr(gateway_chain, "_stored_config", lambda: config)


# ── the per-role chain ────────────────────────────────────────────────────────


def test_a_configured_chain_replaces_that_roles_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {"llm_chain": {"fast": [{"provider": "google", "model": "gemini-3.5-flash"}]}})
    legs = gateway_chain.resolve_chain("fast")
    assert [(leg.provider, leg.model) for leg in legs] == [("google", "gemini-3.5-flash")]


def test_a_configured_chain_keeps_its_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """The editor is ordered; primary first is the whole point."""
    _stub(
        monkeypatch,
        {
            "llm_chain": {
                "reasoning": [
                    {"provider": "openai", "model": "gpt-5.5"},
                    {"provider": "anthropic", "model": "claude-opus-5"},
                ]
            }
        },
    )
    legs = gateway_chain.resolve_chain("reasoning")
    assert [leg.model for leg in legs] == ["gpt-5.5", "claude-opus-5"]


def test_a_role_with_no_configured_chain_keeps_its_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {"llm_chain": {"fast": [{"provider": "google", "model": "gemini-3.5-flash"}]}})
    assert gateway_chain.resolve_chain("vision") == gateway_chain.DEFAULT_CHAINS["vision"]


def test_the_flat_reasoning_settings_still_drive_the_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """D8's fix must not regress: the existing two fields still work."""
    _stub(monkeypatch, {"llm_provider": "google", "llm_model": "gemini-3.1-pro"})
    legs = gateway_chain.resolve_chain("reasoning")
    assert (legs[0].provider, legs[0].model) == ("google", "gemini-3.1-pro")


def test_the_explicit_chain_wins_over_the_flat_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two ways to say it; the more specific one decides, and it is not ambiguous."""
    _stub(
        monkeypatch,
        {
            "llm_provider": "google",
            "llm_model": "gemini-3.1-pro",
            "llm_chain": {"reasoning": [{"provider": "anthropic", "model": "claude-opus-5"}]},
        },
    )
    assert gateway_chain.resolve_chain("reasoning")[0].model == "claude-opus-5"


# ── malformed configuration must not remove the model ─────────────────────────


@pytest.mark.parametrize(
    "broken",
    [
        {"llm_chain": {"fast": []}},
        {"llm_chain": {"fast": [{"provider": "", "model": "x"}]}},
        {"llm_chain": {"fast": [{"provider": "google"}]}},
        {"llm_chain": {"fast": "gemini-3.5-flash"}},
        {"llm_chain": "not a mapping"},
    ],
)
def test_a_malformed_chain_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch, broken: dict) -> None:
    """An empty chain is no model at all. Degrade to the committed default."""
    _stub(monkeypatch, broken)
    legs = gateway_chain.resolve_chain("fast")
    assert legs, "a malformed configuration produced a chain with no legs"
    assert legs[0] == gateway_chain.DEFAULT_CHAINS["fast"][0]


def test_an_unknown_role_in_the_config_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {"llm_chain": {"telepathy": [{"provider": "google", "model": "x"}]}})
    assert gateway_chain.resolve_chain("fast") == gateway_chain.DEFAULT_CHAINS["fast"]
    with pytest.raises(ValueError, match="unknown model role"):
        gateway_chain.resolve_chain("telepathy")


# ── the local leg ─────────────────────────────────────────────────────────────


def test_local_inference_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {})
    for role in gateway_chain.DEFAULT_CHAINS:
        providers = {leg.provider for leg in gateway_chain.resolve_chain(role)}
        assert gateway_chain.LOCAL_PROVIDER not in providers, f"{role} routes to local with no configuration"


def test_enabling_local_appends_it_last_and_never_as_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capability drops sharply. A silent promotion to primary degrades every answer."""
    _stub(monkeypatch, {"llm_local_enabled": True, "llm_local_model": "llama3"})
    legs = gateway_chain.resolve_chain("reasoning")
    assert legs[-1].provider == gateway_chain.LOCAL_PROVIDER
    assert legs[-1].model == "llama3"
    assert legs[0].provider != gateway_chain.LOCAL_PROVIDER
    assert len(legs) == len(gateway_chain.DEFAULT_CHAINS["reasoning"]) + 1


def test_local_only_makes_local_the_only_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    """The privacy mode: a deployment that must not egress prompts at all."""
    _stub(monkeypatch, {"llm_local_only": True, "llm_local_model": "llama3"})
    for role in ("reasoning", "fast"):
        legs = gateway_chain.resolve_chain(role)
        assert [leg.provider for leg in legs] == [gateway_chain.LOCAL_PROVIDER], (
            f"{role} still egresses under local_only"
        )


def test_local_only_overrides_a_configured_hosted_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Privacy mode is a ceiling, not a preference it can be argued out of."""
    _stub(
        monkeypatch,
        {
            "llm_local_only": True,
            "llm_chain": {"reasoning": [{"provider": "anthropic", "model": "claude-opus-5"}]},
        },
    )
    assert [leg.provider for leg in gateway_chain.resolve_chain("reasoning")] == [gateway_chain.LOCAL_PROVIDER]


def test_the_local_leg_is_not_duplicated_when_already_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(
        monkeypatch,
        {
            "llm_local_enabled": True,
            "llm_local_model": "llama3",
            "llm_chain": {
                "fast": [{"provider": "google", "model": "gemini-3.5-flash"}, {"provider": "ollama", "model": "llama3"}]
            },
        },
    )
    legs = gateway_chain.resolve_chain("fast")
    assert [leg.provider for leg in legs].count(gateway_chain.LOCAL_PROVIDER) == 1


# ── the request body carries the new fields ───────────────────────────────────


def test_the_config_body_accepts_the_chain_and_the_local_flags() -> None:
    """A field the API drops is an editor that saves nothing."""
    from api.superadmin._shared import PlatformConfigBody

    body = PlatformConfigBody(
        llm_chain={"fast": [{"provider": "google", "model": "gemini-3.5-flash"}]},
        llm_local_enabled=True,
        llm_local_model="llama3",
        llm_local_only=False,
    )
    dumped = body.model_dump(exclude_none=True)
    assert dumped["llm_chain"]["fast"][0]["model"] == "gemini-3.5-flash"
    assert dumped["llm_local_enabled"] is True
    assert dumped["llm_local_model"] == "llama3"


# ── end to end: the editor changes which model answers the next call ──────────


def test_changing_a_leg_changes_the_model_that_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """D8 inverted, and the done-condition for this task.

    The whole path: what a superadmin saves through /platform/config is what
    `resolve_chain` returns, and what `resolve_chain` returns is the model the
    gateway actually calls.
    """
    from ai.gateway import budget
    from ai.gateway.client import GatewayClient, ModelRequest

    budget.reset_for_testing()

    saved: dict = {}

    def _save(cfg: dict) -> None:
        saved.clear()
        saved.update(cfg)

    from api.superadmin import platform as platform_module

    monkeypatch.setattr(platform_module, "_save_platform_config", _save)
    monkeypatch.setattr(platform_module, "_load_platform_config", lambda: dict(saved))
    monkeypatch.setattr(gateway_chain, "_stored_config", lambda: dict(saved))

    # 1. A superadmin saves a new chain for the fast role.
    cfg = dict(saved)
    cfg["llm_chain"] = {"fast": [{"provider": "google", "model": "gemini-3.5-flash"}]}
    platform_module._save_platform_config(cfg)

    # 2. The resolver reflects it.
    assert gateway_chain.resolve_chain("fast")[0].model == "gemini-3.5-flash"

    # 3. The gateway calls that model, and not the committed default.
    called: list[str] = []

    class _Provider:
        def complete(self, *, model: str, prompt: str, timeout_s: float) -> object:
            called.append(model)
            return type("R", (), {"text": "ok", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0})()

    client = GatewayClient(providers={"google": _Provider(), "anthropic": _Provider()})
    response = client.call_sync(ModelRequest(role="fast", prompt="classify this"), operator="op-chain")

    assert called == ["gemini-3.5-flash"], f"the gateway called {called}, not the configured leg"
    assert response.model == "gemini-3.5-flash"
    assert response.provider == "google"
