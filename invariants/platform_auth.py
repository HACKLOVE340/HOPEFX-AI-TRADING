# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
invariants.platform_auth — authentication, authorization, tenancy & web security.

Pure predicates for the framework's auth/security categories: token signatures
valid, sessions/tokens not expired, password & MFA policy enforced, revoked
credentials actually blocked, a principal touches only its own resources, no
cross-tenant access, secrets not exposed in responses, rate limiting active, and
the standard browser-security headers present (CSP/CSRF/HSTS). On a money-moving
platform an authz hole is a constitutional breach. Each returns ``list[Violation]``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from invariants.constitution import (
    CONSTITUTIONAL,
    CRITICAL,
    WARNING,
    Violation,
    _is_finite_number,
    _v,
)

_AUTHZ = "No Unauthorized Trade"
_TENANT = "No Cross-Tenant Leakage"
_SEC = "No Compliance Breach"


def verify_token_signature_valid(valid: bool) -> list[Violation]:
    """A JWT/session token with an invalid signature must be rejected."""
    if not valid:
        return [_v(_AUTHZ, CONSTITUTIONAL, "token signature failed verification (forged/tampered)")]
    return []


def verify_token_not_expired(now: float, expires_at: float) -> list[Violation]:
    """An expired credential must not be accepted."""
    if _is_finite_number(now) and _is_finite_number(expires_at) and now >= expires_at:
        return [_v(_AUTHZ, CRITICAL, f"token expired at {expires_at} (now {now})")]
    return []


def verify_session_valid(active: bool, revoked: bool = False) -> list[Violation]:
    """A session must be active and not revoked."""
    if revoked:
        return [_v(_AUTHZ, CONSTITUTIONAL, "revoked session was accepted")]
    if not active:
        return [_v(_AUTHZ, CRITICAL, "inactive session was accepted")]
    return []


def verify_password_policy(length: int, min_length: int, *, has_complexity: bool = True) -> list[Violation]:
    """Stored/accepted passwords must satisfy the length & complexity policy."""
    out: list[Violation] = []
    if length < min_length:
        out.append(_v(_SEC, WARNING, f"password length {length} below policy {min_length}"))
    if not has_complexity:
        out.append(_v(_SEC, WARNING, "password fails complexity policy"))
    return out


def verify_mfa_enforced(required: bool, satisfied: bool, action: str = "sensitive") -> list[Violation]:
    """When MFA is required for an action it must have been satisfied."""
    if required and not satisfied:
        return [_v(_AUTHZ, CRITICAL, f"MFA required for {action} but not satisfied")]
    return []


def verify_revoked_blocked(credential_id: Any, revoked_ids: set[Any]) -> list[Violation]:
    """A revoked credential/key must be blocked from use."""
    if credential_id in revoked_ids:
        return [_v(_AUTHZ, CONSTITUTIONAL, f"revoked credential {credential_id!r} was used")]
    return []


def verify_owns_resource(principal: Any, resource_owner: Any) -> list[Violation]:
    """A principal may act on a resource only if it owns it (IDOR / BOLA guard)."""
    if principal != resource_owner:
        return [_v(_AUTHZ, CONSTITUTIONAL,
                   f"principal {principal!r} accessed resource owned by {resource_owner!r}")]
    return []


def verify_has_permission(required: str, granted: Iterable[str]) -> list[Violation]:
    """An action must be covered by an explicitly granted permission/scope."""
    if required not in set(granted):
        return [_v(_AUTHZ, CONSTITUTIONAL, f"missing required permission/scope {required!r}")]
    return []


def verify_no_cross_tenant(principal_tenant: Any, resource_tenant: Any) -> list[Violation]:
    """A principal must never reach another tenant's data."""
    if principal_tenant != resource_tenant:
        return [_v(_TENANT, CONSTITUTIONAL,
                   f"cross-tenant access: tenant {principal_tenant!r} -> {resource_tenant!r}")]
    return []


def verify_no_secret_in_response(payload: Any, secret_markers: tuple[str, ...] = (
        "password", "api_key", "secret", "private_key", "token", "ssn")) -> list[Violation]:
    """An API response body must not leak credential-shaped keys."""
    leaked: list[str] = []
    if isinstance(payload, Mapping):
        for k in payload:
            kl = str(k).lower()
            if any(m in kl for m in secret_markers):
                leaked.append(str(k))
    if leaked:
        return [_v(_SEC, CONSTITUTIONAL, f"response leaks secret-shaped field(s): {sorted(set(leaked))}")]
    return []


def verify_rate_limiter_active(enabled: bool, endpoint: str = "") -> list[Violation]:
    """Auth-sensitive endpoints must have an active rate limiter (brute-force guard)."""
    if not enabled:
        return [_v(_SEC, CRITICAL, f"rate limiter not active on {endpoint or 'endpoint'}")]
    return []


def verify_security_headers(headers: Mapping[str, Any], required: Iterable[str] = (
        "content-security-policy", "x-content-type-options",
        "x-frame-options", "strict-transport-security")) -> list[Violation]:
    """Responses must carry the standard browser-security headers."""
    present = {str(h).lower() for h in headers}
    missing = sorted({r.lower() for r in required} - present)
    if missing:
        return [_v(_SEC, WARNING, f"missing security header(s): {missing}")]
    return []


def verify_csrf_protected(state_changing: bool, csrf_validated: bool) -> list[Violation]:
    """A state-changing request must carry a validated CSRF token."""
    if state_changing and not csrf_validated:
        return [_v(_SEC, CRITICAL, "state-changing request without validated CSRF token")]
    return []


def verify_failed_login_throttled(attempts: int, max_attempts: int) -> list[Violation]:
    """Repeated failed logins must be throttled/locked (credential-stuffing guard)."""
    if attempts > max_attempts:
        return [_v(_SEC, CRITICAL, f"{attempts} failed logins exceeds lockout threshold {max_attempts}")]
    return []


def verify_token_algorithm(alg: str, allowed: tuple[str, ...] = ("HS256", "RS256")) -> list[Violation]:
    """A JWT must be signed with an allow-listed algorithm. The ``none`` algorithm
    (or any unexpected alg) is a forgery vector and must always be rejected
    (master-registry #42)."""
    a = str(alg or "").strip()
    if a.lower() == "none" or a == "":
        return [_v(_AUTHZ, CONSTITUTIONAL, f"JWT 'alg' is {alg!r} — unsigned tokens are forbidden")]
    if a not in allowed:
        return [_v(_AUTHZ, CONSTITUTIONAL, f"JWT 'alg' {a!r} not in allow-list {list(allowed)}")]
    return []
