# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/superadmin/trading_oversight.py — whole-book views, for operators only.

``admin`` and ``superadmin`` used to see every user's positions on the ordinary
trading endpoints: ``_owned_position_ids`` returned ``None`` for those roles, and
``None`` meant *apply no filter*. That is the behaviour that was reported —
a superadmin placing a trade saw, and was seen in, everybody's book.

Operators are ordinary traders on ``/api/trading/*`` now. Oversight did not go
away; it moved here, where three things are true that were not true before:

* the route says what it does, so nobody reaches it by accident;
* the account being inspected is **named**, rather than implied by the caller's
  role, so a request is a deliberate act about a specific user;
* every call is written to the tamper-evident audit log via
  ``_log_superadmin_action``, so looking at somebody's positions is a recorded
  event rather than an invisible one.

These are read-only. Closing another user's position from an operator seat is a
separate decision with different consequences, and it is not smuggled in here.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import TokenPayload

from ._shared import _log_superadmin_action, _require_superadmin, _utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


def _position_to_dict(p: Any) -> dict[str, Any]:
    entry = float(getattr(p, "entry_price", 0) or 0)
    current = float(getattr(p, "current_price", entry) or entry)
    opened = getattr(p, "opened_at", None) or getattr(p, "created_at", None)
    side = getattr(p, "side", "")
    return {
        "id": str(getattr(p, "id", "")),
        "symbol": getattr(p, "symbol", ""),
        "side": side.value if hasattr(side, "value") else str(side),
        "quantity": float(getattr(p, "quantity", 0) or 0),
        "entry_price": entry,
        "current_price": current,
        "unrealized_pnl": float(getattr(p, "unrealized_pnl", 0) or 0),
        "opened_at": opened.isoformat() if hasattr(opened, "isoformat") else str(opened or ""),
    }


async def _account_snapshot(user_id: str) -> dict[str, Any]:
    """Positions and balances for one account, or an explicit reason why not."""
    from core.account_registry import get_account_registry

    resolution = await get_account_registry().resolve(user_id)
    if resolution.broker is None:
        return {"user_id": user_id, "available": False, "reason": "no broker for this account"}
    if not resolution.isolated:
        return {
            "user_id": user_id,
            "available": False,
            "isolated": False,
            "reason": resolution.reason,
        }

    from api.trading import _call_on

    try:
        positions = await _call_on(resolution.broker, "get_positions")
        account = await _call_on(resolution.broker, "get_account_info")
    except Exception as exc:
        logger.warning("oversight: could not read account for user=%s: %s", user_id, exc)
        return {"user_id": user_id, "available": False, "reason": str(exc)}

    def _get(key: str, default: float = 0.0) -> float:
        if hasattr(account, key):
            return float(getattr(account, key) or default)
        if isinstance(account, dict):
            return float(account.get(key, default) or default)
        return default

    return {
        "user_id": user_id,
        "available": True,
        "isolated": True,
        "balance": round(_get("balance"), 2),
        "equity": round(_get("equity", _get("balance")), 2),
        "margin_used": round(_get("margin_used"), 2),
        "open_positions": len(positions or []),
        "positions": [_position_to_dict(p) for p in (positions or [])],
    }


@router.get(
    "/trading/accounts",
    summary="Every account with an open book (operator view)",
)
async def list_accounts(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """List the accounts this process is holding, with their exposure.

    Only accounts that have actually traded appear: the registry creates a
    broker on first use, so a user who has never placed an order has no account
    to report. That is a truthful list of where money is at risk, not a user
    directory — ``/api/superadmin/users`` is the directory.
    """
    from core.account_registry import get_account_registry

    registry = get_account_registry()
    user_ids = registry.known_user_ids()

    accounts = [await _account_snapshot(uid) for uid in user_ids]
    _log_superadmin_action(user, "trading.accounts.list", {"account_count": len(accounts)})

    return {
        "accounts": accounts,
        "total_accounts": len(accounts),
        "isolation_supported": registry.isolation_supported(),
        "checked_at": _utcnow().isoformat(),
    }


@router.get(
    "/trading/accounts/{account_user_id}",
    summary="One named account's positions and balance (operator view)",
)
async def get_account_detail(
    account_user_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Inspect a single named account.

    The account is a path parameter rather than an implication of the caller's
    role. That is the whole point of this endpoint existing: reading another
    person's book is an explicit, audited request for a specific person.
    """
    if not account_user_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account_user_id is required")

    snapshot = await _account_snapshot(account_user_id)
    _log_superadmin_action(
        user,
        "trading.account.read",
        {"target_user_id": account_user_id, "available": snapshot.get("available")},
    )
    return snapshot


@router.get(
    "/trading/positions",
    summary="Every open position across all accounts (operator view)",
)
async def all_positions(
    user: TokenPayload = Depends(_require_superadmin),
    symbol: str | None = Query(None, max_length=20, description="Filter by symbol"),
) -> dict:
    """The whole book, with each position attributed to the account holding it.

    This is what admins used to get from ``GET /api/trading/positions`` — the
    difference being that every row now carries the user it belongs to, and
    asking for it is recorded.
    """
    from core.account_registry import get_account_registry

    registry = get_account_registry()
    rows: list[dict[str, Any]] = []
    for uid in registry.known_user_ids():
        snapshot = await _account_snapshot(uid)
        if not snapshot.get("available"):
            continue
        for position in snapshot["positions"]:
            if symbol and position.get("symbol") != symbol:
                continue
            rows.append({**position, "user_id": uid})

    _log_superadmin_action(user, "trading.positions.list_all", {"position_count": len(rows), "symbol": symbol})

    return {
        "positions": rows,
        "total": len(rows),
        "isolation_supported": registry.isolation_supported(),
        "checked_at": _utcnow().isoformat(),
    }
