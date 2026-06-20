# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/community_chat.py
Community chat rooms — rooms, messages, direct messages, online users.
Mounted at /api/chat/rooms (separate from the AI brain chat at /api/chat).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
UTC = timezone.utc

# Mounted at /api/chat so /api/chat/rooms, /api/chat/dm, /api/chat/online work
router = APIRouter(prefix="/api/chat", tags=["Community Chat"])

# Separate router for WebSocket paths (no /api prefix — paths start with /ws/)
ws_router = APIRouter(tags=["Community Chat WS"])

# ── WebSocket connection registry ─────────────────────────────────────────────
# room_id -> list of active WebSocket connections
_CHAT_CONNECTIONS: dict[str, list[WebSocket]] = {}
_MAX_CONNECTIONS_PER_ROOM = 500


async def _ws_broadcast(room_id: str, payload: dict) -> None:
    """Push payload to every WebSocket subscriber currently in this room."""
    conns = _CHAT_CONNECTIONS.get(room_id, [])
    dead: list[WebSocket] = []
    for ws in conns:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for d in dead:
        conns.remove(d)


# ── Storage helpers ───────────────────────────────────────────────────────────

_ROOMS_KEY = "hopefx:community:rooms"
_MSG_PREFIX = "hopefx:community:msgs:"
_DM_PREFIX = "hopefx:community:dm:"
_ONLINE_KEY = "hopefx:community:online"

_MEM_ROOMS: dict[str, dict] = {}
_MEM_MSGS: dict[str, list[dict]] = {}
_MEM_DMS: dict[str, list[dict]] = {}
_MEM_ONLINE: dict[str, float] = {}


def _redis():
    try:
        import redis as _r
        import os

        c = _r.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), socket_connect_timeout=1, socket_timeout=1)
        c.ping()
        return c
    except Exception:
        return None


def _get_rooms() -> dict[str, dict]:
    r = _redis()
    if r:
        try:
            raw = r.hgetall(_ROOMS_KEY)
            return {k.decode(): json.loads(v) for k, v in raw.items()}
        except Exception:  # nosec B110  # noqa: S110
            pass
    return dict(_MEM_ROOMS)


def _save_room(room: dict) -> None:
    r = _redis()
    if r:
        try:
            r.hset(_ROOMS_KEY, room["id"], json.dumps(room))
            return
        except Exception:  # nosec B110  # noqa: S110
            pass
    _MEM_ROOMS[room["id"]] = room


def _get_messages(room_id: str, limit: int = 100) -> list[dict]:
    r = _redis()
    key = f"{_MSG_PREFIX}{room_id}"
    if r:
        try:
            raw = r.lrange(key, 0, limit - 1)
            return [json.loads(x) for x in raw]
        except Exception:  # nosec B110  # noqa: S110
            pass
    return _MEM_MSGS.get(room_id, [])[:limit]


def _save_message(room_id: str, msg: dict) -> None:
    r = _redis()
    key = f"{_MSG_PREFIX}{room_id}"
    if r:
        try:
            r.lpush(key, json.dumps(msg))
            r.ltrim(key, 0, 999)
            return
        except Exception:  # nosec B110  # noqa: S110
            pass
    _MEM_MSGS.setdefault(room_id, []).insert(0, msg)
    _MEM_MSGS[room_id] = _MEM_MSGS[room_id][:1000]


def _get_dms(user_a: str, user_b: str, limit: int = 100) -> list[dict]:
    key = "_".join(sorted([user_a, user_b]))
    r = _redis()
    rkey = f"{_DM_PREFIX}{key}"
    if r:
        try:
            raw = r.lrange(rkey, 0, limit - 1)
            return [json.loads(x) for x in raw]
        except Exception:  # nosec B110  # noqa: S110
            pass
    return _MEM_DMS.get(key, [])[:limit]


def _save_dm(user_a: str, user_b: str, msg: dict) -> None:
    key = "_".join(sorted([user_a, user_b]))
    r = _redis()
    rkey = f"{_DM_PREFIX}{key}"
    if r:
        try:
            r.lpush(rkey, json.dumps(msg))
            r.ltrim(rkey, 0, 999)
            return
        except Exception:  # nosec B110  # noqa: S110
            pass
    _MEM_DMS.setdefault(key, []).insert(0, msg)
    _MEM_DMS[key] = _MEM_DMS[key][:1000]


def _seed_default_rooms() -> None:
    rooms = _get_rooms()
    if rooms:
        return
    now = datetime.now(UTC).isoformat()
    defaults = [
        {
            "id": "general",
            "name": "General",
            "description": "General trading discussion",
            "type": "public",
            "member_count": 0,
            "pinned": True,
            "created_at": now,
            "last_message_at": now,
        },
        {
            "id": "signals",
            "name": "Signals",
            "description": "AI signal alerts and discussion",
            "type": "public",
            "member_count": 0,
            "pinned": True,
            "created_at": now,
            "last_message_at": now,
        },
        {
            "id": "gold-xauusd",
            "name": "Gold / XAUUSD",
            "description": "Gold trading strategies",
            "type": "public",
            "member_count": 0,
            "pinned": False,
            "created_at": now,
            "last_message_at": now,
        },
        {
            "id": "support",
            "name": "Support",
            "description": "Platform support and help",
            "type": "public",
            "member_count": 0,
            "pinned": False,
            "created_at": now,
            "last_message_at": now,
        },
    ]
    for d in defaults:
        _save_room(d)


# ── Pydantic models ───────────────────────────────────────────────────────────

_REACTIONS_PREFIX = "hopefx:community:reactions:"
_READ_PREFIX = "hopefx:community:read:"
_MEM_REACTIONS: dict[str, dict[str, list[str]]] = {}  # msg_id -> emoji -> [user_ids]
_MEM_READ: dict[str, set[str]] = {}  # room_id -> set of user_ids


def _get_reactions(msg_id: str) -> dict[str, list[str]]:
    r = _redis()
    if r:
        try:
            raw = r.hgetall(f"{_REACTIONS_PREFIX}{msg_id}")
            return {k.decode(): json.loads(v) for k, v in raw.items()}
        except Exception:  # nosec B110  # noqa: S110
            pass
    return dict(_MEM_REACTIONS.get(msg_id, {}))


def _save_reaction(msg_id: str, emoji: str, user_ids: list[str]) -> None:
    r = _redis()
    if r:
        try:
            if user_ids:
                r.hset(f"{_REACTIONS_PREFIX}{msg_id}", emoji, json.dumps(user_ids))
            else:
                r.hdel(f"{_REACTIONS_PREFIX}{msg_id}", emoji)
            return
        except Exception:  # nosec B110  # noqa: S110
            pass
    if msg_id not in _MEM_REACTIONS:
        _MEM_REACTIONS[msg_id] = {}
    if user_ids:
        _MEM_REACTIONS[msg_id][emoji] = user_ids
    else:
        _MEM_REACTIONS[msg_id].pop(emoji, None)


def _mark_room_read(room_id: str, user_id: str) -> None:
    r = _redis()
    if r:
        try:
            r.sadd(f"{_READ_PREFIX}{room_id}", user_id)
            return
        except Exception:  # nosec B110  # noqa: S110
            pass
    _MEM_READ.setdefault(room_id, set()).add(user_id)


class CreateRoomBody(BaseModel):
    name: str
    description: str = ""
    type: str = "public"


class SendMessageBody(BaseModel):
    content: str | None = None  # canonical field name
    text: str | None = None  # legacy alias — kept for backward compat
    attachments: list[str] | None = None

    @property
    def message_text(self) -> str:
        return (self.content or self.text or "").strip()

    def validate_non_empty(self) -> None:
        if not self.message_text:
            raise HTTPException(status_code=422, detail="Message content must not be empty")


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/rooms")
async def list_rooms(user: TokenPayload = Depends(get_current_user)) -> dict:
    _seed_default_rooms()
    rooms = list(_get_rooms().values())
    rooms.sort(key=lambda r: (not r.get("pinned", False), r.get("name", "")))
    return {"rooms": rooms, "total": len(rooms)}


@router.get("/rooms/{room_id}")
async def get_room(room_id: str, user: TokenPayload = Depends(get_current_user)) -> dict:
    _seed_default_rooms()
    rooms = _get_rooms()
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    return rooms[room_id]


@router.post("/rooms")
async def create_room(body: CreateRoomBody, user: TokenPayload = Depends(get_current_user)) -> dict:
    room = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "description": body.description,
        "type": body.type,
        "created_by": user.sub,
        "member_count": 1,
        "pinned": False,
        "created_at": datetime.now(UTC).isoformat(),
        "last_message_at": datetime.now(UTC).isoformat(),
    }
    _save_room(room)
    return room


@router.get("/rooms/{room_id}/messages")
async def get_messages(
    room_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    msgs = _get_messages(room_id, limit)
    return {"messages": msgs, "room_id": room_id, "total": len(msgs)}


@router.post("/rooms/{room_id}/messages")
async def send_message(
    room_id: str,
    body: SendMessageBody,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    body.validate_non_empty()
    _seed_default_rooms()
    rooms = _get_rooms()
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    msg = {
        "id": str(uuid.uuid4()),
        "room_id": room_id,
        "user_id": user.sub,
        "username": getattr(user, "email", user.sub).split("@")[0],
        "content": body.message_text,
        "attachments": body.attachments or [],
        "created_at": datetime.now(UTC).isoformat(),
        "edited": False,
    }
    _save_message(room_id, msg)
    room = rooms[room_id]
    room["last_message_at"] = msg["created_at"]
    _save_room(room)
    # Push to WebSocket subscribers in this room (non-blocking)
    try:
        import asyncio

        asyncio.ensure_future(_ws_broadcast(room_id, {"type": "message", "message": msg}))
    except Exception:  # nosec B110  # noqa: S110
        pass
    return msg


@router.delete("/rooms/{room_id}/messages/{msg_id}")
async def delete_message(
    room_id: str,
    msg_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    msgs = _get_messages(room_id, 1000)
    new_msgs = [m for m in msgs if m.get("id") != msg_id]
    if len(new_msgs) == len(msgs):
        raise HTTPException(status_code=404, detail="Message not found")
    r = _redis()
    key = f"{_MSG_PREFIX}{room_id}"
    if r:
        try:
            r.delete(key)
            for m in reversed(new_msgs):
                r.rpush(key, json.dumps(m))
        except Exception:  # nosec B110  # noqa: S110
            pass
    else:
        _MEM_MSGS[room_id] = new_msgs
    return {"success": True}


@router.post("/rooms/{room_id}/messages/{msg_id}/reactions")
async def add_reaction(
    room_id: str,
    msg_id: str,
    body: dict,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Add an emoji reaction to a message. Idempotent — adding the same emoji twice is a no-op."""
    emoji = (body.get("emoji") or "").strip()
    if not emoji:
        raise HTTPException(status_code=422, detail="emoji is required")
    reactions = _get_reactions(msg_id)
    users = reactions.get(emoji, [])
    if user.sub not in users:
        users = users + [user.sub]
        _save_reaction(msg_id, emoji, users)
    return {"msg_id": msg_id, "emoji": emoji, "count": len(users), "reactions": {**reactions, emoji: users}}


@router.delete("/rooms/{room_id}/messages/{msg_id}/reactions/{emoji}")
async def remove_reaction(
    room_id: str,
    msg_id: str,
    emoji: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Remove the current user's emoji reaction from a message."""
    reactions = _get_reactions(msg_id)
    users = [u for u in reactions.get(emoji, []) if u != user.sub]
    _save_reaction(msg_id, emoji, users)
    updated = {**reactions, emoji: users}
    if not users:
        updated.pop(emoji, None)
    return {"msg_id": msg_id, "emoji": emoji, "count": len(users), "reactions": updated}


@router.post("/rooms/{room_id}/read")
async def mark_room_read(
    room_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Mark all messages in a room as read for the current user."""
    _mark_room_read(room_id, user.sub)
    return {"room_id": room_id, "read": True}


@router.get("/dm/{target_user_id}")
async def get_dms(
    target_user_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    msgs = _get_dms(user.sub, target_user_id, limit)
    return {"messages": msgs, "total": len(msgs)}


@router.post("/dm/{target_user_id}")
async def send_dm(
    target_user_id: str,
    body: SendMessageBody,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    body.validate_non_empty()
    msg = {
        "id": str(uuid.uuid4()),
        "from_user_id": user.sub,
        "to_user_id": target_user_id,
        "content": body.message_text,
        "created_at": datetime.now(UTC).isoformat(),
        "read": False,
    }
    _save_dm(user.sub, target_user_id, msg)
    return msg


@router.get("/online")
async def online_users(user: TokenPayload = Depends(get_current_user)) -> dict:
    import time as _time

    now = _time.time()
    r = _redis()
    if r:
        try:
            r.zadd(_ONLINE_KEY, {user.sub: now})
            r.zremrangebyscore(_ONLINE_KEY, 0, now - 60)
            members = r.zrange(_ONLINE_KEY, 0, -1)
            return {"online_users": [m.decode() for m in members], "count": len(members)}
        except Exception:  # nosec B110  # noqa: S110
            pass
    _MEM_ONLINE[user.sub] = now
    active = {uid: ts for uid, ts in _MEM_ONLINE.items() if now - ts < 60}
    _MEM_ONLINE.clear()
    _MEM_ONLINE.update(active)
    return {"online_users": list(active.keys()), "count": len(active)}


# ── WebSocket real-time chat ───────────────────────────────────────────────────


@ws_router.websocket("/ws/chat/{room_id}")
async def chat_ws(room_id: str, websocket: WebSocket) -> None:
    """
    Real-time WebSocket endpoint for community chat rooms.

    Connect: GET ws[s]://host/ws/chat/{room_id}?token=<jwt>
    Server pushes:  {"type": "message", "message": {...}}
    Server pushes:  {"type": "heartbeat"}
    Client sends:   {"type": "ping"}  — server echoes {"type": "pong"}
    """
    import asyncio

    # Auth — token passed as query param (same pattern as /ws/live).
    # FIX: invalid or missing tokens must reject the connection, not silently
    # allow unauthenticated access.  Chat rooms contain user-generated content
    # that should only be visible to authenticated members.
    token_param = websocket.query_params.get("token", "")
    _ws_chat_auth_required: bool = os.getenv("WS_AUTH_REQUIRED", "true").lower() == "true"

    if _ws_chat_auth_required:
        _chat_user_id: str | None = None
        if token_param:
            try:
                from api.auth import decode_access_token

                _payload = decode_access_token(token_param)
                _chat_user_id = str(_payload.get("sub", _payload.get("user_id", ""))) if _payload else None
            except Exception:
                _chat_user_id = None

        if _chat_user_id is None:
            # Must accept before closing — FastAPI requires accept() before close().
            # Guard every send/close: the client may already be gone, which
            # otherwise surfaces as an unhandled ASGI ConnectionClosed error.
            try:
                await websocket.accept()
                await websocket.send_text(
                    json.dumps({"type": "error", "code": "AUTH_REQUIRED", "message": "Valid JWT required"})
                )
                await websocket.close(code=4001)
            except Exception:  # noqa: S110  # nosec B110 — client disconnected before we replied
                pass
            return
    else:
        _chat_user_id = "anonymous"

    try:
        await websocket.accept()
    except Exception:  # nosec B110 — client disconnected during handshake
        return

    # Register connection — enforce per-room limit to prevent memory DoS
    if room_id not in _CHAT_CONNECTIONS:
        _CHAT_CONNECTIONS[room_id] = []
    if len(_CHAT_CONNECTIONS[room_id]) >= _MAX_CONNECTIONS_PER_ROOM:
        await websocket.close(code=1008, reason="Room connection limit reached")
        return
    _CHAT_CONNECTIONS[room_id].append(websocket)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                try:
                    data = json.loads(raw)
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except Exception:  # nosec B110  # noqa: S110
                    pass
            except TimeoutError:
                # Send heartbeat to keep connection alive
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
    except WebSocketDisconnect:  # nosec B110
        pass
    finally:
        conns = _CHAT_CONNECTIONS.get(room_id, [])
        if websocket in conns:
            conns.remove(websocket)
