# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Compatibility shim — real schema is in api/graphql_schema.py.

This package was renamed from graphql/ to hopefx_graphql/ to stop shadowing
graphql-core. Any code that previously imported from graphql.schema should
import from api.graphql_schema instead.
"""
# Do NOT import strawberry here — importing strawberry triggers graphql-core
# imports and must happen after the package rename is in effect.
# Import from api.graphql_schema instead.
