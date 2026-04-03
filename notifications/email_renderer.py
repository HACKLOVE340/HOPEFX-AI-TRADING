# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Email template renderer using Jinja2.

Usage:
    from notifications.email_renderer import render_email

    html = render_email("alert.html", symbol="XAUUSD", price="$2,345.60", ...)
"""

import logging
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    _env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    JINJA2_AVAILABLE = True
except ImportError:
    _env = None  # type: ignore[assignment]
    JINJA2_AVAILABLE = False
    logger.warning("jinja2 not installed — email HTML templates unavailable")


def render_email(template_name: str, **context: Any) -> str:
    """
    Render an email template to an HTML string.

    Falls back to a plain-text representation when Jinja2 is not installed.

    Args:
        template_name: Filename inside notifications/templates/ (e.g. "alert.html").
        **context:     Template variables.

    Returns:
        Rendered HTML string.
    """
    # Inject common defaults
    context.setdefault("sent_at", datetime.now(UTC).strftime("%Y-%m-%d %H:%M"))
    context.setdefault("unsubscribe_url", "#")

    if not JINJA2_AVAILABLE or _env is None:
        # Plain-text fallback
        lines = [f"HOPEFX Notification — {template_name}"]
        for key, value in context.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    try:
        template = _env.get_template(template_name)
        return template.render(**context)
    except Exception as exc:
        logger.error("Failed to render email template %s: %s", template_name, exc)
        # Return minimal fallback so the send still proceeds
        return (
            f"<p><strong>HOPEFX Notification</strong></p><p>Template rendering failed ({exc}). Context: {context}</p>"
        )
