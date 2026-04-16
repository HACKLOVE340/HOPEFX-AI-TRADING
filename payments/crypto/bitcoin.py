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

Withdrawal broadcast priority
------------------------------
1. BitGo custody API  (BITGO_ACCESS_TOKEN + BITGO_WALLET_ID set)
2. Fireblocks custody API  (FIREBLOCKS_API_KEY + FIREBLOCKS_API_SECRET + FIREBLOCKS_VAULT_ACCOUNT_ID set)
3. Bitcoin Core RPC  (BITCOIN_RPC_URL set, e.g. http://user:pass@localhost:8332)
4. BlockCypher public API  (BLOCKCYPHER_TOKEN + BITCOIN_WIF_PRIVATE_KEY + BITCOIN_SOURCE_ADDRESS)

At least one of the above must be configured in production.  The application
raises RuntimeError at withdrawal time if none are available and APP_ENV=production.
"""

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


# =============================================================================
# Broadcast backends
# =============================================================================


async def _broadcast_via_bitgo(
    destination_address: str,
    amount_btc: Decimal,
    fee_btc: Decimal,
) -> str:
    """
    Broadcast a withdrawal via the BitGo custody API.

    Required env vars:
        BITGO_ACCESS_TOKEN  — long-lived API token from BitGo dashboard
        BITGO_WALLET_ID     — wallet ID (hex string) to send from
        BITGO_PASSPHRASE    — wallet passphrase for signing (optional if using
                              BitGo's server-side signing / HSM)
        BITGO_ENV           — "prod" (default) or "test" for BitGo testnet

    Returns the on-chain txid string.
    Raises RuntimeError on API error.
    """
    import httpx

    token = os.environ["BITGO_ACCESS_TOKEN"]
    wallet_id = os.environ["BITGO_WALLET_ID"]
    passphrase = os.getenv("BITGO_PASSPHRASE", "")
    bitgo_env = os.getenv("BITGO_ENV", "prod")

    base_url = (
        "https://app.bitgo.com/api/v2"
        if bitgo_env == "prod"
        else "https://app.bitgo-test.com/api/v2"
    )

    # BitGo uses integer satoshis
    amount_sat = int(amount_btc * Decimal("100000000"))
    fee_sat = int(fee_btc * Decimal("100000000"))

    payload: dict = {
        "address": destination_address,
        "amount": amount_sat,
        "feeRate": fee_sat,
        "walletPassphrase": passphrase,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base_url}/btc/wallet/{wallet_id}/sendcoins",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"BitGo API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    txid: str = data.get("txid") or data.get("tx", {}).get("txid", "")
    if not txid:
        raise RuntimeError(f"BitGo response missing txid: {data}")

    logger.info("BitGo broadcast succeeded: txid=%s", txid)
    return txid


async def _broadcast_via_fireblocks(
    destination_address: str,
    amount_btc: Decimal,
) -> str:
    """
    Broadcast a withdrawal via the Fireblocks custody API.

    Required env vars:
        FIREBLOCKS_API_KEY          — API key from Fireblocks console
        FIREBLOCKS_API_SECRET       — path to RSA private key PEM file, OR the
                                      PEM content itself (newlines as \\n)
        FIREBLOCKS_VAULT_ACCOUNT_ID — source vault account ID (integer string)

    Returns the Fireblocks transaction ID (prefixed "fireblocks:") until the
    on-chain txHash is confirmed.  Poll GET /v1/transactions/{id} for the real hash.
    Raises RuntimeError on API error.
    """
    import hashlib as _hashlib
    import json as _json
    import time as _time

    import httpx

    try:
        import jwt as _jwt  # PyJWT
    except ImportError as exc:
        raise RuntimeError(
            "Fireblocks integration requires PyJWT: pip install PyJWT cryptography"
        ) from exc

    api_key = os.environ["FIREBLOCKS_API_KEY"]
    secret_raw = os.environ["FIREBLOCKS_API_SECRET"]
    vault_id = os.environ["FIREBLOCKS_VAULT_ACCOUNT_ID"]

    # Secret may be a file path or inline PEM
    if os.path.isfile(secret_raw):
        with open(secret_raw) as f:
            private_key_pem = f.read()
    else:
        private_key_pem = secret_raw.replace("\\n", "\n")

    base_url = os.getenv("FIREBLOCKS_BASE_URL", "https://api.fireblocks.io")

    body = {
        "assetId": "BTC",
        "source": {"type": "VAULT_ACCOUNT", "id": vault_id},
        "destination": {
            "type": "ONE_TIME_ADDRESS",
            "oneTimeAddress": {"address": destination_address},
        },
        "amount": str(amount_btc),
        "note": f"HOPEFX withdrawal {datetime.now(UTC).isoformat()}",
    }
    body_str = _json.dumps(body)
    body_hash = _hashlib.sha256(body_str.encode()).hexdigest()

    path = "/v1/transactions"
    now = int(_time.time())
    claims = {
        "uri": path,
        "nonce": f"{now}-{os.urandom(8).hex()}",
        "iat": now,
        "exp": now + 30,
        "sub": api_key,
        "bodyHash": body_hash,
    }
    token = _jwt.encode(claims, private_key_pem, algorithm="RS256")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base_url}{path}",
            content=body_str,
            headers={
                "X-API-Key": api_key,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Fireblocks API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    fb_id: str = data.get("id", "")
    # txHash is populated asynchronously; return Fireblocks ID until confirmed
    txid = data.get("txHash") or f"fireblocks:{fb_id}"
    logger.info("Fireblocks broadcast submitted: id=%s txHash=%s", fb_id, txid)
    return txid


async def _broadcast_via_bitcoin_rpc(
    destination_address: str,
    amount_btc: Decimal,
) -> str:
    """
    Broadcast via a local/remote Bitcoin Core node using JSON-RPC.

    Required env vars:
        BITCOIN_RPC_URL — full URL including credentials, e.g.
                          http://rpcuser:rpcpass@localhost:8332

    The wallet must be loaded and have sufficient funds.
    Returns the txid string.
    """
    import httpx

    rpc_url = os.environ["BITCOIN_RPC_URL"]

    payload = {
        "jsonrpc": "1.0",
        "id": f"hopefx-{int(time.time_ns())}",
        "method": "sendtoaddress",
        "params": [
            destination_address,
            float(amount_btc),
            "",    # comment
            "",    # comment_to
            True,  # subtractfeefromamount — fee deducted from the sent amount
        ],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Bitcoin RPC HTTP error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"Bitcoin RPC error: {data['error']}")

    txid: str = data["result"]
    logger.info("Bitcoin RPC broadcast succeeded: txid=%s", txid)
    return txid


async def _broadcast_via_blockcypher(
    destination_address: str,
    amount_btc: Decimal,
    fee_btc: Decimal,
    source_address: str,
    wif_private_key: str,
) -> str:
    """
    Broadcast via BlockCypher's transaction API (non-custodial).

    Requires the WIF-encoded private key for the source address so the
    transaction can be signed client-side before submission.

    Required env vars:
        BLOCKCYPHER_TOKEN       — API token (optional but raises rate limits)
        BITCOIN_WIF_PRIVATE_KEY — WIF-encoded private key for the hot wallet
        BITCOIN_SOURCE_ADDRESS  — corresponding Bitcoin address

    Returns the txid string.
    """
    try:
        import blockcypher  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "BlockCypher integration requires blockcypher-cli: pip install blockcypher"
        ) from exc

    token = os.getenv("BLOCKCYPHER_TOKEN", "")
    amount_sat = int(amount_btc * Decimal("100000000"))

    tx = blockcypher.simple_spend(
        from_privkey=wif_private_key,
        to_address=destination_address,
        to_satoshis=amount_sat,
        change_address=source_address,
        privkey_is_compressed=True,
        api_key=token or None,
        coin_symbol="btc",
    )

    txid: str = tx.get("tx", {}).get("hash", "")
    if not txid:
        raise RuntimeError(f"BlockCypher response missing hash: {tx}")

    logger.info("BlockCypher broadcast succeeded: txid=%s", txid)
    return txid


async def _broadcast_withdrawal(
    destination_address: str,
    amount_btc: Decimal,
    fee_btc: Decimal,
    source_address: str = "",
) -> str:
    """
    Attempt each broadcast backend in priority order.

    Priority:
        1. BitGo  (BITGO_ACCESS_TOKEN + BITGO_WALLET_ID)
        2. Fireblocks  (FIREBLOCKS_API_KEY + FIREBLOCKS_API_SECRET + FIREBLOCKS_VAULT_ACCOUNT_ID)
        3. Bitcoin Core RPC  (BITCOIN_RPC_URL)
        4. BlockCypher  (BITCOIN_WIF_PRIVATE_KEY + BITCOIN_SOURCE_ADDRESS)

    Raises RuntimeError if no backend is configured or all fail.
    """
    errors: list[str] = []

    # 1. BitGo
    if os.getenv("BITGO_ACCESS_TOKEN") and os.getenv("BITGO_WALLET_ID"):
        try:
            return await _broadcast_via_bitgo(destination_address, amount_btc, fee_btc)
        except Exception as exc:
            logger.error("BitGo broadcast failed: %s", exc)
            errors.append(f"BitGo: {exc}")

    # 2. Fireblocks
    if (
        os.getenv("FIREBLOCKS_API_KEY")
        and os.getenv("FIREBLOCKS_API_SECRET")
        and os.getenv("FIREBLOCKS_VAULT_ACCOUNT_ID")
    ):
        try:
            return await _broadcast_via_fireblocks(destination_address, amount_btc)
        except Exception as exc:
            logger.error("Fireblocks broadcast failed: %s", exc)
            errors.append(f"Fireblocks: {exc}")

    # 3. Bitcoin Core RPC
    if os.getenv("BITCOIN_RPC_URL"):
        try:
            return await _broadcast_via_bitcoin_rpc(destination_address, amount_btc)
        except Exception as exc:
            logger.error("Bitcoin RPC broadcast failed: %s", exc)
            errors.append(f"Bitcoin RPC: {exc}")

    # 4. BlockCypher (non-custodial; requires hot-wallet WIF key)
    wif = os.getenv("BITCOIN_WIF_PRIVATE_KEY", "")
    src = os.getenv("BITCOIN_SOURCE_ADDRESS", source_address)
    if wif and src:
        try:
            return await _broadcast_via_blockcypher(
                destination_address, amount_btc, fee_btc, src, wif
            )
        except Exception as exc:
            logger.error("BlockCypher broadcast failed: %s", exc)
            errors.append(f"BlockCypher: {exc}")

    env = os.getenv("APP_ENV", "development").lower()
    raise RuntimeError(
        "Bitcoin withdrawal broadcast failed — no backend succeeded. "
        f"Errors: {'; '.join(errors) or 'none configured'}. "
        "Set at least one of: BITGO_ACCESS_TOKEN, FIREBLOCKS_API_KEY, "
        "BITCOIN_RPC_URL, or BITCOIN_WIF_PRIVATE_KEY."
        + (" (APP_ENV=production)" if env == "production" else "")
    )


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

    async def process_withdrawal(
        self,
        user_id: str,
        amount: Decimal,
        destination_address: str,
    ) -> dict:
        """
        Broadcast a Bitcoin withdrawal to the network.

        Attempts broadcast backends in priority order:
            BitGo → Fireblocks → Bitcoin Core RPC → BlockCypher

        Args:
            user_id: User ID
            amount: Amount in BTC to send
            destination_address: Recipient bech32 / legacy address

        Returns:
            Withdrawal summary dict with the real on-chain txid.

        Raises:
            ValueError: Invalid address or amount too small.
            RuntimeError: All broadcast backends failed or none configured.
        """
        if not self._validate_address(destination_address):
            raise ValueError(f"Invalid Bitcoin address: {destination_address!r}")

        net_amount = amount - self.NETWORK_FEE
        if net_amount <= 0:
            raise ValueError(f"Amount {amount} BTC is too small after network fee {self.NETWORK_FEE} BTC")

        # Determine source address (most recently used deposit address for this user)
        source_address = ""
        user_addrs = self.user_addresses.get(user_id, [])
        if user_addrs:
            source_address = user_addrs[-1]

        tx_hash = await _broadcast_withdrawal(
            destination_address=destination_address,
            amount_btc=net_amount,
            fee_btc=self.NETWORK_FEE,
            source_address=source_address,
        )

        # Record the broadcast transaction
        transaction = BitcoinTransaction(
            tx_hash=tx_hash,
            address=destination_address,
            amount=amount,
            confirmations=0,
            status="broadcasting",
            created_at=datetime.now(UTC),
        )
        self.transactions[tx_hash] = transaction

        logger.info(
            "BTC withdrawal broadcast: tx=%s amount=%s BTC to=%s user=%s",
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
