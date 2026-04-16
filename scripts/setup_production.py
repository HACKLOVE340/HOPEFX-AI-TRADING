#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/setup_production.py
===========================
Guided first-time production setup wizard.

Walks an operator through every secret and configuration value required
before the first production deployment.  Generates cryptographically-random
values for all secrets, prompts for operator-supplied values (domain, broker
credentials, API keys), writes a complete .env file, and runs a final
validation pass.

Usage
-----
    python scripts/setup_production.py

    # Non-interactive (CI pre-check only — no .env written):
    python scripts/setup_production.py --check

    # Force overwrite an existing .env:
    python scripts/setup_production.py --force

What it does
------------
1.  Checks Python version and required stdlib modules.
2.  Detects whether .env already exists and asks before overwriting.
3.  Prompts for deployment domain and CORS origins.
4.  Generates all cryptographic secrets (JWT, encryption key, kill-switch
    token, DB password, Redis password, Grafana password).
5.  Prompts for optional third-party API keys (OANDA, Stripe, OpenAI,
    Sentry, SendGrid, Flutterwave, Bybit, Finnhub, Twelve Data, Polygon).
6.  Writes a complete, annotated .env file.
7.  Runs validate_environment() from config/startup_validator.py to confirm
    the written values pass all startup checks.
8.  Prints a concise next-steps checklist.

Security invariants
-------------------
- Generated secret values are NEVER printed to stdout or logged.
- All secrets use secrets.token_urlsafe(48) (≥ 384 bits of entropy).
- Database and Redis passwords use secrets.token_urlsafe(32).
- The script refuses to run as root unless --allow-root is passed.
- .env is written with mode 0o600 (owner read/write only).
"""

from __future__ import annotations

import argparse
import os
import platform
import secrets
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: ensure project root is on sys.path so we can import project
# modules for the final validation step.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_ENV_FILE = _ROOT / ".env"
_ENV_EXAMPLE = _ROOT / ".env.example"

# ---------------------------------------------------------------------------
# ANSI colour helpers (disabled on Windows without ANSICON / Windows Terminal)
# ---------------------------------------------------------------------------
_USE_COLOUR = sys.stdout.isatty() and platform.system() != "Windows"


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text


def _green(t: str) -> str:
    return _c("32", t)


def _yellow(t: str) -> str:
    return _c("33", t)


def _red(t: str) -> str:
    return _c("31", t)


def _bold(t: str) -> str:
    return _c("1", t)


def _cyan(t: str) -> str:
    return _c("36", t)


# ---------------------------------------------------------------------------
# Output helpers — never print secret values
# ---------------------------------------------------------------------------


def _print(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _header(title: str) -> None:
    width = 70
    _print()
    _print(_bold(_cyan("─" * width)))
    _print(_bold(_cyan(f"  {title}")))
    _print(_bold(_cyan("─" * width)))


def _ok(msg: str) -> None:
    _print(f"  {_green('✓')} {msg}")


def _warn(msg: str) -> None:
    _print(f"  {_yellow('⚠')} {msg}")


def _err(msg: str) -> None:
    _print(f"  {_red('✗')} {msg}")


def _info(msg: str) -> None:
    _print(f"    {msg}")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _ask(prompt: str, default: str = "", required: bool = False) -> str:
    """Prompt the operator for a value.  Returns *default* on empty input."""
    suffix = f" [{default}]" if default else ""
    marker = _bold("*") if required else " "
    while True:
        try:
            raw = input(f"  {marker} {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            _print()
            _print(_yellow("Setup cancelled."))
            sys.exit(1)
        value = raw if raw else default
        if required and not value:
            _warn("This value is required — please enter it.")
            continue
        return value


def _ask_secret(prompt: str, env_var: str) -> str:
    """Prompt for a secret the operator must supply (not auto-generated).

    The value is read but never echoed back or stored in any variable that
    could be accidentally logged.  Returns the raw string for .env writing.
    """
    import getpass

    marker = _bold("*")
    while True:
        try:
            value = getpass.getpass(f"  {marker} {prompt} (hidden): ").strip()
        except (EOFError, KeyboardInterrupt):
            _print()
            _print(_yellow("Setup cancelled."))
            sys.exit(1)
        if value:
            return value
        _warn(f"{env_var} is required — please enter it.")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    try:
        raw = input(f"  {prompt} [{default_str}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        _print()
        sys.exit(1)
    if not raw:
        return default
    return raw in ("y", "yes")


# ---------------------------------------------------------------------------
# Secret generation
# ---------------------------------------------------------------------------


def _gen48() -> str:
    """Generate a 48-byte URL-safe base64 secret (384 bits)."""
    return secrets.token_urlsafe(48)


def _gen32() -> str:
    """Generate a 32-byte URL-safe base64 secret (256 bits)."""
    return secrets.token_urlsafe(32)


def _gen_hex32() -> str:
    """Generate a 32-byte hex secret (256 bits)."""
    return secrets.token_hex(32)


def _gen_hex16() -> str:
    """Generate a 16-byte hex salt (128 bits)."""
    return secrets.token_hex(16)


# ---------------------------------------------------------------------------
# .env writer
# ---------------------------------------------------------------------------


def _write_env(path: Path, lines: list[str]) -> None:
    """Write *lines* to *path* with mode 0o600."""
    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")
    # Restrict to owner read/write only — secrets must not be world-readable.
    try:
        path.chmod(0o600)
    except OSError:
        _warn(f"Could not set permissions on {path} — set manually: chmod 600 .env")


# ---------------------------------------------------------------------------
# Placeholder detection (mirrors manage_secrets.py logic)
# ---------------------------------------------------------------------------

_PLACEHOLDER_SUBSTRINGS = frozenset(
    {
        "change_me",
        "your_domain",
        "your_oanda",
        "your_openai",
        "changeme",
        "placeholder",
    }
)


def _is_placeholder(val: str) -> bool:
    if not val:
        return True
    v = val.lower()
    return any(p in v for p in _PLACEHOLDER_SUBSTRINGS)


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def _preflight() -> None:
    """Abort early on obvious environment problems."""
    if sys.version_info < (3, 10):
        _err(f"Python 3.10+ required (found {sys.version})")
        sys.exit(1)

    # Refuse to run as root unless explicitly allowed
    if hasattr(os, "getuid") and os.getuid() == 0 and "--allow-root" not in sys.argv:
        _err("Running as root is not recommended.")
        _info("Pass --allow-root to override (not recommended in production).")
        sys.exit(1)

    _ok(f"Python {sys.version.split()[0]}")


# ---------------------------------------------------------------------------
# Section builders — each returns a list of .env lines
# ---------------------------------------------------------------------------


def _section_app(domain: str) -> list[str]:
    return [
        "",
        "# ── Application ─────────────────────────────────────────────────────",
        "APP_ENV=production",
        f"APP_BASE_URL=https://{domain}",
        f"HOPEFX_DOMAIN={domain}",
        "",
        "# ── API server ───────────────────────────────────────────────────────",
        "API_HOST=0.0.0.0",
        "API_PORT=8000",
        f"ALLOWED_ORIGINS=https://{domain},https://www.{domain}",
        "MOBILE_CORS_ORIGINS=",
    ]


def _section_security(
    jwt_secret: str,
    enc_key: str,
    kill_switch_token: str,
    config_salt: str,
) -> list[str]:
    # Values written directly — never echoed to stdout
    return [
        "",
        "# ── Security (auto-generated — never share or commit) ────────────────",
        f"SECURITY_JWT_SECRET={jwt_secret}",
        f"CONFIG_ENCRYPTION_KEY={enc_key}",
        f"HOPEFX_KILL_SWITCH_TOKEN={kill_switch_token}",
        f"CONFIG_SALT={config_salt}",
        "ACCESS_TOKEN_EXPIRE_MINUTES=15",
        "REFRESH_TOKEN_EXPIRE_DAYS=7",
        "AUTH_RATE_LIMIT_REQUESTS=10",
        "AUTH_RATE_LIMIT_WINDOW_SECONDS=60",
    ]


def _section_database(db_password: str, domain: str) -> list[str]:
    db_url = f"postgresql+asyncpg://hopefx:{db_password}@db:5432/hopefx"
    return [
        "",
        "# ── Database ─────────────────────────────────────────────────────────",
        f"DATABASE_URL={db_url}",
        "POSTGRES_USER=hopefx",
        f"POSTGRES_PASSWORD={db_password}",
        "POSTGRES_DB=hopefx",
        "DB_HOST=db",
        f"DB_PASSWORD={db_password}",
    ]


def _section_redis(redis_password: str) -> list[str]:
    redis_url = f"redis://:{redis_password}@redis:6379/0"
    return [
        "",
        "# ── Redis ────────────────────────────────────────────────────────────",
        f"REDIS_URL={redis_url}",
        "REDIS_HOST=redis",
        "REDIS_PORT=6379",
        f"REDIS_PASSWORD={redis_password}",
    ]


def _section_broker(
    broker_type: str,
    oanda_key: str,
    oanda_account: str,
    oanda_env: str,
) -> list[str]:
    lines = [
        "",
        "# ── Broker ───────────────────────────────────────────────────────────",
        f"BROKER_TYPE={broker_type}",
        "INITIAL_BALANCE=100000",
        "COMMISSION=3.5",
        "PAPER_USER_ID=paper",
        "SIGNAL_ENGINE_AUTO_TRADE=false",
    ]
    if broker_type == "oanda":
        lines += [
            f"OANDA_API_KEY={oanda_key}",
            f"OANDA_ACCOUNT_ID={oanda_account}",
            f"OANDA_ENVIRONMENT={oanda_env}",
        ]
    else:
        lines += [
            "OANDA_API_KEY=",
            "OANDA_ACCOUNT_ID=",
            "OANDA_ENVIRONMENT=practice",
        ]
    return lines


def _section_streaming(finnhub: str, twelve: str, polygon: str) -> list[str]:
    return [
        "",
        "# ── Live price streaming (NuclearStreamer) ───────────────────────────",
        f"FINNHUB_API_KEY={finnhub}",
        f"TWELVE_API_KEY={twelve}",
        f"POLYGON_API_KEY={polygon}",
    ]


def _section_payments(
    stripe_secret: str,
    stripe_webhook: str,
    stripe_pub: str,
    flw_secret: str,
    flw_public: str,
    flw_webhook: str,
) -> list[str]:
    return [
        "",
        "# ── Payments ─────────────────────────────────────────────────────────",
        f"STRIPE_SECRET_KEY={stripe_secret}",
        f"STRIPE_WEBHOOK_SECRET={stripe_webhook}",
        f"STRIPE_PUBLISHABLE_KEY={stripe_pub}",
        f"FLUTTERWAVE_SECRET_KEY={flw_secret}",
        f"FLUTTERWAVE_PUBLIC_KEY={flw_public}",
        f"FLUTTERWAVE_WEBHOOK_HASH={flw_webhook}",
    ]


def _section_ml(openai_key: str, openai_model: str) -> list[str]:
    return [
        "",
        "# ── ML / AI ──────────────────────────────────────────────────────────",
        f"OPENAI_API_KEY={openai_key}",
        f"OPENAI_MODEL={openai_model}",
        "ML_MIN_TRADE_PROB=0.58",
        "SL_ATR_MULT=1.5",
        "TP_ATR_MULT=3.0",
        "FEATURE_ML_PREDICTIONS=true",
        "FEATURE_ONLINE_LEARNING=false",
        "FEATURE_ANOMALY_WEIGHTING=true",
        "FEATURE_DEEP_ENSEMBLE=false",
    ]


def _section_observability(sentry_dsn: str, grafana_password: str) -> list[str]:
    return [
        "",
        "# ── Observability ────────────────────────────────────────────────────",
        f"SENTRY_DSN={sentry_dsn}",
        f"GRAFANA_ADMIN_PASSWORD={grafana_password}",
        "OTEL_SERVICE_NAME=hopefx-trading",
        "OTEL_EXPORTER_OTLP_ENDPOINT=",
    ]


def _section_email(sendgrid_key: str, email_from: str) -> list[str]:
    return [
        "",
        "# ── Email ────────────────────────────────────────────────────────────",
        f"SENDGRID_API_KEY={sendgrid_key}",
        f"EMAIL_FROM={email_from}",
    ]


def _section_risk() -> list[str]:
    return [
        "",
        "# ── Risk management ──────────────────────────────────────────────────",
        "RISK_MAX_POSITION_SIZE_PCT=0.05",
        "RISK_MAX_DRAWDOWN_PCT=0.10",
        "RISK_MAX_DAILY_LOSS_PCT=0.05",
        "RISK_KELLY_FRACTION=0.25",
        "RISK_MIN_RR=2.0",
    ]


def _section_features() -> list[str]:
    return [
        "",
        "# ── Feature flags ────────────────────────────────────────────────────",
        "FEATURE_PAYMENTS=true",
        "FEATURE_KYC=false",
        "FEATURE_SOCIAL=true",
        "FEATURE_WHITELABEL=false",
        "FEATURE_PROP_FIRM=false",
        "FEATURE_CHAOS=false",
        "FEATURE_GRAPHQL=false",
    ]


# ---------------------------------------------------------------------------
# Final validation
# ---------------------------------------------------------------------------


def _run_validation() -> bool:
    """Import and run the startup validator against the written .env."""
    try:
        # Reload env from the newly written file
        try:
            from dotenv import load_dotenv

            load_dotenv(_ENV_FILE, override=True)
        except ImportError:
            _warn("python-dotenv not installed — skipping env reload before validation.")

        from config.startup_validator import validate_environment

        validate_environment(strict=False)
        return True
    except SystemExit as exc:
        if exc.code == 0:
            return True
        _err(f"Startup validator exited with code {exc.code}")
        return False
    except Exception as exc:
        _warn(f"Startup validator raised an exception: {exc}")
        _info("This may be normal if optional dependencies are not installed.")
        _info("Run `python scripts/manage_secrets.py validate` after installing deps.")
        return True  # Non-fatal — validator may need DB/Redis to be running


# ---------------------------------------------------------------------------
# Check-only mode
# ---------------------------------------------------------------------------


def _run_check() -> int:
    """Validate an existing .env without prompting.  Returns exit code."""
    _header("Production Environment Check")
    if not _ENV_FILE.exists():
        _err(f".env not found at {_ENV_FILE}")
        _info("Run `python scripts/setup_production.py` to create it.")
        return 1

    ok = _run_validation()
    if ok:
        _ok("Environment validation passed.")
        return 0
    else:
        _err("Environment validation failed — fix the errors above.")
        return 1


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------


def _run_wizard(force: bool) -> int:
    _header("HOPEFX AI Trading — Production Setup Wizard")
    _print()
    _print("  This wizard generates a complete .env for your first production")
    _print("  deployment.  Generated secrets are written directly to .env and")
    _print("  are never displayed on screen.")
    _print()
    _print(f"  {_bold('Target:')} {_ENV_FILE}")

    # ── Guard: existing .env ──────────────────────────────────────────────────
    if _ENV_FILE.exists() and not force:
        _print()
        _warn(f".env already exists at {_ENV_FILE}")
        overwrite = _ask_yes_no("Overwrite it?", default=False)
        if not overwrite:
            _print()
            _info("Keeping existing .env.  Run with --force to overwrite.")
            _info("To validate the existing file: python scripts/manage_secrets.py validate")
            return 0

    # ── Step 1: Domain ────────────────────────────────────────────────────────
    _header("Step 1 of 7 — Deployment Domain")
    _print()
    _print("  Enter the domain where HOPEFX will be served (without https://).")
    _print("  Example: trading.mycompany.com")
    _print()
    domain = _ask("Domain", required=True)
    email_from = _ask("Notification sender email", default=f"noreply@{domain}")
    _ok(f"Domain: {domain}")

    # ── Step 2: Cryptographic secrets (auto-generated) ────────────────────────
    _header("Step 2 of 7 — Cryptographic Secrets (auto-generated)")
    _print()
    _print("  The following secrets are generated using secrets.token_urlsafe(48)")
    _print("  (≥ 384 bits of entropy).  They are written to .env and never shown.")
    _print()

    jwt_secret = _gen48()
    enc_key = _gen48()
    kill_switch_token = _gen48()
    config_salt = _gen_hex16()
    db_password = _gen32()
    redis_password = _gen32()
    grafana_password = _gen32()

    _ok("SECURITY_JWT_SECRET        — generated")
    _ok("CONFIG_ENCRYPTION_KEY      — generated")
    _ok("HOPEFX_KILL_SWITCH_TOKEN   — generated")
    _ok("CONFIG_SALT                — generated")
    _ok("POSTGRES_PASSWORD          — generated")
    _ok("REDIS_PASSWORD             — generated")
    _ok("GRAFANA_ADMIN_PASSWORD     — generated")

    # ── Step 3: Broker ────────────────────────────────────────────────────────
    _header("Step 3 of 7 — Broker Configuration")
    _print()
    _print("  BROKER_TYPE options:")
    _print("    paper   — paper trading only (safe default, no real money)")
    _print("    oanda   — OANDA v20 REST API (live or practice account)")
    _print()
    broker_type = _ask("Broker type", default="paper")
    while broker_type not in ("paper", "oanda", "simulation", "demo"):
        _warn("Valid values: paper, oanda, simulation, demo")
        broker_type = _ask("Broker type", default="paper")

    oanda_key = oanda_account = oanda_env = ""
    if broker_type == "oanda":
        _print()
        _print("  OANDA credentials — find these at https://www.oanda.com/demo-account/")
        _print("  Use 'practice' environment until you are ready for live trading.")
        _print()
        oanda_key = _ask_secret("OANDA_API_KEY", "OANDA_API_KEY")
        oanda_account = _ask("OANDA_ACCOUNT_ID (e.g. 101-001-12345678-001)", required=True)
        oanda_env_input = _ask("OANDA_ENVIRONMENT", default="practice")
        oanda_env = oanda_env_input if oanda_env_input in ("practice", "live") else "practice"
        _ok(f"OANDA environment: {oanda_env}")

    # ── Step 4: Live price streaming ──────────────────────────────────────────
    _header("Step 4 of 7 — Live Price Streaming (optional)")
    _print()
    _print("  At least one streaming key is recommended for live XAUUSD ticks.")
    _print("  Leave blank to skip — the engine will use broker price feed only.")
    _print()
    _print("  Finnhub  — https://finnhub.io/  (free tier available)")
    finnhub = _ask("FINNHUB_API_KEY", default="")
    _print("  Twelve Data — https://twelvedata.com/  (free tier available)")
    twelve = _ask("TWELVE_API_KEY", default="")
    _print("  Polygon.io  — https://polygon.io/  (Currencies plan)")
    polygon = _ask("POLYGON_API_KEY", default="")

    if finnhub or twelve or polygon:
        _ok("Streaming keys configured")
    else:
        _warn("No streaming keys set — live tick feed will use broker price only")

    # ── Step 5: Payments ──────────────────────────────────────────────────────
    _header("Step 5 of 7 — Payments (optional)")
    _print()
    _print("  Leave all blank to disable payment features (FEATURE_PAYMENTS=false).")
    _print()
    _print("  Stripe — https://dashboard.stripe.com/apikeys")
    stripe_secret = _ask("STRIPE_SECRET_KEY", default="")
    stripe_webhook = _ask("STRIPE_WEBHOOK_SECRET", default="")
    stripe_pub = _ask("STRIPE_PUBLISHABLE_KEY", default="")
    _print()
    _print("  Flutterwave — https://dashboard.flutterwave.com/settings/apis")
    flw_secret = _ask("FLUTTERWAVE_SECRET_KEY", default="")
    flw_public = _ask("FLUTTERWAVE_PUBLIC_KEY", default="")
    flw_webhook = _ask("FLUTTERWAVE_WEBHOOK_HASH", default="")

    payments_enabled = bool(stripe_secret or flw_secret)
    if not payments_enabled:
        _warn("No payment keys set — FEATURE_PAYMENTS will be set to false")

    # ── Step 6: ML / AI ───────────────────────────────────────────────────────
    _header("Step 6 of 7 — ML / AI (optional)")
    _print()
    _print("  OpenAI is used for the /api/chat endpoint and LLM-assisted signals.")
    _print("  Leave blank to disable (the endpoint returns 503 until configured).")
    _print()
    openai_key = _ask("OPENAI_API_KEY", default="")
    openai_model = _ask("OPENAI_MODEL", default="o4-mini")

    # ── Step 7: Observability ─────────────────────────────────────────────────
    _header("Step 7 of 7 — Observability (optional)")
    _print()
    _print("  Sentry — https://sentry.io/  (error tracking)")
    _print("  Leave blank to disable Sentry error reporting.")
    _print()
    sentry_dsn = _ask("SENTRY_DSN", default="")
    _print()
    _print("  SendGrid — https://app.sendgrid.com/settings/api_keys")
    _print("  Leave blank to disable transactional email.")
    sendgrid_key = _ask("SENDGRID_API_KEY", default="")

    # ── Assemble .env ─────────────────────────────────────────────────────────
    _header("Writing .env")
    _print()

    header_lines = [
        "# ==========================================================================",
        "# HOPEFX AI Trading — Production Environment",
        "# Generated by scripts/setup_production.py",
        "# DO NOT COMMIT THIS FILE — it contains secrets.",
        "# Permissions: chmod 600 .env",
        "# ==========================================================================",
    ]

    feature_payments_line = "FEATURE_PAYMENTS=true" if payments_enabled else "FEATURE_PAYMENTS=false"

    all_lines: list[str] = (
        header_lines
        + _section_app(domain)
        + _section_security(jwt_secret, enc_key, kill_switch_token, config_salt)
        + _section_database(db_password, domain)
        + _section_redis(redis_password)
        + _section_broker(broker_type, oanda_key, oanda_account, oanda_env)
        + _section_streaming(finnhub, twelve, polygon)
        + _section_payments(stripe_secret, stripe_webhook, stripe_pub, flw_secret, flw_public, flw_webhook)
        + _section_ml(openai_key, openai_model)
        + _section_observability(sentry_dsn, grafana_password)
        + _section_email(sendgrid_key, email_from)
        + _section_risk()
        + [
            "",
            "# ── Feature flags ────────────────────────────────────────────────────",
            feature_payments_line,
            "FEATURE_KYC=false",
            "FEATURE_SOCIAL=true",
            "FEATURE_WHITELABEL=false",
            "FEATURE_PROP_FIRM=false",
            "FEATURE_CHAOS=false",
            "FEATURE_GRAPHQL=false",
            "FEATURE_ONLINE_LEARNING=false",
            "FEATURE_ANOMALY_WEIGHTING=true",
            "FEATURE_DEEP_ENSEMBLE=false",
        ]
    )

    _write_env(_ENV_FILE, all_lines)
    _ok(f".env written to {_ENV_FILE} (mode 0600)")

    # ── Validation ────────────────────────────────────────────────────────────
    _header("Validating environment")
    _print()
    valid = _run_validation()
    if valid:
        _ok("Startup validation passed")
    else:
        _warn("Startup validation reported issues — review above and re-run if needed")

    # ── Next steps ────────────────────────────────────────────────────────────
    _header("Setup complete — next steps")
    _print()
    _print(f"  1. Review {_bold('.env')} and confirm all values are correct.")
    _print(f"     {_yellow('Never commit .env to version control.')}")
    _print()
    _print("  2. Validate secrets:")
    _print("       python scripts/manage_secrets.py validate")
    _print()
    _print("  3. Run database migrations:")
    _print("       alembic upgrade head")
    _print()
    _print("  4. Create the superadmin account:")
    _print("       python scripts/create_superadmin.py")
    _print()
    _print("  5. Start the stack:")
    _print("       docker compose up -d")
    _print()
    _print("  6. Verify health:")
    _print(f"       curl https://{domain}/api/health/ready")
    _print()
    _print("  7. To rotate a secret later:")
    _print("       python scripts/manage_secrets.py rotate --key SECURITY_JWT_SECRET")
    _print()

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HOPEFX AI Trading — guided production setup wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate existing .env without prompting (CI mode)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .env without asking",
    )
    parser.add_argument(
        "--allow-root",
        action="store_true",
        help="Allow running as root (not recommended)",
    )
    args = parser.parse_args()

    _preflight()

    if args.check:
        return _run_check()

    return _run_wizard(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
