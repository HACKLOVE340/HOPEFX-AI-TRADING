"""
Data Handler for Backtesting

Manages historical data loading, validation, and access for backtesting.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Union
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DataHandler:
    """
    Manages historical market data for backtesting.
    
    Loads, validates, and provides access to OHLCV data.
    """
    
    def __init__(self, data_source, symbols: List[str], start_date: str, end_date: str):
        """
        Initialize data handler.
        
        Args:
            data_source: Data source object (YahooFinanceSource, CSVDataSource, etc.)
            symbols: List of symbols to load
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        """
        self.data_source = data_source
        self.symbols = symbols
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)
        
        self.data: Dict[str, pd.DataFrame] = {}
        self.current_index = 0
        self.continue_backtest = True
        
        logger.info(f"Initializing DataHandler for {len(symbols)} symbols from {start_date} to {end_date}")
        
    def load_data(self):
        """Load historical data for all symbols."""
        for symbol in self.symbols:
            try:
                df = self.data_source.get_data(symbol, self.start_date, self.end_date)
                
                # Validate data
                if df is None or df.empty:
                    logger.warning(f"No data found for {symbol}")
                    continue
                
                # Ensure required columns
                required_cols = ['open', 'high', 'low', 'close', 'volume']
                if not all(col in df.columns for col in required_cols):
                    logger.error(f"Missing required columns for {symbol}")
                    continue
                
                # Clean data
                df = self._clean_data(df)
                
                self.data[symbol] = df
                logger.info(f"Loaded {len(df)} bars for {symbol}")
                
            except Exception as e:
                logger.error(f"Error loading data for {symbol}: {e}")
                
        if not self.data:
            raise ValueError("No data loaded for any symbol")
            
        # Align all data to same index
        self._align_data()
        
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and prepare data."""
        # Remove NaN values
        df = df.dropna()
        
        # Remove duplicates
        df = df[~df.index.duplicated(keep='first')]
        
        # Sort by date
        df = df.sort_index()
        
        # Convert column names to lowercase
        df.columns = [col.lower() for col in df.columns]
        
        return df
        
    def _align_data(self):
        """Align all symbols to common date index."""
        if len(self.data) == 1:
            return
            
        # Find common dates
        common_index = None
        for symbol, df in self.data.items():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)
        
        # Reindex all dataframes
        for symbol in self.data:
            self.data[symbol] = self.data[symbol].reindex(common_index)
            
        logger.info(f"Aligned data to {len(common_index)} common dates")
        
    def get_latest_bars(self, symbol: str, n: int = 1) -> Optional[pd.DataFrame]:
        """
        Get the last n bars for a symbol up to current point.
        
        Args:
            symbol: Symbol to get bars for
            n: Number of bars to return
            
        Returns:
            DataFrame with last n bars or None
        """
        if symbol not in self.data:
            return None
            
        if self.current_index < n:
            return None
            
        return self.data[symbol].iloc[self.current_index - n:self.current_index]
        
    def get_latest_bar(self, symbol: str) -> Optional[pd.Series]:
        """Get the latest bar for a symbol."""
        bars = self.get_latest_bars(symbol, n=1)
        if bars is not None and not bars.empty:
            return bars.iloc[-1]
        return None
        
    def update_bars(self):
        """Move to next bar (simulate time passing)."""
        if self.current_index >= self._get_max_index():
            self.continue_backtest = False
            logger.info("Reached end of data")
        else:
            self.current_index += 1
            
    def _get_max_index(self) -> int:
        """Get maximum index across all symbols."""
        if not self.data:
            return 0
        return min(len(df) for df in self.data.values())
        
    def get_current_datetime(self) -> Optional[datetime]:
        """Get current datetime in backtest."""
        if self.current_index == 0:
            return None
            
        # Get datetime from first symbol
        symbol = list(self.data.keys())[0]
        return self.data[symbol].index[self.current_index - 1]
        
    def reset(self):
        """Reset to start of data."""
        self.current_index = 0
        self.continue_backtest = True
        logger.info("Reset data handler to start")
