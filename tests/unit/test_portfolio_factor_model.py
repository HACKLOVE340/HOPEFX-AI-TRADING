# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`portfolio/factor_model.py` — Barra-style factor attribution and factor VaR.

Ridge betas per asset against a six-factor matrix, P&L decomposed into factor
contributions plus residual alpha, and a factor-level 95% VaR. Measured at 0%.

Two properties carry the module, and both are about honesty rather than
arithmetic:

1. **Conservation.** `total_pnl == sum(factor_pnl) + residual_pnl`, exactly.
   An attribution that does not add up is either inventing P&L or losing it, and
   either way somebody reads the factor rows as an explanation of a number they
   do not explain.

2. **Unexplained is residual, never attributed.** When the factor matrix cannot
   be built, every factor contribution is 0.0 and the whole P&L lands in
   residual. Spreading it across factors nothing measured would be a value
   nothing verified presented as though something had — with a risk number on
   the end of it.

`FactorLibrary.get_factor_matrix` is patched throughout: the real one reaches
FRED, and a test that needs the network is a test that silently stops running.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from portfolio.factor_model import (
    FACTOR_NAMES,
    FactorAttribution,
    FactorAttributionEngine,
    FactorExposure,
    FactorLibrary,
    FactorModel,
    LiveFactorEngine,
    get_live_factor_engine,
)


def _factor_matrix(rows: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2025-01-01", periods=rows, freq="D", tz="UTC")
    return pd.DataFrame({name: rng.normal(0, 0.01, rows) for name in FACTOR_NAMES}, index=index)


def _returns(factors: pd.DataFrame, betas: dict[str, float], noise: float = 0.0, seed: int = 3) -> pd.Series:
    """An asset return series built from known betas, so a fit has a right answer."""
    rng = np.random.default_rng(seed)
    series = sum(factors[name] * beta for name, beta in betas.items())
    if noise:
        series = series + rng.normal(0, noise, len(factors))
    return pd.Series(series, index=factors.index, name="asset")


def _exposure(symbol: str = "XAUUSD", **betas) -> FactorExposure:
    full = dict.fromkeys(FACTOR_NAMES, 0.0)
    full.update(betas)
    return FactorExposure(symbol=symbol, betas=full, r_squared=0.5, residual_vol=0.1)


class TestFittingBetas:
    def test_it_recovers_betas_it_was_given(self) -> None:
        """A fit that could not recover a known relationship would make every
        number downstream of it meaningless.

        Regularisation turned almost off, so this measures the regression rather
        than the shrinkage. The shrinkage at the real default is pinned by the
        test below.
        """
        factors = _factor_matrix()
        truth = {"rates_factor": 1.5, "vol_factor": -0.8}
        model = FactorModel(alpha=1e-9, min_obs=60)
        with patch.object(model._library, "get_factor_matrix", return_value=factors):
            exposures = model.fit({"XAUUSD": _returns(factors, truth)})

        betas = exposures["XAUUSD"].betas
        assert betas["rates_factor"] == pytest.approx(1.5, abs=0.05)
        assert betas["vol_factor"] == pytest.approx(-0.8, abs=0.05)

    def test_the_default_ridge_penalty_shrinks_betas_substantially(self) -> None:
        """Measured, not assumed, because it is easy to read a beta off this
        model as the asset's true sensitivity.

        The factors here have a daily standard deviation around 0.01, so
        `X'X` is small and the default `alpha=0.01` is comparable to it. A true
        beta of 1.5 comes back near 1.08 — roughly a 28% shrink toward zero.
        That is Ridge working as intended and it is the documented reason for
        choosing it (correlated macro factors), but a factor VaR built on these
        betas is correspondingly conservative, and anyone changing `alpha`
        changes every downstream risk number.
        """
        factors = _factor_matrix()
        model = FactorModel(min_obs=60)  # the production default, alpha=0.01
        with patch.object(model._library, "get_factor_matrix", return_value=factors):
            fitted = model.fit({"XAUUSD": _returns(factors, {"rates_factor": 1.5})})["XAUUSD"]

        beta = fitted.betas["rates_factor"]
        assert 0 < beta < 1.5, "the ridge penalty should shrink toward zero, not past it or beyond it"
        assert beta == pytest.approx(1.08, abs=0.1)

    def test_an_asset_with_too_little_history_gets_no_exposure(self) -> None:
        """Not a fabricated one. Fewer observations than `min_obs` and the asset
        is absent from the result, so a caller cannot mistake a guess for a fit."""
        factors = _factor_matrix(rows=300)
        short = _returns(factors, {"rates_factor": 1.0}).iloc[:10]
        model = FactorModel(min_obs=60)
        with patch.object(model._library, "get_factor_matrix", return_value=factors):
            exposures = model.fit({"THIN": short})
        assert "THIN" not in exposures
        assert model.get_exposure("THIN") is None

    def test_one_failing_asset_does_not_lose_the_others(self) -> None:
        """A portfolio fit that aborted on its worst asset would leave every
        other position unattributed."""
        factors = _factor_matrix()
        good = _returns(factors, {"rates_factor": 1.0})
        model = FactorModel(min_obs=60)
        with patch.object(model._library, "get_factor_matrix", return_value=factors):
            exposures = model.fit({"THIN": good.iloc[:5], "GOOD": good})
        assert set(exposures) == {"GOOD"}

    def test_r_squared_is_never_negative(self) -> None:
        """Clamped at zero. A negative R^2 is real in regression and reads as a
        corrupt number on a dashboard."""
        factors = _factor_matrix()
        model = FactorModel(min_obs=60)
        with patch.object(model._library, "get_factor_matrix", return_value=factors):
            exposures = model.fit({"NOISE": _returns(factors, {}, noise=0.05)})
        assert exposures["NOISE"].r_squared >= 0.0

    def test_a_flat_return_series_does_not_divide_by_zero(self) -> None:
        """Zero total variance: R^2 is reported as 0.0 rather than raising or
        producing a NaN that propagates into a risk number."""
        factors = _factor_matrix()
        flat = pd.Series(0.0, index=factors.index)
        model = FactorModel(min_obs=60)
        with patch.object(model._library, "get_factor_matrix", return_value=factors):
            exposures = model.fit({"FLAT": flat})
        assert exposures["FLAT"].r_squared == 0.0
        assert not np.isnan(exposures["FLAT"].residual_vol)

    def test_every_factor_gets_a_beta(self) -> None:
        factors = _factor_matrix()
        model = FactorModel(min_obs=60)
        with patch.object(model._library, "get_factor_matrix", return_value=factors):
            exposures = model.fit({"XAUUSD": _returns(factors, {"carry_factor": 0.4})})
        assert set(exposures["XAUUSD"].betas) == set(FACTOR_NAMES)

    def test_exposures_are_handed_out_as_copies(self) -> None:
        """A caller mutating the returned dict must not edit the model's state."""
        factors = _factor_matrix()
        model = FactorModel(min_obs=60)
        with patch.object(model._library, "get_factor_matrix", return_value=factors):
            model.fit({"XAUUSD": _returns(factors, {"carry_factor": 0.4})})
        handed = model.all_exposures()
        handed.pop("XAUUSD")
        assert model.get_exposure("XAUUSD") is not None


class TestAttributionConserves:
    """The identity the decomposition rests on."""

    def _engine(self, *exposures: FactorExposure) -> FactorAttributionEngine:
        model = FactorModel(min_obs=60)
        for e in exposures:
            model._exposures[e.symbol] = e
        return FactorAttributionEngine(model)

    def test_factor_and_residual_add_back_to_the_total(self) -> None:
        engine = self._engine(_exposure("XAUUSD", rates_factor=1.2, vol_factor=-0.4))
        factors = _factor_matrix()
        with patch.object(engine._library, "get_factor_matrix", return_value=factors):
            result = engine.attribute({"XAUUSD": 100_000.0}, total_pnl=1_234.56)
        assert sum(result.factor_pnl.values()) + result.residual_pnl == pytest.approx(1_234.56, abs=1e-6)

    @pytest.mark.parametrize("pnl", [0.0, 500.0, -500.0, 1e6, -1e6])
    def test_it_conserves_for_gains_and_losses_alike(self, pnl: float) -> None:
        engine = self._engine(_exposure("XAUUSD", momentum_factor=0.9))
        factors = _factor_matrix()
        with patch.object(engine._library, "get_factor_matrix", return_value=factors):
            result = engine.attribute({"XAUUSD": -50_000.0}, total_pnl=pnl)
        assert sum(result.factor_pnl.values()) + result.residual_pnl == pytest.approx(pnl, rel=1e-9, abs=1e-6)

    def test_a_symbol_with_no_exposure_contributes_nothing(self) -> None:
        """And the P&L it carried stays in residual rather than being spread
        across the factors of the assets that were fitted."""
        engine = self._engine(_exposure("XAUUSD", rates_factor=1.0))
        factors = _factor_matrix()
        with patch.object(engine._library, "get_factor_matrix", return_value=factors):
            known = engine.attribute({"XAUUSD": 100_000.0}, total_pnl=1000.0)
            plus_unknown = engine.attribute({"XAUUSD": 100_000.0, "MYSTERY": 100_000.0}, total_pnl=1000.0)
        assert plus_unknown.factor_pnl == known.factor_pnl
        assert plus_unknown.residual_pnl == pytest.approx(known.residual_pnl)


class TestWhatCannotBeMeasuredIsNotAttributed:
    def _engine(self) -> FactorAttributionEngine:
        model = FactorModel(min_obs=60)
        model._exposures["XAUUSD"] = _exposure("XAUUSD", rates_factor=1.0)
        return FactorAttributionEngine(model)

    def test_an_unavailable_factor_matrix_puts_everything_in_residual(self) -> None:
        engine = self._engine()
        with patch.object(engine._library, "get_factor_matrix", side_effect=RuntimeError("FRED unreachable")):
            result = engine.attribute({"XAUUSD": 100_000.0}, total_pnl=777.0)
        assert result.residual_pnl == 777.0
        assert set(result.factor_pnl.values()) == {0.0}
        assert set(result.factor_pct.values()) == {0.0}

    def test_it_still_conserves_when_nothing_could_be_measured(self) -> None:
        engine = self._engine()
        with patch.object(engine._library, "get_factor_matrix", side_effect=RuntimeError("down")):
            result = engine.attribute({"XAUUSD": 1.0}, total_pnl=-42.0)
        assert sum(result.factor_pnl.values()) + result.residual_pnl == pytest.approx(-42.0)

    def test_an_unavailable_matrix_reports_zero_var_not_a_guess(self) -> None:
        engine = self._engine()
        with patch.object(engine._library, "get_factor_matrix", side_effect=RuntimeError("down")):
            var = engine.portfolio_factor_var({"XAUUSD": 100_000.0})
        assert set(var) == set(FACTOR_NAMES)
        assert set(var.values()) == {0.0}


class TestFactorVaR:
    def _engine(self, *exposures: FactorExposure) -> FactorAttributionEngine:
        model = FactorModel(min_obs=60)
        for e in exposures:
            model._exposures[e.symbol] = e
        return FactorAttributionEngine(model)

    def test_an_empty_portfolio_has_no_factor_var(self) -> None:
        """Zero exposure is zero risk, and dividing by a zero book would be a
        NaN reported as a VaR."""
        engine = self._engine(_exposure("XAUUSD", rates_factor=1.0))
        factors = _factor_matrix()
        with patch.object(engine._library, "get_factor_matrix", return_value=factors):
            var = engine.portfolio_factor_var({})
        assert set(var.values()) == {0.0}

    def test_every_factor_var_is_non_negative(self) -> None:
        """VaR is a magnitude. A negative one would read as a position that
        makes money in the tail."""
        engine = self._engine(_exposure("XAUUSD", rates_factor=-2.0, vol_factor=1.0))
        factors = _factor_matrix()
        with patch.object(engine._library, "get_factor_matrix", return_value=factors):
            var = engine.portfolio_factor_var({"XAUUSD": -250_000.0})
        assert all(v >= 0.0 for v in var.values()), var

    def test_var_scales_with_the_size_of_the_book(self) -> None:
        """Doubling every position must not leave the risk number unchanged."""
        engine = self._engine(_exposure("XAUUSD", rates_factor=1.5))
        factors = _factor_matrix()
        with patch.object(engine._library, "get_factor_matrix", return_value=factors):
            small = engine.portfolio_factor_var({"XAUUSD": 100_000.0})
            large = engine.portfolio_factor_var({"XAUUSD": 200_000.0})
        assert large["rates_factor"] == pytest.approx(2 * small["rates_factor"], rel=1e-9)

    def test_a_larger_beta_carries_more_factor_risk(self) -> None:
        factors = _factor_matrix()
        timid = self._engine(_exposure("XAUUSD", rates_factor=0.1))
        bold = self._engine(_exposure("XAUUSD", rates_factor=3.0))
        with patch.object(timid._library, "get_factor_matrix", return_value=factors):
            low = timid.portfolio_factor_var({"XAUUSD": 100_000.0})
        with patch.object(bold._library, "get_factor_matrix", return_value=factors):
            high = bold.portfolio_factor_var({"XAUUSD": 100_000.0})
        assert high["rates_factor"] > low["rates_factor"]

    def test_a_nan_in_the_covariance_does_not_become_a_nan_var(self) -> None:
        """A NaN risk number compares false against every limit, so a breach
        reads as a pass."""
        engine = self._engine(_exposure("XAUUSD", rates_factor=1.0))
        factors = _factor_matrix()
        cov = factors.cov()
        cov.iloc[0, 0] = float("nan")
        with patch.object(engine._library, "get_factor_matrix", return_value=factors):
            var = engine.portfolio_factor_var({"XAUUSD": 100_000.0}, factor_cov=cov)
        assert not any(np.isnan(v) for v in var.values()), var


class TestTheReportedShapes:
    def test_an_exposure_serialises_every_field(self) -> None:
        payload = _exposure("XAUUSD", rates_factor=1.0).to_dict()
        assert payload["symbol"] == "XAUUSD"
        assert set(payload["betas"]) == set(FACTOR_NAMES)
        assert "r_squared" in payload and "residual_vol" in payload

    def test_an_attribution_serialises_every_field(self) -> None:
        attribution = FactorAttribution(
            total_pnl=100.0,
            factor_pnl=dict.fromkeys(FACTOR_NAMES, 1.0),
            residual_pnl=94.0,
            factor_pct=dict.fromkeys(FACTOR_NAMES, 0.01),
        )
        payload = attribution.to_dict()
        assert payload["total_pnl"] == 100.0
        assert payload["residual_pnl"] == 94.0
        assert set(payload["factor_pnl"]) == set(FACTOR_NAMES)


class TestTheFactorMatrixCache:
    """`get_factor_matrix` is the single door to the factor data, and its
    refusal is the one that keeps a fabricated matrix out of every risk number
    downstream."""

    def test_a_fresh_library_is_stale(self) -> None:
        """Never refreshed is stale, not fresh. The opposite default would
        serve an empty matrix once and never try again."""
        assert FactorLibrary()._is_stale() is True

    def test_a_recent_refresh_is_not_stale(self) -> None:
        library = FactorLibrary()
        library._last_refresh = datetime.now(UTC)
        assert library._is_stale() is False

    def test_an_old_refresh_is_stale_again(self) -> None:
        library = FactorLibrary()
        library._last_refresh = datetime.now(UTC) - timedelta(seconds=library._cache_ttl_s + 1)
        assert library._is_stale() is True

    def test_it_refuses_rather_than_returning_an_empty_matrix(self) -> None:
        """Fail-closed. An empty frame here would propagate as zero factor
        returns — every attribution silently 'explained' as zero and every
        factor VaR zero, which reads as a flat, riskless book."""
        library = FactorLibrary()
        with patch.object(library, "_refresh", return_value=None):
            with pytest.raises(RuntimeError, match="unavailable"):
                library.get_factor_matrix()

    def test_it_refuses_when_the_refresh_produced_an_empty_frame(self) -> None:
        library = FactorLibrary()

        def _empty():
            library._factor_df = pd.DataFrame()

        with patch.object(library, "_refresh", side_effect=_empty):
            with pytest.raises(RuntimeError, match="unavailable"):
                library.get_factor_matrix()

    def test_a_cached_matrix_is_served_without_refetching(self) -> None:
        library = FactorLibrary()
        library._factor_df = _factor_matrix(rows=80)
        library._last_refresh = datetime.now(UTC)
        with patch.object(library, "_refresh", side_effect=AssertionError("must not refetch")) as refresh:
            frame = library.get_factor_matrix()
        refresh.assert_not_called()
        assert len(frame) == 80

    def test_the_caller_gets_a_copy_it_cannot_corrupt(self) -> None:
        """Every consumer of the factor matrix shares this object. A caller
        mutating it would change the factors every other risk number is
        computed from."""
        library = FactorLibrary()
        library._factor_df = _factor_matrix(rows=80)
        library._last_refresh = datetime.now(UTC)
        handed = library.get_factor_matrix()
        handed.iloc[0, 0] = 999.0
        assert library._factor_df.iloc[0, 0] != 999.0

    def test_force_refresh_refetches_even_when_fresh(self) -> None:
        library = FactorLibrary()
        library._factor_df = _factor_matrix(rows=80)
        library._last_refresh = datetime.now(UTC)
        with patch.object(library, "_refresh") as refresh:
            library.get_factor_matrix(force_refresh=True)
        refresh.assert_called_once()


class TestTheLiveEngine:
    def test_a_fresh_engine_reports_not_running_and_never_fitted(self) -> None:
        status = LiveFactorEngine().status()
        assert status["running"] is False
        assert status["last_fit"] is None
        assert status["symbols_fitted"] == []

    def test_status_names_the_symbols_actually_fitted(self) -> None:
        """Not the symbols it was asked to fit. An engine listing a symbol it
        failed to fit would report coverage it does not have."""
        engine = LiveFactorEngine(symbols=["XAU_USD", "BTC_USD"])
        engine._model._exposures["XAU_USD"] = _exposure("XAU_USD", rates_factor=1.0)
        assert engine.status()["symbols_fitted"] == ["XAU_USD"]

    def test_last_fit_is_none_until_a_fit_happens(self) -> None:
        assert LiveFactorEngine().last_fit is None

    def test_it_exposes_the_interval_it_is_running_on(self) -> None:
        assert LiveFactorEngine(interval_s=42).status()["interval_s"] == 42

    def test_attribution_delegates_to_the_fitted_model(self) -> None:
        engine = LiveFactorEngine()
        engine._model._exposures["XAUUSD"] = _exposure("XAUUSD", rates_factor=1.0)
        factors = _factor_matrix()
        with patch.object(engine._attribution_engine._library, "get_factor_matrix", return_value=factors):
            result = engine.attribute({"XAUUSD": 100_000.0}, total_pnl=500.0)
        assert sum(result.factor_pnl.values()) + result.residual_pnl == pytest.approx(500.0)

    def test_factor_var_delegates_to_the_fitted_model(self) -> None:
        engine = LiveFactorEngine()
        engine._model._exposures["XAUUSD"] = _exposure("XAUUSD", rates_factor=1.0)
        factors = _factor_matrix()
        with patch.object(engine._attribution_engine._library, "get_factor_matrix", return_value=factors):
            var = engine.factor_var({"XAUUSD": 100_000.0})
        assert set(var) == set(FACTOR_NAMES)
        assert all(v >= 0 for v in var.values())

    def test_exposures_are_read_through_to_the_model(self) -> None:
        engine = LiveFactorEngine()
        engine._model._exposures["XAUUSD"] = _exposure("XAUUSD")
        assert set(engine.exposures) == {"XAUUSD"}

    def test_stopping_an_engine_that_never_started_is_safe(self) -> None:
        asyncio.run(LiveFactorEngine().stop())

    def test_starting_twice_does_not_start_two_loops(self) -> None:
        """A second loop would double the fit rate and the API calls behind it."""
        engine = LiveFactorEngine()
        engine._running = True
        with patch.object(engine, "_fit_now", side_effect=AssertionError("must not re-fit")):
            asyncio.run(engine.start())

    def test_a_failing_refit_does_not_kill_the_loop(self) -> None:
        """Nothing restarts it. A loop that died on one bad fetch would leave
        the exposures frozen at whatever they were, with no error afterwards."""
        engine = LiveFactorEngine(interval_s=0)
        engine._running = True
        calls: list[int] = []

        async def flaky():
            calls.append(1)
            if len(calls) >= 3:
                engine._running = False
            raise RuntimeError("yfinance timeout")

        with patch.object(engine, "_fit_now", side_effect=flaky):
            asyncio.run(engine._loop())
        assert len(calls) == 3


class TestTheModuleSingleton:
    def test_it_hands_back_one_engine(self) -> None:
        assert get_live_factor_engine() is get_live_factor_engine()


def _fred(days: int = 400, *, keys=("dxy", "yield_10y", "yield_2y", "cpi")) -> dict[str, pd.Series]:
    """A FRED payload shaped like the real one, without the network."""
    rng = np.random.default_rng(11)
    index = pd.date_range("2024-01-01", periods=days, freq="D")
    base = {
        "dxy": 100 + np.cumsum(rng.normal(0, 0.2, days)),
        "yield_10y": 4.0 + np.cumsum(rng.normal(0, 0.02, days)),
        "yield_2y": 4.5 + np.cumsum(rng.normal(0, 0.02, days)),
        "cpi": 300 + np.cumsum(rng.normal(0, 0.1, days)),
    }
    return {k: pd.Series(base[k], index=index) for k in keys}


def _yf_frame(days: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(5)
    index = pd.date_range("2024-01-01", periods=days, freq="D")
    close = 2000 + np.cumsum(rng.normal(0, 5, days))
    return pd.DataFrame({"Close": close}, index=index)


class TestBuildingTheFactorMatrix:
    """`_refresh` turns a gold price series and four FRED series into the six
    factor columns every downstream risk number is regressed against.

    The property that matters is not which numbers come out but that the SHAPE
    is always the same. A consumer indexes `factor_df[FACTOR_NAMES]`; a missing
    column is a KeyError inside a risk calculation, and a silently absent factor
    is an exposure nobody is measuring.
    """

    @staticmethod
    def _refresh_with(yf_frame, fred, lookback: int = 252) -> FactorLibrary:
        library = FactorLibrary(lookback_days=lookback)
        fake_yf = type("M", (), {"download": staticmethod(lambda *a, **k: yf_frame)})
        with (
            patch.dict(sys.modules, {"yfinance": fake_yf}),
            patch.object(library, "_fetch_fred_series", return_value=fred),
        ):
            library._refresh()
        return library

    def test_it_produces_every_declared_factor_column(self) -> None:
        library = self._refresh_with(_yf_frame(), _fred())
        assert list(library._factor_df.columns) == FACTOR_NAMES

    def test_a_missing_fred_series_still_leaves_every_column(self) -> None:
        """FRED being partly down must not change the matrix's shape. The
        absent factors are filled with 0.0 — neutral — rather than dropped,
        because a dropped column is a KeyError in a VaR calculation."""
        library = self._refresh_with(_yf_frame(), _fred(keys=("dxy",)))
        assert list(library._factor_df.columns) == FACTOR_NAMES
        assert not library._factor_df.isna().any().any()

    def test_no_fred_data_at_all_still_leaves_every_column(self) -> None:
        library = self._refresh_with(_yf_frame(), {})
        assert list(library._factor_df.columns) == FACTOR_NAMES

    def test_an_empty_price_series_refuses_rather_than_building_nothing(self) -> None:
        """Fail-closed at the source. A matrix built with no gold price would
        carry vol and momentum factors derived from an empty series."""
        library = FactorLibrary()
        fake_yf = type("M", (), {"download": staticmethod(lambda *a, **k: pd.DataFrame())})
        with (
            patch.dict(sys.modules, {"yfinance": fake_yf}),
            patch.object(library, "_fetch_fred_series", return_value=_fred()),
        ):
            with pytest.raises(RuntimeError, match="empty data"):
                library._refresh()

    def test_it_keeps_only_the_lookback_window(self) -> None:
        library = self._refresh_with(_yf_frame(days=500), _fred(days=500), lookback=60)
        assert len(library._factor_df) <= 60

    def test_a_successful_refresh_marks_the_cache_fresh(self) -> None:
        """Without this the library refetches on every call and the hourly TTL
        is decorative."""
        library = self._refresh_with(_yf_frame(), _fred())
        assert library._last_refresh is not None
        assert library._is_stale() is False

    def test_the_matrix_carries_no_nan(self) -> None:
        """A NaN factor return propagates into a beta, then into a VaR, and a
        NaN VaR compares false against every limit — so a breach reads as a
        pass."""
        library = self._refresh_with(_yf_frame(), _fred())
        assert not library._factor_df.isna().any().any()

    def test_the_refreshed_matrix_is_servable(self) -> None:
        """End to end: refresh, then the public door hands it out."""
        library = self._refresh_with(_yf_frame(), _fred())
        frame = library.get_factor_matrix()
        assert list(frame.columns) == FACTOR_NAMES
        assert len(frame) > 0


class TestFetchingTheMacroSeries:
    """`_fetch_fred_series` pulls four series and tolerates losing any of them.

    Partial failure is the normal case: FRED publishes on business days, a
    series can 404, and the whole risk stack must not go dark because CPI was
    briefly unavailable. So each series is fetched inside its own `try`, and
    what comes back is what succeeded — never a placeholder for what did not.
    """

    @staticmethod
    def _response(observations, *, raises=None, status_error=None):
        class _Resp:
            def raise_for_status(self):
                if status_error:
                    raise status_error

            def json(self):
                return {"observations": observations}

        def _get(*_a, **_k):
            if raises:
                raise raises
            return _Resp()

        return _get

    def _fetch(self, getter) -> dict[str, pd.Series]:
        import requests

        with patch.object(requests, "get", side_effect=getter):
            return FactorLibrary()._fetch_fred_series()

    def test_it_returns_every_series_that_answered(self) -> None:
        obs = [{"date": f"2025-01-0{i + 1}", "value": str(100 + i)} for i in range(9)]
        result = self._fetch(self._response(obs))
        assert set(result) == {"dxy", "yield_10y", "yield_2y", "cpi"}
        assert all(isinstance(s, pd.Series) and len(s) == 9 for s in result.values())

    def test_a_network_failure_yields_nothing_rather_than_raising(self) -> None:
        """The caller handles an empty dict by filling those factors with 0.0.
        An exception here would take the whole refresh down with it."""
        result = self._fetch(self._response([], raises=OSError("connection reset")))
        assert result == {}

    def test_an_http_error_yields_nothing_rather_than_raising(self) -> None:
        result = self._fetch(self._response([], status_error=RuntimeError("503")))
        assert result == {}

    def test_unparseable_observations_are_skipped_not_fatal(self) -> None:
        """FRED writes '.' for a missing value. One bad row must not discard the
        series around it."""
        obs = [
            {"date": "2025-01-01", "value": "100.0"},
            {"date": "2025-01-02", "value": "."},
            {"date": "2025-01-03", "value": "102.0"},
            {"value": "103.0"},
        ]
        result = self._fetch(self._response(obs))
        assert all(len(s) == 2 for s in result.values()), {k: len(v) for k, v in result.items()}

    def test_a_series_with_no_usable_rows_is_omitted_entirely(self) -> None:
        """Omitted, not present-and-empty. An empty series would propagate as a
        factor column of NaN rather than as an absent factor."""
        result = self._fetch(self._response([{"date": "2025-01-01", "value": "."}]))
        assert result == {}

    def test_every_returned_series_has_a_datetime_index(self) -> None:
        """The refresh aligns these against the gold price series by index; a
        string index would align nothing and produce an all-NaN matrix."""
        obs = [{"date": f"2025-01-0{i + 1}", "value": str(100 + i)} for i in range(5)]
        for series in self._fetch(self._response(obs)).values():
            assert isinstance(series.index, pd.DatetimeIndex)
