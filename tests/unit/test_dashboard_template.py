# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for dashboard/web_dashboard.py

Coverage:
- index_handler: serves HTML when template exists
- index_handler: fallback content when template is missing (FileNotFoundError)
- index_handler: fallback content when template is unreadable (OSError)
- Template file exists at dashboard/templates/dashboard.html
- Template contains expected HTML structure
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dashboard.web_dashboard import _DASHBOARD_TEMPLATE, index_handler


# ── helpers ───────────────────────────────────────────────────────────────────

class _FakeRequest:
    """Minimal aiohttp-like request stub for index_handler tests."""


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── template file ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDashboardTemplate:
    def test_template_file_exists(self):
        assert _DASHBOARD_TEMPLATE.exists(), (
            f"Dashboard template missing: {_DASHBOARD_TEMPLATE}\n"
            "Run: git status dashboard/templates/dashboard.html"
        )

    def test_template_is_html(self):
        content = _DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content or "<html" in content

    def test_template_has_title(self):
        content = _DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
        assert "<title>" in content.lower() or "HOPEFX" in content

    def test_template_not_empty(self):
        content = _DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
        assert len(content) > 100


# ── index_handler ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestIndexHandler:
    def test_serves_html_from_template(self):
        """When template exists, index_handler returns its content."""

        expected = "<html><body>HOPEFX Dashboard</body></html>"
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = expected

        async def _run_handler():
            with patch("dashboard.web_dashboard._DASHBOARD_TEMPLATE", mock_path):
                return await index_handler(_FakeRequest())

        response = _run(_run_handler())
        assert response.status == 200
        assert "HOPEFX Dashboard" in response.text

    def test_fallback_on_file_not_found(self):
        """When template is missing, returns fallback content — not an exception."""

        mock_path = MagicMock(spec=Path)
        mock_path.read_text.side_effect = FileNotFoundError("no file")

        async def _run_handler():
            with patch("dashboard.web_dashboard._DASHBOARD_TEMPLATE", mock_path):
                return await index_handler(_FakeRequest())

        response = _run(_run_handler())
        assert response.status == 200
        assert "missing" in response.text.lower() or "template" in response.text.lower()

    def test_fallback_on_os_error(self):
        """When template read raises OSError, returns fallback — not a server crash."""

        mock_path = MagicMock(spec=Path)
        mock_path.read_text.side_effect = OSError("permission denied")

        async def _run_handler():
            with patch("dashboard.web_dashboard._DASHBOARD_TEMPLATE", mock_path):
                return await index_handler(_FakeRequest())

        response = _run(_run_handler())
        assert response.status == 200
        assert "unavailable" in response.text.lower() or "template" in response.text.lower()

    def test_response_content_type_is_html(self):
        """Response content-type must be text/html."""
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = "<html></html>"

        async def _run_handler():
            with patch("dashboard.web_dashboard._DASHBOARD_TEMPLATE", mock_path):
                return await index_handler(_FakeRequest())

        response = _run(_run_handler())
        assert "text/html" in response.content_type
