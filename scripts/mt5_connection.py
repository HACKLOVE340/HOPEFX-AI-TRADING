# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.

# MetaTrader5 is Windows-only. Run this script on a Windows machine with MT5 installed.
try:
    import MetaTrader5 as mt5
except ImportError as e:
    raise SystemExit(f"MetaTrader5 not available (Windows-only): {e}") from e

import logging
import os
import time

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    filename="mt5_connection.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def validate_mt5_installation():
    if not mt5.initialize():
        logger.error("MetaTrader 5 initialization failed")
        return False
    logger.info("MetaTrader 5 initialized successfully")
    return True


def connect_to_account():
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    for attempt in range(5):
        if mt5.login(login, password, server):
            logger.info("Connected to account successfully")
            return True
        logger.warning("Connection attempt %s failed: %s", attempt + 1, mt5.last_error())
        time.sleep(2**attempt)  # Exponential backoff
    logger.error("All connection attempts failed")
    return False


def get_symbol_info(symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        logger.error("Failed to retrieve symbol info for %s: %s", symbol, mt5.last_error())
        return None
    return info


def fetch_last_ticks(symbol, num_ticks):
    ticks = mt5.copy_ticks_from(symbol, mt5.symbol_info_tick(symbol).time, num_ticks, mt5.COPY_TICKS_ALL)
    if ticks is None:
        logger.error("Failed to fetch ticks for %s: %s", symbol, mt5.last_error())
        return []
    return ticks


def print_ticks_info(ticks):
    for tick in ticks:
        bid = tick["bid"]
        ask = tick["ask"]
        spread = ask - bid
        print(f"Bid: {bid}, Ask: {ask}, Spread: {spread}")
        logger.info("Bid: %s, Ask: %s, Spread: %s", bid, ask, spread)


def main():
    if not validate_mt5_installation():
        return

    if not connect_to_account():
        return

    symbol = "XAUUSD"
    symbol_info = get_symbol_info(symbol)
    if symbol_info:
        print(f"Symbol Info - {symbol}: {symbol_info}")

    last_ticks = fetch_last_ticks(symbol, 100)
    print_ticks_info(last_ticks)

    mt5.shutdown()
    logger.info("MT5 shutdown")


if __name__ == "__main__":
    main()
