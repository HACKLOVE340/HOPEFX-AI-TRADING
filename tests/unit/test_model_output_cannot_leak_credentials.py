# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Nothing screened what a model said on the way out.

`ai/guardrails/output.py` validated the SHAPE of a response rigorously —
required fields, type checks, an explicit refusal to coerce. It never looked at
the CONTENT. A model that had been shown a credential, or that reconstructed one
from context, could hand it straight back to an operator, into a log line, or
into the department memory layer.

Spec §6 asks for "AI-layer security hardening" and names prompt-injection
defence explicitly. The reverse direction — what comes back out — had no stage
at all, while the input side had two.

The one rule that is easy to get backwards: **a scanner must never quote what it
found.** A violation message containing the secret moves it from a model
response into an exception string, a stack trace and a log aggregator, which is
strictly worse than not having scanned.

These tests fail on the pre-fix tree: `scan_output` does not exist there.
"""

from __future__ import annotations

import pytest

from ai.guardrails.output import GuardrailViolation, scan_output

pytestmark = pytest.mark.unit


# Synthetic, structurally valid, never real. Each line is the shape of a
# credential rather than one — the point is the pattern, not the value.
#
# Each case names its secret substring explicitly rather than having the test
# guess at it. An earlier version picked "the longest whitespace token", which
# silently had nothing to check for two of the eight (an AKIA key is exactly 20
# characters, and a PEM header is all short words) — a test that passes because
# it found nothing to assert against is not a test.
_SECRETS = {
    "anthropic key": "sk-ant-api03-" + "A" * 32,
    "openai key": "sk-" + "B" * 40,
    "aws access key": "AKIA" + "C" * 16,
    "google api key": "AIza" + "D" * 35,
    "private key block": "-----BEGIN RSA PRIVATE KEY-----",  # pragma: allowlist secret
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.aaaaaaaaaaaaaaaaaaaaaaa",
    "url with password": "postgres://admin:hunter2@db.internal:5432/hopefx",  # pragma: allowlist secret
    "slack token": "xoxb-111111111111-222222222222-" + "E" * 24,
}

LEAKS = [
    ("anthropic key", "here you go: " + _SECRETS["anthropic key"]),
    ("openai key", "the key is " + _SECRETS["openai key"]),
    ("aws access key", "use " + _SECRETS["aws access key"] + " to connect"),
    ("google api key", _SECRETS["google api key"]),
    ("private key block", _SECRETS["private key block"] + "\nMIIE\n-----END RSA PRIVATE KEY-----"),
    ("jwt", "token: " + _SECRETS["jwt"]),
    ("url with password", "connect to " + _SECRETS["url with password"]),
    ("slack token", _SECRETS["slack token"]),
]


@pytest.mark.parametrize(("label", "text"), LEAKS, ids=[label for label, _ in LEAKS])
def test_a_credential_shaped_string_in_model_output_is_refused(label, text):
    with pytest.raises(GuardrailViolation):
        scan_output(text)


@pytest.mark.parametrize(("label", "text"), LEAKS, ids=[label for label, _ in LEAKS])
def test_the_refusal_never_quotes_the_secret(label, text):
    """The rule that makes this safe rather than counterproductive."""
    with pytest.raises(GuardrailViolation) as excinfo:
        scan_output(text)

    secret = _SECRETS[label]
    assert secret not in str(excinfo.value), f"the {label} was quoted back inside the violation message"


def test_ordinary_trading_answers_pass_untouched():
    """A scanner that refuses real answers is worse than no scanner.

    These are the kinds of thing the platform's own departments return.
    """
    safe = [
        "Current drawdown is 3.2% against a 5% limit. No action required.",
        "XAUUSD is in a high-volatility regime; the model's confidence is 0.61.",
        "The backtest returned a Sharpe of 1.34 over 5 years, 2,181 trades.",
        "I'm not sure — the regime classifier has no reading for this symbol.",
        '{"surface_type": "chart", "instrument": "XAUUSD", "confidence": 0.82}',
        "Order 88213 was rejected: position size 4.10 lots exceeds the 3.00 cap.",
    ]
    for text in safe:
        scan_output(text)  # must not raise


def test_a_registered_live_credential_is_caught_verbatim():
    """The precise case patterns cannot cover: this deployment's own secrets.

    A model shown the system prompt, or an env var, can echo a value that
    matches no generic pattern. Registering the live values catches exactly
    that, and is what makes system-prompt leakage detectable at all.
    """
    from ai.guardrails import output as og

    og.register_known_secret("jwt-signing", "s3cret-value-unique-to-this-deployment")
    try:
        with pytest.raises(GuardrailViolation):
            scan_output("the signing secret is s3cret-value-unique-to-this-deployment")
    finally:
        og.reset_known_secrets()


def test_a_registered_credential_is_not_quoted_either():
    from ai.guardrails import output as og

    value = "s3cret-value-unique-to-this-deployment"
    og.register_known_secret("jwt-signing", value)
    try:
        with pytest.raises(GuardrailViolation) as excinfo:
            scan_output(f"the signing secret is {value}")
        assert value not in str(excinfo.value)
        assert "jwt-signing" in str(excinfo.value), "the label should say WHICH secret, without the value"
    finally:
        og.reset_known_secrets()


def test_short_registered_values_are_ignored():
    """Registering a 3-character value would refuse almost every response."""
    from ai.guardrails import output as og

    og.register_known_secret("too-short", "abc")
    try:
        scan_output("abc is a perfectly ordinary thing to say")  # must not raise
    finally:
        og.reset_known_secrets()


def test_empty_and_none_output_are_not_errors():
    scan_output("")
    scan_output(None)  # type: ignore[arg-type]


def test_validate_output_also_screens_content():
    """The structured path must not be a way around the scanner."""
    from ai.guardrails.output import validate_output

    with pytest.raises(GuardrailViolation):
        validate_output('{"note": "sk-ant-api03-' + "A" * 32 + '"}')


# ── the wiring ────────────────────────────────────────────────────────────────


def test_the_gateway_screens_every_answer_before_returning_it():
    """A scanner nothing calls is the defect this repo keeps finding."""
    import inspect

    from ai.gateway import client as gw

    src = inspect.getsource(gw)
    assert "scan_output" in src, "GatewayClient does not screen model output"
