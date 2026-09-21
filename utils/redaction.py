# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
utils/redaction.py — strip credentials before anything reaches a log
====================================================================

``REDIS_URL`` in this deployment carries a password in its userinfo section. Six
call sites logged it verbatim at INFO or DEBUG on every startup::

    logger.info("Rate limiter: Redis backend at %s", REDIS_URL)
    logger.info("MarketDataOrchestrator: Redis connected (%s)", _REDIS_URL)
    logger.info("PositionManager: Redis client wired (%s)", redis_url)
    logger.info("whitelabel rate limiter: Redis backend at %s", _REDIS_URL)
    logger.info("Rate limiter: Redis backend at %s", redis_url)
    logger.debug("OHLCVStore: Redis connected at %s", _REDIS_URL)

so the Redis password was printed to stdout six times per boot, captured by
Docker's json log driver, and readable by anything with access to the container
logs or a log shipper. A hosting-panel log scan is what surfaced it.

There was no redaction helper anywhere in the codebase, which is why each of the
six sites independently did the wrong thing. This is that helper.

The safe form is "log the shape, never the secret": scheme, host, port and path
are useful when debugging a connection; the password never is.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

__all__ = ["redact_url"]

_REDACTED = "***"


def redact_url(url: str | None) -> str:
    """Return *url* with any userinfo credentials replaced by ``***``.

    A Redis URL with a password  → the same URL with ``***`` in its place
    A Postgres DSN with one      → the same DSN, username kept, password ``***``
    A URL with no userinfo       → returned byte-for-byte (nothing to hide)

    Never raises. A value that cannot be parsed as a URL is reported as
    ``"<unparseable url>"`` rather than returned raw — a string that failed to
    parse is exactly the case where a credential is most likely to be sitting in
    an unexpected position, so falling back to the input would defeat the point.
    """
    if not url:
        return ""

    try:
        parts = urlsplit(url)
    except Exception:
        return "<unparseable url>"

    if not parts.netloc:
        # Not a URL at all. `urlsplit` does not raise on arbitrary text, it just
        # returns an empty netloc, so the earlier `except` never fired and a
        # string like "connecting as user:pw@host" came back verbatim. A value
        # that failed to parse is precisely where a credential is most likely to
        # be sitting somewhere unexpected, so anything carrying userinfo is
        # withheld rather than echoed.
        return "<unparseable url>" if "@" in url else url

    if "@" not in parts.netloc:
        return url

    userinfo, _, hostport = parts.netloc.rpartition("@")
    # A URL whose userinfo is just `:password` has an empty username; keep it
    # empty so the shape of the URL is still recognisable.
    username, sep, _password = userinfo.partition(":")
    netloc = f"{username}:{_REDACTED}@{hostport}" if sep else f"{_REDACTED}@{hostport}"

    try:
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "<unparseable url>"
