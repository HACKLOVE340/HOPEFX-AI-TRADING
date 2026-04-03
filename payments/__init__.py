# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Payment System Module

Complete wallet and payment system for handling subscriptions and commissions.
Supports crypto (Bitcoin, USDT, Ethereum) and Nigerian fintech (Paystack, Flutterwave).
"""

# Wallet Management
# Compliance
from .compliance import (
    AMLCheck,
    ComplianceManager,
    ComplianceReport,
    RiskLevel,
    compliance_manager,
)

# Crypto Payment Methods
from .crypto import (
    AddressGenerator,
    BitcoinClient,
    CryptoWalletManager,
    EthereumClient,
    USDTClient,
    USDTNetwork,
    address_generator,
    bitcoin_client,
    crypto_wallet_manager,
    ethereum_client,
    usdt_client,
)

# Fintech Payment Methods
from .fintech import (
    BankTransferClient,
    FlutterwaveClient,
    PaystackClient,
    bank_transfer_client,
    flutterwave_client,
    paystack_client,
)

# Payment Gateway
from .payment_gateway import (
    PaymentGateway,
    PaymentInfo,
    PaymentMethod,
    PaymentStatus,
    payment_gateway,
)

# Security
from .security import (
    KYCInfo,
    KYCLevel,
    SecurityManager,
    TransactionLimit,
    security_manager,
)

# Transaction Management
from .transaction_manager import (
    Transaction,
    TransactionManager,
    TransactionStatus,
    TransactionType,
    transaction_manager,
)
from .wallet import Wallet, WalletManager, WalletStatus, WalletType, wallet_manager

__all__ = [
    "AMLCheck",
    "AddressGenerator",
    "BankTransferClient",
    # Crypto
    "BitcoinClient",
    # Compliance
    "ComplianceManager",
    "ComplianceReport",
    "CryptoWalletManager",
    "EthereumClient",
    "FlutterwaveClient",
    "KYCInfo",
    "KYCLevel",
    # Payment Gateway
    "PaymentGateway",
    "PaymentInfo",
    "PaymentMethod",
    "PaymentStatus",
    # Fintech
    "PaystackClient",
    "RiskLevel",
    # Security
    "SecurityManager",
    "Transaction",
    "TransactionLimit",
    # Transactions
    "TransactionManager",
    "TransactionStatus",
    "TransactionType",
    "USDTClient",
    "USDTNetwork",
    "Wallet",
    # Wallet
    "WalletManager",
    "WalletStatus",
    "WalletType",
    "address_generator",
    "bank_transfer_client",
    "bitcoin_client",
    "compliance_manager",
    "crypto_wallet_manager",
    "ethereum_client",
    "flutterwave_client",
    "payment_gateway",
    "paystack_client",
    "security_manager",
    "transaction_manager",
    "usdt_client",
    "wallet_manager",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Payment system with crypto and fintech support"
