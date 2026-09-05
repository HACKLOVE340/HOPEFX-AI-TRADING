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

Derivation index persistence:
  HOPEFX_CRYPTO_COUNTER_PATH — path to the JSON counter file
  (default: data/crypto_counters.json relative to the project root)

  The counter file is written atomically after every index increment so
  that a process restart never reuses a derivation index and therefore
  never reuses a deposit address.
"""

import json
import logging
import os
import re
import threading
from pathlib import Path

# hdwallet v3 API. This module was written against the v1/v2 API
# (``HDWallet(symbol=...)``, ``from_path()``, ``p2wpkh_address()``), which does
# not exist in v3 — and requirements.txt has pinned ``hdwallet>=3.6.1,<4.0.0``
# the whole time. `_HDWALLET_AVAILABLE` was set from `import hdwallet`
# succeeding, so the module advertised itself as working while every call to
# generate_address() raised
# ``TypeError: HDWallet.__init__() missing 1 required positional argument``.
# Nothing tested it (F222), and api/billing.py caught the TypeError and handed
# the user a fabricated string instead (F267).
try:
    from hdwallet import HDWallet as _HDWallet
    from hdwallet.cryptocurrencies import Bitcoin as _Bitcoin
    from hdwallet.cryptocurrencies import Ethereum as _Ethereum
    from hdwallet.cryptocurrencies import Tron as _Tron
    from hdwallet.derivations import BIP44Derivation as _BIP44Derivation
    from hdwallet.derivations import BIP84Derivation as _BIP84Derivation
    from hdwallet.hds import BIP44HD as _BIP44HD
    from hdwallet.hds import BIP84HD as _BIP84HD
    from hdwallet.mnemonics import BIP39Mnemonic as _BIP39Mnemonic

    def generate_mnemonic(language: str = "english", strength: int = 128) -> str:
        entropy_bytes = os.urandom(strength // 8)
        return str(_BIP39Mnemonic.from_entropy(entropy=entropy_bytes.hex(), language=language))

    _HDWALLET_AVAILABLE = True

except ImportError:  # pragma: no cover - exercised only without the optional dep
    _HDWallet = None  # type: ignore[assignment,misc]
    _Bitcoin = _Ethereum = _Tron = None  # type: ignore[assignment]
    _BIP44Derivation = _BIP84Derivation = None  # type: ignore[assignment]
    _BIP44HD = _BIP84HD = _BIP39Mnemonic = None  # type: ignore[assignment]
    _HDWALLET_AVAILABLE = False

    def generate_mnemonic(language: str = "english", strength: int = 128) -> str:  # type: ignore[misc]
        raise RuntimeError("Address generation requires the 'hdwallet' package. Install it with: pip install hdwallet")


_HDWALLET_MISSING = "Address generation requires the 'hdwallet' package. Install it with: pip install hdwallet"


logger = logging.getLogger(__name__)

# ── Counter persistence ───────────────────────────────────────────────────────
# Default path is relative to the project root.  Override via env var in
# production so the file lands on a durable volume, not the container FS.
_DEFAULT_COUNTER_PATH = Path(__file__).resolve().parents[2] / "data" / "crypto_counters.json"
_COUNTER_PATH = Path(os.getenv("HOPEFX_CRYPTO_COUNTER_PATH", str(_DEFAULT_COUNTER_PATH)))

# ── Derivation path constants ─────────────────────────────────────────────────
#
# Each entry is (human-readable path, cryptocurrency, HD class, derivation
# class). The path string is documentation and log output; the derivation
# objects are what actually derive, so the two cannot silently disagree --
# test_crypto_addresses_are_really_derived.py asserts the derived address
# matches the published BIP test vector for the path shown here.

_PATHS: dict[str, str] = {
    "BTC": "m/84'/0'/0'/0/{index}",  # BIP84 native SegWit
    "ETH": "m/44'/60'/0'/0/{index}",  # BIP44 Ethereum
    "USDT_ERC20": "m/44'/60'/0'/0/{index}",  # ERC-20 shares ETH path
    "USDT_TRC20": "m/44'/195'/0'/0/{index}",  # BIP44 Tron
}

# currency -> (cryptocurrency class, HD class, derivation class)
_DERIVATION: dict[str, tuple] = (
    {
        "BTC": (_Bitcoin, _BIP84HD, _BIP84Derivation),
        "ETH": (_Ethereum, _BIP44HD, _BIP44Derivation),
        "USDT_ERC20": (_Ethereum, _BIP44HD, _BIP44Derivation),
        "USDT_TRC20": (_Tron, _BIP44HD, _BIP44Derivation),
    }
    if _HDWALLET_AVAILABLE
    else {}
)

# Shape of a correctly derived address, checked before the address is handed
# out. This is a last line of defence, not the primary control: the primary
# control is that the address comes from a real derivation over a mnemonic the
# platform holds. It exists because the failure mode here is silent and
# irreversible -- payments/crypto/ethereum.py returned
# ``"0x" + sha256(f"ETH{user_id}").hexdigest()[:40]``, which is a syntactically
# valid Ethereum address that every wallet accepts and nobody holds the key to.
_ADDRESS_SHAPE: dict[str, str] = {
    "BTC": r"^bc1[02-9ac-hj-np-z]{39,59}$",
    "ETH": r"^0x[0-9a-fA-F]{40}$",
    "USDT_ERC20": r"^0x[0-9a-fA-F]{40}$",
    "USDT_TRC20": r"^T[1-9A-HJ-NP-Za-km-z]{33}$",
}

# Environment variable that holds each currency's mnemonic
_MNEMONIC_ENV: dict[str, str] = {
    "BTC": "BITCOIN_MNEMONIC",
    "ETH": "ETHEREUM_MNEMONIC",
    "USDT_ERC20": "ETHEREUM_MNEMONIC",
    "USDT_TRC20": "TRON_MNEMONIC",
}


# Environments where an ephemeral, throwaway wallet is acceptable. Anything
# else -- staging, sandbox, demo, an unset APP_ENV typo -- must supply a real
# mnemonic. The check used to be ``if app_env == "production": raise``, so every
# other value fell through to an ephemeral mnemonic whose private keys are
# discarded on restart. A staging deployment that takes a real deposit against
# an ephemeral wallet loses the funds permanently, and the only signal was a
# WARNING log line.
_EPHEMERAL_OK_ENVS = frozenset({"development", "dev", "test", "testing", "local"})


def _load_mnemonic(currency: str) -> str:
    """
    Load the HD wallet mnemonic for *currency* from the environment.

    Raises RuntimeError outside a recognised development environment when the
    variable is absent. Generates an ephemeral mnemonic in development, with a
    warning.
    """
    env_var = _MNEMONIC_ENV[currency]
    mnemonic = os.getenv(env_var, "").strip()
    if not mnemonic:
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        if app_env not in _EPHEMERAL_OK_ENVS:
            raise RuntimeError(
                f"{env_var} environment variable is required when APP_ENV={app_env!r}. "
                "Store the BIP39 mnemonic in your secrets manager and inject it at runtime. "
                "Refusing to derive deposit addresses from an ephemeral wallet: any funds "
                "sent to them would be unrecoverable after a restart."
            )
        mnemonic = generate_mnemonic(language="english", strength=256)
        logger.warning(
            "%s not set — using ephemeral mnemonic for %s (APP_ENV=%s). "
            "Addresses will change on restart and any funds sent to them are lost.",
            env_var,
            currency,
            app_env,
        )
    return mnemonic


def _address_is_well_formed(address: str, currency: str) -> bool:
    """True when *address* has the shape a real address for *currency* has.

    Deliberately narrow: it rejects the two fabricated forms this codebase
    actually produced -- ``"T" + sha256(...)[:33]`` (not base58, so no wallet
    would even accept it) and ``"0x" + sha256(...)[:40]`` (indistinguishable
    from a real Ethereum address, and therefore the one that loses money).
    """
    pattern = _ADDRESS_SHAPE.get(currency)
    if pattern is None:
        return False
    return bool(address) and re.fullmatch(pattern, address) is not None


class AddressGenerator:
    """
    Generates unique crypto deposit addresses via BIP32/BIP44/BIP84 derivation.

    Each call advances a per-currency derivation index that is persisted to
    disk (JSON) so restarts never reuse an index.  The same mnemonic + index
    always produces the same address, so the full address history is
    recoverable from the mnemonic alone.

    Counter file location: HOPEFX_CRYPTO_COUNTER_PATH env var (default:
    data/crypto_counters.json relative to the project root).

    Requires the optional 'hdwallet' package.  Raises RuntimeError on first
    use (not at import time) when the package is absent.
    """

    def __init__(self) -> None:
        # currency -> mnemonic (loaded lazily on first use)
        self._mnemonics: dict[str, str] = {}
        # Per-currency derivation index — loaded from disk, written back after
        # every increment so a restart never reuses an index.
        self._counters: dict[str, int] = self._load_counters()
        self._lock = threading.Lock()

    def _load_counters(self) -> dict[str, int]:
        """Read persisted counters from disk; return empty dict on first run."""
        try:
            if _COUNTER_PATH.exists():
                data = json.loads(_COUNTER_PATH.read_text())
                if isinstance(data, dict):
                    return {k: int(v) for k, v in data.items()}
        except Exception as exc:
            logger.error("Failed to load crypto counters from %s: %s", _COUNTER_PATH, exc)
        return {}

    def _save_counters(self) -> None:
        """Atomically write counters to disk using a temp-file + rename.

        Raises on failure. This used to swallow the exception, with the comment
        "a failed write is recoverable on the next call". It is not: the
        in-memory counter has already advanced, so a process restart reloads the
        stale on-disk value and re-derives indices that were already issued.
        The module docstring promises "a process restart never reuses a
        derivation index and therefore never reuses a deposit address", and that
        promise held only while the write happened to succeed.

        Two users sharing a deposit address cannot be told apart at
        reconciliation time, so the safe response to an unwritable counter is to
        stop issuing addresses, not to keep issuing ones we cannot account for.
        """
        _COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _COUNTER_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._counters, indent=2))
        os.replace(tmp, _COUNTER_PATH)

    def _get_mnemonic(self, currency: str) -> str:
        if currency not in self._mnemonics:
            self._mnemonics[currency] = _load_mnemonic(currency)
        return self._mnemonics[currency]

    def _next_index(self, currency: str) -> int:
        """Reserve the next derivation index, durably.

        The index is only handed back once it is on disk. If the write fails the
        in-memory counter is rolled back, so a caller that retries after fixing
        the volume gets the same index rather than skipping one -- and a caller
        that does not retry has been given nothing.
        """
        with self._lock:
            idx = self._counters.get(currency, 0)
            self._counters[currency] = idx + 1
            try:
                self._save_counters()
            except Exception as exc:
                self._counters[currency] = idx  # roll back; nothing was issued
                raise RuntimeError(
                    f"Cannot persist the {currency} derivation counter to {_COUNTER_PATH}: {exc}. "
                    "Refusing to issue a deposit address that a restart could re-issue to "
                    "another user."
                ) from exc
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
            raise RuntimeError(_HDWALLET_MISSING)
        if currency not in _PATHS:
            raise ValueError(f"Unsupported currency: {currency!r}. Supported: {sorted(_PATHS)}")

        mnemonic = self._get_mnemonic(currency)
        index = self._next_index(currency)
        path = _PATHS[currency].format(index=index)
        address = self._derive(currency, mnemonic, index)

        # Verified before it leaves the process. A deposit address is the one
        # value here that cannot be corrected after the fact: once a user sends
        # to it, an address nobody holds the key to has consumed the funds
        # permanently. Raising is the only safe failure -- returning anything at
        # all is what payments/crypto/ethereum.py did.
        if not _address_is_well_formed(address, currency):
            raise RuntimeError(
                f"Derived {currency} address {address!r} does not match the expected format for "
                f"{path}. Refusing to issue it."
            )

        logger.info(
            "Derived %s deposit address for user %s: %s (path=%s)",
            currency,
            user_id,
            address,
            path,
        )
        return address

    @staticmethod
    def _derive(currency: str, mnemonic: str, index: int) -> str:
        """Derive one address via hdwallet v3.

        Kept separate from generate_address so the derivation can be checked
        against the published BIP test vectors without advancing any counter.
        """
        cryptocurrency, hd_class, derivation_class = _DERIVATION[currency]
        wallet = _HDWallet(cryptocurrency=cryptocurrency, hd=hd_class, network="mainnet")
        wallet.from_mnemonic(_BIP39Mnemonic(mnemonic))
        wallet.from_derivation(
            derivation_class(
                coin_type=cryptocurrency.COIN_TYPE,
                account=0,
                change="external-chain",
                address=index,
            )
        )
        return str(wallet.address())

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
