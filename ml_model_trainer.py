# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import cross_val_score, train_test_split

# pandas_ta requires Python >=3.12; use the `ta` library on Python 3.10.
try:
    import pandas_ta as _pta

    _TA_BACKEND = "pandas_ta"
except ImportError:
    import ta as _ta_lib

    _TA_BACKEND = "ta"


def _ema(close, length=14):
    if _TA_BACKEND == "pandas_ta":
        return _pta.ema(close, length=length)
    return _ta_lib.trend.ema_indicator(close, window=length)


def _rsi(close, length=14):
    if _TA_BACKEND == "pandas_ta":
        return _pta.rsi(close, length=length)
    return _ta_lib.momentum.rsi(close, window=length)


def _macd(close):
    if _TA_BACKEND == "pandas_ta":
        return _pta.macd(close)["MACD_12_26_9"]
    return _ta_lib.trend.macd(close)


def _atr(high, low, close, length=14):
    if _TA_BACKEND == "pandas_ta":
        return _pta.atr(high, low, close, length=length)
    return _ta_lib.volatility.average_true_range(high, low, close, window=length)


def _bbands(close):
    if _TA_BACKEND == "pandas_ta":
        bb = _pta.bbands(close)
        return bb["BBU_5_2.0"], bb["BBM_5_2.0"], bb["BBL_5_2.0"]
    ind = _ta_lib.volatility.BollingerBands(close)
    return ind.bollinger_hband(), ind.bollinger_mavg(), ind.bollinger_lband()


# Load historical XAUUSD data.
# Set DATA_PATH env var or pass --data argument; defaults to data/XAU_USD_H1.csv.
import os


import logging

logger = logging.getLogger(__name__)
_DATA_PATH = os.environ.get("DATA_PATH", "data/XAU_USD_H1.csv")
data = pd.read_csv(_DATA_PATH)


def generate_features(data):
    data["EMA"] = _ema(data["Close"], length=14)
    data["RSI"] = _rsi(data["Close"], length=14)
    data["MACD"] = _macd(data["Close"])
    data["ATR"] = _atr(data["High"], data["Low"], data["Close"], length=14)
    data["BB_upper"], data["BB_middle"], data["BB_lower"] = _bbands(data["Close"])
    return data


if __name__ == "__main__":
    data = generate_features(data)

    # Target column: 1=Buy, 0=Sell — must exist in the CSV.
    if "Target" not in data.columns:
        raise ValueError("CSV must contain a 'Target' column (1=Buy, 0=Sell)")

    X = data[["EMA", "RSI", "MACD", "ATR", "BB_upper", "BB_middle", "BB_lower"]].dropna()
    y = data.loc[X.index, "Target"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    cv_scores = cross_val_score(model, X, y, cv=5)
    logger.info(f"Cross-Validation Scores: {cv_scores}")
    logger.info(f"Average Score: {cv_scores.mean():.4f}")

    predictions = model.predict(X_test)
    logger.info(confusion_matrix(y_test, predictions))
    logger.info(classification_report(y_test, predictions))

    joblib.dump(model, "ml/saved_models/ensemble_rf.pkl")
    logger.info("Model saved to ml/saved_models/ensemble_rf.pkl")
