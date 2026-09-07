# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§25: whether the AI may watch, listen, or remember — asked in one place.

`ai/privacy/consent.py` is that place. It exists before §18's ambient
awareness for the same reason `ai/vault/protected.py` existed before the code
walker: a containment that arrives after the thing it contains is not a
containment, it is an apology.
"""

from ai.privacy.consent import SENSORS, Decision, check, grant, revoke, revoke_all, snapshot

__all__ = ["SENSORS", "Decision", "check", "grant", "revoke", "revoke_all", "snapshot"]
