# enhanced_ml_predictor.py – full merged version
# Your original code + deep enhancements: features, walk-forward, online learning, live preds

import pandas as pd
import numpy as np
import os
import joblib
import logging
from typing import List, Dict, Optional, Tuple
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor
from sklearn.preprocessing import RobustScaler
from sklearn.model_selection import TimeSeriesSplit

logger = logging.getLogger(__name__)

class EnhancedMLPredictor:
    """
    Your original predictor—now supercharged.
    Keeps all your methods intact, adds real power underneath.
    """
    def __init__(self, model_type='xgb', save_path='ml/'):
        self.model_type = model_type
        self.save_path = save_path
        self.scaler = RobustScaler()
        self.model = self._init_model()
        self.feature_engineer = self._build_feature_engineer()
        self.loaded = False
        self.feature_names: List = []
        self._ensure_dirs()
        self._load_checkpoint()

        # Your original init stuff (assuming you had these—add yours if different)
        # e.g. self.params = {...}
        # self.history = pd.DataFrame()

    def _ensure_dirs(self):
        os.makedirs(self.save_path, exist_ok=True)

    def _init_model(self):
        if self.model_type == 'xgb':
            return XGBRegressor(
                n_estimators=300,
                learning_rate=0.03,
                max_depth=7,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_lambda=1.5,
                early_stopping_rounds=25,
                random_state=42,
                n_jobs=-1
            )
        elif self.model_type == 'rf':
            return RandomForestRegressor(
                n_estimators=200,
                max_depth=10,
                min_samples_leaf=5,
                random_state=42,
                n_jobs=-1
            )
        else:
            raise ValueError("Only 'xgb' or 'rf' supported")

    def _load_checkpoint(self):
        try:
            self.model = joblib.load(f"{self.save_path}{self.model_type}_model.pkl")
            self.scaler = joblib.load(f"{self.save_path}scaler.pkl")
            self.feature_names = joblib.load(f"{self.save_path}features.pkl")
            self.loaded = True
            logger.info("ML checkpoint loaded successfully")
        except FileNotFoundError:
            logger.info("No checkpoint found—starting fresh")

    def _build_feature_engineer(self):
        """Your features + my hardcore additions"""
        def engineer(df: pd.DataFrame) -> pd.DataFrame:
            if not isinstance(df, pd.DataFrame):
                df = pd.DataFrame(df)

            feats = pd.DataFrame(index=df.index)

            # Your original features (add whatever you had—I'm guessing OHLCV-based)
            feats = df .pct_change().fillna(0)
            feats = df .rolling(20).mean().fillna(0)

            # Added: volatility clustering
            feats = df .pct_change().rolling(5).std().fillna(0)
            feats = df .pct_change().rolling(20).std().fillna(0)

            # Added: momentum & trend
            feats = df .ewm(span=14).mean() - df .ewm(span=50).mean()
            feats = self._rsi(df , 14)

            # Added: order-flow proxy
            feats = df['close'].diff().fillna(0)
            if 'volume' in df.columns:
                feats = df .diff().fillna(0)

            # Added: time decay (cycle features)
            feats = np.sin(2 * np.pi * df.index.hour / 24)
            feats = np.sin(2 * np.pi * df.index.dayofweek / 7)

            self.feature_names = feats.columns.tolist()
            return feats

        return engineer

    def _rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    # Your original predict method—enhanced to use new features
    def predict(self, data: pd.DataFrame) -> float:
        if not self.loaded:
            self.train(data)  # auto-train if empty

        X = self.feature_engineer(data)
        if len(self.feature_names) > 0:
            X = X # align

        X_scaled = self.scaler.transform(X.tail(1))  # latest row
        pred = self.model.predict(X_scaled)[0]
        return pred

    # New: walk-forward training—call this once or on new data
    def train(self, df: pd.DataFrame, target_col: str = 'close', n_splits: int = 5):
        X = self.feature_engineer(df)
        y = df .shift(-1).dropna()
        X = X.iloc[:-1]  # align

        tscv = TimeSeriesSplit(n_splits=n_splits)
        scores = []

        for train_idx, test_idx in tscv.split(X):
            X_train, X_test = X.iloc , X.iloc y_train, y_test = y.iloc , y.iloc X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)

            self.model.fit(
                X_train_scaled, y_train,
                eval_set= ,
                verbose=False
            )
            score = self.model.score(X_test_scaled, y_test)
            scores.append(score)
            logger.debug(f"Split score: {score:.4f}")

        # Save state
        joblib.dump(self.model, f"{self.save_path}{self.model_type}_model.pkl")
        joblib.dump(self.scaler, f"{self.save_path}scaler.pkl")
        joblib.dump(self.feature_names, f"{self.save_path}features.pkl")
        self.loaded = True

        logger.info(f"Walk-forward avg R²: {np.mean(scores):.4f}")

    # New: live prediction with incremental update
    def predict_live(self, new_tick: Dict) -> float:
        df_tick = pd.DataFrame( )
        df_tick.index = pd.to_datetime( )

        X_new = self.feature_engineer(df_tick)
        if len(self.feature_names) > 0:
            X_new = X_new X_scaled = self.scaler.transform(X_new)
        pred = self.model.predict(X_scaled)[0]

        # Light online update (rare—prevents drift without overfitting)
        if np.random.rand() < 0.01:  # ~1% chance per tick
            self.model.fit(X_scaled, , xgb_model=self.model.get_booster())

        return pred

    # Your other methods—left untouched (add them here if you had more)
    # def some_old_method(self): ...