# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Payment System Module

Complete wallet and payment system for handling subscriptions and commissions.
Supports crypto (Bitcoin, USDT, Ethereum) and Nigerian fintech (Paystack, Flutterwave).
"""

# Wallet Management
from .wallet import WalletManager, WalletType, WalletStatus, Wallet, wallet_manager

# Transaction Management
from .transaction_manager import (
    TransactionManager,
    Transaction,
    TransactionType,
    TransactionStatus,
    transaction_manager,
)

# Payment Gateway
from .payment_gateway import (
    PaymentGateway,
    PaymentMethod,
    PaymentStatus,
    PaymentInfo,
    payment_gateway,
)

# Security
from .security import (
    SecurityManager,
    KYCLevel,
    KYCInfo,
    TransactionLimit,
    security_manager,
)

# Compliance
from .compliance import (
    ComplianceManager,
    RiskLevel,
    AMLCheck,
    ComplianceReport,
    compliance_manager,
)

# Crypto Payment Methods
from .crypto import (
    BitcoinClient,
    bitcoin_client,
    USDTClient,
    USDTNetwork,
    usdt_client,
    EthereumClient,
    ethereum_client,
    CryptoWalletManager,
    crypto_wallet_manager,
    AddressGenerator,
    address_generator,
)

# Fintech Payment Methods
from .fintech import (
    PaystackClient,
    paystack_client,
    FlutterwaveClient,
    flutterwave_client,
    BankTransferClient,
    bank_transfer_client,
)

__all__ = [
    # Wallet
    "WalletManager",
    "WalletType",
    "WalletStatus",
    "Wallet",
    "wallet_manager",
    # Transactions
    "TransactionManager",
    "Transaction",
    "TransactionType",
    "TransactionStatus",
    "transaction_manager",
    # Payment Gateway
    "PaymentGateway",
    "PaymentMethod",
    "PaymentStatus",
    "PaymentInfo",
    "payment_gateway",
    # Security
    "SecurityManager",
    "KYCLevel",
    "KYCInfo",
    "TransactionLimit",
    "security_manager",
    # Compliance
    "ComplianceManager",
    "RiskLevel",
    "AMLCheck",
    "ComplianceReport",
    "compliance_manager",
    # Crypto
    "BitcoinClient",
    "bitcoin_client",
    "USDTClient",
    "USDTNetwork",
    "usdt_client",
    "EthereumClient",
    "ethereum_client",
    "CryptoWalletManager",
    "crypto_wallet_manager",
    "AddressGenerator",
    "address_generator",
    # Fintech
    "PaystackClient",
    "paystack_client",
    "FlutterwaveClient",
    "flutterwave_client",
    "BankTransferClient",
    "bank_transfer_client",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Payment system with crypto and fintech support"
