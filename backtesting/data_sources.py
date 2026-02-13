"""
Data Sources for Backtesting

Various data source implementations for loading historical data.
"""

import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime
import logging

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
