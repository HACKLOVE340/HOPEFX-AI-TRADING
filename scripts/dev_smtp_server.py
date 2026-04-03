#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/dev_smtp_server.py
==========================
Local SMTP sink for development and CI.

Accepts all inbound mail on localhost:1025, logs each message to
logs/dev_email.log, and prints a one-line summary to stdout.
No mail is ever forwarded to a real address.

Usage
-----
    python scripts/dev_smtp_server.py            # default port 1025
    python scripts/dev_smtp_server.py --port 2525

.env wiring (already set by the bootstrap below)
-------------------------------------------------
    SMTP_HOST=localhost
    SMTP_PORT=1025
    SMTP_USER=dev
    SMTP_PASSWORD=<any value — auth is accepted but not verified>
    SMTP_FROM=alerts@hopefx.local
    SMTP_TO=dev@hopefx.local
    SMTP_USE_TLS=false
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from email import message_from_bytes
from pathlib import Path

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "dev_email.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("dev_smtp")

# File handler for persisting received mail
_file_handler = logging.FileHandler(LOG_PATH)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logger.addHandler(_file_handler)


class _Authenticator:
    """Accept any LOGIN/PLAIN credentials — dev only."""

    def __call__(self, server, session, envelope, mechanism, auth_data):
        # auth_data is a LoginPassword namedtuple for LOGIN/PLAIN
        if isinstance(auth_data, LoginPassword):
            logger.debug(
                "SMTP AUTH accepted for user=%s",
                auth_data.login.decode(errors="replace"),
            )
        return AuthResult(success=True)


class _Handler:
    """Log every received message; never forward."""

    async def handle_DATA(self, server, session, envelope):
        msg = message_from_bytes(envelope.content)
        subject = msg.get("Subject", "(no subject)")
        from_addr = envelope.mail_from
        to_addrs = envelope.rcpt_tos
        size = len(envelope.content)
        ts = datetime.now(UTC).isoformat()

        logger.info(
            "RECEIVED  from=%-30s  to=%s  subject=%r  size=%d bytes  ts=%s",
            from_addr,
            to_addrs,
            subject,
            size,
            ts,
        )

        # Write full message body to log
        body_lines = envelope.content.decode(errors="replace").splitlines()
        logger.debug("--- MESSAGE START ---")
        for line in body_lines:
            logger.debug("  %s", line)
        logger.debug("--- MESSAGE END ---")

        return "250 Message accepted for delivery"


async def _serve(host: str, port: int) -> None:
    controller = Controller(
        _Handler(),
        hostname=host,
        port=port,
        auth_required=False,
        auth_require_tls=False,
    )
    controller.start()
    logger.info(
        "Dev SMTP server listening on %s:%d — all mail logged to %s",
        host,
        port,
        LOG_PATH,
    )
    logger.info("Press Ctrl+C to stop.")
    try:
        # Keep running until cancelled
        await asyncio.Event().wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        controller.stop()
        logger.info("Dev SMTP server stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="HOPEFX dev SMTP sink")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=2525, help="Bind port (default: 2525)")
    args = parser.parse_args()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(args.host, args.port))


if __name__ == "__main__":
    main()
