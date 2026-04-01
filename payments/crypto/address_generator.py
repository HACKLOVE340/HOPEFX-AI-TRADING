# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
payments/crypto/address_generator.py
=====================================
Generates unique crypto deposit addresses using real BIP32/BIP44/BIP84
HD wallet derivation via the hdwallet library.

Supported currencies and derivation paths
------------------------------------------
BTC          BIP84  m/84'/0'/0'/0/{index}   P2WPKH bech32 (bc1q…)
ETH          BIP44  m/44'/60'/0'/0/{index}  P2PKH  (0x…)
USDT_ERC20   BIP44  m/44'/60'/0'/0/{index}  same as ETH (ERC-20 token)
USDT_TRC20   BIP44  m/44'/195'/0'/0/{index} TRX-compatible (T…)

Mnemonics are loaded from environment variables:
  BITCOIN_MNEMONIC   — BTC wallet
  ETHEREUM_MNEMONIC  — ETH / USDT_ERC20 wallet
  TRON_MNEMONIC      — USDT_TRC20 wallet

In production these must be stored in a secrets manager and injected at
runtime.  In non-production environments an ephemeral mnemonic is generated
with a loud warning.
"""

import logging
import os

try:
    from hdwallet import HDWallet as _HDWallet

    try:
        from hdwallet.symbols import BTC, ETH, TRX
    except ImportError:
        BTC = ETH = TRX = None  # type: ignore[assignment]

    try:
        from hdwallet.utils import generate_mnemonic as _gen_mnemonic

        def generate_mnemonic(language: str = "english", strength: int = 128) -> str:  # type: ignore[misc]
            return _gen_mnemonic(language=language, strength=strength)

    except ImportError:
        # hdwallet v3+: use BIP39Mnemonic.from_entropy
        import os as _os
        from hdwallet.mnemonics import BIP39Mnemonic as _BIP39Mnemonic

        def generate_mnemonic(language: str = "english", strength: int = 128) -> str:  # type: ignore[misc]
            entropy_bytes = _os.urandom(strength // 8)
            return _BIP39Mnemonic.from_entropy(entropy=entropy_bytes.hex(), language=language)

    _HDWALLET_AVAILABLE = True

except ImportError:
    _HDWallet = None  # type: ignore[assignment,misc]
    BTC = ETH = TRX = None  # type: ignore[assignment]
    _HDWALLET_AVAILABLE = False

    def generate_mnemonic(language: str = "english", strength: int = 128) -> str:  # type: ignore[misc]
        raise RuntimeError("Address generation requires the 'hdwallet' package. Install it with: pip install hdwallet")


def HDWallet(*args, **kwargs):  # type: ignore[misc]
    """Thin wrapper that raises a clear error when hdwallet is not installed."""
    if not _HDWALLET_AVAILABLE:
        raise RuntimeError("Address generation requires the 'hdwallet' package. Install it with: pip install hdwallet")
    return _HDWallet(*args, **kwargs)  # type: ignore[misc]


logger = logging.getLogger(__name__)

# ── Derivation path constants ─────────────────────────────────────────────────

_PATHS: dict[str, str] = {
    "BTC": "m/84'/0'/0'/0/{index}",  # BIP84 native SegWit
    "ETH": "m/44'/60'/0'/0/{index}",  # BIP44 Ethereum
    "USDT_ERC20": "m/44'/60'/0'/0/{index}",  # ERC-20 shares ETH path
    "USDT_TRC20": "m/44'/195'/0'/0/{index}",  # BIP44 Tron
}

# hdwallet symbol objects per currency group
_SYMBOLS = {
    "BTC": BTC,
    "ETH": ETH,
    "USDT_ERC20": ETH,
    "USDT_TRC20": TRX,
}

# Semantic override for BTC (native SegWit)
_SEMANTICS: dict[str, str] = {
    "BTC": "p2wpkh",
}

# Environment variable that holds each currency's mnemonic
_MNEMONIC_ENV: dict[str, str] = {
    "BTC": "BITCOIN_MNEMONIC",
    "ETH": "ETHEREUM_MNEMONIC",
    "USDT_ERC20": "ETHEREUM_MNEMONIC",
    "USDT_TRC20": "TRON_MNEMONIC",
}


def _load_mnemonic(currency: str) -> str:
    """
    Load the HD wallet mnemonic for *currency* from the environment.

    Raises RuntimeError in production if the variable is absent.
    Generates an ephemeral mnemonic in non-production with a warning.
    """
    env_var = _MNEMONIC_ENV[currency]
    mnemonic = os.getenv(env_var, "").strip()
    if not mnemonic:
        app_env = os.getenv("APP_ENV", "development").lower()
        if app_env == "production":
            raise RuntimeError(
                f"{env_var} environment variable is required in production. "
                "Store the BIP39 mnemonic in your secrets manager and inject it at runtime."
            )
        mnemonic = generate_mnemonic(language="english", strength=256)
        logger.warning(
            "%s not set — using ephemeral mnemonic for %s. Addresses will change on restart.",
            env_var,
            currency,
        )
    return mnemonic


class AddressGenerator:
    """
    Generates unique crypto deposit addresses via BIP32/BIP44/BIP84 derivation.

    Each (user_id, currency) pair gets a fresh address per call, advancing the
    derivation index.  The same mnemonic + index always produces the same
    address, so addresses are recoverable as long as the mnemonic is stable.

    Requires the optional 'hdwallet' package.  Raises RuntimeError on first
    use (not at import time) when the package is absent.
    """

    def __init__(self) -> None:
        # currency -> mnemonic (loaded lazily on first use)
        self._mnemonics: dict[str, str] = {}
        # (currency, index) counter — shared across all users per currency
        # In production, persist this counter in the database.
        self._counters: dict[str, int] = {}

    def _get_mnemonic(self, currency: str) -> str:
        if currency not in self._mnemonics:
            self._mnemonics[currency] = _load_mnemonic(currency)
        return self._mnemonics[currency]

    def _next_index(self, currency: str) -> int:
        idx = self._counters.get(currency, 0)
        self._counters[currency] = idx + 1
        return idx

    def generate_address(self, user_id: str, currency: str) -> str:
        """
        Derive the next unique deposit address for *user_id* and *currency*.

        Args:
            user_id:  User identifier (used only for logging)
            currency: One of BTC, ETH, USDT_ERC20, USDT_TRC20

        Returns:
            Blockchain address string

        Raises:
            RuntimeError: if hdwallet is not installed
            ValueError: if *currency* is not supported
        """
        if not _HDWALLET_AVAILABLE:
            raise RuntimeError(
                "Address generation requires the 'hdwallet' package. Install it with: pip install hdwallet"
            )
        if currency not in _PATHS:
            raise ValueError(f"Unsupported currency: {currency!r}. Supported: {sorted(_PATHS)}")

        mnemonic = self._get_mnemonic(currency)
        index = self._next_index(currency)
        path = _PATHS[currency].format(index=index)
        symbol = _SYMBOLS[currency]
        semantic = _SEMANTICS.get(currency)

        wallet = HDWallet(symbol=symbol, semantic=semantic) if semantic else HDWallet(symbol=symbol)
        wallet.from_mnemonic(mnemonic)
        wallet.from_path(path)

        if currency == "BTC":
            address: str = wallet.p2wpkh_address()
        else:
            # ETH, USDT_ERC20, USDT_TRC20 all use p2pkh_address()
            address = wallet.p2pkh_address()

        logger.info(
            "Derived %s deposit address for user %s: %s (path=%s)",
            currency,
            user_id,
            address,
            path,
        )
        return address

    def generate_qr_code(self, address: str, currency: str) -> str:
        """
        Return a URI suitable for encoding in a QR code.

        Uses BIP21 for BTC, EIP-681 prefix for ETH/ERC-20, and a plain
        address URI for TRC-20.
        """
        if currency == "BTC":
            return f"bitcoin:{address}"
        if currency in ("ETH", "USDT_ERC20"):
            return f"ethereum:{address}"
        if currency == "USDT_TRC20":
            return f"tron:{address}"
        return address


# Module-level singleton — instantiation is safe even without hdwallet;
# RuntimeError is raised only when generate_address() is actually called.
address_generator = AddressGenerator()
