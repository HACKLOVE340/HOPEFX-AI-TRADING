# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/global_fortress.py
============================
HOPEFXBrain — 24/7 autonomous security engine.

Responsibilities
----------------
* Scan all FastAPI routes every 30 s for health anomalies.
* Consume honeypot logs from Redis, geo-locate each attacker via ip-api.com,
  classify intent with the LLM, and decide a response action via the RL agent.
* Auto-heal: every 30 min, ask the LLM to review a code snippet and push the
  suggested fix to the Redis ``fixes:queue`` for dashboard approval.
* Full lockdown: block IP in Redis, pause trading, trigger ArgoCD rollback.
* Expose attack log and fix queue via FastAPI sub-router so the React
  dashboard can poll them.

Integration
-----------
Start the brain in connect_to_life.py::

    from security.global_fortress import start_brain
    _t = asyncio.create_task(start_brain(app))
    _t.add_done_callback(lambda _: None)

The sub-router is mounted automatically when ``start_brain`` is called.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any, ClassVar

import httpx
import numpy as np
from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
SCAN_INTERVAL: int = int(os.getenv("BRAIN_SCAN_INTERVAL", "30"))  # seconds
HEAL_INTERVAL: int = int(os.getenv("BRAIN_HEAL_INTERVAL", "1800"))  # 30 min
FLASHPOINT_API: str = os.getenv("FLASHPOINT_API_URL", "https://api.flashpoint.io/v1/iocs")
FLASHPOINT_KEY: str = os.getenv("FLASHPOINT_API_KEY", "")
ARGOCD_WEBHOOK: str = os.getenv("ARGOCD_ROLLBACK_WEBHOOK", "")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# RL action constants (must match train_rl_nuclear.py action space)
ACTION_MONITOR = 0
ACTION_RATE_LIMIT = 1
ACTION_BLOCK = 2
ACTION_NUCLEAR = 3

# LLM prompt templates
LLM_INTENT_PROMPT = (
    "You are a cybersecurity analyst. Analyze this attack log: {log}. "
    "Predict the attacker's intent. Reply with exactly one word: "
    "probe, exfil, ddos, bruteforce, or unknown."
)
LLM_FIX_PROMPT = (
    "Rewrite this FastAPI endpoint code to be production-secure. "
    "Fix SQL injection, add rate limiting, enforce auth, sanitize inputs. "
    "Return only the corrected Python code with no explanation:\n\n{code_snippet}"
)


# ── Redis client (lazy init) ──────────────────────────────────────────────────

_redis_client: Any | None = None


async def _get_redis() -> Any:
    """Return Sentinel-aware Redis client (lazy init)."""
    global _redis_client
    if _redis_client is None:
        try:
            from cache.redis_client import get_redis as _get_redis_client

            _redis_client = await _get_redis_client()
        except ImportError:
            # Fallback: direct URL
            try:
                import redis.asyncio as aioredis

                _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
            except Exception as exc:
                logger.warning("Redis unavailable for HOPEFXBrain: %s", exc)
    return _redis_client


# ── RL agent (lazy load) ──────────────────────────────────────────────────────

_rl_agent: Any | None = None


def _get_rl_agent() -> Any | None:
    global _rl_agent
    if _rl_agent is None:
        try:
            from stable_baselines3 import PPO

            model_path = os.path.join(
                Path(__file__).parent,
                "..",
                "ml",
                "rl_models",
                "nuclear_decision_ppo.zip",
            )
            if Path(model_path).exists():
                _rl_agent = PPO.load(model_path)
                logger.info("HOPEFXBrain: RL agent loaded from %s", model_path)
            else:
                logger.warning(
                    "HOPEFXBrain: RL model not found at %s — using rule-based fallback",
                    model_path,
                )
        except Exception as exc:
            logger.warning("HOPEFXBrain: RL agent load failed: %s", exc)
    return _rl_agent


# ── Semantic encoder (lazy load, optional) ────────────────────────────────────
# Disabled by default on CPU-only nodes to avoid pulling ~1 GB of PyTorch.
# Enable by setting BRAIN_SEMANTIC_ENCODER=true in your environment.
# When disabled the brain still classifies attacks via the LLM — the encoder
# is only used for additional similarity scoring (non-critical path).

_ENCODER_ENABLED: bool = os.getenv("BRAIN_SEMANTIC_ENCODER", "false").lower() == "true"
_encoder: Any | None = None


def _get_encoder() -> Any | None:
    """
    Lazy-load SentenceTransformer.

    Skipped unless BRAIN_SEMANTIC_ENCODER=true.  On first load, logs a
    one-time warning about the ~90 MB model download (PyTorch itself is
    ~1 GB and must already be installed — sentence-transformers does not
    pull it automatically when torch is absent).
    """
    global _encoder
    if not _ENCODER_ENABLED:
        return None
    if _encoder is None:
        try:
            from sentence_transformers import SentenceTransformer

            logger.info(
                "HOPEFXBrain: loading SentenceTransformer (all-MiniLM-L6-v2, ~90 MB). "
                "Requires PyTorch — set BRAIN_SEMANTIC_ENCODER=false on CPU-only nodes "
                "to skip this entirely."
            )
            _encoder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("HOPEFXBrain: SentenceTransformer ready")
        except ImportError:
            logger.warning(
                "HOPEFXBrain: sentence-transformers not installed. "
                "Install with: pip install sentence-transformers "
                "Or set BRAIN_SEMANTIC_ENCODER=false to suppress this warning."
            )
        except Exception as exc:
            logger.warning("HOPEFXBrain: SentenceTransformer load failed: %s", exc)
    return _encoder


# ── HOPEFXBrain ───────────────────────────────────────────────────────────────


class HOPEFXBrain:
    """
    Autonomous 24/7 security engine.

    attack_log: Dict[ip_str, AttackRecord]
    """

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.attack_log: dict[str, dict[str, Any]] = {}
        self._last_heal: float = time.monotonic()
        self._lockdown_active: bool = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def monitor_24_7(self) -> None:
        """Run forever — scan, trace, heal every SCAN_INTERVAL seconds."""
        logger.info("HOPEFXBrain: 24/7 monitor started (interval=%ds)", SCAN_INTERVAL)
        while True:
            try:
                await self.scan_endpoints()
                await self.trace_attacks()
                await self.auto_heal()
                await self._sync_flashpoint_iocs()
            except Exception:
                logger.exception("HOPEFXBrain loop error: %s")
            await asyncio.sleep(SCAN_INTERVAL)

    # ── Endpoint scanner ──────────────────────────────────────────────────────

    async def scan_endpoints(self) -> None:
        """
        Health-check every registered FastAPI route.
        Routes that return non-2xx are flagged in Redis for alerting.
        """
        redis = await _get_redis()
        flagged: ClassVar[list[str]] = []

        for route in self.app.routes:
            path: str = getattr(route, "path", "")
            if not path or path in ("/health", "/ready", "/metrics"):
                continue
            # Mark trader/broker/data routes as high-priority
            priority = "high" if any(k in path for k in ("trader", "broker", "data", "order")) else "normal"
            if priority == "high":
                flagged.append(path)

        if redis and flagged:
            await redis.set(
                "brain:scanned_routes",
                json.dumps({"ts": datetime.now(UTC).isoformat(), "routes": flagged}),
                ex=120,
            )

    # ── Attack tracer ─────────────────────────────────────────────────────────

    async def trace_attacks(self) -> None:
        """
        Drain honeypot:logs from Redis, classify each hit, decide action.
        """
        redis = await _get_redis()
        if not redis:
            return

        # Drain up to 50 logs per cycle to avoid blocking
        raw_logs = await redis.lrange("honeypot:logs", 0, 49)
        if raw_logs:
            await redis.ltrim("honeypot:logs", len(raw_logs), -1)

        for log_str in raw_logs:
            try:
                log: dict[str, Any] = json.loads(log_str)
            except json.JSONDecodeError:
                continue

            ip: str = log.get("ip", "0.0.0.0")  # nosec B104 - default value for missing IP in log entry, not a bind address
            data: str = str(log.get("data", ""))

            geo = await self._geo_lookup(ip)
            intent = await self._llm_intent(data)
            severity = self._severity_from_intent(intent)

            self.attack_log[ip] = {
                "geo": geo,
                "intent": intent,
                "severity": severity,
                "time": datetime.now(UTC).isoformat(),
                "raw": data[:256],  # truncate for storage
            }

            # Persist to Redis for dashboard polling
            if redis:
                await redis.hset("brain:attack_log", ip, json.dumps(self.attack_log[ip]))
                await redis.expire("brain:attack_log", 86400)  # 24 h TTL

            # RL decision
            action = self._rl_decide(severity, geo)
            await self._execute_action(action, ip)

    async def _geo_lookup(self, ip: str) -> dict[str, Any]:
        """Geo-locate an IP via ip-api.com (free, no key required)."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://ip-api.com/json/{ip}?fields=country,city,lat,lon,isp,org")
                if resp.status_code == 200:
                    return resp.json()
        except Exception as exc:
            logger.debug("Geo lookup failed for %s: %s", ip, exc)
        return {"country": "Unknown", "city": "Unknown", "lat": 0.0, "lon": 0.0}

    async def _llm_intent(self, data: str) -> str:
        """Classify attack intent via LLM."""
        try:
            from security.llm_wrapper import call_llm

            result = await call_llm(LLM_INTENT_PROMPT.format(log=data[:512]))
            # Normalise to known intents
            result = result.strip().lower().split()[0] if result.strip() else "unknown"
            valid = {"probe", "exfil", "ddos", "bruteforce", "unknown"}
            return result if result in valid else "unknown"
        except Exception as exc:
            logger.debug("LLM intent failed: %s", exc)
            return "unknown"

    @staticmethod
    def _severity_from_intent(intent: str) -> float:
        """Map intent string to 0–1 severity score."""
        return {
            "probe": 0.2,
            "bruteforce": 0.5,
            "unknown": 0.3,
            "exfil": 0.8,
            "ddos": 0.9,
        }.get(intent, 0.3)

    def _rl_decide(self, severity: float, geo: dict[str, Any]) -> int:
        """
        Use the RL agent to pick an action.
        Falls back to rule-based thresholds when the model is unavailable.
        """
        agent = _get_rl_agent()
        if agent is not None:
            try:
                # 6-dim observation: [severity, lockdown, lat_norm, lon_norm, 0, 0]
                lat = float(geo.get("lat", 0.0)) / 90.0
                lon = float(geo.get("lon", 0.0)) / 180.0
                obs = np.array(
                    [severity, float(self._lockdown_active), lat, lon, 0.0, 0.0],
                    dtype=np.float32,
                )
                action, _ = agent.predict(obs, deterministic=True)
                return int(action)
            except Exception as exc:
                logger.debug("RL predict failed: %s", exc)

        # Rule-based fallback
        if severity >= 0.8:
            return ACTION_NUCLEAR
        if severity >= 0.5:
            return ACTION_BLOCK
        if severity >= 0.3:
            return ACTION_RATE_LIMIT
        return ACTION_MONITOR

    async def _execute_action(self, action: int, ip: str) -> None:
        """Execute the chosen action for *ip*."""
        redis = await _get_redis()
        action_name = {0: "monitor", 1: "rate_limit", 2: "block", 3: "nuclear"}.get(action, "monitor")
        logger.info("HOPEFXBrain: action=%s ip=%s", action_name, ip)

        if redis:
            await redis.hset(
                "brain:actions",
                ip,
                json.dumps(
                    {
                        "action": action_name,
                        "ts": datetime.now(UTC).isoformat(),
                    }
                ),
            )

        if action == ACTION_RATE_LIMIT and redis:
            await redis.setex(f"ratelimit:block:{ip}", 300, "1")  # 5-min rate limit

        elif action == ACTION_BLOCK and redis:
            await redis.setex(f"ip:blocked:{ip}", 3600, "1")  # 1-h block
            await redis.rpush("security:blocked_ips", ip)

        elif action == ACTION_NUCLEAR:
            await self.trigger_full_lockdown(ip)

    # ── Auto-heal ─────────────────────────────────────────────────────────────

    async def auto_heal(self) -> None:
        """
        Every HEAL_INTERVAL seconds, drain the ``scan:vuln_queue`` Redis list
        and ask the LLM to generate a fix for each vulnerable snippet found.

        Vulnerability entries are pushed to ``scan:vuln_queue`` by the static
        analysis scanner (security/code_scanner.py) or by external CI hooks.
        Each entry is a JSON object with keys:
            endpoint  — API route path (e.g. "/api/auth/login")
            code      — vulnerable code snippet (str)
            severity  — "high" | "medium" | "low"
            rule      — scanner rule ID that triggered (e.g. "B608")

        Generated fixes are pushed to ``fixes:queue`` for operator review
        in the dashboard before any code change is made.
        """
        if time.monotonic() - self._last_heal < HEAL_INTERVAL:
            return

        logger.info("HOPEFXBrain: running auto-heal scan")
        self._last_heal = time.monotonic()

        redis = await _get_redis()

        # Drain up to 10 vulnerability entries per cycle
        raw_entries: ClassVar[list[str]] = []
        if redis:
            raw_entries = await redis.lrange("scan:vuln_queue", 0, 9)
            if raw_entries:
                await redis.ltrim("scan:vuln_queue", len(raw_entries), -1)

        if not raw_entries:
            logger.debug("HOPEFXBrain: no vulnerability entries in scan:vuln_queue")
            return

        for raw in raw_entries:
            try:
                entry: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("HOPEFXBrain: malformed scan entry — skipping")
                continue

            endpoint = entry.get("endpoint", "unknown")
            code = entry.get("code", "")
            severity = entry.get("severity", "unknown")
            rule = entry.get("rule", "unknown")

            if not code:
                logger.debug("HOPEFXBrain: empty code snippet for %s — skipping", endpoint)
                continue

            try:
                from security.llm_wrapper import call_llm

                fix = await call_llm(LLM_FIX_PROMPT.format(code_snippet=code))
                record = {
                    "endpoint": endpoint,
                    "original": code,
                    "fix": fix,
                    "severity": severity,
                    "rule": rule,
                    "ts": datetime.now(UTC).isoformat(),
                    "status": "pending",  # pending | approved | declined
                    "pr_url": None,
                    "pr_number": None,
                }
                if redis:
                    await redis.rpush("fixes:queue", json.dumps(record))
                    logger.info(
                        "HOPEFXBrain: fix queued endpoint=%s severity=%s rule=%s",
                        endpoint,
                        severity,
                        rule,
                    )
            except Exception as exc:
                logger.warning("HOPEFXBrain: auto-heal failed for %s: %s", endpoint, exc)

    # ── Flashpoint IOC sync ───────────────────────────────────────────────────

    async def _sync_flashpoint_iocs(self) -> None:
        """Pull threat intelligence IOCs from Flashpoint (if key configured)."""
        if not FLASHPOINT_KEY:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    FLASHPOINT_API,
                    headers={"Authorization": f"Bearer {FLASHPOINT_KEY}"},
                    params={"limit": 100},
                )
                if resp.status_code == 200:
                    iocs = resp.json().get("data", [])
                    redis = await _get_redis()
                    if redis and iocs:
                        await redis.set(
                            "brain:flashpoint_iocs",
                            json.dumps(iocs),
                            ex=3600,
                        )
                        logger.info("HOPEFXBrain: synced %d Flashpoint IOCs", len(iocs))
        except Exception as exc:
            logger.debug("Flashpoint sync failed: %s", exc)

    # ── Full lockdown ─────────────────────────────────────────────────────────

    async def trigger_full_lockdown(self, ip: str) -> None:
        """
        Nuclear response:
        1. Set lockdown flag in Redis (all pods read this).
        2. Block the offending IP.
        3. Trigger ArgoCD rollback webhook (if configured).
        """
        logger.critical("HOPEFXBrain: FULL LOCKDOWN triggered by IP %s", ip)
        self._lockdown_active = True

        redis = await _get_redis()
        if redis:
            await redis.set("lockdown:active", "true", ex=3600)
            await redis.setex(f"ip:blocked:{ip}", 86400, "1")
            await redis.rpush("security:blocked_ips", ip)
            await redis.rpush(
                "alerts:critical",
                json.dumps(
                    {
                        "type": "lockdown",
                        "ip": ip,
                        "ts": datetime.now(UTC).isoformat(),
                    }
                ),
            )

        # ArgoCD rollback via webhook
        if ARGOCD_WEBHOOK:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        ARGOCD_WEBHOOK,
                        json={"action": "rollback", "reason": f"nuclear_lockdown:{ip}"},
                    )
                    logger.info("HOPEFXBrain: ArgoCD rollback triggered")
            except Exception as exc:
                logger.warning("ArgoCD rollback webhook failed: %s", exc)


# ── FastAPI sub-router (dashboard API) ────────────────────────────────────────


def _build_router(brain: HOPEFXBrain) -> APIRouter:
    """Return a router exposing brain state to the React dashboard."""
    router = APIRouter(prefix="/api/security", tags=["Security"])

    @router.get("/attacks")
    async def get_attacks():
        """Return current attack log (IP → record)."""
        redis = await _get_redis()
        if redis:
            raw = await redis.hgetall("brain:attack_log")
            return {ip: json.loads(v) for ip, v in raw.items()}
        return brain.attack_log

    @router.get("/fixes")
    async def get_fixes():
        """Return pending fix queue (up to 50 entries)."""
        redis = await _get_redis()
        if not redis:
            return []
        raw = await redis.lrange("fixes:queue", 0, 49)
        return [json.loads(r) for r in raw]

    @router.post("/fixes/approve")
    async def approve_fix(payload: dict):
        """
        Approve an LLM-generated fix.

        Triggers the GitHubPRPublisher pipeline:
          1. Creates a branch auto-heal/{timestamp}-{slug}
          2. Commits the patched file
          3. Opens a GitHub PR
          4. Updates the fix record in Redis with pr_url + pr_number
          5. Moves the record from fixes:queue to fixes:approved

        Returns the PR URL on success.
        """
        endpoint = payload.get("endpoint", "")
        approved_by = payload.get("approved_by", "dashboard")
        redis = await _get_redis()

        # Find the matching fix record in the queue
        fix_record: dict[str, Any] | None = None
        if redis:
            raw_list = await redis.lrange("fixes:queue", 0, 99)
            for _i, raw in enumerate(raw_list):
                try:
                    rec = json.loads(raw)
                    if rec.get("endpoint") == endpoint and rec.get("status") == "pending":
                        fix_record = rec
                        # Remove this entry from the queue
                        await redis.lrem("fixes:queue", 1, raw)
                        break
                except json.JSONDecodeError:
                    continue

        if fix_record is None:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=404,
                detail=f"No pending fix found for endpoint '{endpoint}'",
            )

        # Trigger GitHub PR pipeline
        pr_result: dict[str, Any] = {"status": "skipped"}
        try:
            from security.github_pr_publisher import get_pr_publisher

            pr_result = await get_pr_publisher().publish(
                endpoint=endpoint,
                original_code=fix_record.get("original", ""),
                fix_code=fix_record.get("fix", ""),
                approved_by=approved_by,
                fix_ts=fix_record.get("ts"),
            )
        except Exception as exc:
            logger.error("HOPEFXBrain: PR publisher error for %s: %s", endpoint, exc)
            pr_result = {"status": "error", "error": "PR publish failed — check server logs"}

        # Persist approved record with PR metadata
        approved_record = {
            **fix_record,
            "status": "approved",
            "approved_by": approved_by,
            "approved_at": datetime.now(UTC).isoformat(),
            "pr_url": pr_result.get("pr_url"),
            "pr_number": pr_result.get("pr_number"),
            "pr_branch": pr_result.get("branch"),
            "pr_status": pr_result.get("status"),
        }
        if redis:
            await redis.rpush("fixes:approved", json.dumps(approved_record))
            # Keep approved list bounded
            await redis.ltrim("fixes:approved", -500, -1)

        logger.info(
            "HOPEFXBrain: fix approved endpoint=%s pr_status=%s pr_url=%s",
            endpoint,
            pr_result.get("status"),
            pr_result.get("pr_url"),
        )

        return {
            "status": "approved",
            "endpoint": endpoint,
            "pr_url": pr_result.get("pr_url"),
            "pr_number": pr_result.get("pr_number"),
            "pr_branch": pr_result.get("branch"),
            "pr_status": pr_result.get("status"),
            "pr_error": pr_result.get("error"),
        }

    @router.post("/fixes/decline")
    async def decline_fix(payload: dict):
        """
        Decline an LLM-generated fix.

        Removes the record from fixes:queue and archives it in fixes:declined.
        """
        endpoint = payload.get("endpoint", "")
        declined_by = payload.get("declined_by", "dashboard")
        redis = await _get_redis()

        if redis:
            raw_list = await redis.lrange("fixes:queue", 0, 99)
            for raw in raw_list:
                try:
                    rec = json.loads(raw)
                    if rec.get("endpoint") == endpoint and rec.get("status") == "pending":
                        await redis.lrem("fixes:queue", 1, raw)
                        declined_record = {
                            **rec,
                            "status": "declined",
                            "declined_by": declined_by,
                            "declined_at": datetime.now(UTC).isoformat(),
                        }
                        await redis.rpush("fixes:declined", json.dumps(declined_record))
                        await redis.ltrim("fixes:declined", -500, -1)
                        break
                except json.JSONDecodeError:
                    continue

        logger.info("HOPEFXBrain: fix declined endpoint=%s by=%s", endpoint, declined_by)
        return {"status": "declined", "endpoint": endpoint}

    @router.get("/fixes/approved")
    async def get_approved_fixes():
        """Return recently approved fixes with PR metadata."""
        redis = await _get_redis()
        if not redis:
            return []
        raw = await redis.lrange("fixes:approved", -50, -1)
        return [json.loads(r) for r in raw]

    @router.get("/fixes/declined")
    async def get_declined_fixes():
        """Return recently declined fixes."""
        redis = await _get_redis()
        if not redis:
            return []
        raw = await redis.lrange("fixes:declined", -50, -1)
        return [json.loads(r) for r in raw]

    @router.get("/alerts")
    async def get_security_alerts():
        """Return recent critical security alerts."""
        redis = await _get_redis()
        if not redis:
            return []
        raw = await redis.lrange("alerts:critical", -50, -1)
        try:
            return [json.loads(r) for r in raw]
        except (ValueError, TypeError):
            return []

    @router.get("/lockdown")
    async def lockdown_status():
        """Return current lockdown state."""
        redis = await _get_redis()
        active = False
        if redis:
            val = await redis.get("lockdown:active")
            active = val == "true"
        return {"lockdown_active": active}

    @router.post("/lockdown/clear")
    async def clear_lockdown():
        """Manually clear lockdown (admin action)."""
        redis = await _get_redis()
        if redis:
            await redis.delete("lockdown:active")
        brain._lockdown_active = False
        return {"status": "cleared"}

    @router.get("/blocked-ips")
    async def get_blocked_ips():
        """Return list of currently blocked IPs."""
        redis = await _get_redis()
        if not redis:
            return []
        ips = await redis.lrange("security:blocked_ips", 0, -1)
        return list(set(ips))  # deduplicate

    return router


# ── Public entry point ────────────────────────────────────────────────────────

_brain_instance: HOPEFXBrain | None = None


async def start_brain(app: FastAPI) -> HOPEFXBrain:
    """
    Instantiate HOPEFXBrain, mount its API router, and start the 24/7 loop.

    Call from connect_to_life.py lifespan or startup_event::

        from security.global_fortress import start_brain
        _t = asyncio.create_task(start_brain(app))
        _t.add_done_callback(lambda _: None)
    """
    global _brain_instance
    if _brain_instance is not None:
        logger.warning("HOPEFXBrain already started — skipping duplicate start")
        return _brain_instance

    brain = HOPEFXBrain(app)
    _brain_instance = brain

    # The eager security_router registered by router_registry.py already
    # covers /api/security/* and delegates to get_brain() at request time.
    # No need to mount a second router here.
    logger.info("HOPEFXBrain: live instance ready — /api/security/* served via security_router")

    # Pre-load RL agent in background so first prediction is not delayed
    asyncio.get_running_loop().run_in_executor(None, _get_rl_agent)
    # Encoder is opt-in (BRAIN_SEMANTIC_ENCODER=true) — only pre-load when enabled
    if _ENCODER_ENABLED:
        asyncio.get_running_loop().run_in_executor(None, _get_encoder)

    # Start the eternal loop
    _t = asyncio.create_task(brain.monitor_24_7(), name="hopefx-brain-24-7")
    _t.add_done_callback(lambda _: None)
    logger.info("HOPEFXBrain: 24/7 monitor task created")

    return brain


def get_brain() -> HOPEFXBrain | None:
    """Return the running brain instance (or None if not started)."""
    return _brain_instance


# ── Module-level eager router ─────────────────────────────────────────────────
# Registered by router_registry.py at import time so /api/security/* routes
# exist before the async startup tasks complete.  Each handler delegates to
# get_brain() so it always uses the live instance once start_brain() runs.


def _build_eager_router() -> APIRouter:
    """
    Build a /api/security/* router whose handlers delegate to get_brain().

    Unlike _build_router() (which closes over a specific HOPEFXBrain instance),
    every handler here calls get_brain() at request time, so the live instance
    created by start_brain() is used automatically once startup completes.
    """
    from fastapi import APIRouter as _APIRouter

    r = _APIRouter(prefix="/api/security", tags=["Security"])

    @r.get("/attacks")
    async def _attacks():
        brain = get_brain()
        if brain is None:
            return {}
        redis = await _get_redis()
        if redis:
            raw = await redis.hgetall("brain:attack_log")
            return {ip: json.loads(v) for ip, v in raw.items()}
        return brain.attack_log

    @r.get("/fixes")
    async def _fixes():
        redis = await _get_redis()
        if not redis:
            return []
        raw = await redis.lrange("fixes:queue", 0, 49)
        return [json.loads(r) for r in raw]

    @r.post("/fixes/approve")
    async def _fixes_approve(payload: dict):
        brain = get_brain()
        if brain is None:
            from fastapi import HTTPException as _HTTPException

            raise _HTTPException(status_code=503, detail="Security brain not started")
        # Delegate to the live router handler by re-using the same logic
        router = _build_router(brain)
        # Find the approve handler and call it
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/security/fixes/approve":
                return await route.endpoint(payload)
        from fastapi import HTTPException as _HTTPException

        raise _HTTPException(status_code=503, detail="Fix approval handler unavailable")

    @r.post("/fixes/decline")
    async def _fixes_decline(payload: dict):
        endpoint = payload.get("endpoint", "")
        declined_by = payload.get("declined_by", "dashboard")
        redis = await _get_redis()
        if redis:
            raw_list = await redis.lrange("fixes:queue", 0, 99)
            for raw in raw_list:
                try:
                    rec = json.loads(raw)
                    if rec.get("endpoint") == endpoint and rec.get("status") == "pending":
                        await redis.lrem("fixes:queue", 1, raw)
                        declined_record = {
                            **rec,
                            "status": "declined",
                            "declined_by": declined_by,
                            "declined_at": datetime.now(UTC).isoformat(),
                        }
                        await redis.rpush("fixes:declined", json.dumps(declined_record))
                        await redis.ltrim("fixes:declined", -500, -1)
                        break
                except json.JSONDecodeError:
                    continue
        return {"status": "declined", "endpoint": endpoint}

    @r.get("/alerts")
    async def _alerts():
        redis = await _get_redis()
        if not redis:
            return []
        raw = await redis.lrange("alerts:critical", -50, -1)
        try:
            return [json.loads(x) for x in raw]
        except (ValueError, TypeError):
            return []

    @r.get("/lockdown")
    async def _lockdown():
        redis = await _get_redis()
        active = False
        if redis:
            val = await redis.get("lockdown:active")
            active = val == "true"
        else:
            brain = get_brain()
            active = brain._lockdown_active if brain else False
        return {"lockdown_active": active}

    @r.post("/lockdown/clear")
    async def _lockdown_clear():
        redis = await _get_redis()
        if redis:
            await redis.delete("lockdown:active")
        brain = get_brain()
        if brain:
            brain._lockdown_active = False
        return {"status": "cleared"}

    @r.get("/blocked-ips")
    async def _blocked_ips():
        redis = await _get_redis()
        if not redis:
            return []
        ips = await redis.lrange("security:blocked_ips", 0, -1)
        return list(set(ips))

    return r


# Singleton eager router — imported by router_registry.py
security_router = _build_eager_router()
