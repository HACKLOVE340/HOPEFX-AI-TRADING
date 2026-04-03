# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for notifications/email_triggers.py

Verifies:
- Log-only fallback when email channel is unavailable
- send_trade_fill_email produces correct subject and template context
- send_daily_report_email produces correct subject and template context
- send_risk_halt_email produces correct subject and template context
- Missing recipient address returns False without raising
- Template render failure falls back gracefully
"""

from __future__ import annotations

import os
from unittest.mock import patch

# ── Helpers ───────────────────────────────────────────────────────────────────


def _no_channel():
    """Patch _get_email_channel to return None (log-only mode)."""
    return patch(
        "notifications.email_triggers._get_email_channel",
        return_value=None,
    )


# ── Log-only fallback ─────────────────────────────────────────────────────────


class TestLogOnlyFallback:
    def test_trade_fill_returns_true_without_channel(self, caplog):
        with _no_channel():
            from notifications.email_triggers import send_trade_fill_email

            result = send_trade_fill_email(
                symbol="XAUUSD",
                direction="buy",
                quantity=0.1,
                fill_price=2050.0,
                to="trader@example.com",
            )
        assert result is True

    def test_daily_report_returns_true_without_channel(self):
        with _no_channel():
            from notifications.email_triggers import send_daily_report_email

            result = send_daily_report_email(
                date="2026-03-25",
                daily_pnl=312.50,
                daily_pnl_pct=0.31,
                total_trades=3,
                win_rate_pct=66.7,
                equity=105_312.50,
                to="trader@example.com",
            )
        assert result is True

    def test_risk_halt_returns_true_without_channel(self):
        with _no_channel():
            from notifications.email_triggers import send_risk_halt_email

            result = send_risk_halt_email(
                reason="Daily loss limit reached",
                drawdown_pct=5.02,
                limit_pct=5.0,
                to="trader@example.com",
            )
        assert result is True

    def test_missing_recipient_returns_false(self):
        """No recipient and no SMTP_TO env var → return False, no error."""
        with _no_channel(), patch.dict(os.environ, {"SMTP_TO": ""}):
            from importlib import reload

            import notifications.email_triggers as mod

            reload(mod)
            result = mod.send_trade_fill_email(
                symbol="XAUUSD",
                direction="buy",
                quantity=0.1,
                fill_price=2050.0,
                to="",  # explicit empty
            )
        assert result is False


# ── Subject line correctness ──────────────────────────────────────────────────


class TestSubjectLines:
    """Verify the subject strings contain the right data."""

    def test_trade_fill_subject_contains_symbol_and_price(self):
        captured_subjects = []

        def fake_send(to, subject, template, **ctx):
            captured_subjects.append(subject)
            return True

        with patch("notifications.email_triggers._send", side_effect=fake_send):
            from notifications.email_triggers import send_trade_fill_email

            send_trade_fill_email(
                symbol="XAUUSD",
                direction="sell",
                quantity=0.2,
                fill_price=2100.0,
                to="t@example.com",
            )

        assert len(captured_subjects) == 1
        subj = captured_subjects[0]
        assert "XAUUSD" in subj
        assert "SELL" in subj
        assert "2,100.00" in subj

    def test_daily_report_subject_contains_date_and_pnl(self):
        captured = []

        def fake_send(to, subject, template, **ctx):
            captured.append(subject)
            return True

        with patch("notifications.email_triggers._send", side_effect=fake_send):
            from notifications.email_triggers import send_daily_report_email

            send_daily_report_email(
                date="2026-03-25",
                daily_pnl=312.50,
                daily_pnl_pct=0.31,
                total_trades=3,
                win_rate_pct=66.7,
                equity=105_312.50,
                to="t@example.com",
            )

        assert "2026-03-25" in captured[0]
        assert "312.50" in captured[0]

    def test_risk_halt_subject_contains_reason(self):
        captured = []

        def fake_send(to, subject, template, **ctx):
            captured.append(subject)
            return True

        with patch("notifications.email_triggers._send", side_effect=fake_send):
            from notifications.email_triggers import send_risk_halt_email

            send_risk_halt_email(
                reason="Max drawdown breached",
                drawdown_pct=10.5,
                limit_pct=10.0,
                to="t@example.com",
            )

        assert "Max drawdown breached" in captured[0]

    def test_negative_pnl_shows_minus_sign(self):
        captured = []

        def fake_send(to, subject, template, **ctx):
            captured.append(subject)
            return True

        with patch("notifications.email_triggers._send", side_effect=fake_send):
            from notifications.email_triggers import send_daily_report_email

            send_daily_report_email(
                date="2026-03-25",
                daily_pnl=-150.0,
                daily_pnl_pct=-0.15,
                total_trades=2,
                win_rate_pct=0.0,
                equity=99_850.0,
                to="t@example.com",
            )

        assert "-150.00" in captured[0]


# ── Template context ──────────────────────────────────────────────────────────


class TestTemplateContext:
    def test_trade_fill_passes_correct_template(self):
        captured = []

        def fake_send(to, subject, template, **ctx):
            captured.append(template)
            return True

        with patch("notifications.email_triggers._send", side_effect=fake_send):
            from notifications.email_triggers import send_trade_fill_email

            send_trade_fill_email("XAUUSD", "buy", 0.1, 2050.0, to="t@e.com")

        assert captured[0] == "trade_fill.html"

    def test_daily_report_passes_correct_template(self):
        captured = []

        def fake_send(to, subject, template, **ctx):
            captured.append(template)
            return True

        with patch("notifications.email_triggers._send", side_effect=fake_send):
            from notifications.email_triggers import send_daily_report_email

            send_daily_report_email("2026-03-25", 100.0, 0.1, 2, 50.0, 100100.0, to="t@e.com")

        assert captured[0] == "daily_report.html"

    def test_risk_halt_passes_correct_template(self):
        captured = []

        def fake_send(to, subject, template, **ctx):
            captured.append(template)
            return True

        with patch("notifications.email_triggers._send", side_effect=fake_send):
            from notifications.email_triggers import send_risk_halt_email

            send_risk_halt_email("reason", 5.0, 5.0, to="t@e.com")

        assert captured[0] == "risk_halt.html"


# ── Template render failure ───────────────────────────────────────────────────


class TestTemplateRenderFailure:
    def test_render_failure_falls_back_to_none_html(self):
        """If render_email raises, _send is still called (log-only path returns True)."""
        with (
            _no_channel(),
            patch(
                "notifications.email_renderer.render_email",
                side_effect=Exception("jinja2 missing"),
            ),
        ):
            from notifications.email_triggers import send_trade_fill_email

            # Should not raise
            result = send_trade_fill_email("XAUUSD", "buy", 0.1, 2050.0, to="t@example.com")
        # Log-only path returns True even with render failure
        assert result is True
