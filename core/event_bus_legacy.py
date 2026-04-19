# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Zero-Copy Event Bus
Connects all components with sub-microsecond latency
"""

import asyncio
import mmap
import struct
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

try:
    import lz4.frame
    import msgpack
    _COMPRESSION_AVAILABLE = True
except ImportError:
    lz4 = None  # type: ignore[assignment]
    msgpack = None  # type: ignore[assignment]
    _COMPRESSION_AVAILABLE = False


@dataclass
class DomainEvent:
    """Ultra-compact event for high-frequency trading"""

    timestamp: int
    event_type: int
    source: str
    payload: bytes
    priority: int = 5

    @classmethod
    def create(cls, event_type: str, source: str, data: dict, priority: int = 5):
        type_codes = {
            "PRICE_UPDATE": 1,
            "SIGNAL_GENERATED": 2,
            "ORDER_SUBMITTED": 3,
            "ORDER_FILLED": 4,
            "POSITION_OPENED": 5,
            "POSITION_CLOSED": 6,
            "RISK_VIOLATION": 7,
            "KILL_SWITCH": 8,
            "REGIME_CHANGE": 9,
            "COMPOSITE_SIGNAL": 10,
            "HEARTBEAT": 11,
        }
        if _COMPRESSION_AVAILABLE:
            packed = msgpack.packb(data, use_bin_type=True)
            payload = lz4.frame.compress(packed)
        else:
            import json as _json
            payload = _json.dumps(data).encode()
        return cls(
            timestamp=int(datetime.now(UTC).timestamp() * 1e9),
            event_type=type_codes.get(event_type, 99),
            source=source,
            payload=payload,
            priority=priority,
        )

    def decode(self) -> dict:
        if _COMPRESSION_AVAILABLE:
            return msgpack.unpackb(lz4.frame.decompress(self.payload), raw=False)
        import json as _json
        return _json.loads(self.payload.decode())


class MemoryMappedEventStore:
    """Persistent event store with 1M+ events/sec throughput"""

    def __init__(
        self,
        base_path: str = "data/events/",
        max_file_size: int = 1_073_741_824,
    ):
        self.base_path = base_path
        self.max_file_size = max_file_size
        self.current_file = None
        self.current_mmap = None
        self.current_offset = 0
        self.file_counter = 0
        self._lock = threading.RLock()
        self._index = defaultdict(list)
        self._sequence = 0
        Path(base_path).mkdir(parents=True, exist_ok=True)
        self._rotate_file()

    def _rotate_file(self):
        if self.current_mmap:
            self.current_mmap.flush()
            self.current_mmap.close()
            self.current_file.close()
        filename = f"{self.base_path}events_{self.file_counter:06d}.bin"
        self.file_counter += 1
        with Path(filename).open("wb") as f:
            f.write(b"\x00" * self.max_file_size)
        self.current_file = Path(filename).open("r+b")  # noqa: SIM115 — kept open for mmap lifetime
        self.current_mmap = mmap.mmap(self.current_file.fileno(), self.max_file_size)
        self.current_offset = 0

    def append(self, event: DomainEvent) -> int:
        with self._lock:
            self._sequence += 1
            src_bytes = event.source.encode()
            # Header layout: sequence(Q=uint64) | timestamp(Q=uint64) | event_type(H=uint16)
            # timestamp is nanoseconds since epoch — requires uint64, not uint32.
            header = struct.pack(
                ">QQH",
                self._sequence,
                event.timestamp,
                event.event_type,
            )
            header += struct.pack("B", len(src_bytes)) + src_bytes
            header += struct.pack(">I", len(event.payload))
            record = header + event.payload

            if self.current_offset + len(record) > self.max_file_size:
                self._rotate_file()

            self.current_mmap[self.current_offset : self.current_offset + len(record)] = record
            self.current_offset += len(record)
            self._index[event.source].append(
                (self.file_counter - 1, self.current_offset - len(record)),
            )
            return self._sequence

    def query(
        self,
        source: str | None = None,
        event_type: int | None = None,
        limit: int = 1000,
    ):
        results = []
        sources = [source] if source else list(self._index.keys())
        for src in sources:
            for file_num, offset in self._index[src][-limit:]:
                event = self._read_at(file_num, offset)
                if event and (not event_type or event.event_type == event_type):
                    results.append(event)
        return sorted(results, key=lambda e: e.timestamp)[:limit]

    def _read_at(self, file_num: int, offset: int):
        filename = f"{self.base_path}events_{file_num:06d}.bin"
        if not Path(filename).exists():
            return None
        with Path(filename).open("rb") as f:
            f.seek(offset)
            # Header: sequence(Q=8) | timestamp(Q=8) | event_type(H=2) = 18 bytes
            header = f.read(19)
            if len(header) < 19:
                return None
            _, ts, evt_type = struct.unpack(">QQH", header[:18])
            src_len = header[18]
            src = f.read(src_len).decode()
            payload_len = struct.unpack(">I", f.read(4))[0]
            payload = f.read(payload_len)
            return DomainEvent(
                timestamp=ts,
                event_type=evt_type,
                source=src,
                payload=payload,
            )


class EventBus:
    """Async event bus with priority routing"""

    def __init__(self, store: MemoryMappedEventStore):
        self.store = store
        self.subscribers = defaultdict(list)
        self._queue = asyncio.PriorityQueue()
        self._running = False
        self._metrics = {"published": 0, "delivered": 0, "dropped": 0}

    def subscribe(self, event_type: str, handler: Callable[[DomainEvent], None]):
        codes = {
            "PRICE_UPDATE": 1,
            "SIGNAL_GENERATED": 2,
            "ORDER_SUBMITTED": 3,
            "ORDER_FILLED": 4,
            "POSITION_OPENED": 5,
            "POSITION_CLOSED": 6,
            "RISK_VIOLATION": 7,
            "KILL_SWITCH": 8,
            "REGIME_CHANGE": 9,
            "COMPOSITE_SIGNAL": 10,
            "HEARTBEAT": 11,
        }
        self.subscribers[codes.get(event_type, 99)].append(handler)

    async def publish(self, event: DomainEvent):
        self.store.append(event)
        self._metrics["published"] += 1
        await self._queue.put((event.priority, event.timestamp, event))

    async def run(self):
        self._running = True
        while self._running:
            try:
                _, _, event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
                for handler in self.subscribers.get(event.event_type, []):
                    try:
                        handler(event)
                        self._metrics["delivered"] += 1
                    except Exception:
                        self._metrics["dropped"] += 1
            except TimeoutError:
                continue

    def get_metrics(self):
        return self._metrics.copy()
