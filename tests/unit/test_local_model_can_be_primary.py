# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The AI must not be dead on a deployment with no API key.

Owner requirement, 2026-09-10: *"our local model should be our primary model, so
our AI can be active if an API token is not available — it should not be waiting
for a key before it activates. If a key is dictated it can switch."*

Measured before this change, with every provider credential unset:

    credentialed providers : []
    embedding    chain=['openai', 'google']                answerable legs=0
    fast         chain=['anthropic', 'anthropic', 'google'] answerable legs=0
    reasoning    chain=['anthropic', 'openai', 'google']    answerable legs=0
    vision       chain=['google', 'anthropic']              answerable legs=0

Every role resolved to a chain that could not answer. `ai/local_model.py` was
running on the box the whole time and was not in any chain, because the policy
was "local inference is optional and never a primary": it joined only when a
superadmin enabled it, and then LAST.

Two ways in now, and they are different things:

* **`llm_local_first`** — an explicit preference. Local leads, the hosted legs
  stay behind it as fallback. This is the owner's "operate primary on the local
  model", chosen deliberately.
* **Automatic promotion** — when *no* leg in the resolved chain is credentialed,
  a ready local runtime goes to the front rather than leaving the platform with
  no AI at all. A weaker answer beats no answer; a *fabricated* one would not,
  which is why the next section exists.

## The trap this file exists to prevent

`providers.local_inference_enabled()` returns `is_credentialed("ollama")`, and
"credentialed" for ollama means `OLLAMA_BASE_URL` is a non-empty string. **A
string is not a server.** Promoting the local leg to primary on that evidence
would replace a chain that cannot answer with a chain that cannot answer *and
claims it can* — strictly worse, and precisely the defect class this programme
keeps removing.

`LocalModelRuntime.is_ready()` probes. Promotion must use the probe.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _chain(role: str = "reasoning"):
    from ai.gateway.chain import resolve_chain

    return resolve_chain(role)


def _providers(*names: str):
    """Patch which providers hold credentials."""
    return patch("ai.gateway.chain._credentialed_providers", return_value=frozenset(names))


def _local(ready: bool):
    """Patch whether the local runtime actually answers a probe."""
    return patch("ai.gateway.chain._local_is_ready", return_value=ready)


class TestExplicitLocalFirst:
    def test_llm_local_first_puts_local_at_the_head(self):
        from ai.gateway.chain import LOCAL_PROVIDER

        with (
            patch("ai.gateway.chain._stored_config", return_value={"llm_local_first": True}),
            _providers("anthropic", "openai"),
            _local(True),
        ):
            legs = _chain("reasoning")

        assert legs[0].provider == LOCAL_PROVIDER, f"local should lead, got {[l.provider for l in legs]}"

    def test_the_hosted_legs_remain_as_fallback(self):
        """Primary, not exclusive. `llm_local_only` is the exclusive one."""
        from ai.gateway.chain import LOCAL_PROVIDER

        with (
            patch("ai.gateway.chain._stored_config", return_value={"llm_local_first": True}),
            _providers("anthropic", "openai"),
            _local(True),
        ):
            legs = _chain("reasoning")

        hosted = [leg for leg in legs if leg.provider != LOCAL_PROVIDER]
        assert hosted, "local-first must keep the hosted legs behind it, unlike local-only"

    def test_local_only_still_means_only(self):
        """The privacy mode must not be weakened into a preference."""
        from ai.gateway.chain import LOCAL_PROVIDER

        with (
            patch("ai.gateway.chain._stored_config", return_value={"llm_local_only": True}),
            _providers("anthropic", "openai"),
            _local(True),
        ):
            legs = _chain("reasoning")

        assert [leg.provider for leg in legs] == [LOCAL_PROVIDER]


class TestAutomaticPromotionWhenNothingElseCanAnswer:
    def test_a_deployment_with_no_keys_still_has_an_answerable_chain(self):
        """The owner's requirement, stated as the test that would have caught it."""
        from ai.gateway.chain import LOCAL_PROVIDER

        with patch("ai.gateway.chain._stored_config", return_value={}), _providers(), _local(True):
            legs = _chain("reasoning")

        assert legs, "no legs at all"
        assert legs[0].provider == LOCAL_PROVIDER, (
            f"with no API key the chain must lead with local, got {[l.provider for l in legs]}"
        )

    @pytest.mark.parametrize("role", ["reasoning", "fast", "vision", "embedding"])
    def test_every_role_is_covered_not_just_reasoning(self, role: str):
        """All four roles measured as dead; all four must be revived."""
        from ai.gateway.chain import LOCAL_PROVIDER

        with patch("ai.gateway.chain._stored_config", return_value={}), _providers(), _local(True):
            legs = _chain(role)

        assert legs[0].provider == LOCAL_PROVIDER, f"{role} still has no answerable primary"

    def test_a_credentialed_provider_keeps_the_lead(self):
        """ "If a key is dictated it can switch" — the key wins by default.

        Automatic promotion is a floor, not a preference. A deployment that has
        paid for a frontier model must not be quietly downgraded because a
        local runtime happens to be up.
        """
        from ai.gateway.chain import LOCAL_PROVIDER

        with (
            patch("ai.gateway.chain._stored_config", return_value={}),
            _providers("anthropic"),
            _local(True),
        ):
            legs = _chain("reasoning")

        assert legs[0].provider != LOCAL_PROVIDER, (
            "a credentialed hosted provider must stay primary unless local-first is chosen"
        )

    def test_local_still_joins_as_a_fallback_when_hosted_leads(self):
        """Being up is worth something even when it is not primary."""
        from ai.gateway.chain import LOCAL_PROVIDER

        with (
            patch("ai.gateway.chain._stored_config", return_value={}),
            _providers("anthropic"),
            _local(True),
        ):
            legs = _chain("reasoning")

        assert any(leg.provider == LOCAL_PROVIDER for leg in legs), (
            "a ready local runtime should be reachable as a last resort"
        )


class TestPromotionRequiresAProbeNotAnEnvVar:
    def test_an_unreachable_local_runtime_is_not_promoted(self):
        """A string in OLLAMA_BASE_URL is not a server.

        Promoting on the env var would turn "no AI" into "no AI that claims to
        work", which is worse: the caller stops looking for the real problem.
        """
        from ai.gateway.chain import LOCAL_PROVIDER

        with patch("ai.gateway.chain._stored_config", return_value={}), _providers(), _local(False):
            legs = _chain("reasoning")

        assert not (legs and legs[0].provider == LOCAL_PROVIDER), (
            "local was promoted to primary without a successful readiness probe"
        )

    def test_explicit_local_first_also_respects_the_probe(self):
        """Even a deliberate choice must not put a dead leg first.

        The setting says which model is preferred; the probe says which can
        answer. A preference cannot make an absent server respond.
        """
        from ai.gateway.chain import LOCAL_PROVIDER

        with (
            patch("ai.gateway.chain._stored_config", return_value={"llm_local_first": True}),
            _providers("anthropic"),
            _local(False),
        ):
            legs = _chain("reasoning")

        assert legs[0].provider != LOCAL_PROVIDER, "an unready local leg must not lead"

    def test_a_set_env_var_alone_does_not_promote_local(self):
        """The credential check says yes, the probe says no. The probe wins.

        Asserted behaviourally rather than by grepping the source. The first
        version of this test read `inspect.getsource(_local_is_ready)` and
        asserted the string "local_inference_enabled" was absent — and failed,
        because that function's docstring *explains* why it does not use it. A
        checker that reads prose is not reading code; this repository has had
        that defect before (F255) and it is no better in a test.
        """
        from ai.gateway.chain import LOCAL_PROVIDER

        with (
            patch("ai.gateway.chain._stored_config", return_value={}),
            _providers(),
            patch("ai.gateway.providers.local_inference_enabled", return_value=True),
            patch("ai.local_model.get_local_model_runtime") as runtime,
        ):
            runtime.return_value.is_ready.return_value = False
            legs = _chain("reasoning")

        assert not (legs and legs[0].provider == LOCAL_PROVIDER), (
            "local led the chain on a set env var while the readiness probe said no"
        )

    def test_a_probe_that_raises_is_not_ready(self):
        """Fail closed: an unknown state is not a working one."""
        from ai.gateway import chain

        with patch("ai.local_model.get_local_model_runtime", side_effect=RuntimeError("no runtime")):
            assert chain._local_is_ready() is False
