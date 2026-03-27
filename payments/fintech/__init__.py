# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Fintech Payment Module

Handles Nigerian fintech payments via Paystack, Flutterwave, and direct bank transfers.
"""

from .paystack import PaystackClient, paystack_client
from .flutterwave import FlutterwaveClient, flutterwave_client
from .bank_transfer import BankTransferClient, bank_transfer_client

__all__ = [
    "PaystackClient",
    "paystack_client",
    "FlutterwaveClient",
    "flutterwave_client",
    "BankTransferClient",
    "bank_transfer_client",
]
