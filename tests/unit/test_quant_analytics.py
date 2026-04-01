# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for api/quant_analytics.py

Coverage:
- Input validation (HTTP 400) for every POST endpoint.
- Happy-path shape checks via mocked underlying modules.
- GET endpoints return 200 or 500 (module unavailable) — never crash the server.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.quant_analytics import (
    HRPRequest,
    BLRequest,
    DSRRequest,
    HARRVRequest,
    EVTRequest,
    CapacityRequest,
    LaVaRRequest,
    router as quant_router,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(quant_router)
    return TestClient(app, raise_server_exceptions=False)


# Minimal synthetic returns for tests (30 daily values)
_RETURNS_A = [0.001 * (i % 7 - 3) for i in range(30)]
_RETURNS_B = [0.002 * (i % 5 - 2) for i in range(30)]

# Returns dict with two assets — used for portfolio endpoints
_RETURNS_DICT = {"XAUUSD": _RETURNS_A, "EURUSD": _RETURNS_B}


# ── Pydantic model validation ─────────────────────────────────────────────────

@pytest.mark.unit
class TestQuantRequestModels:
    """Pydantic model defaults and validation."""

    def test_hrp_request_defaults(self):
        req = HRPRequest(returns=_RETURNS_DICT)
        assert req.linkage_method == "single"
        assert req.frequency == 252  # noqa: PLR2004

    def test_bl_request_defaults(self):
        req = BLRequest(returns=_RETURNS_DICT)
        assert req.risk_aversion == 2.5  # noqa: PLR2004
        assert req.tau == 0.05  # noqa: PLR2004
        assert req.market_caps is None
        assert req.views is None

    def test_dsr_request_defaults(self):
        req = DSRRequest(returns_list=[_RETURNS_A])
        assert req.frequency == 252  # noqa: PLR2004
        assert req.sr_benchmark == 0.0

    def test_harrv_request_defaults(self):
        req = HARRVRequest(rv_series=_RETURNS_A)
        assert req.method == "parkinson"

    def test_evt_request_defaults(self):
        req = EVTRequest(returns=_RETURNS_A)
        assert req.threshold_quantile == 0.90  # noqa: PLR2004

    def test_lavar_request_defaults(self):
        req = LaVaRRequest(returns=_RETURNS_A, position_value=100_000.0)
        assert req.avg_spread_pct == 0.0002  # noqa: PLR2004
        assert req.confidence == 0.99  # noqa: PLR2004


# ── Input validation (HTTP 400) ───────────────────────────────────────────────

@pytest.mark.unit
class TestQuantEndpointInputValidation:
    """POST endpoints must return 400 for semantically invalid input."""

    def setup_method(self):
        self.client = _make_client()

    # HRP — fewer than 5 rows triggers an explicit 400 inside the handler.
    # The import of portfolio.hrp is mocked so the validation guard is reached.
    def test_hrp_insufficient_data(self):
        mock_hrp_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"portfolio.hrp": types.SimpleNamespace(HRP=mock_hrp_cls)},
        ):
            resp = self.client.post(
                "/api/quant/hrp/optimise",
                json={"returns": {"A": [0.01, 0.02], "B": [0.03, 0.01]}},
            )
        assert resp.status_code == 400  # noqa: PLR2004

    def test_hrp_empty_returns(self):
        mock_hrp_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"portfolio.hrp": types.SimpleNamespace(HRP=mock_hrp_cls)},
        ):
            resp = self.client.post(
                "/api/quant/hrp/optimise",
                json={"returns": {}},
            )
        assert resp.status_code == 400  # noqa: PLR2004

    # DSR — empty returns_list triggers an explicit 400.
    # Mock the import so the guard is reached.
    def test_dsr_empty_returns_list(self):
        mock_fn = MagicMock()
        with patch.dict(
            "sys.modules",
            {"ml.deflated_sharpe": types.SimpleNamespace(deflated_sharpe_ratio=mock_fn)},
        ):
            resp = self.client.post(
                "/api/quant/deflated-sharpe",
                json={"returns_list": []},
            )
        assert resp.status_code == 400  # noqa: PLR2004

    # HAR-RV — omitting both ohlcv and rv_series triggers an explicit 400.
    def test_harrv_no_data(self):
        mock_harv_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "ml.realized_vol": types.SimpleNamespace(
                    HARV=mock_harv_cls,
                    daily_rv_from_ohlcv=MagicMock(),
                )
            },
        ):
            resp = self.client.post(
                "/api/quant/realized-vol/har-rv",
                json={},
            )
        assert resp.status_code == 400  # noqa: PLR2004

    # Pydantic rejects missing required fields with 422
    def test_hrp_missing_returns_field(self):
        resp = self.client.post("/api/quant/hrp/optimise", json={})
        assert resp.status_code == 422  # noqa: PLR2004

    def test_lavar_missing_position_value(self):
        resp = self.client.post(
            "/api/quant/lavar",
            json={"returns": _RETURNS_A},
        )
        assert resp.status_code == 422  # noqa: PLR2004

    def test_capacity_missing_volume(self):
        resp = self.client.post(
            "/api/quant/capacity/estimate",
            json={"returns": _RETURNS_A},
        )
        assert resp.status_code == 422  # noqa: PLR2004


# ── Happy-path with mocked underlying modules ─────────────────────────────────

@pytest.mark.unit
class TestQuantEndpointHappyPath:
    """Endpoints return 200 and the expected response keys when internals succeed."""

    def setup_method(self):
        self.client = _make_client()

    # ── HRP ───────────────────────────────────────────────────────────────────

    def test_hrp_success(self):
        mock_result = MagicMock(
            weights={"XAUUSD": 0.6, "EURUSD": 0.4},
            cluster_order=["XAUUSD", "EURUSD"],
            diversification_ratio=1.2,
            portfolio_vol=0.08,
        )
        mock_hrp = MagicMock()
        mock_hrp.fit.return_value = mock_result
        mock_hrp_cls = MagicMock(return_value=mock_hrp)

        with patch.dict("sys.modules", {"portfolio.hrp": types.SimpleNamespace(HRP=mock_hrp_cls)}):
            resp = self.client.post(
                "/api/quant/hrp/optimise",
                json={
                    "returns": {k: v * 10 for k, v in _RETURNS_DICT.items()},
                    # 30 rows per asset → satisfies the ≥ 5 row guard
                },
            )
        assert resp.status_code == 200  # noqa: PLR2004
        body = resp.json()
        assert "weights" in body
        assert "cluster_order" in body
        assert "diversification_ratio" in body
        assert "portfolio_vol_annualised" in body

    # ── Black-Litterman ───────────────────────────────────────────────────────

    def test_black_litterman_success(self):
        mock_result = MagicMock(
            weights={"XAUUSD": 0.5, "EURUSD": 0.5},
            bl_returns={"XAUUSD": 0.07, "EURUSD": 0.05},
            assets=["XAUUSD", "EURUSD"],
        )
        mock_bl = MagicMock()
        mock_bl.fit.return_value = mock_result
        mock_bl_cls = MagicMock(return_value=mock_bl)

        with patch.dict(
            "sys.modules",
            {"portfolio.black_litterman": types.SimpleNamespace(BlackLitterman=mock_bl_cls)},
        ):
            resp = self.client.post(
                "/api/quant/black-litterman/optimise",
                json={"returns": _RETURNS_DICT},
            )
        assert resp.status_code == 200  # noqa: PLR2004
        body = resp.json()
        assert "weights" in body
        assert "bl_returns" in body
        assert "assets" in body

    # ── Deflated Sharpe ───────────────────────────────────────────────────────

    def test_deflated_sharpe_success(self):
        mock_result = MagicMock(
            sharpe_ratio=1.5,
            psr=0.95,
            dsr=0.90,
            skewness=-0.3,
            kurtosis=3.2,
            n_observations=252,
            n_trials=1,
            sr_benchmark=0.0,
        )
        mock_fn = MagicMock(return_value=mock_result)

        with patch.dict(
            "sys.modules",
            {"ml.deflated_sharpe": types.SimpleNamespace(deflated_sharpe_ratio=mock_fn)},
        ):
            resp = self.client.post(
                "/api/quant/deflated-sharpe",
                json={"returns_list": [_RETURNS_A, _RETURNS_B]},
            )
        assert resp.status_code == 200  # noqa: PLR2004
        body = resp.json()
        for key in ("sharpe_ratio", "psr", "dsr", "n_observations", "n_trials"):
            assert key in body

    # ── HAR-RV ────────────────────────────────────────────────────────────────

    def test_harrv_from_rv_series_success(self):
        mock_result = MagicMock(
            forecast_1d=0.0012,
            forecast_5d=0.0015,
            forecast_22d=0.0018,
            r_squared=0.82,
            model_coeffs={"beta_d": 0.4, "beta_w": 0.3, "beta_m": 0.2},
            n_observations=200,
        )
        mock_harv = MagicMock()
        mock_harv.fit.return_value = mock_result
        mock_harv_cls = MagicMock(return_value=mock_harv)

        with patch.dict(
            "sys.modules",
            {
                "ml.realized_vol": types.SimpleNamespace(
                    HARV=mock_harv_cls,
                    daily_rv_from_ohlcv=MagicMock(),
                )
            },
        ):
            resp = self.client.post(
                "/api/quant/realized-vol/har-rv",
                json={"rv_series": _RETURNS_A},
            )
        assert resp.status_code == 200  # noqa: PLR2004
        body = resp.json()
        for key in ("forecast_1d", "forecast_5d", "forecast_22d", "r_squared"):
            assert key in body

    # ── EVT ───────────────────────────────────────────────────────────────────

    def test_evt_tail_risk_success(self):
        mock_result = MagicMock(
            var_99=0.025,
            var_999=0.04,
            es_99=0.032,
            es_999=0.05,
            threshold=0.015,
            gpd_xi=0.2,
            gpd_sigma=0.01,
            n_exceedances=15,
            n_total=252,
        )
        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result
        mock_cls = MagicMock(return_value=mock_model)

        with patch.dict(
            "sys.modules",
            {"risk.evt": types.SimpleNamespace(EVTRiskModel=mock_cls)},
        ):
            resp = self.client.post(
                "/api/quant/evt/tail-risk",
                json={"returns": _RETURNS_A},
            )
        assert resp.status_code == 200  # noqa: PLR2004
        body = resp.json()
        for key in ("var_99", "es_99", "threshold", "n_exceedances"):
            assert key in body

    # ── Capacity ──────────────────────────────────────────────────────────────

    def test_capacity_estimate_success(self):
        mock_result = MagicMock(
            gross_alpha_bps=12.5,
            breakeven_aum_usd=500_000.0,
            optimal_aum_usd=2_000_000.0,
            optimal_dollar_profit=25_000.0,
        )
        mock_analyzer = MagicMock()
        mock_analyzer.estimate.return_value = mock_result
        mock_cls = MagicMock(return_value=mock_analyzer)

        with patch.dict(
            "sys.modules",
            {"ml.capacity": types.SimpleNamespace(CapacityAnalyzer=mock_cls)},
        ):
            resp = self.client.post(
                "/api/quant/capacity/estimate",
                json={
                    "returns": _RETURNS_A,
                    "avg_daily_volume_usd": 10_000_000.0,
                    "turnover_per_year": 50.0,
                },
            )
        assert resp.status_code == 200  # noqa: PLR2004
        body = resp.json()
        for key in ("gross_alpha_bps", "breakeven_aum_usd", "optimal_aum_usd"):
            assert key in body

    # ── LaVaR ─────────────────────────────────────────────────────────────────

    def test_lavar_success(self):
        mock_result = MagicMock(
            lavar=5_200.0,
            var_market=4_800.0,
            liquidity_cost=400.0,
            liquidation_horizon=3,
            confidence=0.99,
        )
        mock_model = MagicMock()
        mock_model.calculate.return_value = mock_result
        mock_cls = MagicMock(return_value=mock_model)

        with patch.dict(
            "sys.modules",
            {"risk.liquidity_var": types.SimpleNamespace(LiquidityAdjustedVaR=mock_cls)},
        ):
            resp = self.client.post(
                "/api/quant/lavar",
                json={
                    "returns": _RETURNS_A,
                    "position_value": 100_000.0,
                    "avg_spread_pct": 0.0002,
                },
            )
        assert resp.status_code == 200  # noqa: PLR2004
        body = resp.json()
        for key in ("lavar", "var_market", "liquidity_cost", "confidence"):
            assert key in body


# ── GET endpoints — server stability ─────────────────────────────────────────

@pytest.mark.unit
class TestQuantGetEndpointStability:
    """
    GET endpoints must never return a 5xx that propagates uncaught.
    They are expected to return 200 (module available) or 500 (module
    unavailable) — both are acceptable; a 200 must include the right keys.
    """

    def setup_method(self):
        self.client = _make_client()

    def test_model_monitor_health_no_crash(self):
        resp = self.client.get("/api/quant/model-monitor/health")
        assert resp.status_code in (200, 500)

    def test_universe_snapshot_no_crash(self):
        resp = self.client.get("/api/quant/universe/snapshot")
        assert resp.status_code in (200, 500)

    def test_vpin_features_no_crash(self):
        resp = self.client.get("/api/quant/vpin/features")
        assert resp.status_code in (200, 500)

    def test_crowding_health_no_crash(self):
        resp = self.client.get("/api/quant/crowding/health")
        assert resp.status_code in (200, 500)

    def test_feature_store_health_no_crash(self):
        resp = self.client.get("/api/quant/feature-store/health")
        assert resp.status_code in (200, 500)

    def test_model_monitor_health_mocked(self):
        mock_health = {"status": "ok", "model": "advanced_oos_v1"}
        mock_monitor = MagicMock()
        mock_monitor.health.return_value = mock_health

        with patch.dict(
            "sys.modules",
            {"ml.model_monitor": types.SimpleNamespace(model_monitor=mock_monitor)},
        ):
            resp = self.client.get("/api/quant/model-monitor/health")
        assert resp.status_code == 200  # noqa: PLR2004
        assert resp.json()["status"] == "ok"

    def test_universe_snapshot_mocked(self):
        mock_snapshot = {"active": ["XAUUSD", "EURUSD"], "count": 2}
        mock_engine = MagicMock()
        mock_engine.snapshot.return_value = mock_snapshot

        with patch.dict(
            "sys.modules",
            {"core.universe": types.SimpleNamespace(universe_engine=mock_engine)},
        ):
            resp = self.client.get("/api/quant/universe/snapshot")
        assert resp.status_code == 200  # noqa: PLR2004
        assert "active" in resp.json()
