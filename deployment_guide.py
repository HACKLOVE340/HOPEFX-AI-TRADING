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
import subprocess
import sys
from typing import List, Tuple

# ── result collectors ─────────────────────────────────────────────────────────
_errors:   List[str] = []
_warnings: List[str] = []
_ok:       List[str] = []


def _err(msg: str) -> None:
    _errors.append(msg)
    print(f"  [ERROR]   {msg}")


def _warn(msg: str) -> None:
    _warnings.append(msg)
    print(f"  [WARN]    {msg}")


def _good(msg: str) -> None:
    _ok.append(msg)
    print(f"  [OK]      {msg}")


# ── checks ────────────────────────────────────────────────────────────────────

def check_python_version() -> None:
    print("\n── Python version ───────────────────────────────────────────")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        _err(f"Python {major}.{minor} detected — 3.10+ required")
    elif (major, minor) > (3, 11):
        _warn(
            f"Python {major}.{minor} detected — Dockerfile uses 3.10. "
            "Serialised ML models (.pkl) may be incompatible."
        )
    else:
        _good(f"Python {major}.{minor}")


def check_required_env_vars() -> None:
    print("\n── Required environment variables ───────────────────────────")
    required = [
        ("SECURITY_JWT_SECRET",    "JWT signing secret (min 64 chars)"),
        ("CONFIG_ENCRYPTION_KEY",  "Config encryption key (min 48 chars)"),
        ("HOPEFX_KILL_SWITCH_TOKEN", "Kill-switch HMAC token"),
        ("DATABASE_URL",           "SQLAlchemy DB URL"),
        ("OANDA_API_KEY",          "OANDA v20 API key"),
        ("OANDA_ACCOUNT_ID",       "OANDA account ID"),
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
    print("\n── Optional environment variables ───────────────────────────")
    optional = [
        ("TELEGRAM_BOT_TOKEN",  "Telegram alerts"),
        ("TELEGRAM_CHAT_ID",    "Telegram chat ID"),
        ("SENTRY_DSN",          "Sentry error tracking"),
        ("REDIS_URL",           "Redis pub/sub URL"),
        ("SMTP_HOST",           "Email delivery"),
    ]
    for key, desc in optional:
        val = os.environ.get(key, "")
        if not val:
            _warn(f"{key} not set — {desc} will be disabled")
        else:
            _good(f"{key} set")


def check_kill_switch() -> None:
    print("\n── Kill switch ───────────────────────────────────────────────")
    flag = pathlib.Path("kill_switch.flag")
    if flag.exists():
        content = flag.read_text().strip()
        _err(
            f"kill_switch.flag exists — trading is halted.\n"
            f"         Content: {content}\n"
            f"         Delete the file to resume: rm kill_switch.flag"
        )
    else:
        _good("kill_switch.flag absent — trading not halted")


def check_ml_model() -> None:
    print("\n── ML model ──────────────────────────────────────────────────")
    model_path = pathlib.Path("ml/saved_models/advanced_oos.pkl")
    meta_path  = pathlib.Path("ml/saved_models/advanced_oos_meta.json")

    if not model_path.exists():
        _err(f"{model_path} not found — run ml/run_training.py first")
        return

    # Attempt to load the model to catch pickle version mismatches early
    try:
        import pickle
        with open(model_path, "rb") as fh:
            model = pickle.load(fh)
        _good(f"advanced_oos.pkl loads cleanly ({type(model).__name__})")
    except Exception as exc:
        _err(
            f"advanced_oos.pkl failed to load: {exc}\n"
            "         Likely a Python version mismatch. Retrain on Python 3.10."
        )

    if meta_path.exists():
        import json
        meta = json.loads(meta_path.read_text())
        oos_acc = meta.get("oos_accuracy", 0)
        sharpe  = meta.get("sharpe_gate", {}).get("sharpe", 0)
        _good(f"Model meta: OOS accuracy={oos_acc:.1%}  Sharpe={sharpe:.2f}")
    else:
        _warn(f"{meta_path} not found — cannot verify model metrics")


def check_dependencies() -> None:
    print("\n── Python dependencies ───────────────────────────────────────")
    critical = ["fastapi", "uvicorn", "pydantic", "sqlalchemy", "xgboost",
                "sklearn", "pandas", "numpy", "redis", "aiohttp", "jwt",
                "passlib", "structlog", "prometheus_client"]
    for pkg in critical:
        try:
            importlib.import_module(pkg)
            _good(f"{pkg} importable")
        except ImportError:
            _err(f"{pkg} not installed — run: pip install -r requirements.txt")


def check_alembic() -> None:
    print("\n── Database migrations ───────────────────────────────────────")
    if not pathlib.Path("alembic.ini").exists():
        _warn("alembic.ini not found — migrations cannot run")
        return
    try:
        result = subprocess.run(
            ["python", "-m", "alembic", "current"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            _good(f"Alembic current: {result.stdout.strip()[:80]}")
        else:
            _warn(f"Alembic check failed: {result.stderr.strip()[:120]}")
    except Exception as exc:
        _warn(f"Could not run alembic current: {exc}")


def check_docker() -> None:
    print("\n── Docker ────────────────────────────────────────────────────")
    for cmd in (["docker", "--version"], ["docker", "compose", "version"]):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
            _good(out[:60])
        except Exception:
            _warn(f"{' '.join(cmd)} not available")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="HOPEFX pre-flight deployment checker")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 on any warning (not just errors)")
    args = parser.parse_args()

    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass

    print("=" * 60)
    print("  HOPEFX AI Trading — Pre-flight Deployment Check")
    print("=" * 60)

    check_python_version()
    check_required_env_vars()
    check_optional_env_vars()
    check_kill_switch()
    check_ml_model()
    check_dependencies()
    check_alembic()
    check_docker()

    print("\n" + "=" * 60)
    print(f"  Results: {len(_ok)} OK  |  {len(_warnings)} warnings  |  {len(_errors)} errors")
    print("=" * 60)

    if _errors:
        print("\nFix all errors before deploying to production.")
        return 1
    if args.strict and _warnings:
        print("\n--strict mode: warnings treated as errors.")
        return 1
    if _warnings:
        print("\nWarnings present — review before going live.")
    else:
        print("\nAll checks passed. Safe to deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
