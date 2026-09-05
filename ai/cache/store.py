# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A response cache in front of the gateway (AI Core plan Task 12, spec §3.5).

"Inference economics": a repeated query stops hitting the paid tier. A cache in
front of a model is cheap to add and easy to turn into a correctness bug, so the
four properties that keep it honest are enforced here rather than left to
callers:

* **A failure is never cached.** `put` refuses a null value. Caching an error
  makes a transient outage sticky -- the next caller gets a stale failure
  instead of a live attempt, and the outage outlives its cause.
* **The key includes the tool state.** The same prompt asked against different
  open positions is a different question. An answer computed under one state
  must never be served against another, so the state is part of the key and
  `invalidate_tool_state` drops every entry under a state that has moved.
* **A hit costs nothing.** The gateway returns a hit before `budget.charge`,
  so a ceiling never falls for a call that was not made.
* **The prompt is not stored.** Prompts here carry position sizes and stop
  levels. Only a SHA-256 digest is kept -- the same rule the gateway's audit
  record already follows -- and `entries()` exposes metadata only, never the
  cached value, so no introspection path can leak either side of the exchange.

The store is bounded (`max_entries`) and evicts the oldest entry first: an
unbounded cache in a long-lived process is a slow memory leak, and a slow leak
in a trading process is an outage at the worst possible time.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL_S = 300.0
DEFAULT_MAX_ENTRIES = 512


def _digest(*parts: str) -> str:
    """A stable key over parts that must not be recoverable from the store."""
    joined = "\x00".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    """What `entries()` may reveal: metadata, never the prompt or the answer."""

    key: str
    model: str
    tool_state_digest: str
    stored_at: float
    expires_at: float

    def is_live(self, now: float) -> bool:
        return now < self.expires_at


class ResponseCache:
    """Keyed on (prompt digest, model, tool-state digest), bounded and expiring."""

    def __init__(self, ttl_s: float = DEFAULT_TTL_S, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if ttl_s < 0:
            raise ValueError("ttl_s cannot be negative")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl_s = float(ttl_s)
        self._max_entries = int(max_entries)
        self._lock = threading.Lock()
        self._entries: dict[str, CacheEntry] = {}
        self._values: dict[str, Any] = {}
        self._hits = 0
        self._misses = 0

    # ── keying ────────────────────────────────────────────────────────────────

    @staticmethod
    def key_for(*, prompt: str, model: str, tool_state: str) -> str:
        return _digest(prompt, model, tool_state)

    # ── reads ─────────────────────────────────────────────────────────────────

    def get(self, *, prompt: str, model: str, tool_state: str = "") -> Any | None:
        """The cached value, or None on a miss or an expired entry."""
        key = self.key_for(prompt=prompt, model=model, tool_state=tool_state)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if not entry.is_live(now):
                # Drop rather than serve: an expired answer is a miss, and
                # leaving it in place would keep the store growing.
                self._entries.pop(key, None)
                self._values.pop(key, None)
                self._misses += 1
                return None
            self._hits += 1
            return self._values.get(key)

    def entries(self) -> tuple[CacheEntry, ...]:
        """Metadata for every live entry. Deliberately excludes prompts and values."""
        now = time.monotonic()
        with self._lock:
            return tuple(entry for entry in self._entries.values() if entry.is_live(now))

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._entries),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": (self._hits / total) if total else 0.0,
                "ttl_s": self._ttl_s,
                "max_entries": self._max_entries,
            }

    # ── writes ────────────────────────────────────────────────────────────────

    def put(self, *, prompt: str, model: str, tool_state: str = "", value: Any) -> str:
        """Store `value`. Refuses a null value: a failure is never cached."""
        if value is None:
            raise ValueError("refusing to cache a failure: a null value is not an answer")
        key = self.key_for(prompt=prompt, model=model, tool_state=tool_state)
        now = time.monotonic()
        entry = CacheEntry(
            key=key,
            model=model,
            tool_state_digest=_digest(tool_state),
            stored_at=now,
            expires_at=now + self._ttl_s,
        )
        with self._lock:
            self._entries[key] = entry
            self._values[key] = value
            self._evict_locked(now)
        return key

    def invalidate(self, *, prompt: str, model: str, tool_state: str = "") -> bool:
        """Drop one entry. True if something was actually dropped."""
        key = self.key_for(prompt=prompt, model=model, tool_state=tool_state)
        with self._lock:
            self._values.pop(key, None)
            return self._entries.pop(key, None) is not None

    def invalidate_tool_state(self, tool_state: str) -> int:
        """Drop every entry computed under `tool_state`; returns how many.

        This is the call a position change, a fill, or a config edit makes. An
        answer computed under a state that has moved is not stale in the TTL
        sense -- it is wrong -- so it does not get to wait for its TTL.
        """
        target = _digest(tool_state)
        with self._lock:
            doomed = [key for key, entry in self._entries.items() if entry.tool_state_digest == target]
            for key in doomed:
                self._entries.pop(key, None)
                self._values.pop(key, None)
            return len(doomed)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._values.clear()

    # ── internals ─────────────────────────────────────────────────────────────

    def _evict_locked(self, now: float) -> None:
        """Expired first, then oldest. Caller holds the lock."""
        for key in [k for k, e in self._entries.items() if not e.is_live(now)]:
            self._entries.pop(key, None)
            self._values.pop(key, None)
        while len(self._entries) > self._max_entries:
            oldest = min(self._entries.values(), key=lambda e: e.stored_at)
            self._entries.pop(oldest.key, None)
            self._values.pop(oldest.key, None)


# -- the process-wide instance --------------------------------------------------
#
# Absent by default, and reported as absent. A panel that showed "cache:
# enabled" for a store nothing consults would be exactly the decorative control
# this work exists to remove, so installation is explicit and `shared_cache()`
# returns None until something installs one.

_SHARED: ResponseCache | None = None


def install_shared_cache(cache: ResponseCache | None) -> ResponseCache | None:
    """Install (or, with None, remove) the process-wide response cache."""
    global _SHARED
    _SHARED = cache
    return _SHARED


def shared_cache() -> ResponseCache | None:
    """The process-wide cache, or None when no deployment installed one."""
    return _SHARED


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_S",
    "CacheEntry",
    "ResponseCache",
    "install_shared_cache",
    "shared_cache",
]
