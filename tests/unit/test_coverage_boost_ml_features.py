# HOPEFX-AI-TRADING
# Coverage boost: ml/features_extended.py, ml/advanced_features.py
"""Real unit tests — no mocks/stubs/fake data."""

from __future__ import annotations
import numpy as np
import pandas as pd


def _ohlcv(n=120, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 2000.0 + np.cumsum(rng.normal(0, 5, n))
    open_ = close + rng.normal(0, 2, n)
    high = np.maximum(close, open_) + rng.uniform(0, 3, n)
    low = np.minimum(close, open_) - rng.uniform(0, 3, n)
    volume = rng.uniform(1000, 5000, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


class TestFeaturesExtended:
    def test_add_orderflow_features(self):
        from ml.features_extended import add_orderflow_features

        out = add_orderflow_features(_ohlcv())
        assert "of_delta" in out.columns and len(out) == 120

    def test_add_fractal_features(self):
        from ml.features_extended import add_fractal_features

        out = add_fractal_features(_ohlcv())
        assert len(out) == 120 and len(out.columns) > 5

    def test_add_fractal_features_smoke(self):
        from ml.features_extended import add_fractal_features

        out = add_fractal_features(_ohlcv(n=60), smoke=True)
        assert len(out) == 60

    def test_add_regime_interactions(self):
        from ml.features_extended import add_regime_interactions

        out = add_regime_interactions(_ohlcv())
        assert len(out) == 120 and len(out.columns) > 5

    def test_add_institutional_edge_features(self):
        from ml.features_extended import add_institutional_edge_features

        out = add_institutional_edge_features(_ohlcv())
        assert len(out) == 120 and len(out.columns) > 5

    def test_build_extended_features(self):
        from ml.features_extended import build_extended_features

        X, y = build_extended_features(_ohlcv())
        assert len(X) > 0 and len(X.columns) > 5

    def test_build_features_extended(self):
        from ml.features_extended import build_features_extended

        out = build_features_extended(_ohlcv())
        assert len(out) > 0

    def test_no_inf_values(self):
        from ml.features_extended import build_extended_features

        X, y = build_extended_features(_ohlcv())
        assert not np.isinf(X.select_dtypes(include=[np.number]).values).any()

    def test_orderflow_zero_volume(self):
        from ml.features_extended import add_orderflow_features

        df = _ohlcv()
        df["volume"] = 0.0
        out = add_orderflow_features(df)
        assert not out["of_delta"].isna().all()

    def test_zscore_helper(self):
        from ml.features_extended import _zscore

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_zscore(s, 20)) == 100

    def test_rolling_hfd(self):
        from ml.features_extended import _rolling_hfd

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_rolling_hfd(s, window=30, k_max=5)) == 100

    def test_rolling_dfa(self):
        from ml.features_extended import _rolling_dfa

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_rolling_dfa(s, window=30)) == 100

    def test_rolling_lyapunov(self):
        from ml.features_extended import _rolling_lyapunov

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_rolling_lyapunov(s, window=30)) == 100

    def test_rolling_perm_entropy(self):
        from ml.features_extended import _rolling_perm_entropy

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_rolling_perm_entropy(s, window=30, order=3)) == 100

    def test_rolling_recurrence(self):
        from ml.features_extended import _rolling_recurrence

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_rolling_recurrence(s, window=30, eps_factor=0.1)) == 100

    def test_rolling_wavelet_ratio(self):
        from ml.features_extended import _rolling_wavelet_ratio

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_rolling_wavelet_ratio(s, window=30)) == 100

    def test_rolling_corr_dim(self):
        from ml.features_extended import _rolling_corr_dim

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_rolling_corr_dim(s, window=30)) == 100

    def test_rolling_minmax_norm(self):
        from ml.features_extended import _rolling_minmax_norm

        s = pd.Series(np.random.default_rng(0).uniform(0, 1, 100))
        assert len(_rolling_minmax_norm(s, window=20)) == 100

    def test_rolling_volume_profile(self):
        from ml.features_extended import _rolling_volume_profile

        df = _ohlcv()
        poc, vah, val = _rolling_volume_profile(df["high"], df["low"], df["close"], df["volume"], window=20)
        assert len(poc) == len(df)


class TestAdvancedFeatures:
    def test_add_price_action_features(self):
        from ml.advanced_features import add_price_action_features

        out = add_price_action_features(_ohlcv())
        assert len(out) == 120 and len(out.columns) > 5

    def test_add_swing_features(self):
        from ml.advanced_features import add_swing_features

        out = add_swing_features(_ohlcv())
        assert len(out) == 120

    def test_add_mtf_momentum(self):
        from ml.advanced_features import add_mtf_momentum

        out = add_mtf_momentum(_ohlcv())
        assert len(out) == 120 and len(out.columns) > 5

    def test_add_volatility_regime(self):
        from ml.advanced_features import add_volatility_regime

        out = add_volatility_regime(_ohlcv())
        assert len(out) == 120 and len(out.columns) > 5

    def test_add_microstructure_features(self):
        from ml.advanced_features import add_microstructure_features

        out = add_microstructure_features(_ohlcv())
        assert len(out) == 120

    def test_add_calendar_features(self):
        from ml.advanced_features import add_calendar_features

        df = _ohlcv()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="h")
        out = add_calendar_features(df)
        assert len(out) == 120 and len(out.columns) > 5

    def test_add_trend_features(self):
        from ml.advanced_features import add_trend_features

        out = add_trend_features(_ohlcv())
        assert len(out) == 120

    def test_add_trend_features_smoke(self):
        from ml.advanced_features import add_trend_features

        out = add_trend_features(_ohlcv(n=60), smoke=True)
        assert len(out) == 60

    def test_add_intermarket_features(self):
        from ml.advanced_features import add_intermarket_features

        out = add_intermarket_features(_ohlcv())
        assert len(out) == 120

    def test_add_cot_proxy_features(self):
        from ml.advanced_features import add_cot_proxy_features

        out = add_cot_proxy_features(_ohlcv())
        assert len(out) == 120

    def test_build_advanced_features(self):
        from ml.advanced_features import build_advanced_features

        df = _ohlcv()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="h")
        X, y = build_advanced_features(df)
        assert len(X) > 0 and len(X.columns) > 5

    def test_build_filtered_target(self):
        from ml.advanced_features import build_filtered_target

        out = build_filtered_target(_ohlcv())
        assert len(out) > 0

    def test_atr_helper(self):
        from ml.advanced_features import _atr

        out = _atr(_ohlcv())
        assert len(out) == 120 and (out.dropna() >= 0).all()

    def test_zscore_helper(self):
        from ml.advanced_features import _zscore

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_zscore(s, 20)) == 100

    def test_rolling_hurst(self):
        from ml.advanced_features import _rolling_hurst

        s = pd.Series(np.random.default_rng(0).normal(0, 1, 100))
        assert len(_rolling_hurst(s, window=40)) == 100

    def test_no_inf_in_advanced(self):
        from ml.advanced_features import build_advanced_features

        df = _ohlcv()
        df.index = pd.date_range("2024-01-01", periods=len(df), freq="h")
        X, y = build_advanced_features(df)
        assert not np.isinf(X.select_dtypes(include=[np.number]).values).any()
