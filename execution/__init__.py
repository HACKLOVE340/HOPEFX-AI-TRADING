# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""execution package

Re-exports legacy paper-trading classes for backward compatibility.
New code should import directly from the relevant sub-module.
"""

from execution.legacy import (  # noqa: F401
    ExecutionResult,
    Order,
    OrderStatus,
    PaperExecutor,
    SmartOrderRouter,
)
