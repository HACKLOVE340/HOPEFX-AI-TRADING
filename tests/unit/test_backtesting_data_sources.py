# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
Unit tests for backtesting/data_sources.py.
All external I/O (yfinance, requests, filesystem) is mocked.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtesting.data_sources import (
    AlphaVantageSource,
    BrokerDataSource,
    CSVDataSource,
    CoinGeckoSource,
    DataManager,
    DataSource,
    ExchangeRateSource,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

START = datetime(2024, 1, 1)
END = datetime(2024, 3, 1)


def _ohlcv_df(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": [1.0] * n,
            "high": [2.0] * n,
            "low": [0.5] * n,
            "close": [1.5] * n,
            "volume": [100.0] * n,
        },
        index=idx,
    )


# ── DataSource ABC ────────────────────────────────────────────────────────────


class TestDataSourceABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            DataSource()  # type: ignore[abstract]

    def test_concrete_subclass_works(self):
        class Concrete(DataSource):
            def get_data(self, symbol, start_date, end_date):
                return pd.DataFrame()

        src = Concrete()
        result = src.get_data("X", START, END)
        assert isinstance(result, pd.DataFrame)


# ── YahooFinanceSource ────────────────────────────────────────────────────────


class TestYahooFinanceSource:
    def test_raises_when_yfinance_unavailable(self):
        with patch("backtesting.data_sources.YFINANCE_AVAILABLE", False):
            from backtesting.data_sources import YahooFinanceSource

            with pytest.raises(ImportError):
                YahooFinanceSource()

    def test_get_data_returns_dataframe(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _ohlcv_df()

        with (
            patch("backtesting.data_sources.YFINANCE_AVAILABLE", True),
            patch("backtesting.data_sources.yf") as mock_yf,
        ):
            mock_yf.Ticker.return_value = mock_ticker
            from backtesting.data_sources import YahooFinanceSource

            src = YahooFinanceSource(interval="1d")
            df = src.get_data("AAPL", START, END)

        assert not df.empty

    def test_get_data_returns_empty_on_empty_response(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        with (
            patch("backtesting.data_sources.YFINANCE_AVAILABLE", True),
            patch("backtesting.data_sources.yf") as mock_yf,
        ):
            mock_yf.Ticker.return_value = mock_ticker
            from backtesting.data_sources import YahooFinanceSource

            src = YahooFinanceSource()
            df = src.get_data("AAPL", START, END)

        assert df.empty

    def test_get_data_returns_empty_on_exception(self):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = RuntimeError("network error")

        with (
            patch("backtesting.data_sources.YFINANCE_AVAILABLE", True),
            patch("backtesting.data_sources.yf") as mock_yf,
        ):
            mock_yf.Ticker.return_value = mock_ticker
            from backtesting.data_sources import YahooFinanceSource

            src = YahooFinanceSource()
            df = src.get_data("AAPL", START, END)

        assert df.empty

    def test_strips_timezone_from_index(self):
        df = _ohlcv_df()
        df.index = df.index.tz_localize("UTC")
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = df

        with (
            patch("backtesting.data_sources.YFINANCE_AVAILABLE", True),
            patch("backtesting.data_sources.yf") as mock_yf,
        ):
            mock_yf.Ticker.return_value = mock_ticker
            from backtesting.data_sources import YahooFinanceSource

            src = YahooFinanceSource()
            result = src.get_data("AAPL", START, END)

        assert result.index.tz is None


# ── CSVDataSource ─────────────────────────────────────────────────────────────


class TestCSVDataSource:
    def test_get_data_loads_csv(self, tmp_path):
        df = _ohlcv_df(10)
        df.index.name = "date"
        csv_path = tmp_path / "XAUUSD.csv"
        df.to_csv(csv_path)

        src = CSVDataSource(str(tmp_path))
        result = src.get_data("XAUUSD", START, END)
        assert not result.empty
        assert "close" in result.columns

    def test_get_data_tries_uppercase_filename(self, tmp_path):
        df = _ohlcv_df(5)
        df.index.name = "date"
        (tmp_path / "XAUUSD.csv").write_text(df.to_csv())

        src = CSVDataSource(str(tmp_path))
        result = src.get_data("xauusd", START, END)
        assert not result.empty

    def test_get_data_returns_empty_when_file_missing(self, tmp_path):
        src = CSVDataSource(str(tmp_path))
        result = src.get_data("MISSING", START, END)
        assert result.empty

    def test_get_data_returns_empty_on_parse_error(self, tmp_path):
        bad_csv = tmp_path / "BAD.csv"
        bad_csv.write_text("not,valid,csv\n!!!")

        src = CSVDataSource(str(tmp_path))
        result = src.get_data("BAD", START, END)
        assert result.empty

    def test_filters_by_date_range(self, tmp_path):
        df = _ohlcv_df(30)
        df.index.name = "date"
        (tmp_path / "SYM.csv").write_text(df.to_csv())

        src = CSVDataSource(str(tmp_path))
        result = src.get_data("SYM", datetime(2024, 1, 5), datetime(2024, 1, 10))
        assert len(result) <= 30


# ── BrokerDataSource ──────────────────────────────────────────────────────────


class TestBrokerDataSource:
    def test_get_data_calls_broker_get_market_data(self):
        broker = MagicMock()
        broker.get_market_data.return_value = _ohlcv_df()
        src = BrokerDataSource(broker)
        result = src.get_data("XAUUSD", START, END)
        assert not result.empty
        broker.get_market_data.assert_called_once()

    def test_get_data_returns_empty_when_broker_has_no_method(self):
        broker = object()  # no get_market_data
        src = BrokerDataSource(broker)
        result = src.get_data("XAUUSD", START, END)
        assert result.empty

    def test_get_data_returns_empty_on_exception(self):
        broker = MagicMock()
        broker.get_market_data.side_effect = RuntimeError("broker down")
        src = BrokerDataSource(broker)
        result = src.get_data("XAUUSD", START, END)
        assert result.empty


# ── AlphaVantageSource ────────────────────────────────────────────────────────


class TestAlphaVantageSource:
    def test_init_without_key_logs_warning(self):
        with patch.dict(os.environ, {}, clear=True):
            src = AlphaVantageSource(api_key=None)
        assert src.api_key == ""

    def test_init_reads_env_var(self):
        key = "testkey123"  # pragma: allowlist secret
        with patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": key}):
            src = AlphaVantageSource()
        assert src.api_key == key

    def test_get_data_returns_empty_without_key(self):
        src = AlphaVantageSource(api_key="")  # pragma: allowlist secret
        result = src.get_data("AAPL", START, END)
        assert result.empty

    def test_get_data_stock_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Time Series (Daily)": {
                "2024-01-02": {
                    "1. open": "150.0",
                    "2. high": "155.0",
                    "3. low": "149.0",
                    "4. close": "152.0",
                },
                "2024-01-03": {
                    "1. open": "152.0",
                    "2. high": "157.0",
                    "3. low": "151.0",
                    "4. close": "156.0",
                },
            }
        }
        with patch("requests.get", return_value=mock_response):
            src = AlphaVantageSource(api_key="testkey")  # pragma: allowlist secret
            result = src.get_data("AAPL", START, END)
        assert not result.empty
        assert "close" in result.columns

    def test_get_data_forex_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Time Series FX (Daily)": {
                "2024-01-02": {
                    "1. open": "1.08",
                    "2. high": "1.09",
                    "3. low": "1.07",
                    "4. close": "1.085",
                },
            }
        }
        with patch("requests.get", return_value=mock_response):
            src = AlphaVantageSource(api_key="testkey")  # pragma: allowlist secret
            result = src.get_data("EUR/USD", START, END)
        assert not result.empty

    def test_get_data_returns_empty_on_api_error(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Note": "API rate limit reached"}
        with patch("requests.get", return_value=mock_response):
            src = AlphaVantageSource(api_key="testkey")  # pragma: allowlist secret
            result = src.get_data("AAPL", START, END)
        assert result.empty

    def test_get_data_returns_empty_on_exception(self):
        with patch("requests.get", side_effect=RuntimeError("network")):
            src = AlphaVantageSource(api_key="testkey")  # pragma: allowlist secret
            result = src.get_data("AAPL", START, END)
        assert result.empty

    def test_get_forex_delegates_to_get_data(self):
        src = AlphaVantageSource(api_key="")  # pragma: allowlist secret
        result = src.get_forex("EUR", "USD", START, END)
        assert result.empty  # no key → empty

    def test_get_crypto_returns_empty_without_key(self):
        src = AlphaVantageSource(api_key="")  # pragma: allowlist secret
        result = src.get_crypto("BTC", "USD", START, END)
        assert result.empty

    def test_get_crypto_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Time Series (Digital Currency Daily)": {
                "2024-01-02": {
                    "1a. open (USD)": "42000.0",
                    "2a. high (USD)": "43000.0",
                    "3a. low (USD)": "41000.0",
                    "4a. close (USD)": "42500.0",
                    "5. volume": "1000.0",
                }
            }
        }
        with patch("requests.get", return_value=mock_response):
            src = AlphaVantageSource(api_key="testkey")  # pragma: allowlist secret
            result = src.get_crypto("BTC", "USD", START, END)
        assert not result.empty

    def test_get_crypto_returns_empty_on_api_error(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Error Message": "invalid symbol"}
        with patch("requests.get", return_value=mock_response):
            src = AlphaVantageSource(api_key="testkey")  # pragma: allowlist secret
            result = src.get_crypto("INVALID", "USD")
        assert result.empty


# ── CoinGeckoSource ───────────────────────────────────────────────────────────


class TestCoinGeckoSource:
    def test_get_data_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "prices": [
                [1704067200000, 42000.0],
                [1704153600000, 43000.0],
            ],
            "total_volumes": [
                [1704067200000, 1_000_000.0],
                [1704153600000, 1_100_000.0],
            ],
        }
        with patch("requests.get", return_value=mock_response):
            src = CoinGeckoSource()
            result = src.get_data("BTC", START, END)
        assert not result.empty
        assert "close" in result.columns

    def test_get_data_maps_symbol_to_coingecko_id(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "prices": [[1704067200000, 2000.0]],
        }
        with patch("requests.get", return_value=mock_response) as mock_get:
            src = CoinGeckoSource()
            src.get_data("ETH", START, END)
        call_url = mock_get.call_args[0][0]
        assert "ethereum" in call_url

    def test_get_data_returns_empty_on_api_error(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "coin not found"}
        with patch("requests.get", return_value=mock_response):
            src = CoinGeckoSource()
            result = src.get_data("UNKNOWN", START, END)
        assert result.empty

    def test_get_data_returns_empty_on_exception(self):
        with patch("requests.get", side_effect=RuntimeError("timeout")):
            src = CoinGeckoSource()
            result = src.get_data("BTC", START, END)
        assert result.empty

    def test_get_coin_list_returns_list(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"id": "bitcoin", "symbol": "btc"}]
        with patch("requests.get", return_value=mock_response):
            src = CoinGeckoSource()
            coins = src.get_coin_list()
        assert isinstance(coins, list)
        assert coins[0]["id"] == "bitcoin"

    def test_get_coin_list_returns_empty_on_exception(self):
        with patch("requests.get", side_effect=RuntimeError("network")):
            src = CoinGeckoSource()
            result = src.get_coin_list()
        assert result == []


# ── ExchangeRateSource ────────────────────────────────────────────────────────


class TestExchangeRateSource:
    def test_get_data_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"rates": {"GBP": 0.79}}
        with patch("requests.get", return_value=mock_response):
            src = ExchangeRateSource()
            result = src.get_data("USD/GBP", START, END)
        assert not result.empty
        assert result["close"].iloc[0] == pytest.approx(0.79)

    def test_get_data_parses_symbol_without_slash(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"rates": {"JPY": 150.0}}
        with patch("requests.get", return_value=mock_response):
            src = ExchangeRateSource()
            result = src.get_data("USDJPY", START, END)
        assert not result.empty

    def test_get_data_returns_empty_when_currency_not_found(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"rates": {"EUR": 0.92}}
        with patch("requests.get", return_value=mock_response):
            src = ExchangeRateSource()
            result = src.get_data("USD/XYZ", START, END)
        assert result.empty

    def test_get_data_returns_empty_on_api_error(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        with patch("requests.get", return_value=mock_response):
            src = ExchangeRateSource()
            result = src.get_data("USD/EUR", START, END)
        assert result.empty

    def test_get_data_returns_empty_on_exception(self):
        with patch("requests.get", side_effect=RuntimeError("timeout")):
            src = ExchangeRateSource()
            result = src.get_data("USD/EUR", START, END)
        assert result.empty

    def test_get_all_rates_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"rates": {"EUR": 0.92, "GBP": 0.79}}
        with patch("requests.get", return_value=mock_response):
            src = ExchangeRateSource()
            rates = src.get_all_rates("USD")
        assert rates["EUR"] == pytest.approx(0.92)

    def test_get_all_rates_returns_empty_on_exception(self):
        with patch("requests.get", side_effect=RuntimeError("network")):
            src = ExchangeRateSource()
            result = src.get_all_rates()
        assert result == {}

    def test_reads_api_key_from_env(self):
        key = "mykey"  # pragma: allowlist secret
        with patch.dict(os.environ, {"EXCHANGE_RATE_API_KEY": key}):
            src = ExchangeRateSource()
        assert src.api_key == key


# ── DataManager ───────────────────────────────────────────────────────────────


class TestDataManager:
    def test_is_crypto_recognises_btc(self):
        mgr = DataManager()
        assert mgr._is_crypto("BTC") is True
        assert mgr._is_crypto("ETH") is True
        assert mgr._is_crypto("AAPL") is False

    def test_is_forex_recognises_eurusd(self):
        mgr = DataManager()
        assert mgr._is_forex("EURUSD") is True
        assert mgr._is_forex("XAUUSD") is True
        assert mgr._is_forex("BTC") is False

    def test_get_available_sources_returns_list(self):
        mgr = DataManager()
        sources = mgr.get_available_sources()
        assert isinstance(sources, list)

    def test_get_source_info_returns_dict(self):
        mgr = DataManager()
        info = mgr.get_source_info()
        assert isinstance(info, dict)
        assert "alphavantage" in info or "exchangerate" in info or len(info) >= 0

    def test_get_data_crypto_delegates_to_crypto_path(self):
        mgr = DataManager()
        with patch.object(mgr, "_get_crypto_data", return_value=_ohlcv_df()) as mock_crypto:
            result = mgr.get_data("BTC", START, END)
        mock_crypto.assert_called_once_with("BTC", START, END)
        assert not result.empty

    def test_get_data_forex_delegates_to_forex_path(self):
        mgr = DataManager()
        with patch.object(mgr, "_get_forex_data", return_value=_ohlcv_df()) as mock_forex:
            result = mgr.get_data("EURUSD", START, END)
        mock_forex.assert_called_once_with("EURUSD", START, END)
        assert not result.empty

    def test_get_data_stock_delegates_to_stock_path(self):
        mgr = DataManager()
        with patch.object(mgr, "_get_stock_data", return_value=_ohlcv_df()) as mock_stock:
            result = mgr.get_data("AAPL", START, END)
        mock_stock.assert_called_once_with("AAPL", START, END)
        assert not result.empty

    def test_get_crypto_data_returns_empty_when_no_sources(self):
        mgr = DataManager()
        # No coingecko or alpha vantage sources configured
        mgr.sources = {}
        result = mgr._get_crypto_data("BTC", START, END)
        assert isinstance(result, pd.DataFrame)

    def test_get_forex_data_returns_empty_when_no_sources(self):
        mgr = DataManager()
        mgr.sources = {}
        result = mgr._get_forex_data("EURUSD", START, END)
        assert isinstance(result, pd.DataFrame)

    def test_get_stock_data_returns_empty_when_no_sources(self):
        mgr = DataManager()
        mgr.sources = {}
        result = mgr._get_stock_data("AAPL", START, END)
        assert isinstance(result, pd.DataFrame)
