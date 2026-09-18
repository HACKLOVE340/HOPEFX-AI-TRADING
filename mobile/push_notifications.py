# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Push Notification System — Firebase Cloud Messaging (FCM)

Supports two delivery modes:
  1. Legacy HTTP API  — set FIREBASE_SERVER_KEY (deprecated by Google but still works)
  2. Firebase Admin SDK — set FIREBASE_CREDENTIALS_JSON (path to service-account JSON)
                          or FIREBASE_CREDENTIALS_BASE64 (base64-encoded JSON for containers)

Without any key, notifications are logged only (safe for development).

Trigger points:
  - New high-confidence signal
  - Drawdown warning
  - Trade filled
  - Prop-firm challenge near breach

Environment variables
---------------------
FIREBASE_SERVER_KEY          — Legacy FCM server key (from Firebase Console →
                               Project Settings → Cloud Messaging → Server key)
FIREBASE_CREDENTIALS_JSON    — Path to Firebase service-account JSON file
FIREBASE_CREDENTIALS_BASE64  — Base64-encoded service-account JSON (for containers)
FIREBASE_PROJECT_ID          — Firebase project ID (required for Admin SDK)
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# In-memory device token registry: user_id → list of FCM tokens
#: In-process fallback. Authoritative only when no shared store is reachable —
#: which is the normal state in dev and test, and a degraded one in production.
_device_tokens: dict[str, list[str]] = {}

#: Resolved once, like core/idempotency.py's client: a deployment without Redis
#: falls back permanently rather than re-probing on every registration.
_TOKEN_STORE: Any | None = None
_TOKEN_STORE_RESOLVED: bool = False

# A Redis key namespace, not a credential — "token" here is an FCM device
# token, which is an address the sender pushes to, not a secret it holds.
_TOKEN_KEY_PREFIX = "hopefx:push:tokens:"  # noqa: S105


def _resolve_token_store() -> Any | None:
    """A Redis client for device tokens, or None to use process memory.

    Device tokens were held in a module-level dict and nothing else (F220), so
    every deploy silently unregistered every device — a correctly configured
    FCM with real credentials and real tokens simply stopped delivering, with
    no error, because the server believed the user had no devices. Each worker
    also held its own set, so registering through one and sending from another
    found nothing and looked like a flaky client.

    Redis rather than a table: the tokens are shared state that must cross
    workers, they already have a natural key shape, and a new table would need
    a migration (F218 — 36 of 44 model tables have none).
    """
    url = os.getenv("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis as _redis_lib

        client = _redis_lib.from_url(url, decode_responses=True, socket_timeout=1.0)
        client.ping()
    except Exception as exc:
        logger.info(
            "Push tokens: no shared store (%s) — device registrations will not "
            "survive a restart and are not visible to other workers",
            exc,
        )
        return None
    return client


def _token_store() -> Any | None:
    global _TOKEN_STORE, _TOKEN_STORE_RESOLVED
    if not _TOKEN_STORE_RESOLVED:
        _TOKEN_STORE = _resolve_token_store()
        _TOKEN_STORE_RESOLVED = True
    return _TOKEN_STORE


def _reset_token_store_for_tests() -> None:
    """Forget the resolved client so a test can supply its own."""
    global _TOKEN_STORE, _TOKEN_STORE_RESOLVED
    _TOKEN_STORE = None
    _TOKEN_STORE_RESOLVED = False


def _load_firebase_admin() -> Any | None:
    """
    Attempt to initialise the Firebase Admin SDK.

    Returns the firebase_admin.messaging module if successful, else None.
    Tries FIREBASE_CREDENTIALS_BASE64 first (container-friendly), then
    FIREBASE_CREDENTIALS_JSON (file path), then falls back to Application
    Default Credentials (GCP / Cloud Run environments).
    """
    try:
        import firebase_admin  # type: ignore[import]
        from firebase_admin import credentials, messaging  # type: ignore[import]

        # Already initialised (e.g. called twice at startup)
        if firebase_admin._apps:
            return messaging

        cred = None

        # Option 1: base64-encoded JSON (ideal for Docker / Kubernetes secrets)
        b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64", "")
        if b64:
            try:
                raw = base64.b64decode(b64).decode("utf-8")
                cred_dict = json.loads(raw)
                cred = credentials.Certificate(cred_dict)
                logger.info("FCM: using base64-encoded service-account credentials")
            except Exception as exc:
                logger.warning("FCM: failed to decode FIREBASE_CREDENTIALS_BASE64: %s", exc)

        # Option 2: path to service-account JSON file
        if cred is None:
            json_path = os.getenv("FIREBASE_CREDENTIALS_JSON", "")
            if json_path and Path(json_path).is_file():
                cred = credentials.Certificate(json_path)
                logger.info("FCM: using service-account JSON at %s", json_path)

        # Option 3: Application Default Credentials (GCP / Cloud Run)
        if cred is None:
            cred = credentials.ApplicationDefault()
            logger.info("FCM: using Application Default Credentials")

        options: dict[str, Any] = {}
        project_id = os.getenv("FIREBASE_PROJECT_ID", "")
        if project_id:
            options["projectId"] = project_id

        firebase_admin.initialize_app(cred, options)
        logger.info("Firebase Admin SDK initialised — FCM v1 API active")
        return messaging

    except ImportError:
        logger.debug("firebase-admin not installed — FCM Admin SDK unavailable")
        return None
    except Exception as exc:
        logger.warning("Firebase Admin SDK init failed: %s", exc)
        return None


class PushNotificationManager:
    """
    Manages push notifications for mobile devices via FCM.

    Delivery priority:
      1. Firebase Admin SDK (v1 API) — preferred, uses OAuth2 service account
      2. Legacy FCM HTTP API         — fallback when only FIREBASE_SERVER_KEY is set
      3. Log-only                    — when no credentials are configured (dev/test)
    """

    def __init__(self) -> None:
        self.server_key: str = os.getenv("FIREBASE_SERVER_KEY", "")
        self._admin_messaging: Any | None = None
        self.apns_enabled: bool = False

        # Try Admin SDK first (preferred — uses v1 API with OAuth2)
        has_admin_creds = bool(
            os.getenv("FIREBASE_CREDENTIALS_BASE64")
            or os.getenv("FIREBASE_CREDENTIALS_JSON")
            or os.getenv("FIREBASE_PROJECT_ID")
        )
        if has_admin_creds:
            self._admin_messaging = _load_firebase_admin()

        self.fcm_enabled: bool = bool(self._admin_messaging or self.server_key)

        if self._admin_messaging:
            logger.info("FCM push notifications enabled (Admin SDK / v1 API)")
        elif self.server_key:
            logger.info("FCM push notifications enabled (legacy server key)")
        else:
            # Debug-level: absence of Firebase credentials is expected in dev/test.
            # Operators who need FCM will see this in debug logs or the health endpoint.
            logger.debug(
                "FCM push notifications disabled — set FIREBASE_SERVER_KEY or "
                "FIREBASE_CREDENTIALS_JSON in .env to enable real delivery"
            )

    # ── Device token management ───────────────────────────────────────────────

    def register_device(self, user_id: str, fcm_token: str) -> bool:
        """Register a device token. Returns whether the registration is DURABLE.

        Not "did it work" — it always works, in the sense that the token is
        usable by this process either way. False means the registration lives
        only in this process's memory and will be lost on the next deploy, so a
        caller can say so rather than answering an unqualified `registered:
        true` for something it knows will not last.

        The in-process copy is written in both cases. Refusing to register a
        device because Redis is unreachable would convert a delivery gap into an
        outage.
        """
        tokens = _device_tokens.setdefault(user_id, [])
        if fcm_token not in tokens:
            tokens.append(fcm_token)

        store = _token_store()
        if store is None:
            logger.warning(
                "Registered FCM token for user %s in process memory only — it will "
                "not survive a restart and other workers cannot see it",
                user_id,
            )
            return False
        try:
            store.sadd(f"{_TOKEN_KEY_PREFIX}{user_id}", fcm_token)
        except Exception as exc:
            logger.error(
                "Could not persist the FCM token for user %s (%s) — the device is "
                "registered in this process only and will be lost on restart",
                user_id,
                exc,
            )
            return False
        logger.info("Registered FCM token for user %s", user_id)
        return True

    def unregister_device(self, user_id: str, fcm_token: str) -> bool:
        """Remove a token everywhere it is held.

        Removed from the shared store first: a revoked device that keeps
        receiving is the failure that matters, and dropping only the local copy
        would leave every other worker still delivering to it.
        """
        tokens = _device_tokens.get(user_id, [])
        if fcm_token in tokens:
            tokens.remove(fcm_token)

        store = _token_store()
        if store is None:
            return False
        try:
            store.srem(f"{_TOKEN_KEY_PREFIX}{user_id}", fcm_token)
        except Exception as exc:
            logger.error(
                "Could not remove the FCM token for user %s from the shared store "
                "(%s) — other workers may keep delivering to it",
                user_id,
                exc,
            )
            return False
        return True

    def get_tokens(self, user_id: str) -> list[str]:
        """Every token registered for *user_id*, from the shared store if there is one.

        The shared store is authoritative when reachable, so a process that
        never saw the registration still finds it. The in-process copy is the
        fallback, and is unioned in rather than ignored: a token registered
        while the store was down is still deliverable from this worker.
        """
        local = list(_device_tokens.get(user_id, []))
        store = _token_store()
        if store is None:
            return local
        try:
            shared = store.smembers(f"{_TOKEN_KEY_PREFIX}{user_id}")
        except Exception as exc:
            logger.error(
                "Could not read FCM tokens for user %s from the shared store (%s) — "
                "falling back to this process's own registrations",
                user_id,
                exc,
            )
            return local
        merged = list(shared)
        merged.extend(t for t in local if t not in shared)
        return merged

    def registered_users(self) -> list[str]:
        """Every user with at least one registered device, across all workers.

        Discovered by scanning the token keys rather than kept in a second set
        alongside them. A parallel index has to be maintained in step with every
        register and unregister, and this repository's recurring defect is
        exactly that: a second copy that drifts and that nothing notices. A scan
        cannot disagree with the keys it is scanning.

        `broadcast_signal` used `_device_tokens.keys()`, so "all registered
        users" meant "users who happened to register through this process". A
        deploy emptied that dict, and the broadcast then reached nobody and
        returned a notified count of zero as a successful send (F220).
        """
        local = list(_device_tokens.keys())
        store = _token_store()
        if store is None:
            return local
        try:
            users = {key[len(_TOKEN_KEY_PREFIX) :] for key in store.scan_iter(match=f"{_TOKEN_KEY_PREFIX}*")}
        except Exception as exc:
            logger.error(
                "Could not enumerate registered devices from the shared store (%s) — "
                "a broadcast will reach only this process's own registrations",
                exc,
            )
            return local
        users.update(local)
        return sorted(users)

    # ── Core send ─────────────────────────────────────────────────────────────

    def send_notification(
        self,
        user_id: str,
        title: str,
        body: str,
        category: str = "general",
        data: dict[str, Any] | None = None,
    ) -> bool:
        tokens = self.get_tokens(user_id)

        if not self.fcm_enabled or not tokens:
            # Print to stdout so dev/test environments can observe notifications
            # without a real FCM key. logger.info alone is not captured by capsys
            # (pytest's capsys only captures direct sys.stdout writes).
            print(f"[FCM-LOG] {user_id} -> {title}: {body}")
            logger.info("[FCM-LOG] %s -> %s: %s", user_id, title, body)

            # Returns False. This used to return True, so every push on a fresh
            # deployment -- all three Firebase variables are blank in
            # .env.example -- reported success and reached no device (F219). The
            # callers cannot distinguish "delivered" from "logged", so the return
            # value has to.
            #
            # The two no-send cases are logged differently on purpose. FCM
            # switched off is the expected state of a dev box and warning per
            # notification would be noise. FCM configured while this user has no
            # device token is a real gap: somebody enabled notifications and will
            # not receive any.
            if self.fcm_enabled and not tokens:
                logger.warning(
                    "Push not delivered to %s: no device token registered. FCM is "
                    "configured, so this user expects notifications and will not "
                    "receive them.",
                    user_id,
                )
            return False

        str_data = {str(k): str(v) for k, v in (data or {}).items()}

        if self._admin_messaging is not None:
            return self._send_admin(tokens, title, body, str_data)
        return self._send_legacy(tokens, title, body, str_data)

    def _send_admin(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict[str, str],
    ) -> bool:
        """Send via Firebase Admin SDK (v1 API — OAuth2 authenticated)."""
        try:
            messaging = self._admin_messaging
            notification = messaging.Notification(title=title, body=body)

            if len(tokens) == 1:
                msg = messaging.Message(
                    notification=notification,
                    data=data,
                    token=tokens[0],
                )
                messaging.send(msg)
            else:
                # MulticastMessage supports up to 500 tokens per call
                for i in range(0, len(tokens), 500):
                    batch = tokens[i : i + 500]
                    msg = messaging.MulticastMessage(
                        notification=notification,
                        data=data,
                        tokens=batch,
                    )
                    resp = messaging.send_each_for_multicast(msg)
                    if resp.failure_count:
                        logger.warning(
                            "FCM Admin: %d/%d tokens failed",
                            resp.failure_count,
                            len(batch),
                        )
            return True
        except Exception as exc:
            logger.error("FCM Admin SDK send error: %s", exc)
            # Fall back to legacy if Admin SDK fails mid-flight
            if self.server_key:
                logger.info("FCM: falling back to legacy HTTP API")
                return self._send_legacy(tokens, title, body, data)
            return False

    def _send_legacy(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict[str, str],
    ) -> bool:
        """Send via legacy FCM HTTP API (server key)."""
        try:
            import urllib.request

            results = []
            for token in tokens:
                fcm_payload = json.dumps(
                    {
                        "to": token,
                        "notification": {"title": title, "body": body},
                        "data": data,
                    }
                ).encode()

                req = urllib.request.Request(
                    "https://fcm.googleapis.com/fcm/send",
                    data=fcm_payload,
                    headers={
                        "Authorization": f"key={self.server_key}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 - FCM/APNs https:// endpoint
                    result = json.loads(resp.read())
                    results.append(result)
                    if result.get("failure"):
                        logger.warning("FCM legacy delivery failed for token: %s", token[:20])

            return all(r.get("success", 0) > 0 for r in results)
        except Exception as exc:
            logger.error("FCM legacy send error: %s", exc)
            return False

    # ── Typed helpers ─────────────────────────────────────────────────────────

    def send_price_alert(self, user_id: str, symbol: str, price: float, direction: str) -> bool:
        return self.send_notification(
            user_id=user_id,
            title=f"Price Alert: {symbol}",
            body=f"{symbol} is {direction} ${price:,.2f}",
            category="price_alert",
            data={"symbol": symbol, "price": str(price)},
        )

    def send_new_signal(self, user_id: str, symbol: str, direction: str, confidence: float) -> bool:
        return self.send_notification(
            user_id=user_id,
            title=f"New Signal: {symbol}",
            body=f"{direction} signal with {confidence:.0f}% confidence",
            category="signal",
            data={
                "symbol": symbol,
                "direction": direction,
                "confidence": str(confidence),
            },
        )

    def send_drawdown_warning(self, user_id: str, drawdown_pct: float, limit_pct: float) -> bool:
        return self.send_notification(
            user_id=user_id,
            title="Drawdown Warning",
            body=f"Account drawdown at {drawdown_pct:.1f}% — limit is {limit_pct:.1f}%",
            category="risk",
            data={"drawdown_pct": str(drawdown_pct), "limit_pct": str(limit_pct)},
        )

    def send_trade_filled(
        self,
        user_id: str,
        symbol: str,
        direction: str,
        price: float,
        lots: float,
    ) -> bool:
        return self.send_notification(
            user_id=user_id,
            title=f"Trade Filled: {symbol}",
            body=f"{direction} {lots:.2f} lots @ {price:,.2f}",
            category="trade",
            data={
                "symbol": symbol,
                "direction": direction,
                "price": str(price),
                "lots": str(lots),
            },
        )

    def send_challenge_warning(self, user_id: str, rule: str, current: float, limit: float) -> bool:
        return self.send_notification(
            user_id=user_id,
            title="Challenge Rule Near Breach",
            body=f"{rule}: {current:.1f}% of {limit:.1f}% limit used",
            category="challenge",
            data={"rule": rule, "current": str(current), "limit": str(limit)},
        )

    def broadcast_signal(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        model_version: str = "unknown",
    ) -> int:
        """
        Send a signal push to all registered users.

        Returns the number of users notified.
        """
        notified = 0
        for user_id in self.registered_users():
            ok = self.send_new_signal(
                user_id=user_id,
                symbol=symbol,
                direction=direction,
                confidence=confidence * 100,
            )
            if ok:
                notified += 1
        if notified:
            logger.info(
                "FCM signal broadcast: %s %s conf=%.2f notified=%d users",
                symbol,
                direction,
                confidence,
                notified,
            )
        return notified


# Module-level singleton — auto-configures from environment at import time
push_manager = PushNotificationManager()
