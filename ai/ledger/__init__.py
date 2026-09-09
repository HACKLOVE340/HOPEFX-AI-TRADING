# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The Decision Ledger and its outcome linkage — Group 3 Chapters 7 and 8.

`decisions` records what an automated actor decided, including what it refused.
`outcomes` closes the loop: what was predicted, what was observed, and what was
learned.

Kept apart from `ai/memory/`, which is the operator's view of what the AI
remembers, and from `ai/gateway/audit.py`, which records model *calls*. This is
neither: it is one schema across every actor, which is the thing that turns
per-component logging into a ledger somebody can query.
"""

from __future__ import annotations

__all__ = ["decisions", "outcomes"]
