#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/bootstrap_env.py
========================
Generate a deployable production ``.env`` from ``.env.example``.

Why this exists
---------------
``scripts/bootstrap_dev.py`` generates a complete ``.env`` with real random
secrets for development. Production had no equivalent: the only starting point
was ``.env.example``, which ships fourteen ``CHANGE_ME_*`` placeholders that an
operator had to find and replace by hand. Missing one does not fail at the point
of the mistake — it fails at container start, as::

    dependency failed to start: container hopefx-ai-trading-app-1 is unhealthy

which is what ``sys.exit(1)`` inside startup validation looks like from outside.

Three of those placeholders are load-bearing in a way hand-editing gets wrong:

* ``CHANGE_ME_db_password`` appears **three** times — ``POSTGRES_PASSWORD``,
  ``DB_PASSWORD``, and embedded inside ``DATABASE_URL``. All three must carry
  the same value or the app cannot log in to the database it just created.
* ``CHANGE_ME_redis_password`` appears twice, once embedded in ``REDIS_URL``.
* ``CHANGE_ME_generate_64_char_hex_secret`` is shared by ``SECURITY_JWT_SECRET``
  and ``CRYPTO_WEBHOOK_SECRET``, which must **not** end up equal — they are
  independent secrets, and one value for both means recovering either one hands
  over the other.

So substitution is keyed by variable name from an explicit table, not by
placeholder token, with the sharing relationships written down. A ``CHANGE_ME``
variable that is not in the table is a hard error rather than a passthrough, so
a placeholder added to ``.env.example`` later cannot quietly ship unset.

Character set
-------------
Every generated value uses ``secrets.token_urlsafe`` or hex — ``[A-Za-z0-9_-]``.
That is deliberate. ``$`` would be interpolated by docker compose, ``#`` starts a
comment in most ``.env`` parsers, and ``@ : /`` would break the DSNs these values
are embedded into. The human login passwords add a symbol from a restricted pool
for password-policy compliance; none of them are embedded in a URL.

Usage
-----
    python3 scripts/bootstrap_env.py --domain hopefx.example.com

    # overwrite an existing file (keeps a timestamped backup)
    python3 scripts/bootstrap_env.py --domain example.com --force

    # values only, no comment lines — for control panels whose environment
    # editor parses every line as NAME=VALUE and rejects the '#' ones
    python3 scripts/bootstrap_env.py --domain example.com --no-comments

The generated file is written with mode 0600 and must never be committed.
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import os
import re
import secrets
import shutil
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Symbols safe in a .env value, in a docker-compose interpolated value, and on a
# shell command line: no $ # @ : / & ' " \ or backtick.
_SAFE_SYMBOLS = "!%^*-_"


def _hex(n_bytes: int) -> str:
    """``2 * n_bytes`` hex characters."""
    return secrets.token_hex(n_bytes)


def _urlsafe(n_chars: int) -> str:
    """At least *n_chars* of URL-safe base64, trimmed to exactly *n_chars*."""
    raw = secrets.token_urlsafe(n_chars + 8)
    return raw[:n_chars]


def _aes256_key() -> str:
    """A key that base64-urlsafe-decodes to exactly 32 bytes.

    ``database/encryption.py`` requires exactly AES-256 key length and, when the
    value does not decode to 32 bytes, logs an error and returns ``None`` —
    field-level encryption then silently falls back to plaintext. A value that
    is merely "random enough" is not enough here.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def _login_password(n_chars: int = 24) -> str:
    """A password satisfying the strictest policy in the codebase.

    ``security/security_manager.py`` requires >= 12 characters with an
    uppercase, a digit, and one of ``!@#$%^&*``. Guaranteeing one of each rather
    than hoping a random string happens to contain them — at these lengths it
    almost always would, and "almost always" is how an occasional failed deploy
    gets blamed on something else.
    """
    pool = string.ascii_letters + string.digits + _SAFE_SYMBOLS
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!%^*"),  # intersection of _SAFE_SYMBOLS and the policy set
    ]
    rest = [secrets.choice(pool) for _ in range(max(0, n_chars - len(required)))]
    chars = required + rest
    # secrets.SystemRandom().shuffle so the required characters are not always
    # in the first four positions.
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


# ── What each placeholder variable gets ──────────────────────────────────────
#
# Keyed by variable name. Every variable assigned a CHANGE_ME value in
# .env.example must appear here or generation fails.

_GENERATORS: dict[str, object] = {
    # Security
    "SECURITY_JWT_SECRET": lambda: _hex(32),  # 64 hex chars
    "CONFIG_ENCRYPTION_KEY": lambda: _urlsafe(48),
    "DB_ENCRYPTION_KEY": _aes256_key,
    "HOPEFX_KILL_SWITCH_TOKEN": lambda: _hex(32),
    "CRYPTO_WEBHOOK_SECRET": lambda: _hex(32),
    # Infrastructure passwords — embedded in DSNs, so URL-safe only.
    "POSTGRES_PASSWORD": lambda: _urlsafe(32),
    "REDIS_PASSWORD": lambda: _urlsafe(32),
    "GRAFANA_ADMIN_PASSWORD": lambda: _urlsafe(24),
    # Human logins — policy-compliant.
    "BOOTSTRAP_SUPERADMIN_PASSWORD": _login_password,
    "BOOTSTRAP_ADMIN_PASSWORD": _login_password,
    "BOOTSTRAP_TRADER_PASSWORD": _login_password,
}

# Variables that must hold the identical value as another. DB_PASSWORD and
# POSTGRES_PASSWORD are the same Postgres account credential; compose passes
# POSTGRES_PASSWORD to the postgres container and the app reads DB_PASSWORD.
_ALIASES: dict[str, str] = {
    "DB_PASSWORD": "POSTGRES_PASSWORD",  # pragma: allowlist secret — variable names, not values
}

# Placeholders for third-party credentials. There is nothing to generate — an
# invented Bybit key is worse than an empty one, because empty means "disabled"
# and random means "enabled and failing every call".
_LEAVE_EMPTY: frozenset[str] = frozenset({"BYBIT_API_KEY", "BYBIT_API_SECRET"})

# Placeholder token → the variable whose generated value it must reuse, for
# occurrences embedded inside a composite value such as a DSN.
_EMBEDDED: dict[str, dict[str, str]] = {
    "DATABASE_URL": {"CHANGE_ME_db_password": "POSTGRES_PASSWORD"},  # pragma: allowlist secret
    "REDIS_URL": {"CHANGE_ME_redis_password": "REDIS_PASSWORD"},  # pragma: allowlist secret
}

# Values forced regardless of what .env.example says.
_FORCED: dict[str, str] = {
    "APP_ENV": "production",
    # Billing needs a Stripe account, which an operator sets up after the
    # platform is running. Left on, startup validation hard-fails on the missing
    # STRIPE_WEBHOOK_SECRET and the deploy never comes up at all. Turning it on
    # later is one variable and a restart.
    "FEATURE_BILLING_SUBSCRIPTION": "false",
}

_ASSIGN_RE = re.compile(r"^(\s*)([A-Z0-9_]+)(\s*=\s*)(.*)$")
_PLACEHOLDER_RE = re.compile(r"CHANGE_ME\S*")

# An inline comment is a '#' preceded by whitespace — the rule docker compose
# and python-dotenv both use. It matters: '.env.example' contains
# ``ELITE_AM_SLACK=#elite-support``, where the '#' is the Slack channel sigil and
# part of the value, next to lines like ``LOG_JSON=false   # comment`` where it
# is not. Splitting on a bare '#' would silently blank the first one.
_INLINE_COMMENT_RE = re.compile(r"\s+#.*$")


def _strip_inline_comment(value: str) -> str:
    return _INLINE_COMMENT_RE.sub("", value)


# Credentials worth printing once at the end — an operator cannot log in
# without them and the file is 0600.
_REPORT = (
    "BOOTSTRAP_SUPERADMIN_PASSWORD",
    "BOOTSTRAP_ADMIN_PASSWORD",
    "BOOTSTRAP_TRADER_PASSWORD",
    "GRAFANA_ADMIN_PASSWORD",
)


class GenerationError(RuntimeError):
    """Raised when the template contains something this script cannot fill."""


def generate(template: str, domain: str, *, keep_comments: bool = True) -> tuple[str, dict[str, str]]:
    """Return ``(env_text, generated_values)`` for *template*.

    Pure: no filesystem access, so the tests can exercise the real template.
    """
    values: dict[str, str] = {}

    # Pass 1 — assign a value to every standalone placeholder variable.
    for line in template.splitlines():
        match = _ASSIGN_RE.match(line)
        if not match:
            continue
        name, raw = match.group(2), match.group(4).strip()
        if not _PLACEHOLDER_RE.fullmatch(raw):
            continue  # embedded placeholders are handled in pass 2
        if name in _LEAVE_EMPTY:
            values[name] = ""
        elif name in _ALIASES:
            continue  # resolved after its source
        elif name in _GENERATORS:
            values[name] = _GENERATORS[name]()  # type: ignore[operator]
        else:
            raise GenerationError(
                f"{name} has a placeholder value in .env.example but no entry in "
                f"_GENERATORS in {Path(__file__).name}. Add one — otherwise this "
                f"variable ships as a literal CHANGE_ME and startup validation "
                f"rejects the deployment."
            )

    for alias, source in _ALIASES.items():
        if source not in values:
            raise GenerationError(f"{alias} aliases {source}, which was never generated")
        values[alias] = values[source]

    # Pass 2 — rewrite the template.
    out: list[str] = []
    for line in template.splitlines():
        match = _ASSIGN_RE.match(line)
        if not match:
            if keep_comments:
                out.append(line)
            continue

        indent, name, sep, raw = match.groups()
        value = raw

        if name in _FORCED:
            value = _FORCED[name]
        elif name in values:
            value = values[name]
        else:
            for token, source in _EMBEDDED.get(name, {}).items():
                if token in value:
                    value = value.replace(token, values[source])
            value = value.replace("YOUR_DOMAIN", domain)

        if not keep_comments:
            # The control-panel environment editors that need this mode parse
            # every line as NAME=VALUE, so a trailing comment becomes part of
            # the value.
            value = _strip_inline_comment(value)

        out.append(f"{indent}{name}{sep}{value}")

    text = "\n".join(out).rstrip("\n") + "\n"

    leftover = _PLACEHOLDER_RE.search(text)
    if leftover:
        line_no = text[: leftover.start()].count("\n") + 1
        raise GenerationError(f"line {line_no} still contains {leftover.group()!r} after generation")

    return text, values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a production .env with real secrets.")
    parser.add_argument("--domain", required=True, help="public domain, e.g. hopefx.example.com")
    parser.add_argument("--template", default=str(ROOT / ".env.example"))
    parser.add_argument("--output", default=str(ROOT / ".env"))
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file (keeps a backup)")
    parser.add_argument("--no-comments", action="store_true", help="emit NAME=VALUE lines only")
    args = parser.parse_args(argv)

    template_path, output_path = Path(args.template), Path(args.output)
    if not template_path.exists():
        print(f"error: template not found: {template_path}", file=sys.stderr)
        return 1

    if output_path.exists() and not args.force:
        print(
            f"error: {output_path} already exists. Refusing to overwrite — regenerating "
            f"secrets on a running deployment invalidates every session and locks the app "
            f"out of its own database. Pass --force if that is what you want.",
            file=sys.stderr,
        )
        return 1

    try:
        text, values = generate(
            template_path.read_text(encoding="utf-8"),
            args.domain,
            keep_comments=not args.no_comments,
        )
    except GenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if output_path.exists():
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = output_path.with_suffix(f".backup-{stamp}")
        shutil.copy2(output_path, backup)
        print(f"  backed up existing file -> {backup}")

    output_path.write_text(text, encoding="utf-8")
    try:
        os.chmod(output_path, 0o600)
    except OSError as exc:
        print(f"  warning: could not chmod 0600 ({exc}) — check permissions yourself", file=sys.stderr)

    print(f"\n  Wrote {output_path} (mode 0600) for domain {args.domain}")
    print(f"  {len(values)} secrets generated. Save these now — the file is not readable by other users:\n")
    for name in _REPORT:
        if name in values:
            print(f"    {name:<32} {values[name]}")
    print(
        "\n  Next:\n"
        "    docker compose up -d\n"
        "    docker compose exec app python3 scripts/bootstrap_prod.py\n\n"
        "  Stripe billing is off (FEATURE_BILLING_SUBSCRIPTION=false). Set the\n"
        "  Stripe keys and flip it to true when you are ready to take payments.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
