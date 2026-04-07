# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
deployment_guide.py
===================
Pre-flight deployment checker.

Validates that all required environment variables, dependencies, and runtime
conditions are satisfied before starting the application in production.

Usage
-----
    python deployment_guide.py            # check current environment
    python deployment_guide.py --strict   # exit 1 on any warning

This script does NOT start the application. Use deploy.sh for VPS deployment
or docker compose up for containerised deployment.
"""

from __future__ import annotations

import argparse
import importlib
import os
import pathlib
import socket
import subprocess  # nosec B404 - list-form calls with fixed tool names; no shell=True, no user input
import sys
import urllib.parse
from pathlib import Path
import logging
logger = logging.getLogger(__name__)


# ── result collectors ─────────────────────────────────────────────────────────
_errors: list[str] = []
_warnings: list[str] = []
_ok: list[str] = []


def _err(msg: str) -> None:
    _errors.append(msg)
    logger.error(f"  [ERROR]   {msg}")


def _warn(msg: str) -> None:
    _warnings.append(msg)
    logger.warning(f"  [WARN]    {msg}")


def _good(msg: str) -> None:
    _ok.append(msg)
    logger.info(f"  [OK]      {msg}")


# ── checks ────────────────────────────────────────────────────────────────────


def check_python_version() -> None:
    logger.info("\n── Python version ───────────────────────────────────────────")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        _err(f"Python {major}.{minor} detected — 3.10+ required")
    elif (major, minor) > (3, 11):
        _warn(
            f"Python {major}.{minor} detected — Dockerfile uses 3.10. Serialised ML models (.pkl) may be incompatible."
        )
    else:
        _good(f"Python {major}.{minor}")


def check_required_env_vars() -> None:
    logger.info("\n── Required environment variables ───────────────────────────")
    required = [
        ("SECURITY_JWT_SECRET", "JWT signing secret (min 64 chars)"),
        ("CONFIG_ENCRYPTION_KEY", "Config encryption key (min 48 chars)"),
        ("HOPEFX_KILL_SWITCH_TOKEN", "Kill-switch HMAC token"),
        ("DATABASE_URL", "SQLAlchemy DB URL"),
        ("OANDA_API_KEY", "OANDA v20 API key"),
        ("OANDA_ACCOUNT_ID", "OANDA account ID"),
    ]
    for key, desc in required:
        val = os.environ.get(key, "")
        if not val:
            _err(f"{key} not set — {desc}")
        elif "CHANGE_ME" in val or "your_" in val.lower():
            _err(f"{key} still contains placeholder value")
        else:
            _good(f"{key} set")


def check_optional_env_vars() -> None:
    logger.info("\n── Optional environment variables ───────────────────────────")
    optional = [
        ("TELEGRAM_BOT_TOKEN", "Telegram alerts"),
        ("TELEGRAM_CHAT_ID", "Telegram chat ID"),
        ("SENTRY_DSN", "Sentry error tracking"),
        ("REDIS_URL", "Redis pub/sub URL"),
        ("SMTP_HOST", "Email delivery"),
    ]
    for key, desc in optional:
        val = os.environ.get(key, "")
        if not val:
            _warn(f"{key} not set — {desc} will be disabled")
        else:
            _good(f"{key} set")


def check_kill_switch() -> None:
    logger.info("\n── Kill switch ───────────────────────────────────────────────")
    flag = pathlib.Path("kill_switch.flag")
    if flag.exists():
        content = flag.read_text(encoding="utf-8").strip()
        _err(
            f"kill_switch.flag exists — trading is halted.\n"
            f"         Content: {content}\n"
            f"         Delete the file to resume: rm kill_switch.flag"
        )
    else:
        _good("kill_switch.flag absent — trading not halted")


def check_ml_model() -> None:
    logger.info("\n── ML model ──────────────────────────────────────────────────")
    model_path = pathlib.Path("ml/saved_models/advanced_oos.pkl")
    meta_path = pathlib.Path("ml/saved_models/advanced_oos_meta.json")

    if not model_path.exists():
        _err(f"{model_path} not found — run ml/run_training.py first")
        return

    # Attempt to load the model to catch version mismatches early.
    # Use joblib (the serialisation format used by train_advanced.py) with a
    # pickle fallback so the check works regardless of how the model was saved.
    try:
        try:
            import joblib

            model = joblib.load(model_path)  # nosec B301 - model_path is hardcoded to ml/saved_models
        except Exception:
            import pickle  # nosec B403

            with Path(model_path).open("rb") as fh:
                model = pickle.load(fh)  # nosec B301 - joblib failed; legacy pickle fallback for deployment check only
        _good(f"advanced_oos.pkl loads cleanly ({type(model).__name__})")
    except Exception as exc:
        _err(
            f"advanced_oos.pkl failed to load: {exc}\n"
            "         Likely a Python version mismatch. Retrain on Python 3.10:\n"
            "           docker compose run --rm app python ml/train_advanced.py"
        )

    if meta_path.exists():
        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        oos_acc = meta.get("oos_accuracy", 0)
        sharpe = meta.get("sharpe_gate", {}).get("sharpe", 0)
        _good(f"Model meta: OOS accuracy={oos_acc:.1%}  Sharpe={sharpe:.2f}")
    else:
        _warn(f"{meta_path} not found — cannot verify model metrics")


def check_dependencies() -> None:
    logger.info("\n── Python dependencies ───────────────────────────────────────")
    critical = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "sqlalchemy",
        "xgboost",
        "sklearn",
        "pandas",
        "numpy",
        "redis",
        "aiohttp",
        "jwt",
        "passlib",
        "structlog",
        "prometheus_client",
    ]
    for pkg in critical:
        try:
            importlib.import_module(pkg)
            _good(f"{pkg} importable")
        except ImportError:
            _err(f"{pkg} not installed — run: pip install -r requirements.txt")


def check_alembic() -> None:
    logger.info("\n── Database migrations ───────────────────────────────────────")
    if not pathlib.Path("alembic.ini").exists():
        _warn("alembic.ini not found — migrations cannot run")
        return
    try:
        result = subprocess.run(  # nosec B603 B607 - list-form calls with fixed tool names; no shell=True, no user input
            ["python", "-m", "alembic", "current"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            _good(f"Alembic current: {result.stdout.strip()[:80]}")
        else:
            _warn(f"Alembic check failed: {result.stderr.strip()[:120]}")
    except Exception as exc:
        _warn(f"Could not run alembic current: {exc}")


def check_docker() -> None:
    logger.info("\n── Docker ────────────────────────────────────────────────────")
    for cmd in (["docker", "--version"], ["docker", "compose", "version"]):
        try:
            out = subprocess.check_output(  # nosec B603 B607 - list-form calls with fixed tool names; no shell=True, no user input
                cmd, stderr=subprocess.DEVNULL, text=True
            ).strip()
            _good(out[:60])
        except Exception:
            _warn(f"{' '.join(cmd)} not available")


def check_database_connectivity() -> None:
    """Attempt a real TCP connection to the database host:port from DATABASE_URL."""
    logger.info("\n── Database connectivity ─────────────────────────────────────")
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        _warn("DATABASE_URL not set — skipping connectivity check")
        return

    try:
        parsed = urllib.parse.urlparse(db_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=5):
            _good(f"TCP connection to {host}:{port} succeeded")
    except OSError as exc:
        _err(
            f"Cannot reach database at {host}:{port} — {exc}\n"
            "         Verify DATABASE_URL and that the DB server is running."
        )
    except Exception as exc:
        _warn(f"DATABASE_URL parse error: {exc}")


def check_redis_connectivity() -> None:
    """Attempt a Redis PING via the redis-py client or raw TCP fallback."""
    logger.info("\n── Redis connectivity ────────────────────────────────────────")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Try redis-py first (already a required dependency)
    try:
        import redis as _redis

        client = _redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
        response = client.ping()
        if response:
            _good(f"Redis PING → PONG  ({redis_url.split('@')[-1]})")
        else:
            _warn("Redis PING returned falsy response")
        client.close()
        return
    except ImportError:
        ...  # nosec B110
    except Exception as exc:
        _err(
            f"Redis unreachable at {redis_url.split('@')[-1]} — {exc}\n"
            "         Verify REDIS_URL and that Redis is running."
        )
        return

    # Fallback: raw TCP to host:port
    try:
        parsed = urllib.parse.urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=5):
            _good(f"TCP connection to Redis {host}:{port} succeeded (redis-py not installed)")
    except OSError as exc:
        _err(f"Cannot reach Redis at {host}:{port} — {exc}")


def check_port_availability() -> None:
    """Verify that the API port (default 8000) is not already in use."""
    logger.info("\n── Port availability ─────────────────────────────────────────")
    api_port = int(os.environ.get("API_PORT", "8000"))
    metrics_port = int(os.environ.get("METRICS_PORT", "9090"))

    for port, label in ((api_port, "API"), (metrics_port, "Metrics/Prometheus")):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            # Bind to loopback only — sufficient to detect port conflicts since
            # a port in use on 127.0.0.1 is unavailable system-wide.
            # The socket is closed immediately in the finally block.
            sock.bind(("127.0.0.1", port))
            _good(f"Port {port} ({label}) is free")
        except OSError:
            _err(
                f"Port {port} ({label}) is already in use.\n"
                f"         Find the process: lsof -i :{port} | grep LISTEN\n"
                f"         Or change API_PORT / METRICS_PORT in your .env"
            )
        finally:
            sock.close()


def check_disk_space() -> None:
    """Warn if free disk space is below the recommended minimum (20 GB)."""
    logger.info("\n── Disk space ────────────────────────────────────────────────")
    try:
        _stat = pathlib.Path().stat()
        usage = pathlib.Path().resolve()
        import shutil

        total, _, free = shutil.disk_usage(usage)
        free_gb = free / (1024**3)
        total_gb = total / (1024**3)
        if free_gb < 5:
            _err(f"Only {free_gb:.1f} GB free of {total_gb:.1f} GB — minimum 20 GB recommended")
        elif free_gb < 20:
            _warn(f"{free_gb:.1f} GB free of {total_gb:.1f} GB — 20 GB recommended for ML training")
        else:
            _good(f"{free_gb:.1f} GB free of {total_gb:.1f} GB")
    except Exception as exc:
        _warn(f"Could not check disk space: {exc}")


def check_env_file() -> None:
    """Verify .env file exists and contains no unresolved placeholder values."""
    logger.info("\n── Environment file ──────────────────────────────────────────")
    env_path = pathlib.Path(".env")
    if not env_path.exists():
        _warn(
            ".env file not found — environment variables must be set externally.\n"
            "         Copy .env.example to .env and fill in real values."
        )
        return

    _good(".env file present")

    # Scan for unresolved placeholders
    placeholders = []
    with Path(env_path).open(encoding="utf-8") as fh:
        for lineno, _line in enumerate(fh, 1):
            line = _line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if any(marker in val for marker in ("CHANGE_ME", "CHANGEME", "your_", "<", "TODO")):
                placeholders.append(f"  line {lineno}: {key.strip()}")

    if placeholders:
        _err(f".env contains {len(placeholders)} unresolved placeholder(s):\n" + "\n".join(placeholders))
    else:
        _good(".env has no placeholder values")


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="HOPEFX pre-flight deployment checker")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any warning (not just errors)")
    args = parser.parse_args()

    # Load .env if present
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:
        ...  # nosec B110

    logger.info("=" * 60)
    logger.info("  HOPEFX AI Trading — Pre-flight Deployment Check")
    logger.info("=" * 60)

    check_python_version()
    check_env_file()
    check_required_env_vars()
    check_optional_env_vars()
    check_kill_switch()
    check_disk_space()
    check_port_availability()
    check_database_connectivity()
    check_redis_connectivity()
    check_ml_model()
    check_dependencies()
    check_alembic()
    check_docker()

    logger.info("\n" + "=" * 60)
    logger.error(f"  Results: {len(_ok)} OK  |  {len(_warnings)} warnings  |  {len(_errors)} errors")
    logger.info("=" * 60)

    if _errors:
        logger.error("\nFix all errors before deploying to production.")
        return 1
    if args.strict and _warnings:
        logger.error("\n--strict mode: warnings treated as errors.")
        return 1
    if _warnings:
        logger.warning("\nWarnings present — review before going live.")
    else:
        logger.info("\nAll checks passed. Safe to deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
