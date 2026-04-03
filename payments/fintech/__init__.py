# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Fintech Payment Module

Handles Nigerian fintech payments via Paystack, Flutterwave, and direct bank transfers.
"""

from .bank_transfer import BankTransferClient, bank_transfer_client
from .flutterwave import FlutterwaveClient, flutterwave_client
from .paystack import PaystackClient, paystack_client

__all__ = [
    "BankTransferClient",
    "FlutterwaveClient",
    "PaystackClient",
    "bank_transfer_client",
    "flutterwave_client",
    "paystack_client",
]
