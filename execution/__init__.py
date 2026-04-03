# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""execution package — re-exports from root execution.py"""

import importlib.util as _ilu
import os as _os
from pathlib import Path as _Path

_spec = _ilu.spec_from_file_location(
    "_execution_module",
    _os.path.join(str(_Path(__file__).parent.parent), "execution.py"),
)
if _spec and _spec.loader:
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    PaperExecutor = getattr(_mod, "PaperExecutor", None)
    SmartOrderRouter = getattr(_mod, "SmartOrderRouter", None)
    Order = getattr(_mod, "Order", None)
    OrderStatus = getattr(_mod, "OrderStatus", None)
    ExecutionResult = getattr(_mod, "ExecutionResult", None)

# Sub-module imports (position_tracker, trade_executor, etc.) work normally
