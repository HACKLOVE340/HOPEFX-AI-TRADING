# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Bitcoin Payment Integration

Handles Bitcoin deposits and withdrawals using BIP84 (native SegWit / bech32)
HD wallet derivation via the hdwallet library.

Derivation path: m/84'/0'/0'/0/{index}  (BIP84 — P2WPKH, bech32 addresses)

The master mnemonic is loaded from the BITCOIN_MNEMONIC environment variable.
In production this secret must be stored in a secrets manager (Vault, AWS
Secrets Manager, etc.) and injected at runtime — never committed to source.
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal

try:
    # hdwallet v3+ — BIP39Mnemonic.from_entropy() is the generator
    from hdwallet import HDWallet
    from hdwallet.mnemonics import BIP39Mnemonic as _BIP39Mnemonic

    def generate_mnemonic(language: str = "english", strength: int = 128) -> str:  # type: ignore[misc]
        # strength is in bits (128 = 12 words, 256 = 24 words)
        entropy_bytes = os.urandom(strength // 8)
        return _BIP39Mnemonic.from_entropy(entropy=entropy_bytes.hex(), language=language)

    BTC = "BTC"
    _HDWALLET_AVAILABLE = True
except ImportError:
    try:
        # hdwallet v2 fallback
        from hdwallet import HDWallet  # type: ignore[assignment]
        from hdwallet.symbols import BTC  # type: ignore[assignment]
        from hdwallet.utils import generate_mnemonic  # type: ignore[assignment]

        _HDWALLET_AVAILABLE = True
    except ImportError:
        # hdwallet not installed — Bitcoin features unavailable
        HDWallet = None  # type: ignore[assignment,misc]
        BTC = "BTC"
        _HDWALLET_AVAILABLE = False

        def generate_mnemonic(language: str = "english", strength: int = 128) -> str:  # type: ignore[misc]
            raise RuntimeError("Bitcoin features require the 'hdwallet' package. Install it with: pip install hdwallet")


logger = logging.getLogger(__name__)

# BIP84 derivation path components for native SegWit (bech32 bc1q… addresses)
_BIP84_PURPOSE = "84'"
_BIP84_COIN = "0'"  # mainnet BTC
_BIP84_ACCOUNT = "0'"
_BIP84_CHANGE = "0"  # external chain (receiving addresses)


def _load_mnemonic() -> str:
    """
    Load the HD wallet mnemonic from the environment.

    Raises RuntimeError in production if the variable is absent so the
    application fails fast rather than silently generating unrecoverable
    addresses.
    """
    mnemonic = os.getenv("BITCOIN_MNEMONIC", "").strip()
    if not mnemonic:
        env = os.getenv("APP_ENV", "development").lower()
        if env == "production":
            raise RuntimeError(
                "BITCOIN_MNEMONIC environment variable is required in production. "
                "Set it to a BIP39 mnemonic stored in your secrets manager."
            )
        # Non-production: generate a fresh ephemeral mnemonic and warn loudly.
        mnemonic = generate_mnemonic(language="english", strength=256)
        logger.warning(
            "BITCOIN_MNEMONIC not set — using ephemeral mnemonic. "
            "Addresses will change on restart. Set BITCOIN_MNEMONIC for persistence."
        )
    return mnemonic


@dataclass
class BitcoinAddress:
    """Bitcoin address information"""

    address: str
    user_id: str
    derivation_path: str
    created_at: datetime
    last_used: datetime | None = None


@dataclass
class BitcoinTransaction:
    """Bitcoin transaction"""

    tx_hash: str
    address: str
    amount: Decimal
    confirmations: int
    status: str
    created_at: datetime


class BitcoinClient:
    """
    Bitcoin payment client with BIP84 HD wallet support.

    Each user receives a unique bech32 deposit address derived from the master
    mnemonic at path m/84'/0'/0'/0/{index}.  The same mnemonic always produces
    the same address for a given index, so addresses survive restarts as long as
    BITCOIN_MNEMONIC is stable.
    """

    REQUIRED_CONFIRMATIONS = 3
    MIN_DEPOSIT = Decimal("0.001")  # BTC
    NETWORK_FEE = Decimal("0.0005")  # BTC (conservative estimate)

    def __init__(self) -> None:
        if not _HDWALLET_AVAILABLE:
            raise RuntimeError("BitcoinClient requires the 'hdwallet' package. Install it with: pip install hdwallet")
        self._mnemonic: str = _load_mnemonic()
        # user_id -> list of derived address strings (in derivation order)
        self.user_addresses: dict[str, list[str]] = {}
        # address string -> BitcoinAddress metadata
        self.addresses: dict[str, BitcoinAddress] = {}
        # tx_hash -> BitcoinTransaction
        self.transactions: dict[str, BitcoinTransaction] = {}

    # ── Address derivation ────────────────────────────────────────────────────

    def _derive_address(self, index: int) -> tuple[str, str]:
        """
        Derive a BIP84 P2WPKH (bech32) address at the given index.

        Returns:
            (address, derivation_path)
        """
        path = f"m/{_BIP84_PURPOSE}/{_BIP84_COIN}/{_BIP84_ACCOUNT}/{_BIP84_CHANGE}/{index}"
        wallet = HDWallet(symbol=BTC, semantic="p2wpkh")
        wallet.from_mnemonic(self._mnemonic)
        wallet.from_path(path)
        address: str = wallet.p2wpkh_address()
        return address, path

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_deposit_address(self, user_id: str) -> dict:
        """
        Generate (or return the next unused) BIP84 deposit address for a user.

        Each call advances the address index so every deposit request gets a
        fresh address, improving privacy and simplifying reconciliation.

        Returns:
            Dict with address, qr_code URI, network, min_deposit,
            confirmations_required
        """
        index = len(self.user_addresses.get(user_id, []))
        address, path = self._derive_address(index)

        btc_address = BitcoinAddress(
            address=address,
            user_id=user_id,
            derivation_path=path,
            created_at=datetime.now(UTC),
        )
        self.addresses[address] = btc_address
        self.user_addresses.setdefault(user_id, []).append(address)

        logger.info(
            "Generated BTC deposit address for user %s: %s (path=%s)",
            user_id,
            address,
            path,
        )
        return {
            "address": address,
            "qr_code": f"bitcoin:{address}",
            "network": "bitcoin",
            "min_deposit": float(self.MIN_DEPOSIT),
            "confirmations_required": self.REQUIRED_CONFIRMATIONS,
        }

    def process_deposit(
        self,
        user_id: str,
        amount: Decimal,
        tx_hash: str,
        confirmations: int = 0,
    ) -> BitcoinTransaction | None:
        """
        Record or update a Bitcoin deposit transaction.

        Args:
            user_id: User ID
            amount: Amount in BTC
            tx_hash: On-chain transaction hash
            confirmations: Current confirmation count

        Returns:
            BitcoinTransaction or None if validation fails
        """
        if amount < self.MIN_DEPOSIT:
            logger.warning("Deposit below minimum: %s BTC (user=%s)", amount, user_id)
            return None

        if tx_hash in self.transactions:
            self.transactions[tx_hash].confirmations = confirmations
            if confirmations >= self.REQUIRED_CONFIRMATIONS:
                self.transactions[tx_hash].status = "confirmed"
            return self.transactions[tx_hash]

        user_addrs = self.user_addresses.get(user_id, [])
        if not user_addrs:
            logger.error("No deposit address found for user %s", user_id)
            return None

        address = user_addrs[-1]
        status = "confirmed" if confirmations >= self.REQUIRED_CONFIRMATIONS else "pending"

        transaction = BitcoinTransaction(
            tx_hash=tx_hash,
            address=address,
            amount=amount,
            confirmations=confirmations,
            status=status,
            created_at=datetime.now(UTC),
        )
        self.transactions[tx_hash] = transaction

        if address in self.addresses:
            self.addresses[address].last_used = datetime.now(UTC)

        logger.info(
            "BTC deposit recorded: tx=%s amount=%s BTC confirmations=%d user=%s",
            tx_hash,
            amount,
            confirmations,
            user_id,
        )
        return transaction

    def process_withdrawal(
        self,
        user_id: str,
        amount: Decimal,
        destination_address: str,
    ) -> dict:
        """
        Prepare a Bitcoin withdrawal.

        In production this method should broadcast the signed transaction via a
        Bitcoin node or a custody API (e.g. BitGo, Fireblocks).  The tx_hash
        returned here is a deterministic placeholder until the broadcast step
        is wired in.

        Args:
            user_id: User ID
            amount: Amount in BTC to send
            destination_address: Recipient bech32 / legacy address

        Returns:
            Withdrawal summary dict
        """
        if not self._validate_address(destination_address):
            raise ValueError(f"Invalid Bitcoin address: {destination_address!r}")

        net_amount = amount - self.NETWORK_FEE
        if net_amount <= 0:
            raise ValueError(f"Amount {amount} BTC is too small after network fee {self.NETWORK_FEE} BTC")

        # Deterministic placeholder txid — replace with real broadcast result.
        tx_hash = hashlib.sha256(f"{user_id}{amount}{destination_address}{time.time_ns()}".encode()).hexdigest()

        logger.info(
            "BTC withdrawal prepared: tx=%s amount=%s BTC to=%s user=%s",
            tx_hash,
            amount,
            destination_address,
            user_id,
        )
        return {
            "tx_hash": tx_hash,
            "user_id": user_id,
            "amount": float(amount),
            "fee": float(self.NETWORK_FEE),
            "net_amount": float(net_amount),
            "destination": destination_address,
            "status": "broadcasting",
            "created_at": datetime.now(UTC).isoformat(),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _validate_address(self, address: str) -> bool:
        """Validate Bitcoin address format (bech32, P2PKH, P2SH)."""
        if address.startswith("bc1"):  # native SegWit bech32
            return 42 <= len(address) <= 62
        if address.startswith(("1", "3")):  # legacy P2PKH / P2SH
            return 26 <= len(address) <= 35
        return False

    def get_transaction_status(self, tx_hash: str) -> dict | None:
        """Return status dict for a known transaction, or None."""
        tx = self.transactions.get(tx_hash)
        if not tx:
            return None
        return {
            "tx_hash": tx.tx_hash,
            "address": tx.address,
            "amount": float(tx.amount),
            "confirmations": tx.confirmations,
            "status": tx.status,
            "created_at": tx.created_at.isoformat(),
        }

    def get_user_transactions(self, user_id: str) -> list[dict]:
        """Return all transactions for a user, newest first."""
        user_addrs = set(self.user_addresses.get(user_id, []))
        txs = [
            {
                "tx_hash": tx.tx_hash,
                "amount": float(tx.amount),
                "confirmations": tx.confirmations,
                "status": tx.status,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in self.transactions.values()
            if tx.address in user_addrs
        ]
        txs.sort(key=lambda x: x["created_at"], reverse=True)
        return txs


# Module-level singleton — lazily initialised on first use so that importing
# this module does not crash when hdwallet is not installed.
_bitcoin_client: "BitcoinClient | None" = None


def get_bitcoin_client() -> "BitcoinClient":
    """Return the module-level BitcoinClient singleton, creating it on first call."""
    global _bitcoin_client
    if _bitcoin_client is None:
        _bitcoin_client = BitcoinClient()
    return _bitcoin_client


# Legacy alias kept for backwards compatibility — resolves lazily.
class _LazyBitcoinClient:
    """Proxy that forwards attribute access to the real BitcoinClient singleton."""

    def __getattr__(self, name: str):  # type: ignore[override]
        return getattr(get_bitcoin_client(), name)


bitcoin_client = _LazyBitcoinClient()  # type: ignore[assignment]
