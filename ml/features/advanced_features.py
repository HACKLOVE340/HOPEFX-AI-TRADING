# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Advanced ML Feature Engineering for Trading
- Technical indicator features
- Market microstructure features
- Volatility features
- Correlation features
- Entropy features
- Deep learning ready features
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AdvancedFeatureEngineer:
    """Enterprise-grade feature engineering"""

    def __init__(self, lookback_periods: int = 252):
        """Initialize feature engineer"""
        self.lookback_periods = lookback_periods

    def engineer_features(
        self,
        df: pd.DataFrame,
        include_advanced: bool = True,
    ) -> pd.DataFrame:
        """
        Engineer all features

        Args:
            df: OHLCV DataFrame
            include_advanced: Include advanced features

        Returns:
            DataFrame with engineered features
        """

        features_df = df.copy()

        # Price-based features
        features_df = self._add_price_features(features_df)

        # Volatility features
        features_df = self._add_volatility_features(features_df)

        # Trend features
        features_df = self._add_trend_features(features_df)

        # Momentum features
        features_df = self._add_momentum_features(features_df)

        # Volume features
        features_df = self._add_volume_features(features_df)

        # Pattern features
        features_df = self._add_pattern_features(features_df)

        # Microstructure features
        features_df = self._add_microstructure_features(features_df)

        if include_advanced:
            # Entropy features
            features_df = self._add_entropy_features(features_df)

            # Fractal features
            features_df = self._add_fractal_features(features_df)

            # Regime features
            features_df = self._add_regime_features(features_df)

        # Remove NaN values
        features_df = features_df.dropna()

        logger.info("Engineered %s features", len(features_df.columns))

        return features_df

    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add price-based features"""

        df["returns"] = df["close"].pct_change(fill_method=None)
        df["log_returns"] = np.log(df["close"] / df["close"].shift(1))

        # Price position in range
        df["high_low_ratio"] = (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-10)

        # Close to open
        df["close_open_ratio"] = df["close"] / df["open"]

        # Body size (normalized)
        range_size = df["high"] - df["low"]
        df["body_size"] = abs(df["close"] - df["open"]) / (range_size + 1e-10)

        # Shadows
        df["upper_shadow"] = (df["high"] - np.maximum(df["open"], df["close"])) / (range_size + 1e-10)
        df["lower_shadow"] = (np.minimum(df["open"], df["close"]) - df["low"]) / (range_size + 1e-10)

        # Multi-period returns
        for period in [2, 5, 10, 20, 60]:
            df[f"returns_{period}d"] = df["close"].pct_change(period)

        # Price acceleration
        df["price_accel"] = df["returns"].diff()

        # Price jerk (3rd derivative)
        df["price_jerk"] = df["price_accel"].diff()

        return df

    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volatility features"""

        # Historical volatility
        for period in [10, 20, 60]:
            df[f"volatility_{period}d"] = df["returns"].rolling(period).std()

        # Parkinson volatility
        hl_ratio = np.log(df["high"] / df["low"])
        df["parkinson_vol"] = np.sqrt(np.mean(hl_ratio**2) / (4 * np.log(2)))

        # Garman-Klass volatility
        hl = np.log(df["high"] / df["low"])
        co = np.log(df["close"] / df["open"])
        df["garman_klass_vol"] = np.sqrt(0.5 * hl**2 - (2 * np.log(2) - 1) * co**2)

        # True Range & ATR
        df["tr"] = np.maximum(
            df["high"] - df["low"],
            np.maximum(
                abs(df["high"] - df["close"].shift()),
                abs(df["low"] - df["close"].shift()),
            ),
        )

        for period in [14, 20]:
            df[f"atr_{period}"] = df["tr"].rolling(period).mean()

        # Volatility of volatility
        df["vol_of_vol"] = df["volatility_20d"].rolling(20).std()

        # Normalized volatility
        df["vol_normalized"] = df["volatility_20d"] / df["volatility_20d"].rolling(60).mean()

        return df

    def _add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add trend features"""

        # Moving averages
        for period in [5, 10, 20, 50, 200]:
            df[f"sma_{period}"] = df["close"].rolling(period).mean()
            df[f"ema_{period}"] = df["close"].ewm(span=period).mean()

        # Price vs MA
        df["price_sma_20_ratio"] = df["close"] / (df["sma_20"] + 1e-10)
        df["price_ema_20_ratio"] = df["close"] / (df["ema_20"] + 1e-10)

        # Trend strength
        df["trend_strength"] = self._calculate_trend_strength(df)

        # Slope of MA
        for period in [20, 50]:
            sma = df[f"sma_{period}"]
            df[f"sma_{period}_slope"] = sma.diff() / sma.shift() * 100

        # Price distance from MA
        for period in [20, 50, 200]:
            sma = df[f"sma_{period}"]
            df[f"price_dist_sma_{period}"] = (df["close"] - sma) / sma * 100

        return df

    def _add_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add momentum features"""

        # RSI
        for period in [14, 21]:
            df[f"rsi_{period}"] = self._calculate_rsi(df["close"], period)

        # MACD
        df["macd"], df["macd_signal"], df["macd_hist"] = self._calculate_macd(
            df["close"],
        )

        # Momentum
        for period in [10, 20]:
            df[f"momentum_{period}"] = df["close"] - df["close"].shift(period)
            df[f"momentum_pct_{period}"] = (df["close"] - df["close"].shift(period)) / df["close"].shift(period) * 100

        # Rate of Change
        for period in [5, 10, 20]:
            df[f"roc_{period}"] = (df["close"] - df["close"].shift(period)) / df["close"].shift(period) * 100

        # Stochastic
        df["stoch_k"], df["stoch_d"] = self._calculate_stochastic(df, period=14)

        # Williams %R
        df["williams_r"] = self._calculate_williams_r(df, period=14)

        # CCI (Commodity Channel Index)
        df["cci"] = self._calculate_cci(df, period=20)

        return df

    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume features"""

        # Volume SMA
        for period in [5, 20]:
            df[f"volume_sma_{period}"] = df["volume"].rolling(period).mean()

        # Volume ratio
        df["volume_ratio"] = df["volume"] / (df["volume_sma_20"] + 1e-10)

        # OBV (On Balance Volume)
        df["obv"] = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()

        # MFI (Money Flow Index)
        df["mfi"] = self._calculate_mfi(df, period=14)

        # Volume ROC
        df["volume_roc"] = df["volume"].pct_change(fill_method=None) * 100

        # Accumulation/Distribution
        hlc_ratio = (df["close"] - df["low"]) - (df["high"] - df["close"])
        df["ad"] = (hlc_ratio / (df["high"] - df["low"] + 1e-10)) * df["volume"]

        # Volume-price trend
        df["vpt"] = df["ad"].cumsum()

        return df

    def _add_pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add candlestick pattern features"""

        body = abs(df["close"] - df["open"])
        upper_shadow = df["high"] - np.maximum(df["close"], df["open"])
        lower_shadow = np.minimum(df["close"], df["open"]) - df["low"]

        # Hammer/Hanging Man
        df["hammer_score"] = (lower_shadow > 2 * upper_shadow).astype(int) * (body < body.rolling(20).mean()).astype(
            int
        )

        # Doji
        df["doji_score"] = (body < 0.1 * (df["high"] - df["low"])).astype(int)

        # Engulfing
        df["bullish_engulfing"] = (
            (df["close"] > df["open"]).astype(int)
            * (df["close"] > df["open"].shift()).astype(int)
            * (df["open"] < df["close"].shift()).astype(int)
        )

        df["bearish_engulfing"] = (
            (df["close"] < df["open"]).astype(int)
            * (df["close"] < df["open"].shift()).astype(int)
            * (df["open"] > df["close"].shift()).astype(int)
        )

        # Marubozu (no shadows)
        df["marubozu_score"] = (upper_shadow < body * 0.01).astype(int) * (lower_shadow < body * 0.01).astype(int)

        return df

    def _add_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add market microstructure features"""

        # Spread estimate
        df["spread_estimate"] = (df["high"] - df["low"]) / df["close"] * 100

        # Price impact
        df["price_impact"] = abs(df["close"] - df["open"]) / df["close"] * 100

        # Amihud illiquidity
        df["amihud_illiquidity"] = abs(df["returns"]) / (df["volume"] + 1)

        # VWAP (Volume Weighted Average Price)
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (typical_price * df["volume"]).rolling(20).sum() / df["volume"].rolling(20).sum()

        # Distance from VWAP
        df["price_vwap_dist"] = (df["close"] - df["vwap"]) / df["vwap"] * 100

        return df

    def _add_entropy_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add entropy and information features"""

        # Approximate entropy
        for period in [10, 20]:
            df[f"entropy_{period}"] = df["returns"].rolling(period).apply(self._calculate_entropy, raw=True)

        # Permutation entropy
        df["perm_entropy_10"] = df["returns"].rolling(10).apply(self._calculate_permutation_entropy, raw=True)

        return df

    def _add_fractal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add fractal/scaling features"""

        # Hurst exponent
        for period in [20, 50]:
            df[f"hurst_{period}"] = df["returns"].rolling(period).apply(self._calculate_hurst, raw=True)

        # Detrended fluctuation analysis
        df["dfa_10"] = df["returns"].rolling(10).apply(self._calculate_dfa, raw=True)

        return df

    def _add_regime_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add regime detection features"""

        # Volatility regime
        vol_20 = df["volatility_20d"]
        vol_ma = vol_20.rolling(60).mean()
        df["vol_regime"] = (vol_20 > vol_ma).astype(int)

        # Trend regime
        df["trend_regime"] = (df["ema_20"] > df["ema_50"]).astype(int) * 2 - 1

        # Momentum regime
        df["momentum_regime"] = np.sign(df["rsi_14"] - 50)

        return df

    # ============ INDICATOR CALCULATIONS ============

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / (loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_macd(
        self,
        prices: pd.Series,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD"""
        ema12 = prices.ewm(span=12).mean()
        ema26 = prices.ewm(span=26).mean()

        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        hist = macd - signal

        return macd, signal, hist

    def _calculate_stochastic(
        self,
        df: pd.DataFrame,
        period: int = 14,
    ) -> tuple[pd.Series, pd.Series]:
        """Calculate Stochastic Oscillator"""
        low_min = df["low"].rolling(period).min()
        high_max = df["high"].rolling(period).max()

        k = 100 * ((df["close"] - low_min) / (high_max - low_min + 1e-10))
        d = k.rolling(3).mean()

        return k, d

    def _calculate_williams_r(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Williams %R"""
        high_max = df["high"].rolling(period).max()
        low_min = df["low"].rolling(period).min()

        wr = -100 * ((high_max - df["close"]) / (high_max - low_min + 1e-10))
        return wr

    def _calculate_mfi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate MFI"""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        money_flow = typical_price * df["volume"]

        positive_flow = money_flow.where(typical_price > typical_price.shift(), 0)
        negative_flow = money_flow.where(typical_price < typical_price.shift(), 0)

        positive_sum = positive_flow.rolling(period).sum()
        negative_sum = negative_flow.rolling(period).sum()

        mfi = 100 - (100 / (1 + (positive_sum / (negative_sum + 1e-10))))
        return mfi

    def _calculate_cci(self, df: pd.DataFrame, period: int = 20) -> pd.Series:
        """Calculate CCI"""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        sma = typical_price.rolling(period).mean()
        mad = typical_price.rolling(period).apply(
            lambda x: np.mean(np.abs(x - x.mean())),
        )

        cci = (typical_price - sma) / (0.015 * mad + 1e-10)
        return cci

    def _calculate_trend_strength(self, df: pd.DataFrame) -> pd.Series:
        """Calculate trend strength"""
        sma20 = df["close"].rolling(20).mean()
        sma50 = df["close"].rolling(50).mean()

        strength = abs(sma20 - sma50) / sma20 * 100
        return strength

    def _calculate_entropy(self, prices: np.ndarray, base: int = 2) -> float:
        """Calculate approximate entropy"""
        try:
            # Simple entropy based on price differences
            returns = np.diff(prices)
            if len(returns) == 0:
                return 0

            # Bin returns into positive/negative
            bins = np.array([returns < 0, returns >= 0])
            counts = np.sum(bins, axis=1)
            probs = counts / len(returns)
            probs = probs[probs > 0]

            entropy = -np.sum(probs * np.log(probs + 1e-10))
            return entropy
        except (ValueError, FloatingPointError):
            return 0

    def _calculate_permutation_entropy(
        self,
        prices: np.ndarray,
        order: int = 3,
    ) -> float:
        """Calculate permutation entropy"""
        try:
            if len(prices) < order:
                return 0

            orderings = []
            for i in range(len(prices) - order + 1):
                ordering = tuple(np.argsort(prices[i : i + order]))
                orderings.append(ordering)

            _, counts = np.unique(orderings, return_counts=True)
            probs = counts / len(orderings)
            entropy = -np.sum(probs * np.log(probs + 1e-10))

            import math as _math
            return entropy / np.log(_math.factorial(order))
        except (ValueError, FloatingPointError):
            return 0

    def _calculate_hurst(self, series: np.ndarray) -> float:
        """
        Calculate Hurst exponent via rescaled-range (R/S) analysis.

        Accepts a returns series (not raw prices) — the rolling window in
        _add_fractal_features passes df["returns"] which is already a
        pct-change series, so we work directly on it.
        """
        try:
            if len(series) < 10:
                return 0.5

            # series is already a returns array
            returns = np.asarray(series, dtype=float)
            # Replace any NaN/inf with 0 to avoid propagation
            returns = np.where(np.isfinite(returns), returns, 0.0)

            cumulative = np.cumsum(returns - np.mean(returns))

            max_dev = np.max(cumulative)
            min_dev = np.min(cumulative)
            range_val = max_dev - min_dev

            std_dev = np.std(returns, ddof=1)

            if std_dev > 0 and range_val > 0 and len(returns) > 1:
                hurst = np.log(range_val / std_dev) / np.log(len(returns))
                return float(np.clip(hurst, 0.0, 1.0))

            return 0.5
        except (ValueError, FloatingPointError, ZeroDivisionError):
            return 0.5

    def _calculate_dfa(self, series: np.ndarray) -> float:
        """
        Detrended Fluctuation Analysis approximation.

        Accepts a returns series (same convention as _calculate_hurst).
        Returns the detrended fluctuation value (normalised to [0, 1]).
        """
        try:
            if len(series) < 10:
                return 0.5

            returns = np.asarray(series, dtype=float)
            returns = np.where(np.isfinite(returns), returns, 0.0)

            cumulative = np.cumsum(returns - np.mean(returns))

            # Fit linear trend and compute residual fluctuation
            x = np.arange(len(cumulative))
            coeffs = np.polyfit(x, cumulative, 1)
            trend = np.polyval(coeffs, x)

            fluctuation = float(np.sqrt(np.mean((cumulative - trend) ** 2)))
            # Normalise to a bounded [0,1] range via tanh
            return float(np.tanh(fluctuation))
        except (ValueError, FloatingPointError, np.linalg.LinAlgError):
            return 0.5

    # =========================================================================
    # sklearn-compatible interface
    # =========================================================================

    def fit(self, df: pd.DataFrame, y: pd.Series | None = None) -> "AdvancedFeatureEngineer":
        """
        Fit the engineer on *df* — computes and caches feature column names.

        Calling ``fit`` before ``transform`` is required for the sklearn
        pipeline interface.  The engineer is stateless beyond the column list,
        so fitting is lightweight.

        Args:
            df: OHLCV DataFrame used to derive the feature schema.
            y: Ignored (present for sklearn API compatibility).

        Returns:
            self
        """
        sample = self.engineer_features(df.copy(), include_advanced=True)
        # Store feature columns (exclude raw OHLCV inputs)
        ohlcv_cols = {"open", "high", "low", "close", "volume"}
        self._feature_columns_: list[str] = [c for c in sample.columns if c not in ohlcv_cols]
        self._is_fitted_ = True
        logger.info("AdvancedFeatureEngineer fitted: %d feature columns", len(self._feature_columns_))
        return self

    def transform(self, df: pd.DataFrame, include_advanced: bool = True) -> pd.DataFrame:
        """
        Transform *df* into the feature matrix.

        If ``fit`` has been called previously, only the columns seen during
        fitting are returned (missing columns are filled with 0.0 so that
        the output shape is always consistent).

        Args:
            df: OHLCV DataFrame.
            include_advanced: Passed through to ``engineer_features``.

        Returns:
            DataFrame of engineered features (OHLCV columns excluded).
        """
        result = self.engineer_features(df.copy(), include_advanced=include_advanced)
        ohlcv_cols = {"open", "high", "low", "close", "volume"}

        if getattr(self, "_is_fitted_", False) and self._feature_columns_:
            # Align to fitted schema — add missing cols as 0, drop extras
            for col in self._feature_columns_:
                if col not in result.columns:
                    result[col] = 0.0
            return result[self._feature_columns_]

        return result[[c for c in result.columns if c not in ohlcv_cols]]

    def fit_transform(self, df: pd.DataFrame, y: pd.Series | None = None) -> pd.DataFrame:
        """Fit then transform in one call (sklearn API)."""
        return self.fit(df, y).transform(df)

    def get_feature_names_out(self) -> list[str]:
        """
        Return the list of feature column names produced by ``transform``.

        Requires ``fit`` to have been called first.

        Returns:
            List of feature column names.

        Raises:
            RuntimeError: If called before ``fit``.
        """
        if not getattr(self, "_is_fitted_", False):
            raise RuntimeError(
                "AdvancedFeatureEngineer is not fitted. Call fit() or fit_transform() first."
            )
        return list(self._feature_columns_)

    # Alias used by some sklearn utilities
    get_feature_names = get_feature_names_out

    # =========================================================================
    # Feature importance and selection
    # =========================================================================

    def feature_importance(
        self,
        df: pd.DataFrame,
        target: pd.Series,
        method: str = "mutual_info",
        n_top: int | None = None,
    ) -> pd.Series:
        """
        Compute feature importance scores against *target*.

        Two methods are supported:

        ``mutual_info`` (default)
            Uses ``sklearn.feature_selection.mutual_info_regression``.
            Model-free, captures non-linear relationships.  Preferred for
            initial feature screening.

        ``random_forest``
            Fits a ``RandomForestRegressor`` and returns its
            ``feature_importances_`` attribute.  Slower but accounts for
            feature interactions.

        Args:
            df: OHLCV DataFrame (will be transformed internally).
            target: Target series aligned with *df* (e.g. next-bar returns).
            method: ``"mutual_info"`` or ``"random_forest"``.
            n_top: If set, return only the top-*n_top* features.

        Returns:
            pd.Series of importance scores indexed by feature name,
            sorted descending.
        """
        from sklearn.feature_selection import mutual_info_regression

        features = self.fit_transform(df)

        # Align target to the transformed index (dropna may have shortened df)
        target_aligned = target.reindex(features.index).dropna()
        features_aligned = features.loc[target_aligned.index]

        if features_aligned.empty:
            raise ValueError("No overlapping rows between features and target after alignment.")

        X = features_aligned.values.astype(np.float64)
        y = target_aligned.values.astype(np.float64)

        # Replace any remaining NaN/inf with column medians
        col_medians = np.nanmedian(X, axis=0)
        nan_mask = ~np.isfinite(X)
        X[nan_mask] = np.take(col_medians, np.where(nan_mask)[1])

        if method == "random_forest":
            from sklearn.ensemble import RandomForestRegressor

            rf = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
            rf.fit(X, y)
            scores = rf.feature_importances_
        else:
            # mutual_info (default)
            scores = mutual_info_regression(X, y, random_state=42)

        importance = pd.Series(scores, index=features_aligned.columns).sort_values(ascending=False)

        if n_top is not None:
            importance = importance.head(n_top)

        logger.info(
            "feature_importance (%s): top feature=%s (%.4f)",
            method,
            importance.index[0] if len(importance) else "none",
            importance.iloc[0] if len(importance) else 0.0,
        )
        return importance

    def select_features(
        self,
        df: pd.DataFrame,
        target: pd.Series,
        n_features: int = 30,
        method: str = "mutual_info",
    ) -> pd.DataFrame:
        """
        Return a feature DataFrame reduced to the *n_features* most important.

        Fits the engineer, computes importance scores, then restricts the
        output to the top-*n_features* columns.  The selected column list is
        stored in ``self._selected_features_`` for use in subsequent
        ``transform`` calls.

        Args:
            df: OHLCV DataFrame.
            target: Target series (e.g. forward returns).
            n_features: Number of features to retain.
            method: Importance method — ``"mutual_info"`` or ``"random_forest"``.

        Returns:
            DataFrame with only the selected feature columns.
        """
        importance = self.feature_importance(df, target, method=method)
        selected = importance.head(n_features).index.tolist()
        self._selected_features_: list[str] = selected

        features = self.transform(df)
        available = [c for c in selected if c in features.columns]
        logger.info(
            "select_features: retained %d/%d features via %s",
            len(available),
            n_features,
            method,
        )
        return features[available]

    def get_selected_features(self) -> list[str]:
        """
        Return the feature names chosen by the last ``select_features`` call.

        Raises:
            RuntimeError: If ``select_features`` has not been called.
        """
        if not hasattr(self, "_selected_features_"):
            raise RuntimeError("Call select_features() first.")
        return list(self._selected_features_)

    # =========================================================================
    # Online / incremental update
    # =========================================================================

    def _engineer_live_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute a minimal, short-window feature set for live inference.

        Unlike ``engineer_features``, this method does not call ``dropna()``
        globally — it fills NaN values with 0 so that the last row is always
        available even when the window is shorter than the longest indicator
        period.  Only indicators that are meaningful on windows of 20+ bars
        are included.

        Args:
            df: OHLCV DataFrame (at least 20 bars recommended).

        Returns:
            DataFrame with live-safe features; last row corresponds to the
            most recent bar.
        """
        out = df.copy()

        # Returns
        out["returns"] = out["close"].pct_change(fill_method=None)
        out["log_returns"] = np.log(out["close"] / out["close"].shift(1))

        # Price position
        rng = out["high"] - out["low"]
        out["high_low_ratio"] = (out["close"] - out["low"]) / (rng + 1e-10)
        out["close_open_ratio"] = out["close"] / out["open"]
        out["body_size"] = abs(out["close"] - out["open"]) / (rng + 1e-10)

        # Short-window MAs
        for p in [5, 10, 20]:
            out[f"sma_{p}"] = out["close"].rolling(p, min_periods=1).mean()
            out[f"ema_{p}"] = out["close"].ewm(span=p, min_periods=1).mean()

        out["price_sma_20_ratio"] = out["close"] / (out["sma_20"] + 1e-10)

        # Volatility
        out["volatility_10d"] = out["returns"].rolling(10, min_periods=2).std()
        out["volatility_20d"] = out["returns"].rolling(20, min_periods=2).std()
        out["tr"] = np.maximum(
            out["high"] - out["low"],
            np.maximum(
                abs(out["high"] - out["close"].shift()),
                abs(out["low"] - out["close"].shift()),
            ),
        )
        out["atr_14"] = out["tr"].rolling(14, min_periods=1).mean()

        # Momentum
        out["rsi_14"] = self._calculate_rsi(out["close"], 14)
        macd, signal, hist = self._calculate_macd(out["close"])
        out["macd"] = macd
        out["macd_signal"] = signal
        out["macd_hist"] = hist

        for p in [5, 10]:
            out[f"roc_{p}"] = (out["close"] - out["close"].shift(p)) / (out["close"].shift(p) + 1e-10) * 100

        # Volume
        out["volume_sma_20"] = out["volume"].rolling(20, min_periods=1).mean()
        out["volume_ratio"] = out["volume"] / (out["volume_sma_20"] + 1e-10)

        # Fill remaining NaN with 0 so the last row is always complete
        out = out.fillna(0.0)

        ohlcv_cols = {"open", "high", "low", "close", "volume"}
        feat_cols = [c for c in out.columns if c not in ohlcv_cols]
        return out[feat_cols]

    def online_update(self, new_bar: pd.Series, window: pd.DataFrame) -> pd.Series:
        """
        Compute features for a single new bar without re-processing the full
        history — suitable for live inference on each incoming tick/bar.

        Appends *new_bar* to *window*, runs ``engineer_features``, and returns
        the feature row for the last bar only.

        Args:
            new_bar: A single OHLCV row as a pd.Series with index
                ``["open", "high", "low", "close", "volume"]``.
            window: Recent OHLCV history (at least ``lookback_periods`` bars)
                used to compute rolling indicators.

        Returns:
            pd.Series of feature values for *new_bar*.
        """
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(new_bar.index)
        if missing:
            raise ValueError(f"new_bar is missing columns: {missing}")

        # Append new bar to window
        new_row = pd.DataFrame([new_bar])
        if not isinstance(window.index, pd.DatetimeIndex):
            combined = pd.concat([window, new_row], ignore_index=True)
        else:
            combined = pd.concat([window, new_row])

        # Compute a minimal feature set suitable for live inference.
        # We bypass engineer_features (which calls dropna and requires 200+ bars)
        # and compute only the indicators that work on short windows.
        features = self._engineer_live_features(combined)

        last_row = features.iloc[-1]

        # If fitted, align to known feature schema
        if getattr(self, "_is_fitted_", False) and self._feature_columns_:
            ohlcv_cols = {"open", "high", "low", "close", "volume"}
            feat_cols = [c for c in self._feature_columns_ if c in last_row.index and c not in ohlcv_cols]
            return last_row[feat_cols]

        ohlcv_cols = {"open", "high", "low", "close", "volume"}
        return last_row[[c for c in last_row.index if c not in ohlcv_cols]]
