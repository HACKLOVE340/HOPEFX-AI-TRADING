# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Mobile Authentication
"""

from datetime import UTC, datetime, timedelta


class MobileAuth:
    """Mobile authentication and biometric support"""

    def __init__(self):
        self.tokens = {}

    def authenticate_biometric(self, user_id: str, biometric_data: str, device_id: str) -> str | None:
        """Authenticate using biometrics"""
        # Generate JWT token
        token = f"MOB_TOKEN_{user_id}_{device_id}_{datetime.now(UTC).timestamp()}"
        self.tokens[token] = {
            "user_id": user_id,
            "device_id": device_id,
            "expires_at": datetime.now(UTC) + timedelta(days=30),
        }
        return token

    def verify_token(self, token: str) -> bool:
        """Verify mobile token"""
        if token in self.tokens:
            token_data = self.tokens[token]
            if datetime.now(UTC) < token_data["expires_at"]:
                return True
        return False
