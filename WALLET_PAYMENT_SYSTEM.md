# Wallet & Payment System - Implementation Guide

## Overview

This document describes the wallet and payment system for HOPEFX AI Trading Platform that enables:
- **User deposits** via crypto (BTC, USDT, ETH) and Nigerian fintech (Paystack, Flutterwave)
- **User withdrawals** to crypto wallets and Nigerian banks
- **Admin revenue withdrawals** from subscription and commission wallets
- **Important:** No trading capital is stored - all trading money stays with brokers/prop firms

---

## Architecture

### Money Flow

```
USER FUNDS:
- Subscription payments → Platform Wallet → Admin Revenue Withdrawal
- Trading commissions → Platform Wallet → Admin Revenue Withdrawal

TRADING CAPITAL:
- Direct to Broker/Prop Firm (NOT through platform)
- Platform does NOT hold or manage trading capital
```

### Wallet Types

1. **Subscription Wallet** - Holds user subscription payments
2. **Commission Wallet** - Holds trading commission fees
3. **Admin Revenue Wallet** - Platform's collected revenue

---

## Payment Methods

### Crypto Payments

**Bitcoin (BTC):**
- Network: Bitcoin mainnet
- Confirmations required: 3
- Minimum deposit: 0.001 BTC (~$60)
- Withdrawal fee: Network fee + 0.0005 BTC
- Processing time: ~30 minutes

**USDT (Tether):**
- Networks: TRC20 (recommended), ERC20
- Confirmations: 19 (TRC20), 12 (ERC20)
- Minimum deposit: $10
- Withdrawal fee: $2 (TRC20), Network fee + $5 (ERC20)
- Processing time: 5-15 minutes (TRC20), 15-30 minutes (ERC20)

**Ethereum (ETH):**
- Network: Ethereum mainnet
- Confirmations: 12
- Minimum deposit: 0.01 ETH (~$30)
- Withdrawal fee: Network fee + 0.005 ETH
- Processing time: ~15 minutes

### Nigerian Fintech

**Paystack:**
- Deposit methods: Bank transfer, Card, USSD
- Withdrawal: Bank transfer to Nigerian banks
- Fee: 1.5% + ₦100 (capped)
- Settlement: T+1 (next business day)
- Supported banks: All Nigerian banks

**Flutterwave:**
- Deposit methods: Bank transfer, Card, Mobile money
- Withdrawal: Bank transfer to Nigerian banks
- Fee: 1.4%
- Settlement: T+1 (next business day)
- Supported banks: All Nigerian banks

---

## User Operations

### Deposit Flow

**1. Crypto Deposit:**
```
User → Select crypto (BTC/USDT/ETH)
     → System generates unique deposit address
     → User sends crypto to address
     → System monitors blockchain
     → After confirmations, wallet credited
     → Email notification sent
```

**2. Nigerian Fintech Deposit:**
```
User → Select provider (Paystack/Flutterwave)
     → System generates payment link
     → User completes payment
     → Webhook confirms payment
     → Wallet credited automatically
     → Receipt generated
```

### Withdrawal Flow

**1. Crypto Withdrawal:**
```
User → Enter amount and destination address
     → System validates address format
     → 2FA verification required
     → Admin approval (amounts > $5,000)
     → Transaction broadcast
     → Confirmation tracking
     → Email notification
```

**2. Bank Withdrawal:**
```
User → Enter bank details (Nigerian bank)
     → System validates account
     → User confirms withdrawal
     → Admin approval (amounts > $5,000)
     → Transfer initiated
     → Settlement T+1
     → SMS/Email confirmation
```

---

## Admin Operations

### Revenue Withdrawal

**Process:**
```
1. Admin views platform revenue dashboard
2. Selects withdrawal method (crypto/bank)
3. Enters amount (from subscription or commission wallet)
4. Enters destination (wallet address or bank account)
5. System calculates fees
6. Confirms withdrawal
7. Processing:
   - Crypto: Instant (after network confirmation)
   - Bank: T+1 settlement
8. Revenue transferred to admin account
```

**Withdrawal Limits:**
- Minimum: $1,000
- Maximum: No limit
- Frequency: Daily
- 2FA required: Yes

### User Withdrawal Approval

**For amounts > $5,000:**
```
1. User initiates withdrawal
2. Request appears in admin pending queue
3. Admin reviews:
   - User verification status
   - Transaction history
   - Risk assessment
4. Admin approves or rejects
5. If approved, processing begins
6. Email sent to user with status
```

---

## API Endpoints

### User Wallet API

```python
# Balance
GET /api/wallet/balance
Response: {
    "subscription_balance": 1800.00,
    "commission_balance": 150.00,
    "total_balance": 1950.00,
    "currency": "USD"
}

# Deposit - Crypto
POST /api/wallet/deposit/crypto
Request: {
    "crypto": "bitcoin|usdt|ethereum",
    "network": "mainnet|trc20|erc20"  # For USDT
}
Response: {
    "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
    "qr_code": "data:image/png;base64,...",
    "min_amount": "0.001 BTC",
    "confirmations_required": 3
}

# Deposit - Fintech
POST /api/wallet/deposit/fintech
Request: {
    "provider": "paystack|flutterwave",
    "amount": 50000.00,
    "currency": "NGN"
}
Response: {
    "payment_link": "https://paystack.com/pay/xxx",
    "reference": "PS-2026-XXX",
    "expires_at": "2026-02-13T12:00:00Z"
}

# Withdraw - Crypto
POST /api/wallet/withdraw/crypto
Request: {
    "crypto": "bitcoin|usdt|ethereum",
    "amount": 1000.00,
    "address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
    "two_factor_code": "123456"
}
Response: {
    "withdrawal_id": "WD-2026-001234",
    "amount": 1000.00,
    "fee": 5.00,
    "net_amount": 995.00,
    "status": "pending",
    "estimated_completion": "30 minutes"
}

# Withdraw - Fintech
POST /api/wallet/withdraw/fintech
Request: {
    "provider": "paystack|flutterwave",
    "amount": 500.00,
    "bank_code": "058",
    "account_number": "0123456789",
    "account_name": "John Doe",
    "two_factor_code": "123456"
}
Response: {
    "withdrawal_id": "WD-2026-001235",
    "amount": 500.00,
    "fee": 7.50,
    "net_amount": 492.50,
    "status": "pending_approval",
    "estimated_completion": "1 business day"
}

# Transaction History
GET /api/wallet/transactions?page=1&limit=20
Response: {
    "transactions": [...],
    "total": 45,
    "page": 1,
    "pages": 3
}
```

### Admin Wallet API

```python
# Platform Revenue
GET /admin/wallet/revenue
Response: {
    "subscription_revenue": 125000.00,
    "commission_revenue": 45000.00,
    "total_revenue": 170000.00,
    "pending_withdrawals": 5000.00,
    "available_for_withdrawal": 165000.00
}

# Admin Withdrawal
POST /admin/wallet/withdraw
Request: {
    "amount": 50000.00,
    "method": "bitcoin|usdt|ethereum|paystack|flutterwave",
    "destination": "bc1q... or bank_account_details",
    "wallet_type": "subscription|commission|both"
}
Response: {
    "withdrawal_id": "ADMIN-WD-2026-001",
    "amount": 50000.00,
    "fee": 25.00,
    "net_amount": 49975.00,
    "status": "processing",
    "estimated_completion": "30 minutes"
}

# Pending User Withdrawals
GET /admin/wallet/pending-withdrawals
Response: {
    "withdrawals": [
        {
            "id": "WD-2026-001234",
            "user": "john@example.com",
            "amount": 5500.00,
            "method": "bitcoin",
            "requested_at": "2026-02-13T10:00:00Z",
            "requires_approval": true
        }
    ]
}

# Approve Withdrawal
POST /admin/wallet/approve/{withdrawal_id}
Response: {
    "status": "approved",
    "withdrawal_id": "WD-2026-001234",
    "processing_started": true
}

# All Transactions
GET /admin/wallet/transactions?type=all&page=1
Response: {
    "transactions": [...],
    "total": 1234,
    "revenue_this_month": 45000.00,
    "withdrawals_this_month": 15000.00
}
```

---

## Security Features

### 2FA (Two-Factor Authentication)
- Required for all withdrawals
- TOTP-based (Google Authenticator compatible)
- Backup codes provided
- SMS fallback option

### KYC (Know Your Customer)
- Required for withdrawals > $1,000
- Document verification
- Address proof
- Selfie verification
- Processing time: 24-48 hours

### Transaction Limits

**Deposits:**
- Minimum: $10 (crypto), ₦5,000 (fintech)
- Maximum: No limit
- Daily limit: No limit

**Withdrawals:**
- Minimum: $50 (crypto), ₦10,000 (fintech)
- Maximum (unverified): $1,000/day
- Maximum (verified): $10,000/day
- Maximum (VIP): No limit

### Fraud Prevention
- IP tracking
- Device fingerprinting
- Behavioral analysis
- Velocity checks
- AML screening

---

## Database Schema

### Wallets Table
```sql
CREATE TABLE wallets (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) UNIQUE,
    subscription_balance DECIMAL(18, 8) DEFAULT 0,
    commission_balance DECIMAL(18, 8) DEFAULT 0,
    total_deposited DECIMAL(18, 8) DEFAULT 0,
    total_withdrawn DECIMAL(18, 8) DEFAULT 0,
    currency VARCHAR(10) DEFAULT 'USD',
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_wallets_user ON wallets(user_id);
CREATE INDEX idx_wallets_status ON wallets(status);
```

### Transactions Table
```sql
CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    transaction_id VARCHAR(50) UNIQUE NOT NULL,
    user_id UUID REFERENCES users(id),
    wallet_id UUID REFERENCES wallets(id),
    type VARCHAR(20) NOT NULL,  -- deposit, withdrawal, commission, subscription
    amount DECIMAL(18, 8) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    method VARCHAR(20) NOT NULL,  -- bitcoin, usdt, eth, paystack, flutterwave
    wallet_type VARCHAR(20) NOT NULL,  -- subscription, commission
    status VARCHAR(20) DEFAULT 'pending',  -- pending, completed, failed, cancelled
    reference VARCHAR(100),
    destination VARCHAR(255),  -- crypto address or bank details
    fee DECIMAL(18, 8) DEFAULT 0,
    net_amount DECIMAL(18, 8),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    cancelled_at TIMESTAMP
);

CREATE INDEX idx_transactions_user ON transactions(user_id);
CREATE INDEX idx_transactions_status ON transactions(status);
CREATE INDEX idx_transactions_type ON transactions(type);
CREATE INDEX idx_transactions_created ON transactions(created_at);
```

### Crypto Addresses Table
```sql
CREATE TABLE crypto_addresses (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    crypto VARCHAR(20) NOT NULL,  -- bitcoin, usdt, ethereum
    network VARCHAR(20),  -- mainnet, trc20, erc20
    address VARCHAR(255) NOT NULL,
    derivation_path VARCHAR(100),
    used BOOLEAN DEFAULT false,
    last_checked TIMESTAMP,
    balance DECIMAL(18, 8) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_crypto_addresses_address ON crypto_addresses(address);
CREATE INDEX idx_crypto_addresses_user ON crypto_addresses(user_id);
```

---

## Configuration

### Environment Variables

```bash
# Crypto
BITCOIN_NODE_URL=https://bitcoin.node.url
ETHEREUM_NODE_URL=https://ethereum.node.url
TRON_NODE_URL=https://tron.node.url
CRYPTO_MASTER_SEED=your_master_seed_phrase
CRYPTO_HOT_WALLET_THRESHOLD=10000  # USD

# Nigerian Fintech
PAYSTACK_SECRET_KEY=sk_live_xxx
PAYSTACK_PUBLIC_KEY=pk_live_xxx
FLUTTERWAVE_SECRET_KEY=FLWSECK_TEST-xxx
FLUTTERWAVE_PUBLIC_KEY=FLWPUBK_TEST-xxx
FLUTTERWAVE_ENCRYPTION_KEY=xxx

# Security
TWO_FACTOR_ISSUER=HOPEFX
KYC_REQUIRED_AMOUNT=1000  # USD
ADMIN_APPROVAL_THRESHOLD=5000  # USD

# Fees
CRYPTO_WITHDRAWAL_FEE_BTC=0.0005
CRYPTO_WITHDRAWAL_FEE_ETH=0.005
CRYPTO_WITHDRAWAL_FEE_USDT=2
FINTECH_DEPOSIT_FEE_PERCENT=1.5
FINTECH_WITHDRAWAL_FEE_PERCENT=1.4
```

---

## Testing

### Test Crypto Transactions

```bash
# Bitcoin Testnet
Network: testnet
Faucet: https://testnet-faucet.mempool.co/
Explorer: https://blockstream.info/testnet/

# Ethereum Goerli
Network: goerli
Faucet: https://goerlifaucet.com/
Explorer: https://goerli.etherscan.io/

# TRON Shasta
Network: shasta
Faucet: https://www.trongrid.io/shasta/
Explorer: https://shasta.tronscan.org/
```

### Test Nigerian Fintech

```bash
# Paystack Test Cards
Card: 4084084084084081
CVV: 408
Expiry: 12/30
Pin: 0000

# Flutterwave Test Cards
Card: 5531886652142950
CVV: 564
Expiry: 09/32
Pin: 3310
```

---

## Monitoring

### Metrics to Track

**Deposits:**
- Total deposits (daily, weekly, monthly)
- Average deposit amount
- Deposit success rate
- Popular payment methods

**Withdrawals:**
- Total withdrawals
- Pending approval count
- Average processing time
- Withdrawal success rate

**Revenue:**
- Subscription revenue
- Commission revenue
- Payment processing fees
- Net revenue

**Security:**
- Failed 2FA attempts
- Suspicious transactions
- KYC rejection rate
- Fraud incidents

---

## Support

### Common Issues

**1. Crypto deposit not credited:**
- Check confirmations (may take 30-60 minutes)
- Verify correct address was used
- Check blockchain explorer
- Contact support with transaction ID

**2. Withdrawal pending approval:**
- Amounts > $5,000 require admin approval
- Processing within 24 hours
- Check email for status updates

**3. Nigerian bank transfer failed:**
- Verify bank account details
- Ensure account name matches KYC
- Check if bank is supported
- Try alternative provider

---

## Important Notes

1. **No Trading Capital Storage:** The platform ONLY manages subscription and commission payments. All trading capital is managed directly by brokers and prop firms.

2. **Currency Conversion:** All amounts are stored in USD. NGN amounts are converted at current exchange rate.

3. **Withdrawal Processing:**
   - Crypto: Usually instant after approval
   - Nigerian banks: T+1 settlement

4. **Fees:** All fees are clearly displayed before transaction confirmation.

5. **Security:** Never share your wallet private keys or 2FA codes.

---

## Contact

For integration support:
- Email: support@hopefx.ai
- Documentation: https://docs.hopefx.ai/wallet
- API Reference: https://api.hopefx.ai/docs

---

**Status:** Production Ready ✅  
**Last Updated:** February 13, 2026  
**Version:** 1.0.0
