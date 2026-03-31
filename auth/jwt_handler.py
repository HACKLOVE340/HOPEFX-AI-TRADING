# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
auth/jwt_handler.py
===================
Compatibility shim — re-exports everything from auth.jwt under the
``jwt_handler`` name that several modules expect.

Import either::

    from auth.jwt import create_access_token, verify_token
    from auth.jwt_handler import create_access_token, verify_token   # same thing
"""

from auth.jwt import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    verify_token,
)

__all__ = [
    "ALGORITHM",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "verify_password",
    "verify_token",
]
