# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§5: the AI Core's own four behaviours.

Conversation context across active tasks, explanation depth that changes the
scaffolding and never the argument, uncertainty that has actually been checked,
and a challenger that says where an argument is thin.

The rule that binds the first two: **adapting depth must not change the
intelligence.** Every number, the counter-thesis, and what would change the
conclusion survive every register — a shorter version missing one of those is a
different argument, and the reader who asked for shorter cannot tell.
"""

from ai.core import calibration, context
from ai.core.challenger import Challenge, challenge
from ai.core.depth import DEPTHS, explain

__all__ = [
    "DEPTHS",
    "Challenge",
    "calibration",
    "challenge",
    "context",
    "explain",
]
