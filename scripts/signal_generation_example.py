# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.

# TA-Lib requires a compiled C library. Install with:
#   pip install TA-Lib  (requires libta-lib-dev on Linux)
try:
    import talib
except ImportError as e:
    raise SystemExit(f"TA-Lib not installed: {e}") from e

import pandas as pd
from sklearn.ensemble import RandomForestClassifier


import logging
logger = logging.getLogger(__name__)

# Load historical data
def load_data(file_path):
    try:
        data = pd.read_csv(file_path)
        return data
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return None


# Generate signals
def generate_signals(data):
    data["EMA9"] = talib.EMA(data["Close"], timeperiod=9)
    data["EMA21"] = talib.EMA(data["Close"], timeperiod=21)
    data["RSI14"] = talib.RSI(data["Close"], timeperiod=14)
    data["upper_band"], data["middle_band"], data["lower_band"] = talib.BBANDS(data["Close"])

    # Generate signals based on conditions
    data["Signal"] = 0
    data.loc[(data["EMA9"] > data["EMA21"]) & (data["RSI14"] < 70), "Signal"] = 1  # Buy
    data.loc[(data["EMA9"] < data["EMA21"]) & (data["RSI14"] > 30), "Signal"] = -1  # Sell
    return data


# Random Forest Model
def train_model(data):
    model = RandomForestClassifier()
    try:
        features = data[["EMA9", "EMA21", "RSI14", "upper_band", "lower_band"]]
        labels = data["Signal"]
        model.fit(features, labels)
    except Exception as e:
        logger.error(f"Error training model: {e}")
        return None
    return model


# Test edge cases
def test_edge_cases(data):
    if data is None or data.empty:
        logger.info("Insufficient data for predictions.")
        return
    if data.isnull().values.any():
        logger.info("NaN values found in data. Handling NaN...")
        data.fillna(method="ffill", inplace=True)
    # Simulating stale ticks is more context-dependent.


# Main function
def main(file_path):
    data = load_data(file_path)
    if data is not None:
        data = generate_signals(data)
        train_model(data)
        test_edge_cases(data)
        logger.info(data["Signal"].value_counts())
        # More validation can be added here


# Example usage
if __name__ == "__main__":
    main("historical_XAUUSD_data.csv")
