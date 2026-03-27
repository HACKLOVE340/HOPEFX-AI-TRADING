# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Root conftest.py — ensures both the project root and src/ are on sys.path
so that namespace packages (hopefx, src/hopefx) merge correctly.
"""

import sys
import os

_repo_root = os.path.dirname(__file__)
_src_dir = os.path.join(_repo_root, "src")

# Add src/ so that src/hopefx/* merges into the hopefx namespace package
for _p in (_repo_root, _src_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)
