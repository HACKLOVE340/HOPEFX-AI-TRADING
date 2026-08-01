# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Root conftest.py — ensures both the project root and src/ are on sys.path
so that namespace packages (hopefx, src/hopefx) merge correctly.
"""

import os
import sys
from pathlib import Path

_repo_root = Path(__file__).parent
_src_dir = Path(_repo_root) / "src"

# Add src/ so that src/hopefx/* merges into the hopefx namespace package.
#
# `str(...)` matters: sys.path entries are documented as strings, and inserting
# Path objects breaks any consumer that does string operations on them. It broke
# the whole test job — hypothesis's scrutineer runs `p.endswith(".zip")` over
# sys.path at import time, so `AttributeError: 'PosixPath' object has no
# attribute 'endswith'` aborted collection for test_property_based.py and
# test_risk_properties.py, and pytest exits non-zero on a collection error
# before running anything (170 deselected, 0 run).
for _p in (_repo_root, _src_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Reduce XGBoost n_estimators from 300→50 during test runs so the full suite
# completes within the 120s pytest timeout.  Production training is unaffected
# because this env var is only set when pytest is running.
os.environ.setdefault("CI_FAST", "1")
