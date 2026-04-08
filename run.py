# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
run.py
======
Unified entry point for HOPEFX-AI-TRADING.

Usage
-----
    # Paper trading on OANDA (default)
    python run.py

    # Specific broker + mode
    python run.py --broker oanda --mode paper
    python run.py --broker oanda --mode live
    python run.py --broker ibkr  --mode paper
    python run.py --broker paper --mode paper   # pure in-process simulator

    # API server only (no trading engine)
    python run.py --mode api

    # Backtest
    python run.py --mode backtest

    # Dry-run: validate config + env, print plan, exit
    python run.py --dry-run

Flags
-----
  --broker   oanda | ibkr | binance | alpaca | paper   (default: oanda)
  --mode     paper | live | api | backtest              (default: paper)
  --config   path to prop_firm_mode.json                (default: prop_firm_mode.json)
  --dry-run  validate env + config, print startup plan, exit without trading
  --log      DEBUG | INFO | WARNING                     (default: INFO)

Environment
-----------
All secrets are read from .env (loaded automatically).
OANDA_PRACTICE is forced to "true" when --mode paper is used.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ── logging setup (overridden by --log flag after arg parse) ──────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("run")

# ── supported values ──────────────────────────────────────────────────────────
BROKERS = ("oanda", "mt5", "ibkr", "binance", "alpaca", "paper")
MODES = ("paper", "live", "api", "backtest")


# ─────────────────────────────────────────────────────────────────────────────
# Argument parser
# ─────────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python run.py",
        description="HOPEFX-AI-TRADING — unified entry point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--broker",
        choices=BROKERS,
        default=os.environ.get("DEFAULT_BROKER", "oanda"),
        help="Broker to connect to (default: oanda)",
    )
    p.add_argument(
        "--mode",
        choices=MODES,
        default=os.environ.get("DEFAULT_MODE", "paper"),
        help="Run mode: paper | live | api | backtest (default: paper)",
    )
    p.add_argument(
        "--config",
        default=os.environ.get("PROP_FIRM_CONFIG", "prop_firm_mode.json"),
        help="Path to prop_firm_mode.json (default: prop_firm_mode.json)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate env + config, print startup plan, exit without trading",
    )
    p.add_argument(
        "--symbol",
        default=None,
        help="Primary trading symbol (e.g. XAU_USD, EUR_USD). Overrides OANDA_INSTRUMENTS.",
    )
    p.add_argument(
        "--prop",
        action="store_true",
        default=False,
        help="Enable prop-firm enforcement (sets enabled=true in prop_firm_mode.json)",
    )
    p.add_argument(
        "--log",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Log level (default: INFO)",
    )
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Environment setup
# ─────────────────────────────────────────────────────────────────────────────


def _setup_env(args: argparse.Namespace) -> None:
    """
    Apply broker/mode overrides to the environment before any module imports.

    - paper mode  → forces OANDA_PRACTICE=true
    - live mode   → warns if OANDA_PRACTICE is still true
    - broker flag → sets INGEST_EXCHANGE and DEFAULT_BROKER
    """
    # Force paper flag when mode is paper
    if args.mode == "paper":
        os.environ["OANDA_PRACTICE"] = "true"
        logger.info("Mode=paper — OANDA_PRACTICE forced to true.")

    elif args.mode == "live":
        practice = os.environ.get("OANDA_PRACTICE", "true").lower()
        if practice == "true":
            logger.warning("Mode=live but OANDA_PRACTICE=true — set OANDA_PRACTICE=false in .env to trade real money.")

    # Map broker flag to exchange identifier used by MarketIngest
    broker_exchange_map = {
        "oanda": "oanda",
        "mt5": "mt5",
        "ibkr": "ibkr",
        "binance": "binance",
        "alpaca": "alpaca",
        "paper": "oanda",  # paper broker still uses OANDA for price data
    }
    os.environ["INGEST_EXCHANGE"] = broker_exchange_map.get(args.broker, "oanda")
    os.environ["DEFAULT_BROKER"] = args.broker
    os.environ["BROKER"] = args.broker
    os.environ["TRADING_MODE"] = args.mode

    # Symbol override
    if getattr(args, "symbol", None):
        os.environ["OANDA_INSTRUMENTS"] = args.symbol

    # Prop-firm enforcement
    if getattr(args, "prop", False):
        try:
            cfg_path = Path(args.config)
            cfg = {}
            if cfg_path.exists():
                with Path(cfg_path).open(encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["enabled"] = True
            with Path(cfg_path).open("w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            logger.info("Prop-firm enforcement ENABLED in %s", cfg_path)
        except Exception as exc:
            logger.warning("Could not enable prop-firm mode: %s", exc)

    # Point prop engine at the config file
    os.environ["PROP_FIRM_CONFIG"] = args.config


# ─────────────────────────────────────────────────────────────────────────────
# Config loader
# ─────────────────────────────────────────────────────────────────────────────


def _load_prop_config(path: str) -> dict:
    """Load and return prop_firm_mode.json; return defaults if absent."""
    p = Path(path)
    if not p.exists():
        logger.warning("prop_firm_mode.json not found at %s — using defaults.", path)
        return {}
    with p.open(encoding="utf-8") as fh:
        cfg = json.load(fh)
    logger.info("Loaded prop config from %s", path)
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Dry-run plan printer
# ─────────────────────────────────────────────────────────────────────────────


def _print_plan(args: argparse.Namespace, prop_cfg: dict) -> None:
    """Print the startup plan and env validation result, then exit."""
    from core.env_validator import validate_environment

    logger.info("\n" + "=" * 60)
    logger.info("  HOPEFX-AI-TRADING — Startup Plan (dry-run)")
    logger.info("=" * 60)
    logger.info(f"  Broker  : {args.broker}")
    logger.info(f"  Mode    : {args.mode}")
    logger.info(f"  Config  : {args.config}")
    logger.info(f"  Practice: {os.environ.get('OANDA_PRACTICE', 'true')}")
    logger.info("")

    # Prop firm rules
    logger.info("  Prop Firm Rules:")
    logger.info(f"    daily_dd        : {prop_cfg.get('daily_dd', 0.05) * 100:.1f}%")
    logger.info(f"    max_dd          : {prop_cfg.get('max_dd', 0.10) * 100:.1f}%")
    logger.info(f"    news_blackout   : ±{prop_cfg.get('news_blackout', 5)} min")
    logger.info(f"    weekend_close   : {prop_cfg.get('weekend_close', True)}")
    logger.info(f"    breach_action   : {prop_cfg.get('breach_action', 'pause')}")
    logger.info(f"    max_daily_trades: {prop_cfg.get('max_daily_trades', 20)}")
    logger.info(f"    enabled         : {prop_cfg.get('enabled', True)}")
    logger.info("")

    # Env validation
    result = validate_environment(strict=False)
    logger.info("  Environment:")
    for msg in result.errors:
        logger.error(f"    ❌ {msg}")
    for msg in result.warnings:
        logger.warning(f"    ⚠️  {msg}")
    if not result.errors and not result.warnings:
        logger.info("    ✅ All variables present")
    logger.info("")

    # Pipeline that will start
    pipeline = _get_pipeline(args.mode)
    logger.info("  Pipeline:")
    for step in pipeline:
        logger.info(f"    → {step}")
    logger.info("=" * 60)
    logger.info("")

    if result.errors:
        logger.error("❌ Cannot start — fix errors above.")
        sys.exit(1)
    else:
        logger.info("✅ Dry-run complete — ready to start.")
        sys.exit(0)


def _get_pipeline(mode: str) -> list[str]:
    """Return the list of sub-systems that will start for a given mode."""
    if mode in ("paper", "live"):
        return [
            "EventBus (Redis pub/sub)",
            "FaultGuard (circuit breaker + heartbeat)",
            "NewsCalendarFeed (ForexFactory → Redis)",
            "MarketIngest (XAUUSD ticks via ccxt.pro)",
            "StrategyEngine (ML signal — AdvancedModelPredictor)",
            "Gatekeeper (prop-firm risk checks)",
            "FIXRouter (order execution + OANDA REST fallback)",
        ]
    if mode == "api":
        return ["FastAPI server (uvicorn)", "WebSocket live broadcaster"]
    if mode == "backtest":
        return ["BacktestEngine (historical OHLCV)"]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Mode runners
# ─────────────────────────────────────────────────────────────────────────────


async def _run_trading(args: argparse.Namespace) -> None:
    """
    Start the full trading pipeline via HopeFXEngine.

    HopeFXEngine wires:
      HOPEFXBrain (ML + regime + strategy) → RiskManager → Broker
      TradeLogger (CSV + Prometheus) → HeartbeatService (Telegram)

    Falls back to core.main_loop.MainLoop if HopeFXEngine is unavailable.
    """
    logger.info(
        "Starting trading pipeline — broker=%s mode=%s config=%s",
        args.broker,
        args.mode,
        args.config,
    )

    try:
        import signal as _signal

        from hopefx_engine import HopeFXEngine

        engine = HopeFXEngine()
        loop = asyncio.get_running_loop()
        for sig in (_signal.SIGINT, _signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.stop()))
        await engine.start()

    except ImportError:
        # Fallback to legacy MainLoop
        logger.warning("HopeFXEngine not available — falling back to core.main_loop")
        from core.main_loop import MainLoop

        ml = MainLoop()
        await ml.run()


async def _run_api() -> None:
    """Start the FastAPI server with uvicorn."""
    try:
        import uvicorn

        from app import app as fastapi_app

        config = uvicorn.Config(
            fastapi_app,
            host=os.environ.get("API_HOST", "0.0.0.0"),  # nosec B104 - host read from API_HOST env var
            port=int(os.environ.get("API_PORT", "8000")),
            log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()
    except ImportError:
        logger.critical("uvicorn not installed — run: pip install uvicorn")
        sys.exit(1)


async def _run_backtest(args: argparse.Namespace) -> None:
    """Run the backtest engine."""
    try:
        from backtesting.engine import BacktestEngine

        engine = BacktestEngine()
        from datetime import datetime

        start_dt = datetime.fromisoformat(args.start_date) if hasattr(args, "start_date") and args.start_date else None
        end_dt = datetime.fromisoformat(args.end_date) if hasattr(args, "end_date") and args.end_date else None
        engine.run(start_date=start_dt, end_date=end_dt)
    except ImportError:
        # Fallback to the existing backtest runner
        import subprocess  # nosec B404 - list-form call with sys.executable; no shell=True, no user input

        result = subprocess.run(  # nosec B603 B607 - list-form call with sys.executable; no shell=True, no user input
            [sys.executable, "backtest_runner.py", "--config", args.config],
            check=False,
        )
        sys.exit(result.returncode)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def _main(args: argparse.Namespace) -> None:
    if args.mode in ("paper", "live"):
        await _run_trading(args)
    elif args.mode == "api":
        await _run_api()
    elif args.mode == "backtest":
        await _run_backtest(args)


def main() -> None:
    # Load .env before anything else
    load_dotenv(override=False)

    parser = _build_parser()
    args = parser.parse_args()

    # Apply log level
    logging.getLogger().setLevel(getattr(logging, args.log))

    # Apply env overrides from flags
    _setup_env(args)

    # Load prop config
    prop_cfg = _load_prop_config(args.config)

    # Dry-run: print plan and exit
    if args.dry_run:
        _print_plan(args, prop_cfg)
        return  # unreachable — _print_plan calls sys.exit

    # Safety gate: refuse live mode without explicit confirmation
    if args.mode == "live":
        practice = os.environ.get("OANDA_PRACTICE", "true").lower()
        if practice == "true":
            logger.error(
                "Refusing to start in live mode while OANDA_PRACTICE=true. "
                "Set OANDA_PRACTICE=false in .env to trade real money."
            )
            sys.exit(1)
        confirm = input("\n⚠️  LIVE MODE — real money will be traded.\n   Type 'CONFIRM LIVE' to proceed: ").strip()
        if confirm != "CONFIRM LIVE":
            logger.info("Aborted.")
            sys.exit(0)

    logger.info(
        "HOPEFX-AI-TRADING starting — broker=%s mode=%s",
        args.broker,
        args.mode,
    )
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
