# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/account_registry.py — one trading account per user.

**The defect this closes (backlog T-01).** ``app_state.broker`` is a single
process-wide engine with a single account, and every logged-in user traded
against it. ``PaperTradingBroker.positions`` is a ``dict[str, Position]`` keyed
by *symbol*, and ``_update_position`` merges into the existing entry ("For
simplicity, assume same side"), so two users buying XAUUSD did not get two
positions — they got one, quantity summed, entry price averaged, id equal to the
symbol. Their capital was commingled in a single object and
``close_position("XAUUSD")`` closed it for both.

No amount of filtering on the read path can separate those two users, because
after the merge there is nothing left to attribute. The separation has to exist
in the broker.

**How.** ``PaperTradingBroker`` already supports this and its docstring spells
out the pattern::

    # Per-user production namespace (state persists across restarts)
    broker = PaperTradingBroker(user_id="user-42", namespace="user-42")

Each instance keeps its own ``positions``, ``orders``, ``balance`` and
``equity``, and scopes its Redis keys by namespace, so per-user state survives a
restart without colliding. The capability was there; nothing constructed more
than one instance.

**Live brokers cannot be split this way, and this module does not pretend
otherwise.** With ``BROKER_TYPE=oanda`` or ``mt5`` there is exactly one real
account at the venue. Handing two users "their own" view of one live account
would be a lie with money attached, so in live mode this registry returns the
shared broker and reports ``isolated=False``. Callers decide what to do with
that; they are not silently told the accounts are separate.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "AccountResolution",
    "get_account_registry",
    "reset_account_registry",
]

# Brokers that represent one real account at a venue and therefore cannot be
# partitioned per user inside this process.
_SINGLE_ACCOUNT_BROKERS = frozenset({"oanda", "mt5", "ibkr", "binance", "alpaca"})

_DEFAULT_STARTING_BALANCE = 10_000.0

# Soft ceiling on cached per-user brokers. Nothing is evicted — an eviction
# would drop a user's open positions from memory — but crossing it is logged
# once so an operator learns about unbounded growth from a warning rather than
# from an OOM.
_CACHE_WARN_AT = 500


class AccountResolution:
    """The broker a request should act on, and whether it is really that user's.

    ``isolated`` is the honest bit. ``True`` means this object holds only this
    user's positions and balance. ``False`` means it is the shared venue account
    and anything read from it belongs to the deployment, not the caller.
    """

    __slots__ = ("broker", "isolated", "reason", "user_id")

    def __init__(self, broker: Any, *, isolated: bool, user_id: str, reason: str = "") -> None:
        self.broker = broker
        self.isolated = isolated
        self.user_id = user_id
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AccountResolution user={self.user_id!r} isolated={self.isolated} reason={self.reason!r}>"


def _starting_balance() -> float:
    raw = os.getenv("INITIAL_BALANCE") or os.getenv("PAPER_INITIAL_BALANCE") or ""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_STARTING_BALANCE
    return value if value > 0 else _DEFAULT_STARTING_BALANCE


def _configured_broker_type() -> str:
    return (os.getenv("BROKER_TYPE") or os.getenv("BROKER") or "paper").strip().lower()


class AccountRegistry:
    """Lazily creates and caches one paper broker per user."""

    def __init__(self) -> None:
        self._brokers: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._warned_about_size = False

    # ── Introspection ────────────────────────────────────────────────────────

    def isolation_supported(self) -> bool:
        """False when the configured broker is one real account at a venue."""
        return _configured_broker_type() not in _SINGLE_ACCOUNT_BROKERS

    def known_user_ids(self) -> list[str]:
        return sorted(self._brokers)

    def peek(self, user_id: str) -> Any | None:
        """The user's account **if it already exists**, without creating one.

        For synchronous callers that cannot await — the GraphQL resolvers are
        plain ``def``. Returning ``None`` for a user who has not traded yet is
        correct: they have no account, and the honest answer is an empty one.
        The alternative, falling back to the shared broker, is precisely the bug
        this module exists to remove.
        """
        if not user_id or not self.isolation_supported():
            return None
        return self._brokers.get(user_id)

    # ── Resolution ───────────────────────────────────────────────────────────

    async def resolve(self, user_id: str) -> AccountResolution:
        """Return the account *user_id* trades on.

        Falls back to the shared broker — flagged ``isolated=False`` — when the
        deployment is on a live single-account venue, when no user id is
        available, or when a per-user broker cannot be created. Falling back is
        never silent: the reason travels with the result.
        """
        shared = self._shared_broker()

        if not user_id:
            return AccountResolution(shared, isolated=False, user_id="", reason="no authenticated user id")

        if not self.isolation_supported():
            return AccountResolution(
                shared,
                isolated=False,
                user_id=user_id,
                reason=(
                    f"broker '{_configured_broker_type()}' is a single account at the venue; "
                    "per-user isolation is not possible in-process"
                ),
            )

        existing = self._brokers.get(user_id)
        if existing is not None:
            return AccountResolution(existing, isolated=True, user_id=user_id)

        async with self._lock:
            # Re-check under the lock: two concurrent requests from the same
            # user must not build two brokers and split their positions across
            # them, which would recreate the bug in a new shape.
            existing = self._brokers.get(user_id)
            if existing is not None:
                return AccountResolution(existing, isolated=True, user_id=user_id)

            try:
                broker = await self._create_broker(user_id)
            except Exception as exc:
                logger.error(
                    "Could not create an isolated paper account for user=%s (%s) — "
                    "falling back to the shared broker, which is NOT isolated.",
                    user_id,
                    exc,
                )
                return AccountResolution(
                    shared,
                    isolated=False,
                    user_id=user_id,
                    reason=f"per-user account creation failed: {exc}",
                )

            self._brokers[user_id] = broker
            if len(self._brokers) > _CACHE_WARN_AT and not self._warned_about_size:
                self._warned_about_size = True
                logger.warning(
                    "AccountRegistry now holds %d per-user brokers. Nothing is evicted "
                    "because eviction would drop open positions from memory; if this "
                    "keeps growing the paper engine needs a persistence-backed store.",
                    len(self._brokers),
                )
            logger.info("Created isolated paper account for user=%s", user_id)
            return AccountResolution(broker, isolated=True, user_id=user_id)

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _shared_broker() -> Any:
        try:
            from core.app_state import app_state

            return getattr(app_state, "broker", None)
        except Exception:  # pragma: no cover - defensive
            return None

    async def _create_broker(self, user_id: str) -> Any:
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(
            user_id=user_id,
            # Explicit rather than relying on the default. The default derives
            # the namespace from user_id in production but generates a fresh
            # UUID when APP_ENV=test — which would give the same user a
            # different account on every call under test. Naming it keeps one
            # account per user in every environment.
            namespace=f"user:{user_id}",
            initial_balance=_starting_balance(),
        )
        await broker.connect()
        return broker

    async def close_all(self) -> None:
        """Disconnect every per-user broker. Used on shutdown and by tests."""
        async with self._lock:
            brokers = list(self._brokers.values())
            self._brokers.clear()
        for broker in brokers:
            try:
                disconnect = getattr(broker, "disconnect", None)
                if disconnect is None:
                    continue
                result = disconnect()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("AccountRegistry.close_all: %s", exc)


_registry: AccountRegistry | None = None


def get_account_registry() -> AccountRegistry:
    global _registry
    if _registry is None:
        _registry = AccountRegistry()
    return _registry


def reset_account_registry() -> None:
    """Drop the process-wide registry. For tests and shutdown."""
    global _registry
    _registry = None
