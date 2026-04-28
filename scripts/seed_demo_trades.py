#!/usr/bin/env python3
"""
scripts/seed_demo_trades.py
===========================
Inserts realistic demo trades into the SQLite database so that data-dependent
pages (PnL, Performance, Journal, Correlation, TCA, Walk-Forward, Leaderboard)
show meaningful content instead of blank tables on a fresh install.

Usage:
    python scripts/seed_demo_trades.py [--trades N] [--clear]

Options:
    --trades N   Number of closed trades to generate (default: 60)
    --clear      Delete existing demo trades before seeding

The script is idempotent: re-running without --clear adds no duplicates
because each trade has a deterministic client_order_id.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

# ── Bootstrap path and env ────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("DATABASE_URL", "sqlite:///./hopefx.db")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET_KEY", "devsecret")
os.environ.setdefault("REDIS_DISABLED", "true")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_ASYNC", "false")

UTC = timezone.utc

# ── Constants ─────────────────────────────────────────────────────────────────

DEMO_USER_ID = "demo-seed-user"
DEMO_TAG = "demo_seed"  # stored in notes so we can identify/clear seeded rows

SYMBOLS = ["XAU_USD", "EUR_USD", "GBP_USD", "USD_JPY", "BTC_USD", "ETH_USD"]
STRATEGIES = ["trend_following", "mean_reversion", "breakout", "manual"]
EMOTIONS = ["calm", "confident", "anxious", "fearful", "greedy", "neutral"]
SIDES = ["buy", "sell"]

# Realistic price ranges per symbol
PRICE_RANGES: dict[str, tuple[float, float]] = {
    "XAU_USD": (1900.0, 2400.0),
    "EUR_USD": (1.05, 1.15),
    "GBP_USD": (1.20, 1.35),
    "USD_JPY": (130.0, 155.0),
    "BTC_USD": (25000.0, 70000.0),
    "ETH_USD": (1500.0, 4000.0),
}

# Pip/point size per symbol (used to calculate realistic PnL)
PIP_SIZE: dict[str, float] = {
    "XAU_USD": 0.1,
    "EUR_USD": 0.0001,
    "GBP_USD": 0.0001,
    "USD_JPY": 0.01,
    "BTC_USD": 1.0,
    "ETH_USD": 0.1,
}

LOT_SIZE = 0.1  # standard lot fraction


def _rand_price(symbol: str) -> float:
    lo, hi = PRICE_RANGES[symbol]
    return round(random.uniform(lo, hi), 5)


def _exit_price(symbol: str, entry: float, side: str, pips: float) -> float:
    """Calculate exit price given entry, direction, and pip movement."""
    direction = 1 if side == "buy" else -1
    return round(entry + direction * pips * PIP_SIZE[symbol], 5)


def _pnl(symbol: str, entry: float, exit_p: float, side: str, qty: float) -> float:
    direction = 1 if side == "buy" else -1
    raw = direction * (exit_p - entry) * qty / PIP_SIZE[symbol]
    return round(raw * PIP_SIZE[symbol] * 10, 2)  # normalise to USD-ish


def generate_trades(n: int, base_time: datetime) -> list[dict]:
    """Generate n realistic closed trade dicts."""
    rng = random.Random(42)  # deterministic for idempotency
    trades = []

    for i in range(n):
        symbol = rng.choice(SYMBOLS)
        side = rng.choice(SIDES)
        strategy = rng.choice(STRATEGIES)
        emotion = rng.choice(EMOTIONS)

        entry_time = base_time - timedelta(days=rng.randint(1, 90), hours=rng.randint(0, 23))
        hold_hours = rng.uniform(0.5, 48)
        exit_time = entry_time + timedelta(hours=hold_hours)

        entry_price = _rand_price(symbol)
        qty = round(rng.uniform(0.01, 0.5), 3)

        # 55% win rate, realistic pip distribution
        is_win = rng.random() < 0.55
        pips = rng.uniform(5, 80) if is_win else rng.uniform(3, 40)
        exit_p = _exit_price(symbol, entry_price, side, pips if is_win else -pips)
        pnl = _pnl(symbol, entry_price, exit_p, side, qty)

        sl_pips = rng.uniform(20, 60)
        tp_pips = sl_pips * rng.uniform(1.5, 3.0)
        stop_loss = _exit_price(symbol, entry_price, side, -sl_pips)
        take_profit = _exit_price(symbol, entry_price, side, tp_pips)
        rr = round(tp_pips / sl_pips, 2)

        commission = round(qty * rng.uniform(0.5, 2.0), 2)
        total_pnl = round(pnl - commission, 2)

        # Deterministic client_order_id so re-runs don't duplicate
        coid = f"demo-seed-{i:04d}"

        trades.append(
            {
                "trade_id": str(uuid.UUID(int=abs(hash(coid)))),
                "client_order_id": coid,
                "user_id": DEMO_USER_ID,
                "symbol": symbol,
                "side": side,
                "trade_type": "market",
                "entry_time": entry_time,
                "entry_price": entry_price,
                "entry_quantity": qty,
                "size": qty,
                "exit_time": exit_time,
                "exit_price": exit_p,
                "exit_quantity": qty,
                "realized_pnl": pnl,
                "unrealized_pnl": 0.0,
                "commission": commission,
                "total_pnl": total_pnl,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_reward_ratio": rr,
                "strategy": strategy,
                "notes": f"emotion:{emotion} {DEMO_TAG}",
                "status": "closed",
                "is_open": False,
            }
        )

    return trades


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo trades into the database.")
    parser.add_argument("--trades", type=int, default=60, help="Number of trades to seed")
    parser.add_argument("--clear", action="store_true", help="Delete existing demo trades first")
    args = parser.parse_args()

    # Import DB after env is set
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from database.models import Base, Trade, TradeStatus

    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        if args.clear:
            deleted = db.query(Trade).filter(Trade.user_id == DEMO_USER_ID).delete()
            db.commit()
            print(f"Cleared {deleted} existing demo trades.")

        # Check for existing seeds to avoid duplicates
        existing_coids = {
            row[0]
            for row in db.query(Trade.client_order_id)
            .filter(Trade.user_id == DEMO_USER_ID)
            .all()
        }

        base_time = datetime.now(UTC).replace(tzinfo=None)
        trades = generate_trades(args.trades, base_time)

        inserted = 0
        skipped = 0
        for t in trades:
            if t["client_order_id"] in existing_coids:
                skipped += 1
                continue
            db.add(
                Trade(
                    trade_id=t["trade_id"],
                    client_order_id=t["client_order_id"],
                    user_id=t["user_id"],
                    symbol=t["symbol"],
                    side=t["side"],
                    trade_type=t["trade_type"],
                    entry_time=t["entry_time"],
                    entry_price=t["entry_price"],
                    entry_quantity=t["entry_quantity"],
                    size=t["size"],
                    exit_time=t["exit_time"],
                    exit_price=t["exit_price"],
                    exit_quantity=t["exit_quantity"],
                    realized_pnl=t["realized_pnl"],
                    unrealized_pnl=t["unrealized_pnl"],
                    commission=t["commission"],
                    total_pnl=t["total_pnl"],
                    stop_loss=t["stop_loss"],
                    take_profit=t["take_profit"],
                    risk_reward_ratio=t["risk_reward_ratio"],
                    strategy=t["strategy"],
                    notes=t["notes"],
                    status=TradeStatus.CLOSED,
                    is_open=False,
                )
            )
            inserted += 1

        db.commit()
        total_pnl = sum(t["total_pnl"] for t in trades[:inserted + skipped])
        print(f"Seeded {inserted} demo trades ({skipped} already existed).")
        print(f"Symbols: {', '.join(SYMBOLS)}")
        print(f"User ID: {DEMO_USER_ID}")
        print(f"Date range: last 90 days")
        print(f"Net PnL across all seeded trades: ${round(total_pnl, 2)}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
