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
        c = _r.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                        socket_connect_timeout=1, socket_timeout=1)
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
        except Exception:
            pass
    return dict(_MEM_ROOMS)


def _save_room(room: dict) -> None:
    r = _redis()
    if r:
        try:
            r.hset(_ROOMS_KEY, room["id"], json.dumps(room))
            return
        except Exception:
            pass
    _MEM_ROOMS[room["id"]] = room


def _get_messages(room_id: str, limit: int = 100) -> list[dict]:
    r = _redis()
    key = f"{_MSG_PREFIX}{room_id}"
    if r:
        try:
            raw = r.lrange(key, 0, limit - 1)
            return [json.loads(x) for x in raw]
        except Exception:
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
        except Exception:
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
        except Exception:
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
        except Exception:
            pass
    _MEM_DMS.setdefault(key, []).insert(0, msg)
    _MEM_DMS[key] = _MEM_DMS[key][:1000]


def _seed_default_rooms() -> None:
    rooms = _get_rooms()
    if rooms:
        return
    now = datetime.now(UTC).isoformat()
    defaults = [
        {"id": "general", "name": "General", "description": "General trading discussion",
         "type": "public", "member_count": 0, "pinned": True, "created_at": now, "last_message_at": now},
        {"id": "signals", "name": "Signals", "description": "AI signal alerts and discussion",
         "type": "public", "member_count": 0, "pinned": True, "created_at": now, "last_message_at": now},
        {"id": "gold-xauusd", "name": "Gold / XAUUSD", "description": "Gold trading strategies",
         "type": "public", "member_count": 0, "pinned": False, "created_at": now, "last_message_at": now},
        {"id": "support", "name": "Support", "description": "Platform support and help",
         "type": "public", "member_count": 0, "pinned": False, "created_at": now, "last_message_at": now},
    ]
    for d in defaults:
        _save_room(d)


# ── Pydantic models ───────────────────────────────────────────────────────────

class CreateRoomBody(BaseModel):
    name: str
    description: str = ""
    type: str = "public"


class SendMessageBody(BaseModel):
    content: str | None = None  # canonical field name
    text: str | None = None     # legacy alias — kept for backward compat
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
    except Exception:
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
        except Exception:
            pass
    else:
        _MEM_MSGS[room_id] = new_msgs
    return {"success": True}


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
        except Exception:
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

    # Auth — token passed as query param (same pattern as /ws/live)
    token_param = websocket.query_params.get("token", "")
    if token_param:
        try:
            from api.auth import decode_access_token
            decode_access_token(token_param)
        except Exception:
            pass  # allow unauthenticated reads; writes gated via REST

    await websocket.accept()

    # Register connection
    if room_id not in _CHAT_CONNECTIONS:
        _CHAT_CONNECTIONS[room_id] = []
    _CHAT_CONNECTIONS[room_id].append(websocket)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                try:
                    data = json.loads(raw)
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except Exception:
                    pass
            except TimeoutError:
                # Send heartbeat to keep connection alive
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        conns = _CHAT_CONNECTIONS.get(room_id, [])
        if websocket in conns:
            conns.remove(websocket)
