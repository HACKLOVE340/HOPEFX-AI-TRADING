# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# utils/disaster_recovery.py
"""
HOPEFX Disaster Recovery System
Automated backup, failover, and state restoration
"""

import asyncio
import gzip
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

if TYPE_CHECKING:
    import aiohttp


@dataclass
class SystemState:
    """Complete system state snapshot"""

    timestamp: str
    event_store_position: int
    strategy_states: dict[str, dict]
    open_positions: list[dict]
    risk_metrics: dict
    performance_cache: dict
    checksum: str


class ContinuousBackup:
    """
    Continuous incremental backup with point-in-time recovery.
    """

    def __init__(self, backup_path: str = "backups/", snapshot_interval_minutes: int = 5):
        self.backup_path = Path(backup_path)
        self.snapshot_interval = snapshot_interval_minutes
        self.backup_path.mkdir(parents=True, exist_ok=True)

        # Backup destinations (local + cloud)
        self.destinations: list[Path] = [self.backup_path]
        self.cloud_enabled = False

    async def enable_s3_backup(self, bucket: str, region: str):
        """Enable AWS S3 backup"""
        import aiobotocore

        self.s3_bucket = bucket
        self.s3_region = region
        self.cloud_enabled = True

        # Test connection
        session = aiobotocore.get_session()
        async with session.create_client("s3", region_name=region) as client:
            await client.head_bucket(Bucket=bucket)

        print(f"☁️ S3 backup enabled: {bucket}")

    async def create_snapshot(self, event_store, orchestra, risk_engine) -> SystemState:
        """Create consistent point-in-time snapshot"""
        # Pause event processing briefly
        # (In production, use copy-on-write)

        state = SystemState(
            timestamp=datetime.now(UTC).isoformat(),
            event_store_position=event_store._sequence if hasattr(event_store, "_sequence") else 0,
            strategy_states={
                sid: {
                    "is_active": strat.is_active,
                    "performance": strat.performance if hasattr(strat, "performance") else {},
                }
                for sid, strat in orchestra.strategies.items()
            },
            open_positions=[],  # Query from database
            risk_metrics=asdict(risk_engine.current_risk) if risk_engine.current_risk else {},
            performance_cache={},
            checksum="",  # Calculated below
        )

        # Calculate checksum
        state_str = json.dumps(asdict(state), sort_keys=True)
        state.checksum = hashlib.sha256(state_str.encode()).hexdigest()

        # Compress and save
        filename = f"snapshot_{state.timestamp.replace(':', '-')}.json.gz"
        filepath = self.backup_path / filename

        async with aiofiles.open(filepath, "wb") as f:
            compressed = gzip.compress(json.dumps(asdict(state)).encode())
            await f.write(compressed)

        # Upload to cloud if enabled
        if self.cloud_enabled:
            await self._upload_to_cloud(filepath, filename)

        # Cleanup old snapshots (keep last 100)
        await self._cleanup_old_snapshots()

        print(f"💾 Snapshot created: {filename}")
        return state

    async def _upload_to_cloud(self, local_path: Path, filename: str):
        """Upload to S3 with encryption"""
        import aiobotocore

        session = aiobotocore.get_session()
        async with session.create_client("s3", region_name=self.s3_region) as client:
            with Path(local_path).open("rb") as f:
                await client.put_object(
                    Bucket=self.s3_bucket,
                    Key=f"hopefx/snapshots/{filename}",
                    Body=f,
                    ServerSideEncryption="AES256",
                )

    async def _cleanup_old_snapshots(self):
        """Keep only last 100 local snapshots"""
        snapshots = sorted(self.backup_path.glob("snapshot_*.json.gz"))
        if len(snapshots) > 100:
            for old in snapshots[:-100]:
                old.unlink()

    async def restore_from_snapshot(self, snapshot_file: str) -> SystemState:
        """Restore system state from snapshot"""
        filepath = self.backup_path / snapshot_file

        async with aiofiles.open(filepath, "rb") as f:
            compressed = await f.read()
            data = gzip.decompress(compressed)
            state_dict = json.loads(data)

        # Verify checksum
        state_copy = state_dict.copy()
        stored_checksum = state_copy.pop("checksum")
        calculated = hashlib.sha256(json.dumps(state_copy, sort_keys=True).encode()).hexdigest()

        if stored_checksum != calculated:
            raise ValueError("Snapshot checksum verification failed!")

        state = SystemState(**state_dict)
        print(f"✅ Restored from snapshot: {snapshot_file}")
        return state


class FailoverManager:
    """
    Automatic failover to backup nodes.
    """

    # Default port used when a peer string contains no port component.
    HEARTBEAT_PORT: int = 8765

    def __init__(self, node_id: str, peers: list[str]):
        self.node_id = node_id
        self.peers = peers  # Other HOPEFX nodes
        self.is_primary = False
        self.heartbeat_interval = 5  # seconds
        self.last_peer_heartbeat: dict[str, datetime] = {}
        self.failover_timeout = 15  # seconds
        # Shared aiohttp session — created lazily on first use
        self._session: aiohttp.ClientSession | None = None  # type: ignore[name-defined]

    async def start_election(self):
        """
        Raft/Paxos-style leader election.
        """
        print(f"🗳️ Starting leader election (node: {self.node_id})")

        # Simple bully algorithm for now
        # In production, use proper consensus (etcd, Consul)

        # Assume highest node ID wins
        all_nodes = sorted([self.node_id, *self.peers])
        self.is_primary = all_nodes[-1] == self.node_id

        if self.is_primary:
            print("✅ Elected as PRIMARY node")
        else:
            print("⏸️ Running as SECONDARY node")

    async def heartbeat_loop(self):
        """Send heartbeats to peers and monitor their health"""
        while True:
            # Send heartbeat to all peers
            for peer in self.peers:
                await self._send_heartbeat(peer)

            # Check if primary is alive
            if not self.is_primary:
                primary = max([self.node_id, *self.peers])  # Assume highest is primary
                if primary != self.node_id:
                    last_seen = self.last_peer_heartbeat.get(primary)
                    if last_seen and (datetime.now(UTC) - last_seen).seconds > self.failover_timeout:
                        print(f"⚠️ Primary {primary} appears down! Triggering failover...")
                        await self._trigger_failover()

            await asyncio.sleep(self.heartbeat_interval)

    async def _send_heartbeat(self, peer: str) -> None:
        """POST a heartbeat JSON payload to the peer's /heartbeat endpoint.

        Peer format: ``host``, ``host:port``, or ``http://host:port``.
        Falls back to HEARTBEAT_PORT when no port is specified.
        Updates last_peer_heartbeat on a successful (2xx) response.
        """
        import aiohttp

        # Build the target URL
        if peer.startswith("http://") or peer.startswith("https://"):
            url = peer.rstrip("/") + "/heartbeat"
        elif ":" in peer:
            url = f"http://{peer}/heartbeat"
        else:
            url = f"http://{peer}:{self.HEARTBEAT_PORT}/heartbeat"

        payload = {
            "node_id": self.node_id,
            "is_primary": self.is_primary,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Lazily create a shared session
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3.0))

        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status < 300:
                    self.last_peer_heartbeat[peer] = datetime.now(UTC)
                else:
                    print(f"⚠️ Heartbeat to {peer} returned HTTP {resp.status}")
        except aiohttp.ClientError as exc:
            # Network errors are expected when a peer is down — log and continue
            print(f"⚠️ Heartbeat to {peer} failed: {exc}")

    async def _trigger_failover(self):
        """Promote self to primary"""
        print("🚨 FAILOVER: Promoting to primary")
        self.is_primary = True
        # Take over processing
        # Load latest state from backup
        # Resume trading

    async def graceful_handover(self, new_primary: str):
        """Gracefully hand over primary role"""
        if self.is_primary:
            print(f"🤝 Handing over primary to {new_primary}")
            self.is_primary = False
            # Sync state to new primary
            # Pause new orders
            # Wait for confirmation
