# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
whitelabel/branding.py
======================
Brand theme management for white-label tenants.

Generates CSS custom properties, validates colour values, and produces
a complete brand manifest (colours, fonts, logo, favicon) that the
frontend injects at runtime via the /api/whitelabel/tenants/{id}/preview
endpoint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Validation ────────────────────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _validate_hex(value: str, field_name: str) -> str:
    """Validate and normalise a CSS hex colour. Raises ValueError on bad input."""
    v = value.strip()
    if not _HEX_RE.match(v):
        raise ValueError(f"{field_name} must be a valid CSS hex colour (e.g. #3b82f6), got: {v!r}")
    # Expand 3-digit shorthand to 6-digit
    if len(v) == 4:
        v = "#" + "".join(c * 2 for c in v[1:])
    return v.lower()


# ── Brand theme dataclass ─────────────────────────────────────────────────────


@dataclass
class BrandTheme:
    """
    Complete visual identity for a white-label tenant.

    All colour fields accept CSS hex values (#rrggbb or #rgb).
    """

    company_name: str = "HopeFX"
    logo_url: str = ""
    favicon_url: str = ""

    # Colours
    primary_color: str = "#3b82f6"  # buttons, links, active states
    secondary_color: str = "#1e293b"  # cards, panels
    accent_color: str = "#22c55e"  # positive P&L, buy buttons
    danger_color: str = "#ef4444"  # negative P&L, sell buttons
    background_color: str = "#0f172a"  # page background
    surface_color: str = "#1e293b"  # card/panel background
    text_primary: str = "#f1f5f9"  # primary text
    text_secondary: str = "#94a3b8"  # secondary/muted text
    border_color: str = "#334155"  # borders, dividers

    # Typography
    font_family: str = "'Inter', system-ui, sans-serif"
    font_size_base: str = "14px"

    # Custom CSS injected into the tenant's dashboard (sanitised)
    custom_css: str = ""

    def validate(self) -> BrandTheme:
        """Validate all colour fields in-place. Returns self for chaining."""
        colour_fields = [
            "primary_color",
            "secondary_color",
            "accent_color",
            "danger_color",
            "background_color",
            "surface_color",
            "text_primary",
            "text_secondary",
            "border_color",
        ]
        for f in colour_fields:
            val = getattr(self, f)
            if val:
                setattr(self, f, _validate_hex(val, f))
        return self

    def to_css_vars(self) -> str:
        """
        Generate a CSS :root block with custom properties for this theme.

        Inject this into the tenant's HTML <head> to apply branding.
        """
        return f""":root {{
  --color-primary:    {self.primary_color};
  --color-secondary:  {self.secondary_color};
  --color-accent:     {self.accent_color};
  --color-danger:     {self.danger_color};
  --color-bg:         {self.background_color};
  --color-surface:    {self.surface_color};
  --color-text:       {self.text_primary};
  --color-muted:      {self.text_secondary};
  --color-border:     {self.border_color};
  --font-family:      {self.font_family};
  --font-size-base:   {self.font_size_base};
}}
{self.custom_css}"""

    def to_manifest(self) -> dict[str, str]:
        """Return a JSON-serialisable dict for the frontend brand manifest."""
        return {
            "company_name": self.company_name,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "accent_color": self.accent_color,
            "danger_color": self.danger_color,
            "background_color": self.background_color,
            "surface_color": self.surface_color,
            "text_primary": self.text_primary,
            "text_secondary": self.text_secondary,
            "border_color": self.border_color,
            "font_family": self.font_family,
            "font_size_base": self.font_size_base,
            "css_vars": self.to_css_vars(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> BrandTheme:
        """Construct a BrandTheme from a dict, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ── Default themes per tier ───────────────────────────────────────────────────

DEFAULT_THEMES: dict[str, BrandTheme] = {
    "starter": BrandTheme(
        company_name="HopeFX Partner",
        primary_color="#3b82f6",
    ),
    "growth": BrandTheme(
        company_name="HopeFX Pro",
        primary_color="#8b5cf6",
        accent_color="#a78bfa",
    ),
    "enterprise": BrandTheme(
        company_name="HopeFX Enterprise",
        primary_color="#f59e0b",
        accent_color="#fbbf24",
    ),
}
