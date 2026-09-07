# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The AI reading its own code, and the app's, and reporting what it sees.

Owner request, 2026-09-07: an agent walking through all the code in the app,
including the AI itself.

**This package reports and cannot act.** It does not import `ai.tools`, calls
nothing that writes to disk, and a test parses every module here to keep both
true. Acting on a finding is `security/self_healer.py`'s job, behind
`ai/vault/protected.py` and the two-approver policy in `ai/policy/roles.py`.
"""

from ai.improve.finding import Finding
from ai.improve.walker import CHECKS, WalkReport, walk

__all__ = ["CHECKS", "Finding", "WalkReport", "walk"]
