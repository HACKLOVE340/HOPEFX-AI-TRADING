"""
Push Notification System — Firebase Cloud Messaging (FCM)

Set FIREBASE_SERVER_KEY in .env to enable real FCM delivery.
Without it, notifications are logged only (safe for development).

Trigger points:
  - New high-confidence signal
  - Drawdown warning
  - Trade filled
  - Prop-firm challenge near breach
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory device token registry: user_id → list of FCM tokens
_device_tokens: Dict[str, List[str]] = {}


class PushNotificationManager:
    """Manages push notifications for mobile devices via FCM."""

    def __init__(self):
        self.server_key = os.getenv("FIREBASE_SERVER_KEY", "")
        self.fcm_enabled = bool(self.server_key)
        self.apns_enabled = False

        if self.fcm_enabled:
            logger.info("FCM push notifications enabled")
        else:
            logger.info("FCM push notifications disabled (FIREBASE_SERVER_KEY not set) — logging only")

    # ── Device token management ───────────────────────────────────────────────

    def register_device(self, user_id: str, fcm_token: str) -> bool:
        tokens = _device_tokens.setdefault(user_id, [])
        if fcm_token not in tokens:
            tokens.append(fcm_token)
            logger.info("Registered FCM token for user %s", user_id)
        return True

    def unregister_device(self, user_id: str, fcm_token: str) -> bool:
        tokens = _device_tokens.get(user_id, [])
        if fcm_token in tokens:
            tokens.remove(fcm_token)
        return True

    def get_tokens(self, user_id: str) -> List[str]:
        return _device_tokens.get(user_id, [])

    # ── Core send ─────────────────────────────────────────────────────────────

    def send_notification(
        self,
        user_id: str,
        title: str,
        body: str,
        category: str = "general",
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        tokens = self.get_tokens(user_id)

        if not self.fcm_enabled or not tokens:
            # Print to stdout so dev/test environments can observe notifications
            # without a real FCM key. logger.info alone is not captured by capsys.
            print(f"[FCM-LOG] {user_id} -> {title}: {body}")
            logger.info("[FCM-LOG] %s -> %s: %s", user_id, title, body)
            return True

        return self._send_fcm(tokens, title, body, data or {})

    def _send_fcm(self, tokens: List[str], title: str, body: str, data: Dict[str, Any]) -> bool:
        try:
            import json
            import urllib.request

            results = []
            for token in tokens:
                fcm_payload = json.dumps({
                    "to": token,
                    "notification": {"title": title, "body": body},
                    "data": {str(k): str(v) for k, v in data.items()},
                }).encode()

                req = urllib.request.Request(
                    "https://fcm.googleapis.com/fcm/send",
                    data=fcm_payload,
                    headers={
                        "Authorization": f"key={self.server_key}",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    result = json.loads(resp.read())
                    results.append(result)
                    if result.get("failure"):
                        logger.warning("FCM delivery failed for token: %s", token[:20])

            return all(r.get("success", 0) > 0 for r in results)
        except Exception as exc:
            logger.error("FCM send error: %s", exc)
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
            data={"symbol": symbol, "direction": direction, "confidence": str(confidence)},
        )

    def send_drawdown_warning(self, user_id: str, drawdown_pct: float, limit_pct: float) -> bool:
        return self.send_notification(
            user_id=user_id,
            title="Drawdown Warning",
            body=f"Account drawdown at {drawdown_pct:.1f}% — limit is {limit_pct:.1f}%",
            category="risk",
            data={"drawdown_pct": str(drawdown_pct), "limit_pct": str(limit_pct)},
        )

    def send_trade_filled(self, user_id: str, symbol: str, direction: str, price: float, lots: float) -> bool:
        return self.send_notification(
            user_id=user_id,
            title=f"Trade Filled: {symbol}",
            body=f"{direction} {lots:.2f} lots @ {price:,.2f}",
            category="trade",
            data={"symbol": symbol, "direction": direction, "price": str(price), "lots": str(lots)},
        )

    def send_challenge_warning(self, user_id: str, rule: str, current: float, limit: float) -> bool:
        return self.send_notification(
            user_id=user_id,
            title="Challenge Rule Near Breach",
            body=f"{rule}: {current:.1f}% of {limit:.1f}% limit used",
            category="challenge",
            data={"rule": rule, "current": str(current), "limit": str(limit)},
        )


# Module-level singleton
push_manager = PushNotificationManager()
