# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/secrets_manager.py
=======================
Hot-rotating secrets manager with Vault and AWS Secrets Manager backends.

Problem
-------
Secrets (JWT key, DB password, API keys) are loaded once at startup from
env vars.  If a secret is rotated, the pod must be restarted.  Tier-1
systems integrate with a secrets manager and support hot rotation.

Solution
--------
SecretsManager polls the configured backend on a configurable interval
(SECRETS_REFRESH_INTERVAL_SECONDS, default 300 s) and updates in-memory
values without a restart.  Callers use get() instead of os.getenv() so
they always receive the current value.

Backends (configure via SECRETS_BACKEND env var)
------------------------------------------------
env      — read from environment variables (default, no external dependency)
vault    — HashiCorp Vault KV v2 (requires hvac)
aws      — AWS Secrets Manager (requires boto3)

Configuration
-------------
SECRETS_BACKEND                  — env | vault | aws (default: env)
SECRETS_REFRESH_INTERVAL_SECONDS — poll interval in seconds (default: 300)
SECRETS_REFRESH_ENABLED          — false to disable background refresh (default: true)

Vault-specific
--------------
VAULT_ADDR          — Vault server URL (default: http://localhost:8200)
VAULT_TOKEN         — Vault token (or use VAULT_ROLE_ID + VAULT_SECRET_ID for AppRole)
VAULT_ROLE_ID       — AppRole role_id (alternative to VAULT_TOKEN)
VAULT_SECRET_ID     — AppRole secret_id
VAULT_MOUNT_POINT   — KV v2 mount point (default: secret)
VAULT_SECRET_PATH   — path within the mount (default: hopefx/api)

AWS-specific
------------
AWS_REGION          — AWS region (default: us-east-1)
AWS_SECRET_NAME     — Secrets Manager secret name (default: hopefx/api)

Secret key mapping
------------------
The secrets manager maps well-known secret keys to the env vars they replace:

    "jwt_secret_key"    → JWT_SECRET_KEY
    "db_password"       → DATABASE_URL (password component)
    "oanda_api_key"     → BROKER_OANDA_TOKEN
    "sendgrid_api_key"  → SENDGRID_API_KEY
    "redis_password"    → REDIS_URL (password component)
    "crypto_webhook_secret" → CRYPTO_WEBHOOK_SECRET

Usage
-----
    from core.secrets_manager import secrets, get_secret

    jwt_key = get_secret("jwt_secret_key")   # always current
    db_url  = get_secret("database_url")

    # Start background refresh at startup:
    from core.secrets_manager import secrets
    _t = asyncio.create_task(secrets.refresh_loop())
    _t.add_done_callback(lambda _: None)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

_BACKEND = os.getenv("SECRETS_BACKEND", "env").lower()
_REFRESH_INTERVAL = float(os.getenv("SECRETS_REFRESH_INTERVAL_SECONDS", "300"))
_REFRESH_ENABLED = os.getenv("SECRETS_REFRESH_ENABLED", "true").lower() != "false"

# Mapping: secret key → env var name (fallback when backend is unavailable)
_ENV_FALLBACK: dict[str, str] = {
    "jwt_secret_key": "JWT_SECRET_KEY",  # nosec B105 - env var name string, not a hardcoded secret
    "database_url": "DATABASE_URL",
    "db_password": "DB_PASSWORD",  # nosec B105 - env var name string, not a hardcoded secret
    "oanda_api_key": "BROKER_OANDA_TOKEN",
    "sendgrid_api_key": "SENDGRID_API_KEY",
    "redis_password": "REDIS_PASSWORD",  # nosec B105 - env var name string, not a hardcoded secret
    "redis_url": "REDIS_URL",
    "crypto_webhook_secret": "CRYPTO_WEBHOOK_SECRET",  # nosec B105 - env var name string, not a hardcoded secret
    "sentry_dsn": "SENTRY_DSN",
    "stripe_secret_key": "STRIPE_SECRET_KEY",  # nosec B105 - env var name string, not a hardcoded secret
    "stripe_webhook_secret": "STRIPE_WEBHOOK_SECRET",  # nosec B105 - env var name string, not a hardcoded secret
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",  # nosec B105 - env var name string, not a hardcoded secret
    "openai_api_key": "OPENAI_API_KEY",
}


class SecretsManager:
    """
    Hot-rotating secrets manager.

    Loads secrets from the configured backend and refreshes them on a
    background interval.  Falls back to environment variables when the
    backend is unavailable.

    Thread-safety: _cache reads/writes are protected by asyncio — all
    access happens in the event loop.  Synchronous callers (e.g. SQLAlchemy
    engine creation) should use get_sync() which reads the last cached value.
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._last_refresh: datetime | None = None
        self._refresh_count: int = 0
        self._error_count: int = 0
        self._running: bool = False

        # Load from env vars immediately so get() works before first refresh
        self._load_from_env()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, key: str, default: str | None = None) -> str | None:
        """
        Return the current value of a secret.

        Reads from the in-memory cache (populated by the last refresh).
        Falls back to the env var mapping, then to *default*.
        """
        if key in self._cache:
            return self._cache[key]
        # Env var fallback
        env_var = _ENV_FALLBACK.get(key)
        if env_var:
            return os.getenv(env_var, default)
        return os.getenv(key.upper(), default)

    def get_sync(self, key: str, default: str | None = None) -> str | None:
        """Synchronous alias for get() — safe to call from non-async code."""
        return self.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Manually override a secret value in the cache (for testing)."""
        self._cache[key] = value

    def status(self) -> dict[str, Any]:
        return {
            "backend": _BACKEND,
            "refresh_enabled": _REFRESH_ENABLED,
            "refresh_interval_seconds": _REFRESH_INTERVAL,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "refresh_count": self._refresh_count,
            "error_count": self._error_count,
            "cached_keys": sorted(self._cache.keys()),
        }

    # ── Background refresh loop ───────────────────────────────────────────────

    async def refresh_loop(self) -> None:
        """
        Background task: poll the secrets backend every REFRESH_INTERVAL seconds.

        Runs until cancelled.  Errors are logged but do not stop the loop —
        the last successfully fetched values remain in cache.
        """
        if not _REFRESH_ENABLED:
            logger.info("SecretsManager: background refresh disabled (SECRETS_REFRESH_ENABLED=false)")
            return

        self._running = True
        logger.info(
            "SecretsManager: refresh loop started (backend=%s interval=%.0fs)",
            _BACKEND,
            _REFRESH_INTERVAL,
        )

        while self._running:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                logger.info("SecretsManager: refresh loop stopped")
                return
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._error_count += 1
                logger.warning("SecretsManager: refresh error: %s", exc)

            await asyncio.sleep(_REFRESH_INTERVAL)

    async def refresh(self) -> None:
        """Fetch secrets from the backend and update the cache."""
        if _BACKEND == "vault":
            new_secrets = await self._fetch_vault()
        elif _BACKEND == "aws":
            new_secrets = await self._fetch_aws()
        else:
            new_secrets = self._fetch_env()

        if new_secrets:
            changed = {k for k, v in new_secrets.items() if self._cache.get(k) != v}
            self._cache.update(new_secrets)
            self._last_refresh = datetime.now(UTC)
            self._refresh_count += 1

            if changed:
                # INFO: log only counts — no variable names or values reach the log sink.
                logger.info(
                    "SecretsManager: refreshed %d secrets (%d changed)",
                    len(new_secrets),
                    len(changed),
                )
                # Log only the count of changed keys — no names or values.
                logger.debug(
                    "SecretsManager: %d key(s) changed in this refresh cycle",
                    len(changed),
                )
                # Notify registered rotation callbacks
                await self._notify_rotation(changed)
            else:
                logger.debug(
                    "SecretsManager: refreshed %d secrets (no changes)",
                    len(new_secrets),
                )

    def stop(self) -> None:
        self._running = False

    # ── Rotation callbacks ────────────────────────────────────────────────────

    _rotation_callbacks: ClassVar[list] = []

    def on_rotation(self, callback) -> None:
        """
        Register a callback invoked when secrets change.

        The callback receives a set of changed key names.
        Use this to update live components (e.g. re-sign JWT tokens,
        reconnect DB with new password).

        Example
        -------
            @secrets.on_rotation
            async def _update_jwt(changed_keys):
                if "jwt_secret_key" in changed_keys:
                    auth_module.reload_jwt_key(secrets.get("jwt_secret_key"))
        """
        self._rotation_callbacks.append(callback)
        return callback  # allow use as decorator

    async def _notify_rotation(self, changed_keys: set) -> None:
        for cb in self._rotation_callbacks:
            try:
                result = cb(changed_keys)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("SecretsManager: rotation callback error: %s", exc)

    # ── Backend implementations ───────────────────────────────────────────────

    def _load_from_env(self) -> None:
        """Populate cache from environment variables at startup."""
        for key, env_var in _ENV_FALLBACK.items():
            val = os.getenv(env_var)
            if val:
                self._cache[key] = val

    def _fetch_env(self) -> dict[str, str]:
        """Re-read all mapped env vars (useful for testing rotation)."""
        result: dict[str, str] = {}
        for key, env_var in _ENV_FALLBACK.items():
            val = os.getenv(env_var)
            if val:
                result[key] = val
        return result

    async def _fetch_vault(self) -> dict[str, str]:
        """Fetch secrets from HashiCorp Vault KV v2."""
        try:
            import hvac
        except ImportError:
            logger.warning("SecretsManager: hvac not installed — falling back to env vars. pip install hvac")
            return self._fetch_env()

        vault_addr = os.getenv("VAULT_ADDR", "http://localhost:8200")
        vault_token = os.getenv("VAULT_TOKEN", "")
        role_id = os.getenv("VAULT_ROLE_ID", "")
        secret_id = os.getenv("VAULT_SECRET_ID", "")
        mount_point = os.getenv("VAULT_MOUNT_POINT", "secret")
        secret_path = os.getenv("VAULT_SECRET_PATH", "hopefx/api")

        try:
            client = hvac.Client(url=vault_addr, token=vault_token or None)

            # AppRole auth if token not provided
            if not vault_token and role_id and secret_id:
                resp = client.auth.approle.login(role_id=role_id, secret_id=secret_id)
                client.token = resp["auth"]["client_token"]

            if not client.is_authenticated():
                logger.error("SecretsManager: Vault authentication failed")
                return self._fetch_env()

            # Run blocking Vault call in thread pool
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: client.secrets.kv.v2.read_secret_version(path=secret_path, mount_point=mount_point),
            )
            secrets_data = data["data"]["data"]
            logger.debug("SecretsManager: fetched %d keys from Vault", len(secrets_data))
            return {k.lower(): str(v) for k, v in secrets_data.items()}

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("SecretsManager: Vault fetch failed: %s — using cached/env values", exc)
            return self._fetch_env()

    async def _fetch_aws(self) -> dict[str, str]:
        """Fetch secrets from AWS Secrets Manager."""
        try:
            import json as _json

            import boto3
        except ImportError:
            logger.warning("SecretsManager: boto3 not installed — falling back to env vars. pip install boto3")
            return self._fetch_env()

        region = os.getenv("AWS_REGION", "us-east-1")
        secret_name = os.getenv("AWS_SECRET_NAME", "hopefx/api")

        try:
            loop = asyncio.get_event_loop()

            def _get_secret():
                client = boto3.client("secretsmanager", region_name=region)
                response = client.get_secret_value(SecretId=secret_name)
                return response.get("SecretString", "{}")

            raw = await loop.run_in_executor(None, _get_secret)
            secrets_data = _json.loads(raw)
            logger.debug(
                "SecretsManager: fetched %d keys from AWS Secrets Manager",
                len(secrets_data),
            )
            return {k.lower(): str(v) for k, v in secrets_data.items()}

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "SecretsManager: AWS Secrets Manager fetch failed: %s — using cached/env values",
                exc,
            )
            return self._fetch_env()


# ── Module-level singleton ────────────────────────────────────────────────────

secrets = SecretsManager()


def get_secret(key: str, default: str | None = None) -> str | None:
    """
    Convenience function: return the current value of a secret.

    Always reads from the live cache — reflects the latest rotation.
    """
    return secrets.get(key, default)
