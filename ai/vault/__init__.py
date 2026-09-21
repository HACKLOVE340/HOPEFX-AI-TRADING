# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The paths no AI-originated change may touch, however it is approved.

Owner requirement, 2026-09-07: the AI improves the app and itself, and must be
locked away so nobody can use it to change our code.

`ai/vault/protected.py` is that lock, and it is a FLOOR rather than a default:
configuration can add to it and can never subtract from it.
"""

from ai.vault.protected import FLOOR, Verdict, is_protected, review

__all__ = ["FLOOR", "Verdict", "is_protected", "review"]
