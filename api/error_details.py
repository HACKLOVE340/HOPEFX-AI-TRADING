# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/error_details.py
====================
One place that decides what an unexpected exception is allowed to tell a client.

The problem this solves
-----------------------
Handlers across the API caught a broad ``Exception`` and put ``str(exc)`` into
the response — ``{"ok": False, "error": str(exc)}``, ``detail=str(exc)``, and
so on. The *message* of an arbitrary exception is not a description of what the
caller did wrong; it is whatever the failing library chose to say. In this
codebase that routinely means a DSN with credentials in it (``psycopg2``,
``redis``), an absolute filesystem path (``FileNotFoundError``), a SQL fragment
with column names and bound row values (``sqlalchemy``), or an upstream broker
response. None of that belongs on the wire.

What replaces it
----------------
``safe_error()`` returns the exception's *class name* plus a short reference,
and writes the full exception — message and traceback — to the server log under
that same reference:

    return {"ok": False, "error": safe_error(exc, "broker reconnect")}
    # client sees:  "ConnectionRefusedError [ref:9f3a1c72]"
    # log contains: broker reconnect [ref=9f3a1c72]: ConnectionRefusedError: ...

The class name is deliberately kept. It is the part a frontend can branch on
and an operator can recognise, and it carries no data from the failure itself.
The reference is what turns a support report back into the real traceback, so
the superadmin diagnostics pages lose no debuggability — the detail moves from
the response body to the log, where it was already going.

When *not* to use this
----------------------
A message we raise ourselves is product copy, not a leak. Where a handler
catches a specific exception that our own validation raised — the ``except
ValueError`` in ``api/nocode.py`` that reports why a strategy graph is invalid,
for instance — that message is the whole point of the response and must be
passed through unchanged. This helper is for the catch-all ``except Exception``
arm, where nobody chose the wording.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

__all__ = ["safe_error"]


def safe_error(exc: BaseException, context: str = "") -> str:
    """Log *exc* in full and return a description that is safe to send to a client.

    Parameters
    ----------
    exc:
        The caught exception. Logged with its traceback.
    context:
        Short description of what was being attempted, e.g. ``"redis ping"``.
        Appears in the log line only — never in the returned string.

    Returns
    -------
    str
        ``"<ExceptionClassName> [ref:<8 hex chars>]"``. The reference matches
        the ``ref=`` field of the log entry written by this call.
    """
    ref = uuid.uuid4().hex[:8]
    logger.error(
        "%s [ref=%s]: %s: %s",
        context or "unhandled error in request handler",
        ref,
        type(exc).__name__,
        exc,
        exc_info=exc,
    )
    return f"{type(exc).__name__} [ref:{ref}]"
