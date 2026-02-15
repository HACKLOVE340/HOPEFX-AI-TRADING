"""
Data Sources for Backtesting

Various data source implementations for loading historical data.
Includes multiple FREE data sources:
- Yahoo Finance (stocks, ETFs, forex via yfinance)
- Alpha Vantage (stocks, forex, crypto - free API key)
- Exchange Rates API (forex rates)
- CoinGecko (crypto - no API key needed)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import logging
import os

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not installed. Yahoo Finance source unavailable.")


class DataSource:
    """Base class for data sources."""

    def get_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """
        Get historical data for a symbol.

        Args:
            symbol: Trading symbol
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with OHLCV data
        """
        raise NotImplementedError("Subclasses must implement get_data()")


class YahooFinanceSource(DataSource):
    """Yahoo Finance data source using yfinance library."""

    def __init__(self, interval: str = '1d'):
        """
        Initialize Yahoo Finance source.

        Args:
            interval: Data interval (1d, 1h, etc.)
        """
        if not YFINANCE_AVAILABLE:
            raise ImportError("yfinance is required for YahooFinanceSource")

        self.interval = interval
        logger.info(f"Initialized Yahoo Finance source with {interval} interval")

    def get_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Download data from Yahoo Finance."""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                start=start_date,
                end=end_date,
                interval=self.interval
            )

            if df.empty:
                logger.warning(f"No data returned from Yahoo Finance for {symbol}")
                return pd.DataFrame()

            # Standardize column names
            df.columns = [col.lower() for col in df.columns]

            # Remove timezone info if present
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            logger.info(f"Downloaded {len(df)} bars for {symbol} from Yahoo Finance")
            return df

        except Exception as e:
            logger.error(f"Error downloading {symbol} from Yahoo Finance: {e}")
            return pd.DataFrame()


class CSVDataSource(DataSource):
    """CSV file data source."""

    def __init__(self, data_dir: str, date_column: str = 'date'):
        """
        Initialize CSV data source.

        Args:
            data_dir: Directory containing CSV files
            date_column: Name of date column in CSV
        """
        self.data_dir = data_dir
        self.date_column = date_column
        logger.info(f"Initialized CSV source from {data_dir}")

    def get_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Load data from CSV file."""
        import os

        try:
            # Try different filename patterns
            patterns = [
                f"{symbol}.csv",
                f"{symbol.upper()}.csv",
                f"{symbol.lower()}.csv",
            ]

            filepath = None
            for pattern in patterns:
                path = os.path.join(self.data_dir, pattern)
                if os.path.exists(path):
                    filepath = path
                    break

            if filepath is None:
                logger.error(f"CSV file not found for {symbol} in {self.data_dir}")
                return pd.DataFrame()

            # Load CSV
            df = pd.read_csv(filepath)

            # Parse date column
            df[self.date_column] = pd.to_datetime(df[self.date_column])
            df.set_index(self.date_column, inplace=True)

            # Filter by date range
            df = df[(df.index >= start_date) & (df.index <= end_date)]

            # Standardize column names
            df.columns = [col.lower() for col in df.columns]

            logger.info(f"Loaded {len(df)} bars for {symbol} from CSV")
            return df

        except Exception as e:
            logger.error(f"Error loading CSV for {symbol}: {e}")
            return pd.DataFrame()


class BrokerDataSource(DataSource):
    """Data source from broker connectors."""

    def __init__(self, broker):
        """
        Initialize broker data source.

        Args:
            broker: Broker connector instance
        """
        self.broker = broker
        logger.info(f"Initialized broker data source")

    def get_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Get historical data from broker."""
        try:
            # This depends on broker implementation
            if hasattr(self.broker, 'get_market_data'):
                df = self.broker.get_market_data(
                    symbol=symbol,
                    timeframe='D1',
                    start=start_date,
                    end=end_date
                )
                return df
            else:
                logger.error("Broker does not support historical data retrieval")
                return pd.DataFrame()

        except Exception as e:
            logger.error(f"Error getting data from broker for {symbol}: {e}")
            return pd.DataFrame()


# ============================================================
# FREE DATA SOURCES - No API key or free tier available
# ============================================================

class AlphaVantageSource(DataSource):
    """
    Alpha Vantage data source (FREE tier: 5 API calls/minute, 500/day).

    Get free API key at: https://www.alphavantage.co/support/#api-key

    Supports:
    - Stocks (US and international)
    - Forex pairs
    - Cryptocurrencies
    - Technical indicators
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str = None):
        """
        Initialize Alpha Vantage source.

        Args:
            api_key: Alpha Vantage API key (free at alphavantage.co)
                     Can also be set via ALPHA_VANTAGE_API_KEY env var
        """
        self.api_key = api_key or os.environ.get('ALPHA_VANTAGE_API_KEY', '')
        if not self.api_key:
            logger.warning(
                "Alpha Vantage API key not set. "
                "Get a free key at https://www.alphavantage.co/support/#api-key"
            )
        else:
            logger.info("Initialized Alpha Vantage source")

    def get_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Download data from Alpha Vantage."""
        if not self.api_key:
            logger.error("Alpha Vantage API key required")
            return pd.DataFrame()

        try:
            import requests

            # Determine if forex or stock
            if '/' in symbol:  # Forex pair like EUR/USD
                from_currency, to_currency = symbol.split('/')
                params = {
                    'function': 'FX_DAILY',
                    'from_symbol': from_currency,
                    'to_symbol': to_currency,
                    'outputsize': 'full',
                    'apikey': self.api_key
                }
                data_key = 'Time Series FX (Daily)'
            else:  # Stock symbol
                params = {
                    'function': 'TIME_SERIES_DAILY',
                    'symbol': symbol,
                    'outputsize': 'full',
                    'apikey': self.api_key
                }
                data_key = 'Time Series (Daily)'

            response = requests.get(self.BASE_URL, params=params, timeout=30)
            data = response.json()

            if data_key not in data:
                error_msg = data.get('Note', data.get('Error Message', 'Unknown error'))
                logger.error(f"Alpha Vantage error: {error_msg}")
                return pd.DataFrame()

            # Parse data
            df = pd.DataFrame.from_dict(data[data_key], orient='index')
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            # Standardize column names - Alpha Vantage returns numbered columns
            # Select only the OHLC columns we need
            if len(df.columns) >= 4:
                df = df.iloc[:, :4]  # Take first 4 columns (open, high, low, close)
            df.columns = ['open', 'high', 'low', 'close']
            df = df.astype(float)

            # Filter by date range
            df = df[(df.index >= start_date) & (df.index <= end_date)]

            logger.info(f"Downloaded {len(df)} bars for {symbol} from Alpha Vantage")
            return df

        except ImportError:
            logger.error("requests library required for Alpha Vantage")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error downloading {symbol} from Alpha Vantage: {e}")
            return pd.DataFrame()

    def get_forex(self, from_currency: str, to_currency: str,
                  start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Get forex data."""
        return self.get_data(f"{from_currency}/{to_currency}", start_date, end_date)

    def get_crypto(self, symbol: str, market: str = 'USD',
                   start_date: datetime = None, end_date: datetime = None) -> pd.DataFrame:
        """
        Get cryptocurrency data.

        Args:
            symbol: Crypto symbol (BTC, ETH, etc.)
            market: Market currency (USD, EUR, etc.)
            start_date: Start date
            end_date: End date
        """
        if not self.api_key:
            logger.error("Alpha Vantage API key required")
            return pd.DataFrame()

        try:
            import requests

            params = {
                'function': 'DIGITAL_CURRENCY_DAILY',
                'symbol': symbol,
                'market': market,
                'apikey': self.api_key
            }

            response = requests.get(self.BASE_URL, params=params, timeout=30)
            data = response.json()

            data_key = 'Time Series (Digital Currency Daily)'
            if data_key not in data:
                error_msg = data.get('Note', data.get('Error Message', 'Unknown error'))
                logger.error(f"Alpha Vantage crypto error: {error_msg}")
                return pd.DataFrame()

            # Parse data
            df = pd.DataFrame.from_dict(data[data_key], orient='index')
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            # Extract relevant columns (close price in market currency)
            close_col = f'4a. close ({market})'
            open_col = f'1a. open ({market})'
            high_col = f'2a. high ({market})'
            low_col = f'3a. low ({market})'
            vol_col = '5. volume'

            result = pd.DataFrame({
                'open': df[open_col].astype(float),
                'high': df[high_col].astype(float),
                'low': df[low_col].astype(float),
                'close': df[close_col].astype(float),
                'volume': df[vol_col].astype(float)
            })

            # Filter by date range
            if start_date:
                result = result[result.index >= start_date]
            if end_date:
                result = result[result.index <= end_date]

            logger.info(f"Downloaded {len(result)} bars for {symbol}/{market} crypto from Alpha Vantage")
            return result

        except ImportError:
            logger.error("requests library required for Alpha Vantage")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error downloading crypto {symbol} from Alpha Vantage: {e}")
            return pd.DataFrame()


class CoinGeckoSource(DataSource):
    """
    CoinGecko data source (FREE, no API key required).

    Provides cryptocurrency market data.
    Rate limit: 10-50 calls/minute (free tier).
    """

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self):
        """Initialize CoinGecko source."""
        logger.info("Initialized CoinGecko source (free, no API key needed)")

    def get_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Download crypto data from CoinGecko."""
        try:
            import requests

            # Map common symbols to CoinGecko IDs
            symbol_map = {
                'BTC': 'bitcoin',
                'ETH': 'ethereum',
                'XRP': 'ripple',
                'SOL': 'solana',
                'ADA': 'cardano',
                'DOGE': 'dogecoin',
                'DOT': 'polkadot',
                'MATIC': 'matic-network',
                'LINK': 'chainlink',
                'AVAX': 'avalanche-2',
            }

            coin_id = symbol_map.get(symbol.upper(), symbol.lower())

            # Calculate days needed
            days = (end_date - start_date).days
            if days < 1:
                days = 1

            url = f"{self.BASE_URL}/coins/{coin_id}/market_chart"
            params = {
                'vs_currency': 'usd',
                'days': days,
                'interval': 'daily'
            }

            response = requests.get(url, params=params, timeout=30)
            data = response.json()

            if 'prices' not in data:
                logger.error(f"CoinGecko error: {data.get('error', 'Unknown error')}")
                return pd.DataFrame()

            # Parse price data
            prices = pd.DataFrame(data['prices'], columns=['timestamp', 'price'])
            prices['timestamp'] = pd.to_datetime(prices['timestamp'], unit='ms')
            prices.set_index('timestamp', inplace=True)

            # Add volume if available
            if 'total_volumes' in data:
                volumes = pd.DataFrame(data['total_volumes'], columns=['timestamp', 'volume'])
                volumes['timestamp'] = pd.to_datetime(volumes['timestamp'], unit='ms')
                volumes.set_index('timestamp', inplace=True)
                prices = prices.join(volumes)

            # Create OHLC from daily closes
            df = pd.DataFrame({
                'open': prices['price'],
                'high': prices['price'],
                'low': prices['price'],
                'close': prices['price'],
                'volume': prices.get('volume', 0)
            })

            # Filter by date range
            df = df[(df.index >= start_date) & (df.index <= end_date)]

            logger.info(f"Downloaded {len(df)} bars for {symbol} from CoinGecko")
            return df

        except ImportError:
            logger.error("requests library required for CoinGecko")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error downloading {symbol} from CoinGecko: {e}")
            return pd.DataFrame()

    def get_coin_list(self) -> List[Dict[str, str]]:
        """Get list of all supported coins."""
        try:
            import requests
            response = requests.get(f"{self.BASE_URL}/coins/list", timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"Error getting coin list: {e}")
            return []


class ExchangeRateSource(DataSource):
    """
    Exchange Rate API source (FREE tier: 1500 requests/month).

    Get free API key at: https://www.exchangerate-api.com/

    Provides forex exchange rates.
    """

    BASE_URL = "https://api.exchangerate-api.com/v4/latest"

    def __init__(self, api_key: str = None):
        """
        Initialize Exchange Rate source.

        Args:
            api_key: Optional API key for higher limits
        """
        self.api_key = api_key or os.environ.get('EXCHANGE_RATE_API_KEY', '')
        logger.info("Initialized Exchange Rate source")

    def get_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """
        Get forex data.

        Note: Free tier only provides current rates, not historical.
        For historical data, consider upgrading or using Alpha Vantage.
        """
        try:
            import requests

            # Parse forex pair
            if '/' in symbol:
                base, quote = symbol.split('/')
            else:
                base, quote = symbol[:3], symbol[3:]

            url = f"{self.BASE_URL}/{base}"
            response = requests.get(url, timeout=30)
            data = response.json()

            if 'rates' not in data:
                logger.error(f"Exchange Rate API error for {symbol}")
                return pd.DataFrame()

            rate = data['rates'].get(quote)
            if rate is None:
                logger.error(f"Currency {quote} not found in Exchange Rate API")
                return pd.DataFrame()

            # Create single-row dataframe with current rate
            df = pd.DataFrame({
                'open': [rate],
                'high': [rate],
                'low': [rate],
                'close': [rate],
            }, index=[pd.Timestamp.now()])

            logger.info(f"Got current rate for {symbol}: {rate}")
            return df

        except ImportError:
            logger.error("requests library required for Exchange Rate API")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error getting rate for {symbol}: {e}")
            return pd.DataFrame()

    def get_all_rates(self, base: str = 'USD') -> Dict[str, float]:
        """Get all exchange rates for a base currency."""
        try:
            import requests
            url = f"{self.BASE_URL}/{base}"
            response = requests.get(url, timeout=30)
            data = response.json()
            return data.get('rates', {})
        except Exception as e:
            logger.error(f"Error getting all rates: {e}")
            return {}


# ============================================================
# UNIFIED DATA MANAGER
# ============================================================

class DataManager:
    """
    Unified data manager that tries multiple sources.

    Automatically selects the best available data source
    based on the symbol type and available API keys.

    Usage:
        manager = DataManager()
        df = manager.get_data('XAUUSD', start_date, end_date)
        df = manager.get_data('BTC', start_date, end_date)  # Crypto
        df = manager.get_data('AAPL', start_date, end_date)  # Stock
    """

    # Symbol type mappings
    FOREX_PAIRS = [
        'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD',
        'XAUUSD', 'XAGUSD', 'XAUEUR',  # Gold & Silver
        'EUR/USD', 'GBP/USD', 'USD/JPY', 'XAU/USD',
    ]

    CRYPTO_SYMBOLS = [
        'BTC', 'ETH', 'XRP', 'SOL', 'ADA', 'DOGE', 'DOT', 'MATIC', 'LINK', 'AVAX',
        'BNB', 'USDT', 'USDC', 'SHIB', 'LTC', 'TRX', 'UNI', 'ATOM', 'XMR', 'XLM'
    ]

    # Pre-computed normalized forex pairs for efficient lookup
    _NORMALIZED_FOREX_PAIRS = None

    def __init__(self, alpha_vantage_key: str = None, cache_dir: str = None):
        """
        Initialize data manager.

        Args:
            alpha_vantage_key: Optional Alpha Vantage API key
            cache_dir: Directory for caching data
        """
        self.alpha_vantage_key = alpha_vantage_key or os.environ.get('ALPHA_VANTAGE_API_KEY')
        self.cache_dir = cache_dir or os.environ.get('DATA_CACHE_DIR', './data/cache')

        # Initialize normalized forex pairs set (cached)
        if DataManager._NORMALIZED_FOREX_PAIRS is None:
            DataManager._NORMALIZED_FOREX_PAIRS = set(
                p.replace('/', '') for p in self.FOREX_PAIRS
            )

        # Initialize sources
        self.sources = {}

        # Yahoo Finance (always available with yfinance installed)
        if YFINANCE_AVAILABLE:
            self.sources['yahoo'] = YahooFinanceSource()

        # Alpha Vantage (if API key available)
        if self.alpha_vantage_key:
            self.sources['alphavantage'] = AlphaVantageSource(self.alpha_vantage_key)

        # CoinGecko (always available, free)
        self.sources['coingecko'] = CoinGeckoSource()

        # Exchange Rate API (always available for current rates)
        self.sources['exchangerate'] = ExchangeRateSource()

        logger.info(f"DataManager initialized with sources: {list(self.sources.keys())}")

    def get_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        preferred_source: str = None
    ) -> pd.DataFrame:
        """
        Get historical data for any symbol.

        Automatically selects appropriate data source based on symbol type.

        Args:
            symbol: Trading symbol (XAUUSD, BTC, AAPL, etc.)
            start_date: Start date
            end_date: End date
            preferred_source: Optional preferred source name

        Returns:
            DataFrame with OHLCV data
        """
        # Clean symbol
        symbol = symbol.upper().strip()

        # Try preferred source first
        if preferred_source and preferred_source in self.sources:
            df = self.sources[preferred_source].get_data(symbol, start_date, end_date)
            if not df.empty:
                return df

        # Determine symbol type and try appropriate sources
        if self._is_crypto(symbol):
            return self._get_crypto_data(symbol, start_date, end_date)
        elif self._is_forex(symbol):
            return self._get_forex_data(symbol, start_date, end_date)
        else:
            return self._get_stock_data(symbol, start_date, end_date)

    def _is_crypto(self, symbol: str) -> bool:
        """Check if symbol is cryptocurrency."""
        base = symbol.split('/')[0] if '/' in symbol else symbol
        return base in self.CRYPTO_SYMBOLS

    def _is_forex(self, symbol: str) -> bool:
        """Check if symbol is forex pair using cached normalized set."""
        normalized = symbol.replace('/', '')
        return normalized in self._NORMALIZED_FOREX_PAIRS

    def _get_crypto_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Get cryptocurrency data."""
        # Try CoinGecko first (free, no API key)
        if 'coingecko' in self.sources:
            df = self.sources['coingecko'].get_data(symbol, start_date, end_date)
            if not df.empty:
                return df

        # Try Alpha Vantage
        if 'alphavantage' in self.sources:
            df = self.sources['alphavantage'].get_crypto(symbol, 'USD', start_date, end_date)
            if not df.empty:
                return df

        # Try Yahoo Finance (BTC-USD format)
        if 'yahoo' in self.sources:
            yahoo_symbol = f"{symbol}-USD"
            df = self.sources['yahoo'].get_data(yahoo_symbol, start_date, end_date)
            if not df.empty:
                return df

        logger.warning(f"No data found for crypto symbol {symbol}")
        return pd.DataFrame()

    def _get_forex_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Get forex data."""
        # Try Alpha Vantage first (best forex support)
        if 'alphavantage' in self.sources:
            # Format symbol for Alpha Vantage (EUR/USD)
            if '/' not in symbol:
                formatted = f"{symbol[:3]}/{symbol[3:]}"
            else:
                formatted = symbol
            df = self.sources['alphavantage'].get_data(formatted, start_date, end_date)
            if not df.empty:
                return df

        # Try Yahoo Finance
        if 'yahoo' in self.sources:
            # Yahoo uses format like EURUSD=X
            clean_symbol = symbol.replace('/', '')
            yahoo_symbol = f"{clean_symbol}=X"
            df = self.sources['yahoo'].get_data(yahoo_symbol, start_date, end_date)
            if not df.empty:
                return df

        logger.warning(f"No data found for forex symbol {symbol}")
        return pd.DataFrame()

    def _get_stock_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Get stock data."""
        # Try Yahoo Finance first (best stock support)
        if 'yahoo' in self.sources:
            df = self.sources['yahoo'].get_data(symbol, start_date, end_date)
            if not df.empty:
                return df

        # Try Alpha Vantage
        if 'alphavantage' in self.sources:
            df = self.sources['alphavantage'].get_data(symbol, start_date, end_date)
            if not df.empty:
                return df

        logger.warning(f"No data found for stock symbol {symbol}")
        return pd.DataFrame()

    def get_available_sources(self) -> List[str]:
        """Get list of available data sources."""
        return list(self.sources.keys())

    def get_source_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about available data sources."""
        return {
            'yahoo': {
                'name': 'Yahoo Finance',
                'available': 'yahoo' in self.sources,
                'api_key_required': False,
                'supports': ['stocks', 'forex', 'crypto'],
                'limits': 'Generous, unofficial API'
            },
            'alphavantage': {
                'name': 'Alpha Vantage',
                'available': 'alphavantage' in self.sources,
                'api_key_required': True,
                'supports': ['stocks', 'forex', 'crypto', 'indicators'],
                'limits': 'Free: 5/min, 500/day'
            },
            'coingecko': {
                'name': 'CoinGecko',
                'available': 'coingecko' in self.sources,
                'api_key_required': False,
                'supports': ['crypto'],
                'limits': '10-50 calls/min'
            },
            'exchangerate': {
                'name': 'Exchange Rate API',
                'available': 'exchangerate' in self.sources,
                'api_key_required': False,
                'supports': ['forex (current rates only)'],
                'limits': '1500 requests/month'
            }
        }
