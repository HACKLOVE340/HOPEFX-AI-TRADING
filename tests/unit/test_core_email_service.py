# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_email_service.py
======================================
Coverage tests for core/email_service.py.

External transports (SendGrid, SMTP) are patched at the boundary.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

import core.email_service as svc


# ── _smtp_config ──────────────────────────────────────────────────────────────


def test_smtp_config_none_when_no_host(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert svc._smtp_config() is None


def test_smtp_config_returns_dict(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("FROM_EMAIL", "noreply@example.com")
    cfg = svc._smtp_config()
    assert cfg is not None
    assert cfg["host"] == "smtp.example.com"
    assert cfg["port"] == 465
    assert cfg["from_email"] == "noreply@example.com"


def test_smtp_config_default_port(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.delenv("SMTP_PORT", raising=False)
    cfg = svc._smtp_config()
    assert cfg["port"] == 587


# ── _send — dev fallback (no transport) ──────────────────────────────────────


def test_send_dev_fallback_returns_true(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    result = svc._send("user@test.com", "Subject", "<p>html</p>", "text")
    assert result is True


# ── _send_via_sendgrid ────────────────────────────────────────────────────────


def test_send_via_sendgrid_success(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake")
    monkeypatch.setenv("FROM_EMAIL", "noreply@hopefx.io")

    mock_response = MagicMock()
    mock_response.status_code = 202

    mock_sg = MagicMock()
    mock_sg.send.return_value = mock_response

    with patch.dict("sys.modules", {
        "sendgrid": MagicMock(SendGridAPIClient=MagicMock(return_value=mock_sg)),
        "sendgrid.helpers.mail": MagicMock(Mail=MagicMock()),
    }):
        result = svc._send_via_sendgrid("to@test.com", "Subj", "<p>h</p>", "t")
    assert result is True


def test_send_via_sendgrid_error_status(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake")
    monkeypatch.setenv("FROM_EMAIL", "noreply@hopefx.io")

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.body = "error"

    mock_sg = MagicMock()
    mock_sg.send.return_value = mock_response

    with patch.dict("sys.modules", {
        "sendgrid": MagicMock(SendGridAPIClient=MagicMock(return_value=mock_sg)),
        "sendgrid.helpers.mail": MagicMock(Mail=MagicMock()),
    }):
        result = svc._send_via_sendgrid("to@test.com", "Subj", "<p>h</p>", "t")
    assert result is False


def test_send_via_sendgrid_exception(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake")
    with patch.dict("sys.modules", {
        "sendgrid": MagicMock(SendGridAPIClient=MagicMock(side_effect=Exception("network"))),
        "sendgrid.helpers.mail": MagicMock(Mail=MagicMock()),
    }):
        result = svc._send_via_sendgrid("to@test.com", "Subj", "<p>h</p>", "t")
    assert result is False


# ── _send_via_smtp ────────────────────────────────────────────────────────────


def test_send_via_smtp_no_config(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    result = svc._send_via_smtp("to@test.com", "Subj", "<p>h</p>", "t")
    assert result is False


def test_send_via_smtp_success(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "true")

    mock_server = MagicMock()
    mock_server.__enter__ = MagicMock(return_value=mock_server)
    mock_server.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_server):
        result = svc._send_via_smtp("to@test.com", "Subj", "<p>h</p>", "t")
    assert result is True


def test_send_via_smtp_exception(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "true")

    with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
        result = svc._send_via_smtp("to@test.com", "Subj", "<p>h</p>", "t")
    assert result is False


def test_send_via_smtp_ssl_path(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")

    mock_server = MagicMock()
    mock_server.__enter__ = MagicMock(return_value=mock_server)
    mock_server.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP_SSL", return_value=mock_server):
        result = svc._send_via_smtp("to@test.com", "Subj", "<p>h</p>", "t")
    assert result is True


# ── Public API ────────────────────────────────────────────────────────────────


def test_send_verification_email_dev(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr(svc, "APP_ENV", "development")
    result = svc.send_verification_email("user@test.com", "Alice", "tok123")
    assert result is True


def test_send_password_reset_email_dev(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr(svc, "APP_ENV", "development")
    result = svc.send_password_reset_email("user@test.com", "Bob", "reset456")
    assert result is True


def test_send_login_alert_dev(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    result = svc.send_login_alert("user@test.com", "Carol", "1.2.3.4", "Chrome/Linux")
    assert result is True


def test_send_login_alert_unknown_device(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    result = svc.send_login_alert("user@test.com", "Dave", "10.0.0.1", "")
    assert result is True


def test_send_prefers_sendgrid_over_smtp(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

    called = []

    def _fake_sg(to, subj, html, text):
        called.append("sendgrid")
        return True

    with patch.object(svc, "_send_via_sendgrid", _fake_sg):
        svc._send("to@test.com", "S", "<p/>", "t")

    assert called == ["sendgrid"]
