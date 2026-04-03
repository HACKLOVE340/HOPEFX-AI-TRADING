# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Crypto Payment Module

Handles cryptocurrency payments including Bitcoin, USDT, and Ethereum.
"""

from .address_generator import AddressGenerator, address_generator
from .bitcoin import BitcoinClient, bitcoin_client
from .ethereum import EthereumClient, ethereum_client
from .usdt import USDTClient, USDTNetwork, usdt_client
from .wallet_manager import CryptoWalletManager, crypto_wallet_manager

__all__ = [
    "AddressGenerator",
    "BitcoinClient",
    "CryptoWalletManager",
    "EthereumClient",
    "USDTClient",
    "USDTNetwork",
    "address_generator",
    "bitcoin_client",
    "crypto_wallet_manager",
    "ethereum_client",
    "usdt_client",
]
