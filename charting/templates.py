# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Chart Template Management
"""

from typing import Any
from datetime import datetime, timezone

UTC = timezone.utc


class ChartTemplate:
    """Chart template"""

    def __init__(self, name: str, description: str):
        self.template_id = f"TPL_{name}_{datetime.now(UTC).timestamp()}"
        self.name = name
        self.description = description
        self.config = {}
        self.created_at = datetime.now(UTC)


class TemplateManager:
    """Manages chart templates"""

    def __init__(self):
        self.templates: dict[str, ChartTemplate] = {}

    def save_template(self, name: str, description: str, config: dict[str, Any]) -> ChartTemplate:
        """Save a chart template"""
        template = ChartTemplate(name, description)
        template.config = config

        self.templates[template.template_id] = template
        return template

    def load_template(self, template_id: str) -> ChartTemplate:
        """Load a template"""
        return self.templates.get(template_id)

    def list_templates(self) -> list:
        """List all templates"""
        return list(self.templates.values())
