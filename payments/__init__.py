"""
Payment System Module

Complete wallet and payment system for handling subscriptions and commissions.
Supports crypto (Bitcoin, USDT, Ethereum) and Nigerian fintech (Paystack, Flutterwave).
"""

# Wallet Management
from .wallet import (
    WalletManager,
    WalletType,
    WalletStatus,
    Wallet,
    wallet_manager
)

# Transaction Management
from .transaction_manager import (
    TransactionManager,
    Transaction,
    TransactionType,
    TransactionStatus,
    transaction_manager
)

# Payment Gateway
from .payment_gateway import (
    PaymentGateway,
    PaymentMethod,
    PaymentStatus,
    PaymentInfo,
    payment_gateway
)

# Security
from .security import (
    SecurityManager,
    KYCLevel,
    KYCInfo,
    TransactionLimit,
    security_manager
)

# Compliance
from .compliance import (
    ComplianceManager,
    RiskLevel,
    AMLCheck,
    ComplianceReport,
    compliance_manager
)

__all__ = [
    # Wallet
    'WalletManager', 'WalletType', 'WalletStatus', 'Wallet', 'wallet_manager',
    # Transactions
    'TransactionManager', 'Transaction', 'TransactionType', 'TransactionStatus', 'transaction_manager',
    # Payment Gateway
    'PaymentGateway', 'PaymentMethod', 'PaymentStatus', 'PaymentInfo', 'payment_gateway',
    # Security
    'SecurityManager', 'KYCLevel', 'KYCInfo', 'TransactionLimit', 'security_manager',
    # Compliance
    'ComplianceManager', 'RiskLevel', 'AMLCheck', 'ComplianceReport', 'compliance_manager'
]
