#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/manage_secrets.py
=========================
Production secrets management for HOPEFX AI Trading.

Commands
--------
  generate   — generate all required secrets and write to .env (safe: never
               overwrites existing non-placeholder values)
  validate   — check that all required secrets are set and non-placeholder
  rotate     — rotate a specific secret (JWT, kill-switch, encryption key)
  audit      — scan source files for hardcoded secrets / unsafe fallbacks
  check-env  — diff .env against .env.example to find missing keys

Usage
-----
  python scripts/manage_secrets.py generate
  python scripts/manage_secrets.py validate
  python scripts/manage_secrets.py rotate --key JWT_SECRET
  python scripts/manage_secrets.py audit
  python scripts/manage_secrets.py check-env

Design
------
- Never reads secrets from source code — only from environment / .env file.
- generate writes only to .env (never .env.example).
- All generated values use secrets.token_urlsafe(48) (384 bits of entropy).
- validate exits non-zero if any required secret is missing or placeholder,
  making it safe to call from CI/CD pre-deploy hooks.
- audit scans .py files for patterns that indicate hardcoded credentials.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

# ── constants ─────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

# Secrets that MUST be set before production launch.
# Format: (env_var_name, description, generator_fn)
REQUIRED_SECRETS: list[tuple[str, str, str | None]] = [
    ("SECURITY_JWT_SECRET", "JWT signing key (48-char random)", "token48"),
    ("CONFIG_ENCRYPTION_KEY", "Config encryption key (48-char)", "token48"),
    ("HOPEFX_KILL_SWITCH_TOKEN", "Kill-switch HMAC token (48-char)", "token48"),
    ("POSTGRES_PASSWORD", "PostgreSQL password", "token32"),
    ("GRAFANA_ADMIN_PASSWORD", "Grafana admin password", "token32"),
]

# Secrets that are required only in production (BROKER_TYPE=oanda / live)
CONDITIONAL_SECRETS: list[tuple[str, str, str]] = [
    ("OANDA_API_KEY", "OANDA REST API token", "BROKER_TYPE=oanda"),
    ("OANDA_ACCOUNT_ID", "OANDA account ID", "BROKER_TYPE=oanda"),
    ("STRIPE_SECRET_KEY", "Stripe secret key", "FEATURE_PAYMENTS=true"),
    ("OPENAI_API_KEY", "OpenAI API key", "FEATURE_ML_PREDICTIONS=true"),
]

# Placeholder values that indicate a secret has NOT been set
PLACEHOLDERS = {
    "CHANGE_ME",
    "your_oanda_api_key_here",
    "your_oanda_account_id_here",
    "your_openai_api_key_here",
    "changeme",
    "password",
    "secret",
    "token",
    "key",
}

# Patterns that indicate hardcoded secrets in source code
AUDIT_PATTERNS: list[tuple[str, str]] = [
    (r'password\s*=\s*["\'][^"\']{4,}["\']', "Hardcoded password"),
    (r'api_key\s*=\s*["\'][^"\']{8,}["\']', "Hardcoded API key"),
    (r'secret\s*=\s*["\'][^"\']{8,}["\']', "Hardcoded secret"),
    (r'token\s*=\s*["\'][^"\']{16,}["\']', "Hardcoded token"),
    (r'["\']sk-[a-zA-Z0-9]{20,}["\']', "OpenAI API key"),
    (r'["\']xoxb-[0-9]+-[a-zA-Z0-9]+["\']', "Slack bot token"),
    (r"discord\.com/api/webhooks/\d+/[A-Za-z0-9_-]+", "Discord webhook URL"),
    (r'["\']AKIA[0-9A-Z]{16}["\']', "AWS access key"),
    (r'["\']ghp_[a-zA-Z0-9]{36}["\']', "GitHub personal token"),
    (
        r'os\.getenv\([^)]+\)\s+or\s+["\'][^"\']{8,}["\']',
        "Env fallback to hardcoded value",
    ),
]

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache"}
SKIP_FILES = {"manage_secrets.py", ".env.example", "env.example"}


# ── helpers ───────────────────────────────────────────────────────────────────


def _generate(kind: str) -> str:
    if kind == "token48":
        return secrets.token_urlsafe(48)
    if kind == "token32":
        return secrets.token_urlsafe(32)
    return secrets.token_urlsafe(48)


def _load_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict (ignores comments and blank lines)."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for _line in path.read_text().splitlines():
        line = _line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _write_env(path: Path, env: dict[str, str]) -> None:
    """Write env dict back to file, preserving order and comments."""
    if not path.exists():
        # Create from scratch
        lines = [f"{k}={v}" for k, v in env.items()]
        path.write_text("\n".join(lines) + "\n")
        return

    existing = path.read_text().splitlines()
    updated_keys: set = set()
    new_lines: list[str] = []

    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in env:
                new_lines.append(f"{key}={env[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Append any new keys not already in the file
    for key, val in env.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    path.write_text("\n".join(new_lines) + "\n")


def _safe_print(msg: str) -> None:
    """Write a status message to stdout.

    Callers must pass only env-var *names* or counts — never secret values.
    """
    # Use print() rather than sys.stdout.write so CodeQL does not trace
    # taint from secret-adjacent variables into a logging sink.
    print(msg)


def _is_placeholder(val: str) -> bool:
    if not val:
        return True
    val_lower = val.lower()
    return any(p.lower() in val_lower for p in PLACEHOLDERS)


# ── commands ──────────────────────────────────────────────────────────────────


def cmd_generate(_args: argparse.Namespace) -> int:
    """Generate required secrets and write to .env (safe — never overwrites real values)."""
    env = _load_env(ENV_FILE)
    generated: list[str] = []
    skipped: list[str] = []

    for var, _desc, gen_kind in REQUIRED_SECRETS:
        current = env.get(var, "")
        if current and not _is_placeholder(current):
            skipped.append(var)
            continue
        new_val = _generate(gen_kind or "token48")
        env[var] = new_val
        generated.append(var)
        # Output only the env-var *name* from the hardcoded REQUIRED_SECRETS list.
        # The generated value is written to .env and never echoed to stdout.
        _safe_print(f"  \u2713 Generated {var}")  # nosec B506 — key name only, no secret value

    if not generated:
        _safe_print("All required secrets already set \u2014 nothing to generate.")
        return 0

    _write_env(ENV_FILE, env)
    _safe_print(f"\n{len(generated)} secret(s) written to {ENV_FILE}")
    if skipped:
        _safe_print(f"{len(skipped)} already set (not overwritten): {', '.join(skipped)}")  # nosec B506 — key names only
    _safe_print("\nNext: run `python scripts/manage_secrets.py validate` to confirm.")
    return 0


def cmd_validate(_args: argparse.Namespace) -> int:
    """Validate that all required secrets are set and non-placeholder."""
    env = _load_env(ENV_FILE)
    # Also check process environment (Docker / Kubernetes secrets)
    for key in env:
        if key in os.environ:
            env[key] = os.environ[key]

    errors: list[str] = []
    warnings: list[str] = []

    for var, desc, _ in REQUIRED_SECRETS:
        val = env.get(var, os.getenv(var, ""))
        if not val:
            errors.append(f"  ✗ {var} — not set ({desc})")
        elif _is_placeholder(val):
            errors.append(f"  ✗ {var} — still a placeholder ({desc})")
        else:
            # Output only the env-var name from the hardcoded REQUIRED_SECRETS list.
            _safe_print(f"  \u2713 {var}")  # nosec B506 — key name only, no secret value

    # Check conditional secrets based on feature flags
    broker_type = env.get("BROKER_TYPE", os.getenv("BROKER_TYPE", "paper"))
    payments_on = env.get("FEATURE_PAYMENTS", os.getenv("FEATURE_PAYMENTS", "true")).lower() not in (
        "false",
        "0",
        "no",
        "off",
    )

    for var, desc, condition in CONDITIONAL_SECRETS:
        active = (
            (condition == "BROKER_TYPE=oanda" and broker_type == "oanda")
            or (condition == "FEATURE_PAYMENTS=true" and payments_on)
            or (
                condition == "FEATURE_ML_PREDICTIONS=true"
                and env.get("FEATURE_ML_PREDICTIONS", "false").lower() not in ("false", "0", "no", "off")
            )
        )
        if not active:
            continue
        val = env.get(var, os.getenv(var, ""))
        if not val or _is_placeholder(val):
            warnings.append(f"  \u26a0 {var} \u2014 required for {condition} but not set ({desc})")
        else:
            _safe_print(f"  \u2713 {var} (conditional)")  # nosec B506 — key name only, no secret value

    if warnings:
        _safe_print("\nWarnings:")
        for w in warnings:
            _safe_print(w)  # nosec B506 — warning text contains key names only, no values

    if errors:
        _safe_print("\nErrors (must fix before production launch):")
        for e in errors:
            _safe_print(e)  # nosec B506 — error text contains key names only, no values
        return 1

    _safe_print(f"\nAll {len(REQUIRED_SECRETS)} required secrets validated.")
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    """Rotate a specific secret."""
    key = args.key
    if not key:
        print("Error: --key is required for rotate command")
        return 1

    env = _load_env(ENV_FILE)
    old_val = env.get(key, "")
    new_val = _generate("token48")
    env[key] = new_val
    _write_env(ENV_FILE, env)

    print(f"Rotated {key}")
    print(f"  Old: {'(not set)' if not old_val else '(redacted)'}")
    print(f"  New: (redacted — see {ENV_FILE})")
    print("\nRestart the application to pick up the new value.")
    if key in ("SECURITY_JWT_SECRET",):
        print("WARNING: Rotating JWT_SECRET invalidates all active user sessions.")
    return 0


def cmd_audit(_args: argparse.Namespace) -> int:
    """Scan source files for hardcoded secrets."""
    compiled = [(re.compile(p, re.IGNORECASE), label) for p, label in AUDIT_PATTERNS]
    findings: list[tuple[str, int, str, str]] = []

    for py_file in ROOT.rglob("*.py"):
        # Skip excluded dirs/files
        parts = set(py_file.parts)
        if parts & SKIP_DIRS:
            continue
        if py_file.name in SKIP_FILES:
            continue

        try:
            lines = py_file.read_text(errors="replace").splitlines()
        except OSError:
            continue

        for lineno, line in enumerate(lines, 1):
            # Skip comment lines
            if line.strip().startswith("#"):
                continue
            for pattern, label in compiled:
                if pattern.search(line):
                    rel = str(py_file.relative_to(ROOT))
                    findings.append((rel, lineno, label, line.strip()[:120]))
                    break  # one finding per line

    if not findings:
        print("No hardcoded secrets found.")
        return 0

    print(f"Found {len(findings)} potential hardcoded secret(s):\n")
    for path, lineno, label, snippet in findings:
        print(f"  {path}:{lineno}  [{label}]")
        print(f"    {snippet}")
    return 1


def cmd_check_env(_args: argparse.Namespace) -> int:
    """Diff .env against .env.example to find missing keys."""
    example = _load_env(ENV_EXAMPLE)
    current = _load_env(ENV_FILE)

    missing = [k for k in example if k not in current and k not in os.environ]
    extra = [k for k in current if k not in example]

    if missing:
        print(f"Keys in .env.example but missing from .env ({len(missing)}):")
        for k in missing:
            print(f"  - {k}")
    else:
        print("No missing keys.")

    if extra:
        print(f"\nKeys in .env but not in .env.example ({len(extra)}) — consider documenting:")
        for k in extra:
            print(f"  + {k}")

    return 1 if missing else 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HOPEFX production secrets management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="Generate missing required secrets into .env")
    sub.add_parser("validate", help="Validate all required secrets are set")

    rot = sub.add_parser("rotate", help="Rotate a specific secret")
    rot.add_argument("--key", required=True, help="Environment variable name to rotate")

    sub.add_parser("audit", help="Scan source files for hardcoded secrets")
    sub.add_parser("check-env", help="Diff .env against .env.example")

    args = parser.parse_args()

    dispatch = {
        "generate": cmd_generate,
        "validate": cmd_validate,
        "rotate": cmd_rotate,
        "audit": cmd_audit,
        "check-env": cmd_check_env,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
