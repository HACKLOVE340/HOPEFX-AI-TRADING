# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
whitelabel/tenant_isolation.py
===============================
Cross-Tenant Data Isolation — enforces strict data boundaries between tenants.

Provides Row-Level Security (RLS) enforcement at the application layer,
namespaced Redis caching, and request-scoped tenant context propagation.

Architecture
------------
- TenantContext: async context variable that holds the current tenant ID
  throughout the request lifecycle.
- TenantIsolationMiddleware: FastAPI middleware that extracts tenant ID from
  the request (JWT, header, or domain) and sets the context.
- TenantAwareSession: SQLAlchemy session wrapper that automatically applies
  tenant_id filters to all queries (application-level RLS).
- NamespacedCache: Redis cache wrapper that prefixes all keys with tenant_id.
- RLS migration helpers: generate PostgreSQL RLS policies for defense-in-depth.

Usage
-----
    from whitelabel.tenant_isolation import (
        get_tenant_id,
        TenantAwareSession,
        NamespacedCache,
    )

    # In any request handler, the tenant is already set by middleware:
    tenant_id = get_tenant_id()

    # Database queries are automatically scoped:
    session = TenantAwareSession(base_session, tenant_id)
    trades = session.query(Trade).all()  # Only returns current tenant's trades

    # Cache is automatically namespaced:
    cache = NamespacedCache(redis_client, tenant_id)
    await cache.set("portfolio_value", "125000.50", ttl=60)
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Tenant Context ────────────────────────────────────────────────────────────

_tenant_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)


def get_tenant_id() -> str | None:
    """Return the current request's tenant ID from context."""
    return _tenant_ctx.get()


def set_tenant_id(tenant_id: str) -> contextvars.Token:
    """Set the tenant ID in the current async context. Returns a reset token."""
    return _tenant_ctx.set(tenant_id)


def require_tenant() -> str:
    """
    Return the current tenant ID or raise if not set.

    Use this in code paths that MUST have a tenant context.
    """
    tid = _tenant_ctx.get()
    if not tid:
        raise PermissionError("No tenant context — request must be tenant-scoped")
    return tid


# ── Prometheus metrics ────────────────────────────────────────────────────────

try:
    from prometheus_client import Counter

    _isolation_violations = Counter(
        "hopefx_tenant_isolation_violations_total",
        "Attempted cross-tenant data access violations",
        ["source"],
    )
    _tenant_queries = Counter(
        "hopefx_tenant_queries_total",
        "Database queries scoped to tenant",
        ["tenant_id"],
    )
    _cache_ops = Counter(
        "hopefx_tenant_cache_ops_total",
        "Namespaced cache operations",
        ["tenant_id", "operation"],
    )
    _PROM_OK = True
except Exception:
    _PROM_OK = False


# ── Tenant Isolation Middleware ───────────────────────────────────────────────


class TenantIsolationMiddleware:
    """
    FastAPI middleware that extracts and sets the tenant context.

    Extraction order:
    1. X-Tenant-ID header (for internal service-to-service calls)
    2. JWT claim 'tenant_id' from Authorization header
    3. Domain-based lookup (maps custom domains to tenant IDs)

    The middleware sets the tenant context for the entire request lifecycle
    and clears it on response.
    """

    def __init__(self, app: Any, domain_resolver: Callable | None = None) -> None:
        self.app = app
        self._domain_resolver = domain_resolver

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract tenant ID
        tenant_id = await self._extract_tenant_id(scope)

        if tenant_id:
            token = set_tenant_id(tenant_id)
            try:
                await self.app(scope, receive, send)
            finally:
                _tenant_ctx.reset(token)
        else:
            # Allow public endpoints without tenant context
            await self.app(scope, receive, send)

    async def _extract_tenant_id(self, scope: dict) -> str | None:
        """Extract tenant ID from request headers, JWT, or domain."""
        headers = dict(scope.get("headers", []))

        # 1. Explicit header (service-to-service)
        tenant_header = headers.get(b"x-tenant-id")
        if tenant_header:
            return tenant_header.decode("utf-8")

        # 2. JWT claim
        auth_header = headers.get(b"authorization")
        if auth_header:
            tenant_id = self._extract_from_jwt(auth_header.decode("utf-8"))
            if tenant_id:
                return tenant_id

        # 3. Domain-based resolution
        host_header = headers.get(b"host")
        if host_header and self._domain_resolver:
            domain = host_header.decode("utf-8").split(":")[0]
            tenant_id = await self._resolve_domain(domain)
            if tenant_id:
                return tenant_id

        return None

    def _extract_from_jwt(self, auth_header: str) -> str | None:
        """Extract tenant_id claim from a JWT token."""
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]
        try:
            import jwt

            # Decode without verification to extract claims
            # (verification happens in the auth middleware)
            import os

            secret = os.getenv("JWT_SECRET", "")
            if not secret:
                # Decode unverified for tenant extraction only
                payload = jwt.decode(token, options={"verify_signature": False})
            else:
                payload = jwt.decode(token, secret, algorithms=["HS256"])
            return payload.get("tenant_id")
        except Exception:
            return None

    async def _resolve_domain(self, domain: str) -> str | None:
        """Resolve a custom domain to a tenant ID."""
        if self._domain_resolver:
            try:
                result = self._domain_resolver(domain)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except Exception as exc:
                logger.debug("Domain resolution failed for %s: %s", domain, exc)
        return None


# ── Tenant-Aware Database Session ─────────────────────────────────────────────


class TenantAwareSession:
    """
    SQLAlchemy session wrapper that enforces tenant isolation.

    Automatically applies a tenant_id filter to all queries on models
    that have a 'tenant_id' column. This provides application-level
    Row-Level Security (RLS).

    Also validates that all INSERT/UPDATE operations include the correct
    tenant_id, preventing accidental cross-tenant data writes.
    """

    def __init__(self, session: Any, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def query(self, model: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Create a query with automatic tenant_id filtering.

        If the model has a 'tenant_id' column, the filter is applied
        automatically. Models without tenant_id are returned unfiltered
        (e.g., system-wide configuration tables).
        """
        q = self._session.query(model, *args, **kwargs)

        # Apply tenant filter if the model has a tenant_id column
        if hasattr(model, "tenant_id"):
            q = q.filter(model.tenant_id == self._tenant_id)

            if _PROM_OK:
                _tenant_queries.labels(tenant_id=self._tenant_id).inc()

        return q

    def add(self, instance: Any) -> None:
        """
        Add an instance to the session with tenant_id enforcement.

        If the model has a tenant_id field, it MUST match the current
        tenant context. If it's not set, it will be set automatically.
        """
        if hasattr(instance, "tenant_id"):
            if instance.tenant_id and instance.tenant_id != self._tenant_id:
                if _PROM_OK:
                    _isolation_violations.labels(source="write").inc()
                raise PermissionError(
                    f"Cross-tenant write violation: attempted to write to tenant "
                    f"'{instance.tenant_id}' from context '{self._tenant_id}'"
                )
            # Auto-set tenant_id if not already set
            instance.tenant_id = self._tenant_id

        self._session.add(instance)

    def delete(self, instance: Any) -> None:
        """Delete with tenant_id verification."""
        if hasattr(instance, "tenant_id") and instance.tenant_id != self._tenant_id:
            if _PROM_OK:
                _isolation_violations.labels(source="delete").inc()
            raise PermissionError(
                f"Cross-tenant delete violation: attempted to delete from tenant "
                f"'{instance.tenant_id}' in context '{self._tenant_id}'"
            )
        self._session.delete(instance)

    def commit(self) -> None:
        """Commit the session."""
        self._session.commit()

    def rollback(self) -> None:
        """Rollback the session."""
        self._session.rollback()

    def close(self) -> None:
        """Close the session."""
        self._session.close()

    def flush(self) -> None:
        """Flush pending changes."""
        self._session.flush()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        self.close()
        return False


# ── Namespaced Cache ──────────────────────────────────────────────────────────


class NamespacedCache:
    """
    Redis cache wrapper that enforces tenant-level key isolation.

    All keys are prefixed with the tenant_id, preventing any possibility
    of cross-tenant cache pollution. Also provides tenant-scoped TTL
    management and bulk operations.
    """

    def __init__(self, redis_client: Any, tenant_id: str) -> None:
        self._redis = redis_client
        self._tenant_id = tenant_id
        self._prefix = f"t:{tenant_id}:"

    def _key(self, key: str) -> str:
        """Generate the namespaced key."""
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> str | None:
        """Get a value from the tenant-namespaced cache."""
        if not self._redis:
            return None

        try:
            namespaced_key = self._key(key)
            # Support both sync and async Redis clients
            result = self._redis.get(namespaced_key)
            if asyncio.iscoroutine(result):
                result = await result

            if _PROM_OK:
                _cache_ops.labels(tenant_id=self._tenant_id, operation="get").inc()

            if result is not None and isinstance(result, bytes):
                return result.decode("utf-8")
            return result
        except Exception as exc:
            logger.debug("NamespacedCache get failed: %s", exc)
            return None

    async def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        """Set a value in the tenant-namespaced cache."""
        if not self._redis:
            return False

        try:
            namespaced_key = self._key(key)
            result = self._redis.setex(namespaced_key, ttl, value) if ttl else self._redis.set(namespaced_key, value)

            if asyncio.iscoroutine(result):
                await result

            if _PROM_OK:
                _cache_ops.labels(tenant_id=self._tenant_id, operation="set").inc()

            return True
        except Exception as exc:
            logger.debug("NamespacedCache set failed: %s", exc)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key from the tenant-namespaced cache."""
        if not self._redis:
            return False

        try:
            namespaced_key = self._key(key)
            result = self._redis.delete(namespaced_key)
            if asyncio.iscoroutine(result):
                await result

            if _PROM_OK:
                _cache_ops.labels(tenant_id=self._tenant_id, operation="delete").inc()

            return True
        except Exception as exc:
            logger.debug("NamespacedCache delete failed: %s", exc)
            return False

    async def flush_tenant(self) -> int:
        """
        Delete ALL keys for this tenant.

        Uses SCAN to find all keys with the tenant prefix and deletes them.
        Returns the number of keys deleted.
        """
        if not self._redis:
            return 0

        try:
            pattern = f"{self._prefix}*"
            deleted = 0
            cursor = 0

            while True:
                result = self._redis.scan(cursor, match=pattern, count=100)
                if asyncio.iscoroutine(result):
                    result = await result

                cursor, keys = result
                if keys:
                    del_result = self._redis.delete(*keys)
                    if asyncio.iscoroutine(del_result):
                        del_result = await del_result
                    deleted += del_result

                if cursor == 0:
                    break

            logger.info(
                "NamespacedCache: flushed %d keys for tenant %s",
                deleted,
                self._tenant_id,
            )
            return deleted
        except Exception as exc:
            logger.warning("NamespacedCache flush failed: %s", exc)
            return 0

    async def exists(self, key: str) -> bool:
        """Check if a key exists in the tenant-namespaced cache."""
        if not self._redis:
            return False

        try:
            namespaced_key = self._key(key)
            result = self._redis.exists(namespaced_key)
            if asyncio.iscoroutine(result):
                result = await result
            return bool(result)
        except Exception as exc:
            logger.debug("NamespacedCache exists failed: %s", exc)
            return False


# ── RLS Migration Helpers ─────────────────────────────────────────────────────


def generate_rls_migration() -> str:
    """
    Generate PostgreSQL RLS policies for defense-in-depth.

    These policies enforce tenant isolation at the database level,
    providing a second layer of protection beyond the application-level
    TenantAwareSession.

    Returns SQL migration script as a string.
    """
    tables_with_tenant = [
        "trades",
        "positions",
        "orders",
        "signals",
        "portfolio_snapshots",
        "user_settings",
        "api_keys",
        "notifications",
        "audit_log",
        "strategy_configs",
    ]

    sql_parts = [
        "-- HOPEFX Row-Level Security (RLS) Migration",
        "-- Generated for cross-tenant data isolation",
        "-- Apply after enabling RLS on each table",
        "",
        "-- Enable RLS on tenant-scoped tables",
    ]

    for table in tables_with_tenant:
        sql_parts.extend(
            [
                f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
                f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
                "",
                f"-- Policy for {table}: users can only see their tenant's data",
                f"CREATE POLICY tenant_isolation_{table} ON {table}",
                "    USING (tenant_id = current_setting('app.current_tenant_id'));",
                "",
                f"-- Policy for {table}: users can only insert into their tenant",
                f"CREATE POLICY tenant_insert_{table} ON {table}",
                "    FOR INSERT",
                "    WITH CHECK (tenant_id = current_setting('app.current_tenant_id'));",
                "",
                f"-- Policy for {table}: users can only update their tenant's data",
                f"CREATE POLICY tenant_update_{table} ON {table}",
                "    FOR UPDATE",
                "    USING (tenant_id = current_setting('app.current_tenant_id'))",
                "    WITH CHECK (tenant_id = current_setting('app.current_tenant_id'));",
                "",
                f"-- Policy for {table}: users can only delete their tenant's data",
                f"CREATE POLICY tenant_delete_{table} ON {table}",
                "    FOR DELETE",
                "    USING (tenant_id = current_setting('app.current_tenant_id'));",
                "",
            ]
        )

    # Add superadmin bypass policy
    sql_parts.extend(
        [
            "-- Superadmin bypass: allows superadmin role to access all tenants",
            "-- Apply to each table:",
        ]
    )
    for table in tables_with_tenant:
        sql_parts.append(
            f"CREATE POLICY superadmin_bypass_{table} ON {table}"
            f"    USING (current_setting('app.is_superadmin', true) = 'true');"
        )

    sql_parts.extend(
        [
            "",
            "-- Helper function to set tenant context per connection",
            "CREATE OR REPLACE FUNCTION set_tenant_context(p_tenant_id TEXT, p_is_superadmin BOOLEAN DEFAULT FALSE)",
            "RETURNS VOID AS $$",
            "BEGIN",
            "    PERFORM set_config('app.current_tenant_id', p_tenant_id, true);",
            "    PERFORM set_config('app.is_superadmin', p_is_superadmin::TEXT, true);",
            "END;",
            "$$ LANGUAGE plpgsql;",
        ]
    )

    return "\n".join(sql_parts)


# ── Alembic Migration File Generator ─────────────────────────────────────────


def generate_alembic_migration() -> str:
    """Generate an Alembic migration file for RLS policies."""
    return f'''"""Add Row-Level Security policies for tenant isolation.

Revision ID: auto_generated
Create Date: {datetime.now(UTC).isoformat()}
"""
from alembic import op
import sqlalchemy as sa

revision = "tenant_rls_001"
down_revision = None
branch_labels = None
depends_on = None

_RLS_SQL = """
{generate_rls_migration()}
"""

_DROP_RLS_SQL = """
-- Drop all tenant isolation policies (rollback)
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE policyname LIKE 'tenant_%' OR policyname LIKE 'superadmin_%'
    ) LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I.%I',
                       r.policyname, r.schemaname, r.tablename);
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.execute(_RLS_SQL)


def downgrade() -> None:
    op.execute(_DROP_RLS_SQL)
'''


# ── Tenant-scoped dependency injection helper ─────────────────────────────────


def tenant_scoped(func: Callable) -> Callable:
    """
    Decorator that ensures a function runs within a tenant context.

    Raises PermissionError if no tenant context is active.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        tenant_id = get_tenant_id()
        if not tenant_id:
            raise PermissionError(f"Function '{func.__name__}' requires a tenant context")
        return await func(*args, **kwargs)

    return wrapper


class TenantIsolationManager:
    """Facade over the tenant-isolation primitives, expected by the startup
    factory (``init_tenant_isolation``).

    Holds the DB engine + cache and hands out tenant-scoped sessions/caches via
    the existing TenantAwareSession / NamespacedCache wrappers. Kept intentionally
    thin — the enforcement logic lives in those classes and the middleware.
    """

    def __init__(self, db_engine: Any = None, cache: Any = None) -> None:
        self.db_engine = db_engine
        self.cache = cache
        self._initialized = False

    async def initialize(self) -> bool:
        """No heavy setup required — RLS is enforced per-request by the
        middleware/session wrappers. Marks the manager ready."""
        self._initialized = True
        return True

    def session_for(self, session: Any, tenant_id: str) -> TenantAwareSession:
        """Wrap a SQLAlchemy session so all queries are tenant-scoped."""
        return TenantAwareSession(session, tenant_id)

    def cache_for(self, tenant_id: str) -> NamespacedCache | None:
        """Return a tenant-namespaced cache wrapper, or None if no cache."""
        return NamespacedCache(self.cache, tenant_id) if self.cache is not None else None

    @property
    def is_ready(self) -> bool:
        return self._initialized
