# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_sentry_scrub_coverage.py
========================================
Sentry's `before_send` hook scrubbed three regions of an event and left the
three that carry the most text alone.

It handled `request.data`, `request.headers` and `extra`. It did not touch:

* `logentry` — the log message and its interpolation params. Every
  `logger.error("auth failed for %s", token)` lands here.
* `breadcrumbs` — the trail of log lines and HTTP calls leading up to the
  error, which is usually the richest part of an event.
* `contexts` — despite the function's own docstring claiming "Scrubs sensitive
  fields from request data, extra, and contexts". It never did.
* `request.query_string` — where a token lands when a client passes one in the
  URL, which this codebase does for WebSocket endpoints.

The scrubbing machinery itself was fine: `_scrub_dict` walks nested dicts and
lists, `_scrub_string` applies the PII regexes for Bearer tokens, JWTs,
32-hex API keys, IPv4 and email. It was simply not pointed at most of the event.

These tests build events with a JWT, a Bearer token, an OANDA-shaped key and an
email in each region and assert none of them survive. The docstring is now true.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NSJ9.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
# Deliberately not shaped like any real provider's key. An earlier draft of this
# file used a live-Stripe-style prefix and GitHub push protection blocked the
# push — correctly, because a scanner cannot tell a fixture from the real thing.
# Keep test credentials obviously synthetic.
_BEARER = "Bearer fixture-opaque-token-0000"
_OANDA_KEY = "a1b2c3d4e5f60718293a4b5c6d7e8f90"  # pragma: allowlist secret
_EMAIL = "trader@hopefx.io"


def _send(event):
    from monitoring.sentry_config import _before_send

    return _before_send(event, {})


def _flatten(obj) -> str:
    """Render an event to one string so a leak anywhere is visible."""
    import json

    return json.dumps(obj, default=str)


class TestLogentry:
    def test_the_log_message_is_scrubbed(self):
        event = _send({"logentry": {"message": f"auth failed with {_JWT}"}})

        assert _JWT not in _flatten(event), "a JWT in the log message reached Sentry unscrubbed"

    def test_log_interpolation_params_are_scrubbed(self):
        """logger.error("auth failed for %s", token) puts the token in params."""
        event = _send({"logentry": {"message": "auth failed for %s", "params": [_BEARER]}})

        assert "fixture-opaque-token" not in _flatten(event)

    def test_a_formatted_message_is_scrubbed(self):
        event = _send({"logentry": {"formatted": f"key={_OANDA_KEY}"}})

        assert _OANDA_KEY not in _flatten(event)


class TestBreadcrumbs:
    def test_breadcrumb_messages_are_scrubbed(self):
        event = _send({"breadcrumbs": {"values": [{"message": f"GET /ws?token={_JWT}"}]}})

        assert _JWT not in _flatten(event), "a JWT in a breadcrumb reached Sentry unscrubbed"

    def test_breadcrumb_data_is_scrubbed(self):
        event = _send({"breadcrumbs": {"values": [{"data": {"authorization": _BEARER}}]}})

        assert "fixture-opaque-token" not in _flatten(event)

    def test_a_bare_breadcrumb_list_is_handled(self):
        """Older SDKs send breadcrumbs as a plain list rather than {"values": [...]}"""
        event = _send({"breadcrumbs": [{"message": f"login {_EMAIL}"}]})

        assert _EMAIL not in _flatten(event)


class TestContexts:
    def test_contexts_are_scrubbed_as_the_docstring_claims(self):
        event = _send({"contexts": {"trading": {"api_key": _OANDA_KEY}}})

        assert _OANDA_KEY not in _flatten(event), "before_send's docstring says it scrubs contexts, and it did not"

    def test_nested_context_values_are_scrubbed(self):
        event = _send({"contexts": {"session": {"nested": {"jwt": _JWT}}}})

        assert _JWT not in _flatten(event)


class TestRequestQueryString:
    def test_a_token_in_the_query_string_is_scrubbed(self):
        """WebSocket clients in this codebase pass tokens in the URL."""
        event = _send({"request": {"query_string": f"token={_JWT}&symbol=XAUUSD"}})

        assert _JWT not in _flatten(event), "a token in the query string reached Sentry unscrubbed"

    def test_a_query_string_given_as_pairs_is_scrubbed(self):
        event = _send({"request": {"query_string": [["token", _JWT]]}})

        assert _JWT not in _flatten(event)


class TestPreservedBehaviour:
    def test_existing_regions_are_still_scrubbed(self):
        event = _send(
            {
                "request": {
                    "data": {"password": "hunter2"},  # pragma: allowlist secret
                    "headers": {"Authorization": _BEARER},
                },
                "extra": {"note": f"user {_EMAIL}"},
            }
        )
        flat = _flatten(event)

        assert "hunter2" not in flat
        assert "fixture-opaque-token" not in flat
        assert _EMAIL not in flat

    def test_health_check_events_are_still_dropped(self):
        assert _send({"transaction": "/health"}) is None

    def test_non_sensitive_content_survives(self):
        """Scrubbing must not gut the event — it still has to be useful."""
        event = _send({"logentry": {"message": "order rejected: insufficient margin"}})

        assert "insufficient margin" in _flatten(event)

    def test_an_event_with_none_of_these_regions_is_unharmed(self):
        event = _send({"transaction": "/api/trading/order", "level": "error"})

        assert event["transaction"] == "/api/trading/order"
        assert event["level"] == "error"

    @pytest.mark.parametrize(
        "region",
        [
            {"logentry": None},
            {"breadcrumbs": None},
            {"contexts": None},
            {"request": None},
            {"logentry": "a string, not a dict"},
            {"breadcrumbs": {"values": "not a list"}},
            {"contexts": []},
        ],
    )
    def test_malformed_regions_do_not_raise(self, region):
        """before_send runs inside the SDK — raising there loses the event."""
        _send(dict(region))
