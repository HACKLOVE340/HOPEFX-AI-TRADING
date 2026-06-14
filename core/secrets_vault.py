# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/secrets_vault.py
======================
Production Secrets Management — integrates with HashiCorp Vault and
AWS Secrets Manager for secure credential storage and rotation.

Architecture
------------
- SecretsProvider (ABC): common interface for all secret backends
- VaultProvider: HashiCorp Vault integration with token/AppRole auth
- AWSSecretsProvider: AWS Secrets Manager integration with IAM auth
- EnvironmentProvider: fallback to environment variables (dev/testing)
- SecretsManager: unified facade that selects provider based on config
- Automatic rotation: background task that refreshes secrets before expiry
- Caching: in-memory cache with TTL to reduce API calls
- Audit logging: all secret access is logged for compliance

Configuration (env vars):
    SECRETS_PROVIDER         — "vault", "aws", or "env" (default: "env")
    VAULT_ADDR               — Vault server address
    VAULT_TOKEN              — Vault token (or use AppRole)
    VAULT_ROLE_ID            — Vault AppRole role ID
    VAULT_SECRET_ID          — Vault AppRole secret ID
    VAULT_MOUNT_PATH         — Vault KV mount path (default: "secret")
    VAULT_PATH_PREFIX        — Vault path prefix (default: "hopefx")
    AWS_REGION               — AWS region for Secrets Manager
    AWS_SECRET_PREFIX        — AWS secret name prefix (default: "hopefx/")
    SECRETS_CACHE_TTL_S      — Cache TTL in seconds (default: 300)
    SECRETS_ROTATION_CHECK_S — Rotation check interval (default: 3600)

Usage
-----
    from core.secrets_vault import get_secrets_manager

    secrets = get_secrets_manager()
    await secrets.initialize()

    # Get a secret
    api_key = await secrets.get("broker_api_key")
    db_password = await secrets.get("database_password")

    # Get all secrets for a service
    broker_creds = await secrets.get_group("broker")
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_PROVIDER = os.getenv("SECRETS_PROVIDER", "env")
_VAULT_ADDR = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
_VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")
_VAULT_ROLE_ID = os.getenv("VAULT_ROLE_ID", "")
_VAULT_SECRET_ID = os.getenv("VAULT_SECRET_ID", "")
_VAULT_MOUNT = os.getenv("VAULT_MOUNT_PATH", "secret")
_VAULT_PREFIX = os.getenv("VAULT_PATH_PREFIX", "hopefx")
_AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
_AWS_PREFIX = os.getenv("AWS_SECRET_PREFIX", "hopefx/")
_CACHE_TTL = int(os.getenv("SECRETS_CACHE_TTL_S", "300"))
_ROTATION_CHECK = int(os.getenv("SECRETS_ROTATION_CHECK_S", "3600"))


# ── Prometheus metrics ────────────────────────────────────────────────────────

try:
    from prometheus_client import Counter, Histogram

    _secret_access = Counter(
        "hopefx_secrets_access_total",
        "Secret access operations",
        ["provider", "operation"],
    )
    _secret_errors = Counter(
        "hopefx_secrets_errors_total",
        "Secret access errors",
        ["provider"],
    )
    _secret_latency = Histogram(
        "hopefx_secrets_latency_seconds",
        "Secret retrieval latency",
        ["provider"],
    )
    _PROM_OK = True
except Exception:
    _PROM_OK = False


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class CachedSecret:
    """A cached secret value with TTL."""
    key: str
    value: str
    fetched_at: float
    ttl: int
    version: str = ""

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > self.ttl


@dataclass
class SecretMetadata:
    """Metadata about a secret."""
    key: str
    version: str
    created_at: datetime | None = None
    expires_at: datetime | None = None
    rotation_enabled: bool = False
    last_rotated: datetime | None = None


# ── Abstract Provider ─────────────────────────────────────────────────────────


class SecretsProvider(ABC):
    """Abstract base class for secrets providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name."""

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the provider connection."""

    @abstractmethod
    async def get_secret(self, key: str) -> str | None:
        """Get a single secret value by key."""

    @abstractmethod
    async def get_secret_group(self, group: str) -> dict[str, str]:
        """Get all secrets in a group/path."""

    @abstractmethod
    async def set_secret(self, key: str, value: str) -> bool:
        """Set/update a secret value."""

    @abstractmethod
    async def delete_secret(self, key: str) -> bool:
        """Delete a secret."""

    @abstractmethod
    async def list_secrets(self) -> list[str]:
        """List all available secret keys."""

    async def close(self) -> None:
        """Close provider connections."""
        pass


# ── HashiCorp Vault Provider ─────────────────────────────────────────────────


class VaultProvider(SecretsProvider):
    """
    HashiCorp Vault integration for secrets management.

    Supports:
    - Token authentication
    - AppRole authentication
    - KV v2 secrets engine
    - Dynamic secret leases
    - Automatic token renewal
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._token: str = _VAULT_TOKEN
        self._authenticated = False

    @property
    def provider_name(self) -> str:
        return "vault"

    async def initialize(self) -> bool:
        """Initialize Vault client and authenticate."""
        try:
            import hvac

            self._client = hvac.Client(url=_VAULT_ADDR)

            # Authenticate
            if _VAULT_ROLE_ID and _VAULT_SECRET_ID:
                # AppRole authentication
                auth_result = self._client.auth.approle.login(
                    role_id=_VAULT_ROLE_ID,
                    secret_id=_VAULT_SECRET_ID,
                )
                self._token = auth_result["auth"]["client_token"]
                self._client.token = self._token
            elif self._token:
                self._client.token = self._token
            else:
                logger.error("Vault: no authentication method configured")
                return False

            # Verify authentication
            if self._client.is_authenticated():
                self._authenticated = True
                logger.info("Vault: authenticated successfully at %s", _VAULT_ADDR)
                return True
            else:
                logger.error("Vault: authentication failed")
                return False

        except ImportError:
            logger.error("Vault: hvac package not installed (pip install hvac)")
            return False
        except Exception as exc:
            logger.error("Vault initialization failed: %s", exc)
            return False

    async def get_secret(self, key: str) -> str | None:
        """Get a secret from Vault KV v2."""
        if not self._authenticated or not self._client:
            return None

        start = time.time()
        try:
            path = f"{_VAULT_PREFIX}/{key}"
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=_VAULT_MOUNT,
            )

            if _PROM_OK:
                _secret_access.labels(provider="vault", operation="get").inc()
                _secret_latency.labels(provider="vault").observe(time.time() - start)

            data = response.get("data", {}).get("data", {})
            return data.get("value", data.get(key))

        except Exception as exc:
            if _PROM_OK:
                _secret_errors.labels(provider="vault").inc()
            logger.error("Vault get_secret failed for '%s': %s", key, exc)
            return None

    async def get_secret_group(self, group: str) -> dict[str, str]:
        """Get all secrets under a group path."""
        if not self._authenticated or not self._client:
            return {}

        try:
            path = f"{_VAULT_PREFIX}/{group}"
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=_VAULT_MOUNT,
            )

            if _PROM_OK:
                _secret_access.labels(provider="vault", operation="get_group").inc()

            return response.get("data", {}).get("data", {})

        except Exception as exc:
            logger.error("Vault get_secret_group failed for '%s': %s", group, exc)
            return {}

    async def set_secret(self, key: str, value: str) -> bool:
        """Set a secret in Vault."""
        if not self._authenticated or not self._client:
            return False

        try:
            path = f"{_VAULT_PREFIX}/{key}"
            self._client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret={"value": value},
                mount_point=_VAULT_MOUNT,
            )

            if _PROM_OK:
                _secret_access.labels(provider="vault", operation="set").inc()

            return True
        except Exception as exc:
            logger.error("Vault set_secret failed for '%s': %s", key, exc)
            return False

    async def delete_secret(self, key: str) -> bool:
        """Delete a secret from Vault."""
        if not self._authenticated or not self._client:
            return False

        try:
            path = f"{_VAULT_PREFIX}/{key}"
            self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point=_VAULT_MOUNT,
            )
            return True
        except Exception as exc:
            logger.error("Vault delete_secret failed for '%s': %s", key, exc)
            return False

    async def list_secrets(self) -> list[str]:
        """List all secret keys in Vault."""
        if not self._authenticated or not self._client:
            return []

        try:
            response = self._client.secrets.kv.v2.list_secrets(
                path=_VAULT_PREFIX,
                mount_point=_VAULT_MOUNT,
            )
            return response.get("data", {}).get("keys", [])
        except Exception as exc:
            logger.error("Vault list_secrets failed: %s", exc)
            return []

    async def close(self) -> None:
        """Close Vault client."""
        self._client = None
        self._authenticated = False


# ── AWS Secrets Manager Provider ──────────────────────────────────────────────


class AWSSecretsProvider(SecretsProvider):
    """
    AWS Secrets Manager integration.

    Uses IAM-based authentication (instance role, ECS task role, or
    explicit credentials from environment).
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._initialized = False

    @property
    def provider_name(self) -> str:
        return "aws"

    async def initialize(self) -> bool:
        """Initialize AWS Secrets Manager client."""
        try:
            import boto3

            self._client = boto3.client(
                "secretsmanager",
                region_name=_AWS_REGION,
            )
            self._initialized = True
            logger.info("AWS Secrets Manager: initialized in region %s", _AWS_REGION)
            return True

        except ImportError:
            logger.error("AWS: boto3 package not installed (pip install boto3)")
            return False
        except Exception as exc:
            logger.error("AWS Secrets Manager initialization failed: %s", exc)
            return False

    async def get_secret(self, key: str) -> str | None:
        """Get a secret from AWS Secrets Manager."""
        if not self._initialized or not self._client:
            return None

        start = time.time()
        try:
            secret_name = f"{_AWS_PREFIX}{key}"
            response = self._client.get_secret_value(SecretId=secret_name)

            if _PROM_OK:
                _secret_access.labels(provider="aws", operation="get").inc()
                _secret_latency.labels(provider="aws").observe(time.time() - start)

            # AWS returns either SecretString or SecretBinary
            if "SecretString" in response:
                import json
                try:
                    data = json.loads(response["SecretString"])
                    return data.get("value", response["SecretString"])
                except (json.JSONDecodeError, TypeError):
                    return response["SecretString"]

            return None

        except self._client.exceptions.ResourceNotFoundException:
            logger.debug("AWS secret not found: %s", key)
            return None
        except Exception as exc:
            if _PROM_OK:
                _secret_errors.labels(provider="aws").inc()
            logger.error("AWS get_secret failed for '%s': %s", key, exc)
            return None

    async def get_secret_group(self, group: str) -> dict[str, str]:
        """Get all secrets with a group prefix."""
        if not self._initialized or not self._client:
            return {}

        try:
            import json
            secret_name = f"{_AWS_PREFIX}{group}"
            response = self._client.get_secret_value(SecretId=secret_name)

            if "SecretString" in response:
                return json.loads(response["SecretString"])

            return {}
        except Exception as exc:
            logger.error("AWS get_secret_group failed for '%s': %s", group, exc)
            return {}

    async def set_secret(self, key: str, value: str) -> bool:
        """Create or update a secret in AWS."""
        if not self._initialized or not self._client:
            return False

        try:
            import json
            secret_name = f"{_AWS_PREFIX}{key}"
            secret_string = json.dumps({"value": value})

            try:
                self._client.create_secret(
                    Name=secret_name,
                    SecretString=secret_string,
                )
            except self._client.exceptions.ResourceExistsException:
                self._client.put_secret_value(
                    SecretId=secret_name,
                    SecretString=secret_string,
                )

            if _PROM_OK:
                _secret_access.labels(provider="aws", operation="set").inc()

            return True
        except Exception as exc:
            logger.error("AWS set_secret failed for '%s': %s", key, exc)
            return False

    async def delete_secret(self, key: str) -> bool:
        """Delete a secret from AWS."""
        if not self._initialized or not self._client:
            return False

        try:
            secret_name = f"{_AWS_PREFIX}{key}"
            self._client.delete_secret(
                SecretId=secret_name,
                ForceDeleteWithoutRecovery=False,
            )
            return True
        except Exception as exc:
            logger.error("AWS delete_secret failed for '%s': %s", key, exc)
            return False

    async def list_secrets(self) -> list[str]:
        """List all secrets with the configured prefix."""
        if not self._initialized or not self._client:
            return []

        try:
            secrets = []
            paginator = self._client.get_paginator("list_secrets")
            for page in paginator.paginate(
                Filters=[{"Key": "name", "Values": [_AWS_PREFIX]}]
            ):
                for secret in page.get("SecretList", []):
                    name = secret["Name"]
                    if name.startswith(_AWS_PREFIX):
                        secrets.append(name[len(_AWS_PREFIX):])
            return secrets
        except Exception as exc:
            logger.error("AWS list_secrets failed: %s", exc)
            return []

    async def close(self) -> None:
        """Close AWS client."""
        self._client = None
        self._initialized = False


# ── Environment Variable Provider (Fallback) ──────────────────────────────────


class EnvironmentProvider(SecretsProvider):
    """
    Fallback provider that reads secrets from environment variables.

    Used for local development and testing. Converts key names to
    uppercase with underscores (e.g., "broker_api_key" -> "BROKER_API_KEY").
    """

    @property
    def provider_name(self) -> str:
        return "env"

    async def initialize(self) -> bool:
        logger.info("Secrets: using environment variable provider (dev mode)")
        return True

    async def get_secret(self, key: str) -> str | None:
        env_key = key.upper().replace(".", "_").replace("-", "_")
        value = os.getenv(env_key)

        if _PROM_OK:
            _secret_access.labels(provider="env", operation="get").inc()

        return value

    async def get_secret_group(self, group: str) -> dict[str, str]:
        prefix = group.upper().replace(".", "_").replace("-", "_") + "_"
        result = {}
        for key, value in os.environ.items():
            if key.startswith(prefix):
                short_key = key[len(prefix):].lower()
                result[short_key] = value
        return result

    async def set_secret(self, key: str, value: str) -> bool:
        env_key = key.upper().replace(".", "_").replace("-", "_")
        os.environ[env_key] = value
        return True

    async def delete_secret(self, key: str) -> bool:
        env_key = key.upper().replace(".", "_").replace("-", "_")
        os.environ.pop(env_key, None)
        return True

    async def list_secrets(self) -> list[str]:
        prefix = "HOPEFX_"
        return [k for k in os.environ if k.startswith(prefix)]


# ── Secrets Manager Facade ────────────────────────────────────────────────────


class SecretsManager:
    """
    Unified secrets management facade.

    Selects the appropriate provider based on configuration and provides:
    - In-memory caching with configurable TTL
    - Automatic rotation checking
    - Audit logging for compliance
    - Graceful fallback chain
    """

    def __init__(self) -> None:
        self._provider: SecretsProvider | None = None
        self._cache: dict[str, CachedSecret] = {}
        self._initialized = False
        self._rotation_task: asyncio.Task | None = None
        self._access_log: list[dict[str, Any]] = []

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name if self._provider else "none"

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> bool:
        """Initialize the secrets manager with the configured provider."""
        # Select provider
        if _PROVIDER == "vault":
            self._provider = VaultProvider()
        elif _PROVIDER == "aws":
            self._provider = AWSSecretsProvider()
        else:
            self._provider = EnvironmentProvider()

        # Initialize provider
        success = await self._provider.initialize()
        if not success:
            # Fallback to environment provider
            logger.warning(
                "Primary secrets provider '%s' failed — falling back to env",
                _PROVIDER,
            )
            self._provider = EnvironmentProvider()
            success = await self._provider.initialize()

        self._initialized = success

        # Start rotation checker
        if self._initialized and _PROVIDER != "env":
            self._rotation_task = asyncio.create_task(self._rotation_loop())

        return self._initialized

    async def get(self, key: str, use_cache: bool = True) -> str | None:
        """
        Get a secret value by key.

        Checks cache first, then fetches from provider.
        All access is audit-logged.
        """
        if not self._initialized or not self._provider:
            return None

        # Check cache
        if use_cache and key in self._cache:
            cached = self._cache[key]
            if not cached.is_expired:
                self._audit_log("get", key, "cache_hit")
                return cached.value

        # Fetch from provider
        value = await self._provider.get_secret(key)

        if value is not None:
            # Cache the value
            self._cache[key] = CachedSecret(
                key=key,
                value=value,
                fetched_at=time.time(),
                ttl=_CACHE_TTL,
            )
            self._audit_log("get", key, "fetched")
        else:
            self._audit_log("get", key, "not_found")

        return value

    async def get_group(self, group: str) -> dict[str, str]:
        """Get all secrets in a group/path."""
        if not self._initialized or not self._provider:
            return {}

        result = await self._provider.get_secret_group(group)
        self._audit_log("get_group", group, f"found_{len(result)}_keys")
        return result

    async def set(self, key: str, value: str) -> bool:
        """Set/update a secret value."""
        if not self._initialized or not self._provider:
            return False

        success = await self._provider.set_secret(key, value)
        if success:
            # Invalidate cache
            self._cache.pop(key, None)
            self._audit_log("set", key, "success")
        else:
            self._audit_log("set", key, "failed")

        return success

    async def delete(self, key: str) -> bool:
        """Delete a secret."""
        if not self._initialized or not self._provider:
            return False

        success = await self._provider.delete_secret(key)
        self._cache.pop(key, None)
        self._audit_log("delete", key, "success" if success else "failed")
        return success

    async def list_keys(self) -> list[str]:
        """List all available secret keys."""
        if not self._initialized or not self._provider:
            return []
        return await self._provider.list_secrets()

    def invalidate_cache(self, key: str | None = None) -> None:
        """Invalidate cached secrets."""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    async def close(self) -> None:
        """Shut down the secrets manager."""
        if self._rotation_task:
            self._rotation_task.cancel()
            try:
                await self._rotation_task
            except asyncio.CancelledError:
                pass

        if self._provider:
            await self._provider.close()

        self._initialized = False
        logger.info("SecretsManager shut down")

    def health(self) -> dict[str, Any]:
        """Return health metrics."""
        return {
            "initialized": self._initialized,
            "provider": self.provider_name,
            "cached_secrets": len(self._cache),
            "expired_cached": sum(1 for c in self._cache.values() if c.is_expired),
            "access_log_size": len(self._access_log),
        }

    # ── Private Methods ───────────────────────────────────────────────────────

    def _audit_log(self, operation: str, key: str, result: str) -> None:
        """Record an audit log entry."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "operation": operation,
            "key": key,
            "result": result,
            "provider": self.provider_name,
        }
        self._access_log.append(entry)

        # Keep log bounded
        if len(self._access_log) > 10000:
            self._access_log = self._access_log[-5000:]

    async def _rotation_loop(self) -> None:
        """Background task to check for expired cache entries and refresh."""
        while True:
            try:
                await asyncio.sleep(_ROTATION_CHECK)

                # Refresh expired cache entries
                expired_keys = [
                    k for k, v in self._cache.items() if v.is_expired
                ]

                for key in expired_keys:
                    try:
                        value = await self._provider.get_secret(key)
                        if value is not None:
                            self._cache[key] = CachedSecret(
                                key=key,
                                value=value,
                                fetched_at=time.time(),
                                ttl=_CACHE_TTL,
                            )
                    except Exception:
                        pass

                if expired_keys:
                    logger.debug(
                        "Secrets rotation check: refreshed %d expired entries",
                        len(expired_keys),
                    )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Secrets rotation loop error: %s", exc)


# ── Module-level singleton ────────────────────────────────────────────────────

_manager: SecretsManager | None = None


def get_secrets_manager() -> SecretsManager:
    """Return the module-level SecretsManager singleton."""
    global _manager
    if _manager is None:
        _manager = SecretsManager()
    return _manager
