# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
portfolio/factor_model.py
=========================
Live Barra-style factor attribution engine.

Decomposes portfolio returns into systematic factor exposures (rates, vol,
momentum, carry, macro) and idiosyncratic alpha using PCA + OLS regression.

Architecture
------------
1. FactorLibrary   — builds the factor return matrix from live market data
2. FactorModel     — fits OLS betas per asset; updates incrementally on each bar
3. FactorAttribution — decomposes P&L into factor contributions + residual alpha
4. LiveFactorEngine  — async loop that refreshes exposures every ``interval_s``

Factor definitions
------------------
rates_factor    : daily change in US 10Y yield (FRED DGS10)
vol_factor      : daily change in realised 30-day vol of XAUUSD
momentum_factor : 20-day return of XAUUSD (cross-sectional momentum proxy)
carry_factor    : yield spread 10Y-2Y (term premium / carry)
macro_factor    : first PCA component of [DXY, CPI YoY, yield_spread]
dxy_factor      : daily change in Trade-Weighted USD Index (FRED DTWEXBGS)

Usage
-----
    from portfolio.factor_model import LiveFactorEngine, FactorAttribution

    engine = LiveFactorEngine()
    await engine.start()                        # background refresh loop

    attribution = engine.attribute(positions)   # dict of factor P&L
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import contextlib

logger = logging.getLogger(__name__)

# ── Factor names ──────────────────────────────────────────────────────────────

FACTOR_NAMES = [
    "rates_factor",
    "vol_factor",
    "momentum_factor",
    "carry_factor",
    "macro_factor",
    "dxy_factor",
]


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class FactorExposure:
    """Beta loadings of one asset to each systematic factor."""

    symbol: str
    betas: Dict[str, float]  # factor_name -> beta
    r_squared: float  # fraction of variance explained by factors
    residual_vol: float  # annualised idiosyncratic vol
    fitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "betas": self.betas,
            "r_squared": round(self.r_squared, 4),
            "residual_vol": round(self.residual_vol, 6),
            "fitted_at": self.fitted_at.isoformat(),
        }


@dataclass
class FactorAttribution:
    """P&L decomposition for a portfolio snapshot."""

    total_pnl: float
    factor_pnl: Dict[str, float]  # factor_name -> attributed P&L
    residual_pnl: float  # idiosyncratic / alpha
    factor_pct: Dict[str, float]  # factor_name -> % of total variance
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_pnl": round(self.total_pnl, 4),
            "factor_pnl": {k: round(v, 4) for k, v in self.factor_pnl.items()},
            "residual_pnl": round(self.residual_pnl, 4),
            "factor_pct": {k: round(v, 4) for k, v in self.factor_pct.items()},
            "computed_at": self.computed_at.isoformat(),
        }


# ── Factor Library ────────────────────────────────────────────────────────────


class FactorLibrary:
    """
    Builds the factor return matrix from live FRED + yfinance data.

    All factors are expressed as daily returns / changes so they are
    stationary and directly comparable across assets.
    """

    def __init__(self, lookback_days: int = 252):
        self.lookback_days = lookback_days
        self._factor_df: pd.DataFrame | None = None
        self._last_refresh: datetime | None = None
        self._cache_ttl_s: int = 3600  # refresh at most once per hour

    # ── public ────────────────────────────────────────────────────────────────

    def get_factor_matrix(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        Return a (T × F) DataFrame of daily factor returns.

        Columns: FACTOR_NAMES.  Index: DatetimeIndex (business days).
        Refreshes from live sources when cache is stale.
        """
        if force_refresh or self._is_stale():
            self._refresh()
        if self._factor_df is None or self._factor_df.empty:
            raise RuntimeError("Factor matrix unavailable — data fetch failed")
        return self._factor_df.copy()

    async def get_factor_matrix_async(self, force_refresh: bool = False) -> pd.DataFrame:
        """Async wrapper — runs the blocking refresh in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_factor_matrix, force_refresh)

    # ── internals ─────────────────────────────────────────────────────────────

    def _is_stale(self) -> bool:
        if self._last_refresh is None:
            return True
        age = (datetime.now(UTC) - self._last_refresh).total_seconds()
        return age > self._cache_ttl_s

    def _refresh(self) -> None:
        """Fetch all factor data and build the factor return matrix."""
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ImportError("yfinance is required for FactorLibrary") from exc

        end = pd.Timestamp.now(tz="UTC").normalize()
        start = end - pd.Timedelta(days=self.lookback_days + 30)

        # ── XAUUSD price series (for vol + momentum factors) ──────────────────
        xau = yf.download(
            "GC=F",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if xau.empty:
            raise RuntimeError("yfinance returned empty data for GC=F")

        xau_close = xau["Close"].squeeze()
        xau_ret = xau_close.pct_change().dropna()

        # ── Macro data from FRED ──────────────────────────────────────────────
        fred_data = self._fetch_fred_series()

        # ── Build factor columns ──────────────────────────────────────────────
        factors: Dict[str, pd.Series] = {}

        # rates_factor: daily change in 10Y yield
        if "yield_10y" in fred_data:
            factors["rates_factor"] = fred_data["yield_10y"].diff().dropna()

        # dxy_factor: daily change in DXY
        if "dxy" in fred_data:
            factors["dxy_factor"] = fred_data["dxy"].diff().dropna()

        # carry_factor: daily change in yield spread (10Y - 2Y)
        if "yield_10y" in fred_data and "yield_2y" in fred_data:
            spread = fred_data["yield_10y"] - fred_data["yield_2y"]
            factors["carry_factor"] = spread.diff().dropna()

        # vol_factor: daily change in 30-day realised vol of XAUUSD
        rvol = xau_ret.rolling(30).std() * np.sqrt(252)
        factors["vol_factor"] = rvol.diff().dropna()

        # momentum_factor: 20-day return of XAUUSD
        factors["momentum_factor"] = xau_close.pct_change(20).dropna()

        # macro_factor: first PCA component of [DXY change, CPI YoY, yield_spread]
        macro_inputs = {}
        if "dxy" in fred_data:
            macro_inputs["dxy_chg"] = fred_data["dxy"].pct_change().dropna()
        if "yield_10y" in fred_data and "yield_2y" in fred_data:
            macro_inputs["spread"] = (fred_data["yield_10y"] - fred_data["yield_2y"]).diff().dropna()
        if "cpi" in fred_data:
            macro_inputs["cpi_chg"] = fred_data["cpi"].pct_change().dropna()

        if len(macro_inputs) >= 2:
            macro_df = pd.DataFrame(macro_inputs).dropna()
            if len(macro_df) >= 10:
                scaler = StandardScaler()
                scaled = scaler.fit_transform(macro_df.values)
                pca = PCA(n_components=1)
                pc1 = pca.fit_transform(scaled).squeeze()
                factors["macro_factor"] = pd.Series(pc1, index=macro_df.index, name="macro_factor")

        # ── Align all factors to a common date index ──────────────────────────
        factor_df = pd.DataFrame(factors)
        # Forward-fill FRED daily series (published on business days only)
        factor_df = factor_df.ffill().dropna(how="all")
        # Keep only rows where at least 4 of 6 factors are available
        factor_df = factor_df.dropna(thresh=4)
        # Fill remaining NaN with 0 (neutral)
        factor_df = factor_df.fillna(0.0)
        # Ensure all expected columns exist
        for col in FACTOR_NAMES:
            if col not in factor_df.columns:
                factor_df[col] = 0.0
        factor_df = factor_df[FACTOR_NAMES]

        self._factor_df = factor_df.tail(self.lookback_days)
        self._last_refresh = datetime.now(UTC)
        logger.info(
            "FactorLibrary refreshed: %d rows, %d factors",
            len(self._factor_df),
            len(FACTOR_NAMES),
        )

    def _fetch_fred_series(self) -> Dict[str, pd.Series]:
        """Fetch DXY, 10Y yield, 2Y yield, CPI from FRED."""
        import requests

        fred_key = __import__("os").getenv("FRED_API_KEY", "")
        base = "https://api.stlouisfed.org/fred/series/observations"
        series_map = {
            "dxy": "DTWEXBGS",
            "yield_10y": "DGS10",
            "yield_2y": "DGS2",
            "cpi": "CPIAUCNS",
        }
        result: Dict[str, pd.Series] = {}
        for name, sid in series_map.items():
            params: Dict[str, Any] = {
                "series_id": sid,
                "sort_order": "asc",
                "limit": 500,
                "file_type": "json",
            }
            if fred_key:
                params["api_key"] = fred_key
            try:
                resp = requests.get(base, params=params, timeout=15)
                resp.raise_for_status()
                obs = resp.json().get("observations", [])
                rows = []
                for o in obs:
                    try:
                        rows.append({"date": pd.to_datetime(o["date"]), "value": float(o["value"])})
                    except (ValueError, KeyError):
                        continue
                if rows:
                    df = pd.DataFrame(rows).set_index("date")["value"]
                    df.index = pd.DatetimeIndex(df.index)
                    result[name] = df
            except Exception as exc:
                logger.warning("FRED fetch failed for %s (%s): %s", name, sid, exc)
        return result


# ── Factor Model (OLS regression per asset) ───────────────────────────────────


class FactorModel:
    """
    Fits Ridge regression betas for each asset against the factor matrix.

    beta_i = argmin ||r_i - F * beta||^2 + alpha * ||beta||^2

    Uses Ridge (L2) rather than OLS to handle multicollinearity between
    correlated macro factors (rates, carry, DXY are often correlated).
    """

    def __init__(self, alpha: float = 0.01, min_obs: int = 60):
        self.alpha = alpha  # Ridge regularisation
        self.min_obs = min_obs  # minimum observations to fit
        self._exposures: Dict[str, FactorExposure] = {}
        self._library = FactorLibrary()

    # ── public ────────────────────────────────────────────────────────────────

    def fit(self, asset_returns: Dict[str, pd.Series]) -> Dict[str, FactorExposure]:
        """
        Fit factor betas for each asset.

        Parameters
        ----------
        asset_returns : dict of symbol -> daily return Series (DatetimeIndex)

        Returns
        -------
        dict of symbol -> FactorExposure
        """
        factor_df = self._library.get_factor_matrix()

        for symbol, ret_series in asset_returns.items():
            try:
                exposure = self._fit_single(symbol, ret_series, factor_df)
                self._exposures[symbol] = exposure
            except Exception as exc:
                logger.warning("FactorModel.fit failed for %s: %s", symbol, exc)

        return self._exposures.copy()

    async def fit_async(self, asset_returns: Dict[str, pd.Series]) -> Dict[str, FactorExposure]:
        """Async wrapper for fit()."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fit, asset_returns)

    def get_exposure(self, symbol: str) -> FactorExposure | None:
        return self._exposures.get(symbol)

    def all_exposures(self) -> Dict[str, FactorExposure]:
        return self._exposures.copy()

    # ── internals ─────────────────────────────────────────────────────────────

    def _fit_single(
        self,
        symbol: str,
        ret_series: pd.Series,
        factor_df: pd.DataFrame,
    ) -> FactorExposure:
        """Fit Ridge regression for one asset."""
        # Align on common dates
        aligned = pd.concat([ret_series.rename("asset"), factor_df], axis=1).dropna()
        if len(aligned) < self.min_obs:
            raise ValueError(f"Insufficient data for {symbol}: {len(aligned)} < {self.min_obs}")

        y = aligned["asset"].values
        X = aligned[FACTOR_NAMES].values

        model = Ridge(alpha=self.alpha, fit_intercept=True)
        model.fit(X, y)

        y_pred = model.predict(X)
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        residuals = y - y_pred
        residual_vol = float(np.std(residuals) * np.sqrt(252))

        betas = {name: float(model.coef_[i]) for i, name in enumerate(FACTOR_NAMES)}

        return FactorExposure(
            symbol=symbol,
            betas=betas,
            r_squared=max(0.0, r2),
            residual_vol=residual_vol,
        )


# ── Factor Attribution ────────────────────────────────────────────────────────


class FactorAttributionEngine:
    """
    Decomposes portfolio P&L into factor contributions.

    P&L_factor_k = sum_i( w_i * beta_ik * F_k_today )

    where w_i is the dollar weight of asset i, beta_ik is its loading on
    factor k, and F_k_today is today's factor return.
    """

    def __init__(self, factor_model: FactorModel):
        self._model = factor_model
        self._library = factor_model._library

    def attribute(
        self,
        positions: Dict[str, float],  # symbol -> dollar value (signed)
        total_pnl: float,
    ) -> FactorAttribution:
        """
        Attribute total_pnl across factors.

        Parameters
        ----------
        positions   : {symbol: dollar_value}  (positive = long, negative = short)
        total_pnl   : realised P&L for the period being attributed

        Returns
        -------
        FactorAttribution
        """
        try:
            factor_df = self._library.get_factor_matrix()
        except RuntimeError as exc:
            logger.warning("FactorAttribution: factor matrix unavailable: %s", exc)
            return FactorAttribution(
                total_pnl=total_pnl,
                factor_pnl=dict.fromkeys(FACTOR_NAMES, 0.0),
                residual_pnl=total_pnl,
                factor_pct=dict.fromkeys(FACTOR_NAMES, 0.0),
            )

        # Latest factor returns (most recent row)
        latest_factors = factor_df.iloc[-1]

        factor_pnl: Dict[str, float] = dict.fromkeys(FACTOR_NAMES, 0.0)
        _total_weight = sum(abs(v) for v in positions.values())

        for symbol, dollar_value in positions.items():
            exposure = self._model.get_exposure(symbol)
            if exposure is None:
                continue
            for factor_name, beta in exposure.betas.items():
                factor_ret = float(latest_factors.get(factor_name, 0.0))
                # Contribution: dollar_value * beta * factor_return
                factor_pnl[factor_name] += dollar_value * beta * factor_ret

        explained_pnl = sum(factor_pnl.values())
        residual_pnl = total_pnl - explained_pnl

        # Factor % of total variance (|factor_pnl| / sum(|all|))
        total_abs = sum(abs(v) for v in factor_pnl.values()) + abs(residual_pnl)
        factor_pct = {k: abs(v) / total_abs if total_abs > 0 else 0.0 for k, v in factor_pnl.items()}

        return FactorAttribution(
            total_pnl=total_pnl,
            factor_pnl=factor_pnl,
            residual_pnl=residual_pnl,
            factor_pct=factor_pct,
        )

    def portfolio_factor_var(
        self,
        positions: Dict[str, float],
        factor_cov: pd.DataFrame | None = None,
    ) -> Dict[str, float]:
        """
        Compute factor-level VaR contributions using the factor covariance matrix.

        Returns dict of factor_name -> annualised factor VaR (95%, 1-day scaled).
        """
        try:
            factor_df = self._library.get_factor_matrix()
        except RuntimeError:
            return dict.fromkeys(FACTOR_NAMES, 0.0)

        if factor_cov is None:
            factor_cov = factor_df.cov()

        # Aggregate portfolio beta vector: beta_port_k = sum_i(w_i * beta_ik)
        total_value = sum(abs(v) for v in positions.values())
        if total_value == 0:
            return dict.fromkeys(FACTOR_NAMES, 0.0)

        beta_port = np.zeros(len(FACTOR_NAMES))
        for symbol, dollar_value in positions.items():
            exposure = self._model.get_exposure(symbol)
            if exposure is None:
                continue
            weight = dollar_value / total_value
            for i, fname in enumerate(FACTOR_NAMES):
                beta_port[i] += weight * exposure.betas.get(fname, 0.0)

        cov_matrix = factor_cov.loc[FACTOR_NAMES, FACTOR_NAMES].values
        # Factor variance contribution: beta_k^2 * sigma_k^2 (diagonal approx)
        factor_vols = np.sqrt(np.diag(cov_matrix)) * np.sqrt(252)
        z95 = 1.645

        return {
            FACTOR_NAMES[i]: float(abs(beta_port[i]) * factor_vols[i] * z95 * total_value)
            for i in range(len(FACTOR_NAMES))
        }


# ── Live Factor Engine (async background loop) ────────────────────────────────


class LiveFactorEngine:
    """
    Background async engine that keeps factor exposures current.

    Refreshes the factor matrix and re-fits betas every ``interval_s`` seconds.
    Exposes the latest attribution via ``attribute()`` and ``exposures``.

    Usage
    -----
        engine = LiveFactorEngine()
        await engine.start()
        attribution = engine.attribute(positions, total_pnl)
        await engine.stop()
    """

    def __init__(
        self,
        interval_s: int = 3600,
        symbols: List[str] | None = None,
    ):
        self.interval_s = interval_s
        self.symbols = symbols or ["XAU_USD", "BTC_USD", "ETH_USD"]
        self._model = FactorModel()
        self._attribution_engine = FactorAttributionEngine(self._model)
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_fit: datetime | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background refresh loop."""
        if self._running:
            return
        self._running = True
        # Initial fit (blocking, in executor)
        await self._fit_now()
        self._task = asyncio.create_task(self._loop())
        logger.info("LiveFactorEngine started (interval=%ds)", self.interval_s)

    async def stop(self) -> None:
        """Stop the background loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("LiveFactorEngine stopped")

    # ── public API ────────────────────────────────────────────────────────────

    def attribute(
        self,
        positions: Dict[str, float],
        total_pnl: float,
    ) -> FactorAttribution:
        """Attribute P&L to factors using the latest fitted betas."""
        return self._attribution_engine.attribute(positions, total_pnl)

    def factor_var(self, positions: Dict[str, float]) -> Dict[str, float]:
        """Return factor-level VaR contributions."""
        return self._attribution_engine.portfolio_factor_var(positions)

    @property
    def exposures(self) -> Dict[str, FactorExposure]:
        return self._model.all_exposures()

    @property
    def last_fit(self) -> datetime | None:
        return self._last_fit

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "last_fit": self._last_fit.isoformat() if self._last_fit else None,
            "symbols_fitted": list(self._model.all_exposures().keys()),
            "interval_s": self.interval_s,
        }

    # ── internals ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.interval_s)
            try:
                await self._fit_now()
            except Exception as exc:
                logger.error("LiveFactorEngine refresh failed: %s", exc)

    async def _fit_now(self) -> None:
        """Fetch asset returns and re-fit the factor model."""
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance not installed — cannot fit factor model")
            return

        symbol_map = {
            "XAU_USD": "GC=F",
            "BTC_USD": "BTC-USD",
            "ETH_USD": "ETH-USD",
            "XAUUSD": "GC=F",
        }

        end = pd.Timestamp.now(tz="UTC").normalize()
        start = end - pd.Timedelta(days=400)

        asset_returns: Dict[str, pd.Series] = {}
        for sym in self.symbols:
            ticker = symbol_map.get(sym, sym)
            try:
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda t=ticker: yf.download(
                        t,
                        start=start.strftime("%Y-%m-%d"),
                        end=end.strftime("%Y-%m-%d"),
                        progress=False,
                        auto_adjust=True,
                    ),
                )
                if not data.empty:
                    closes = data["Close"].squeeze()
                    asset_returns[sym] = closes.pct_change().dropna()
            except Exception as exc:
                logger.warning("LiveFactorEngine: failed to fetch %s: %s", sym, exc)

        if asset_returns:
            await self._model.fit_async(asset_returns)
            self._last_fit = datetime.now(UTC)
            logger.info(
                "LiveFactorEngine: fitted %d assets at %s",
                len(asset_returns),
                self._last_fit.isoformat(),
            )


# ── module-level singleton ────────────────────────────────────────────────────

_engine: LiveFactorEngine | None = None


def get_live_factor_engine() -> LiveFactorEngine:
    """Return the module-level LiveFactorEngine singleton (lazy init)."""
    global _engine
    if _engine is None:
        _engine = LiveFactorEngine()
    return _engine
