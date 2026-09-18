# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The output guardrail's known-secret registry is actually populated.

`ai/guardrails/output.py` scans model output two ways: regex shapes for
credentials with a distinctive form, and an exact-match registry of *this
deployment's real values*. The module says why the second exists:

    Patterns cannot cover a secret with no distinctive shape -- this
    platform's own JWT signing key, a broker password, the system prompt.
    Registering the live values is what makes leakage of those detectable at
    all, and it is the only mechanism here that can catch system-prompt echo.

and `register_known_secret` says when it runs:

    Called at startup with values already in the process (the JWT signing
    secret, broker passwords).

It was not. `scripts/capability_callers.py` flagged `sec.secrets` with no
production caller, and the only callers were tests. So `_KNOWN` was empty in
every running process: the exact-match arm scanned against nothing, the
system-prompt echo check did not exist, and `StreamScanner`'s holdback never
widened to cover a registered value.

That is F176 — a control that exists, is documented accurately, and is never
invoked. The registry was never wrong; it was never filled.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

JWT = "s3cret-jwt-signing-value-not-a-real-one-0123456789"
ENC = "config-encryption-value-not-a-real-one-9876543210"


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    """Start every test from a deployment with NO credentials configured.

    Clearing `_KNOWN` is not enough: `register_deployment_secrets` reads the
    real environment, and this one has several of those variables set. Two
    tests here asserted `known_secret_count() == 0` after clearing only the two
    they named, passed in isolation, and failed in the full suite — the same
    shape of harness bug as the `_redis_sync` fixture in §E46, and the reason
    an assertion about a global count needs a controlled global.
    """
    from ai.guardrails.output import _DEPLOYMENT_SECRET_ENV, reset_known_secrets

    for name in _DEPLOYMENT_SECRET_ENV:
        monkeypatch.delenv(name, raising=False)
    reset_known_secrets()
    yield
    reset_known_secrets()


class TestTheRegistrarExists:
    def test_the_guardrail_offers_a_way_to_register_the_deployment(self):
        from ai.guardrails import output

        assert hasattr(output, "register_deployment_secrets")

    def test_it_registers_the_values_present_in_the_environment(self, monkeypatch):
        from ai.guardrails.output import known_secret_count, register_deployment_secrets

        monkeypatch.setenv("SECURITY_JWT_SECRET", JWT)
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENC)

        n = register_deployment_secrets()

        assert n >= 2
        assert known_secret_count() >= 2

    def test_it_returns_a_count_and_never_the_values(self, monkeypatch):
        """A registrar that returned or logged what it registered would copy
        the secret into the caller's log line."""
        from ai.guardrails.output import register_deployment_secrets

        monkeypatch.setenv("SECURITY_JWT_SECRET", JWT)
        result = register_deployment_secrets()

        assert isinstance(result, int)

    def test_an_absent_variable_is_simply_not_registered(self, monkeypatch):
        from ai.guardrails.output import known_secret_count, register_deployment_secrets

        # The fixture already cleared every name; setting one to empty proves
        # an empty value is not registered either.
        monkeypatch.setenv("REDIS_PASSWORD", "")

        register_deployment_secrets()

        assert known_secret_count() == 0

    def test_a_placeholder_short_value_is_not_registered(self, monkeypatch):
        """`register_known_secret` already floors at 8 characters, because a
        short value matches ordinary prose and refuses every answer."""
        from ai.guardrails.output import known_secret_count, register_deployment_secrets

        monkeypatch.setenv("SECURITY_JWT_SECRET", "short")

        register_deployment_secrets()

        assert known_secret_count() == 0


class TestRegisteringMakesTheScannerRefuse:
    """The point of the registry, executed."""

    def test_a_registered_jwt_secret_is_refused_in_output(self, monkeypatch):
        from ai.guardrails.output import GuardrailViolation, register_deployment_secrets, scan_output

        monkeypatch.setenv("SECURITY_JWT_SECRET", JWT)
        register_deployment_secrets()

        with pytest.raises(GuardrailViolation):
            scan_output(f"Sure! The signing secret is {JWT} — hope that helps.")

    def test_without_registration_the_same_output_passes(self, monkeypatch):
        """The counterfactual, in the suite: this is exactly what production
        did before the wiring, and it is why an empty registry matters."""
        from ai.guardrails.output import scan_output

        monkeypatch.setenv("SECURITY_JWT_SECRET", JWT)
        # deliberately NOT registering

        scan_output(f"Sure! The signing secret is {JWT} — hope that helps.")

    def test_the_refusal_does_not_reproduce_the_value(self, monkeypatch):
        from ai.guardrails.output import GuardrailViolation, register_deployment_secrets, scan_output

        monkeypatch.setenv("SECURITY_JWT_SECRET", JWT)
        register_deployment_secrets()

        with pytest.raises(GuardrailViolation) as exc:
            scan_output(f"the secret is {JWT}")

        assert JWT not in str(exc.value), "the guardrail copied the secret into an exception string"

    def test_ordinary_output_still_passes(self, monkeypatch):
        from ai.guardrails.output import register_deployment_secrets, scan_output

        monkeypatch.setenv("SECURITY_JWT_SECRET", JWT)
        register_deployment_secrets()

        scan_output("Gold is trading around 2000 and the model is 62% confident.")


class TestStartupCallsIt:
    def test_init_env_registers_them(self, monkeypatch):
        """The wiring itself — the part that was missing.

        `init_env` is where the secrets are resolved into the process, so it is
        where the guardrail learns them.
        """
        import asyncio
        import types

        from ai.guardrails.output import known_secret_count
        from core import startup_factories as F

        monkeypatch.setenv("SECURITY_JWT_SECRET", JWT)
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", ENC)
        monkeypatch.setenv("APP_ENV", "development")

        asyncio.run(F.init_env(types.SimpleNamespace()))

        assert known_secret_count() >= 2, "startup completed with an empty known-secret registry"
