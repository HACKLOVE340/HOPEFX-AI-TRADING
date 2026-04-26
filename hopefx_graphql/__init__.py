# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
hopefx_graphql — GraphQL schema definitions.

Renamed from graphql/ to hopefx_graphql/ to avoid shadowing the graphql-core
library (which strawberry-graphql depends on).

The primary GraphQL router is in api/graphql_schema.py (Strawberry).
This package contains supplementary schema utilities.
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)
__all__: list[str] = []
