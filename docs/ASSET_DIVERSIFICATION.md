# HOPEFX Asset Diversification Guide

> Trading multiple asset classes with HOPEFX AI Trading

---

## 📋 Overview

HOPEFX supports trading across multiple asset classes:

| Asset Class | Status | Brokers |
|-------------|--------|---------|
| **Forex** | ✅ Full Support | OANDA, MT5, IB |
| **Gold (XAU/USD)** | ✅ Optimized | All |
| **Crypto** | ✅ Full Support | Binance, Alpaca, Coinbase |
| **Stocks** | ✅ Full Support | Alpaca, IB |
| **Futures** | ✅ Full Support | Interactive Brokers |
| **Indices** | ✅ Full Support | MT5, IB |
| **Commodities** | ✅ Full Support | MT5, IB |

---

## 💱 Forex Trading

### Supported Pairs

**Major Pairs:**
- EUR/USD, GBP/USD, USD/JPY, USD/CHF
- AUD/USD, NZD/USD, USD/CAD

**Cross Pairs:**
- EUR/GBP, EUR/JPY, GBP/JPY
- AUD/JPY, CHF/JPY, EUR/AUD

**Exotic Pairs:**
- USD/ZAR, USD/MXN, EUR/TRY
- USD/SGD, USD/HKD

### Broker Configuration

```python
# config/brokers.py
forex_config = {
    'oanda': {
        'api_key': os.getenv('OANDA_API_KEY'),
        'account_id': os.getenv('OANDA_ACCOUNT_ID'),
        'environment': 'practice',  # or 'live'
        'instruments': ['EUR_USD', 'GBP_USD', 'XAU_USD']
    },
    'mt5': {
        'login': os.getenv('MT5_LOGIN'),
        'password': os.getenv('MT5_PASSWORD'),
        'server': os.getenv('MT5_SERVER'),
        'symbols': ['EURUSD', 'GBPUSD', 'XAUUSD']
    }
}
```

### Example: Multi-Pair Strategy

```python
from strategies.base import BaseStrategy
from brokers import BrokerFactory

class MultiPairStrategy(BaseStrategy):
    def __init__(self, config):
        super().__init__(config)
        self.pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD']
        
    def analyze_all_pairs(self, broker):
        signals = []
        for pair in self.pairs:
            data = broker.get_market_data(pair, '1H', limit=100)
            signal = self.generate_signal(data)
            if signal:
                signal.symbol = pair
                signals.append(signal)
        return signals
```

---

## 🥇 Gold (XAU/USD) Trading

### Optimized Features

HOPEFX is specially optimized for gold trading:

- **Gold-specific ML models** trained on XAU/USD patterns
- **Session-aware trading** (London, NY, Asian)
- **News event filters** (FOMC, NFP, etc.)
- **Correlation analysis** with USD index

### Gold Trading Configuration

```python
gold_config = {
    'symbol': 'XAUUSD',
    'timeframes': ['15m', '1H', '4H'],
    'sessions': {
        'london': {'start': '08:00', 'end': '16:00', 'weight': 1.2},
        'new_york': {'start': '13:00', 'end': '21:00', 'weight': 1.3},
        'asian': {'start': '00:00', 'end': '08:00', 'weight': 0.8}
    },
    'risk': {
        'max_spread': 3.0,  # pips
        'min_volatility': 50,  # pips/day
        'max_position': 0.5  # lots
    }
}
```

### Gold-Specific Indicators

```python
from charting.indicators import FibonacciRetracement

# Gold often respects Fibonacci levels
fib = FibonacciRetracement()
levels = fib.calculate_levels(
    swing_high=1950.00,
    swing_low=1900.00,
    is_uptrend=True
)

# Key levels for gold
# 23.6%: 1938.20
# 38.2%: 1930.90
# 50.0%: 1925.00
# 61.8%: 1919.10
```

---

## 🪙 Cryptocurrency Trading

### Supported Exchanges

| Exchange | Features | API |
|----------|----------|-----|
| **Binance** | Spot, Futures, Margin | ✅ Full |
| **Alpaca** | Spot | ✅ Full |
| **Coinbase** | Spot | ✅ Planned |
| **Kraken** | Spot, Futures | ✅ Planned |

### Binance Configuration

```python
from brokers import BinanceConnector

binance = BinanceConnector({
    'api_key': os.getenv('BINANCE_API_KEY'),
    'api_secret': os.getenv('BINANCE_SECRET_KEY'),
    'testnet': True,  # Use testnet for development
})

# Available markets
symbols = binance.get_symbols()
# ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', ...]
```

### Crypto Trading Strategy

```python
class CryptoMomentumStrategy(BaseStrategy):
    """
    Crypto-specific momentum strategy
    
    Considers:
    - 24/7 market operation
    - Higher volatility
    - Correlation with BTC
    """
    
    def __init__(self, config):
        super().__init__(config)
        self.symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
        self.btc_correlation_threshold = 0.7
        
    def generate_signal(self, data):
        # Check BTC trend first (market leader)
        btc_trend = self._get_btc_trend()
        
        # Only trade alts in direction of BTC
        if btc_trend == 'bullish':
            return self._find_bullish_alt()
        elif btc_trend == 'bearish':
            return self._find_bearish_alt()
        
        return None
```

### Crypto-Specific Risk Management

```python
crypto_risk_config = {
    'max_position_pct': 0.05,  # 5% of portfolio per position
    'stop_loss_pct': 0.03,     # 3% stop loss (higher volatility)
    'take_profit_pct': 0.06,   # 6% take profit (2:1 RR)
    'max_daily_trades': 10,    # 24/7 market, limit overtrading
    'correlation_limit': 3,    # Max correlated positions
}
```

---

## 📈 Stock Trading

### Supported Markets

- **US Stocks** via Alpaca, Interactive Brokers
- **International Stocks** via Interactive Brokers
- **ETFs** via all stock brokers

### Alpaca Configuration

```python
from brokers import AlpacaConnector

alpaca = AlpacaConnector({
    'api_key': os.getenv('ALPACA_API_KEY'),
    'api_secret': os.getenv('ALPACA_SECRET_KEY'),
    'paper': True,  # Paper trading
    'base_url': 'https://paper-api.alpaca.markets'
})

# Get account
account = alpaca.get_account()
print(f"Buying Power: ${account.buying_power}")

# Trade stocks
alpaca.place_order(
    symbol='AAPL',
    qty=10,
    side='buy',
    type='market',
    time_in_force='day'
)
```

### Stock Selection Strategy

```python
class StockSelectionStrategy(BaseStrategy):
    """
    Select stocks based on momentum and fundamentals
    """
    
    def __init__(self, config):
        super().__init__(config)
        self.universe = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 
                         'META', 'TSLA', 'JPM', 'V', 'WMT']
        
    def select_stocks(self, broker):
        """Select top momentum stocks"""
        ranked = []
        
        for symbol in self.universe:
            data = broker.get_market_data(symbol, '1D', limit=60)
            momentum = self._calculate_momentum(data)
            ranked.append({'symbol': symbol, 'momentum': momentum})
        
        # Sort by momentum
        ranked.sort(key=lambda x: x['momentum'], reverse=True)
        
        # Return top 5
        return [s['symbol'] for s in ranked[:5]]
```

---

## 📊 Futures Trading

### Supported Contracts

| Category | Contracts |
|----------|-----------|
| **Indices** | ES (S&P 500), NQ (Nasdaq), YM (Dow) |
| **Commodities** | GC (Gold), CL (Oil), SI (Silver) |
| **Currencies** | 6E (Euro), 6B (GBP), 6J (Yen) |
| **Bonds** | ZB (30Y), ZN (10Y), ZF (5Y) |

### Interactive Brokers Configuration

```python
from brokers import InteractiveBrokersConnector

ib = InteractiveBrokersConnector({
    'host': '127.0.0.1',
    'port': 7497,  # TWS paper trading port
    'client_id': 1
})

# Trade ES futures
ib.place_futures_order(
    symbol='ES',
    expiry='202603',
    quantity=1,
    side='buy',
    order_type='market'
)
```

### Futures-Specific Considerations

```python
futures_config = {
    # Contract specifications
    'ES': {
        'tick_size': 0.25,
        'point_value': 50,  # $50 per point
        'margin': 12000,
        'trading_hours': '17:00-16:00'  # Nearly 24h
    },
    'GC': {
        'tick_size': 0.10,
        'point_value': 100,  # $100 per point
        'margin': 8000,
        'trading_hours': '18:00-17:00'
    },
    
    # Risk management
    'risk': {
        'max_contracts': 5,
        'daily_loss_limit': 500,
        'tick_stop_loss': 8  # 8 ticks
    }
}
```

---

## 📉 Indices Trading

### Available Indices

| Index | Symbol | Broker |
|-------|--------|--------|
| S&P 500 | SPX500, US500 | MT5, IB |
| Nasdaq 100 | NAS100, USTEC | MT5, IB |
| Dow Jones | US30, DJI | MT5, IB |
| DAX 40 | GER40, DE40 | MT5, IB |
| FTSE 100 | UK100 | MT5, IB |
| Nikkei 225 | JPN225 | MT5, IB |

### Index Trading Strategy

```python
class IndexCorrelationStrategy(BaseStrategy):
    """
    Trade indices based on market correlations
    """
    
    def __init__(self, config):
        super().__init__(config)
        self.indices = {
            'US500': 'S&P 500',
            'NAS100': 'Nasdaq',
            'US30': 'Dow Jones'
        }
        
    def generate_signal(self, data):
        # Calculate correlation matrix
        correlations = self._calculate_correlations()
        
        # Look for divergence
        if self._detect_divergence():
            return self._trade_divergence()
        
        return None
```

---

## 🏭 Commodities Trading

### Available Commodities

| Category | Commodities |
|----------|-------------|
| **Precious Metals** | Gold (XAU), Silver (XAG), Platinum |
| **Energy** | Crude Oil (WTI, Brent), Natural Gas |
| **Agriculture** | Wheat, Corn, Soybeans, Coffee |

### Commodity Configuration

```python
commodity_config = {
    'XAUUSD': {
        'type': 'precious_metal',
        'pip_value': 0.01,
        'spread_typical': 0.30,
        'correlated_with': ['DXY_inverse', 'XAGUSD']
    },
    'WTIUSD': {
        'type': 'energy',
        'pip_value': 0.01,
        'spread_typical': 0.03,
        'news_sensitive': ['EIA', 'OPEC']
    }
}
```

---

## 🔄 Multi-Asset Portfolio

### Portfolio Allocation

```python
class MultiAssetPortfolio:
    """
    Manage a diversified multi-asset portfolio
    """
    
    def __init__(self, config):
        self.allocation = {
            'forex': 0.30,      # 30% forex
            'crypto': 0.20,     # 20% crypto
            'stocks': 0.25,     # 25% stocks
            'commodities': 0.15, # 15% commodities
            'indices': 0.10     # 10% indices
        }
        
        self.brokers = {
            'forex': OANDAConnector(config['oanda']),
            'crypto': BinanceConnector(config['binance']),
            'stocks': AlpacaConnector(config['alpaca']),
            'commodities': MT5Connector(config['mt5']),
            'indices': InteractiveBrokersConnector(config['ib'])
        }
    
    def rebalance(self):
        """Rebalance portfolio to target allocation"""
        total_equity = self.get_total_equity()
        
        for asset_class, target_pct in self.allocation.items():
            current_value = self.get_asset_class_value(asset_class)
            target_value = total_equity * target_pct
            
            if current_value < target_value * 0.95:
                self._increase_position(asset_class, target_value - current_value)
            elif current_value > target_value * 1.05:
                self._decrease_position(asset_class, current_value - target_value)
```

### Correlation Management

```python
class CorrelationManager:
    """
    Manage portfolio correlation to reduce risk
    """
    
    def __init__(self, max_correlation: float = 0.7):
        self.max_correlation = max_correlation
        
    def check_new_position(self, existing_positions: list, new_symbol: str):
        """Check if new position is too correlated"""
        for position in existing_positions:
            correlation = self._calculate_correlation(
                position['symbol'], 
                new_symbol
            )
            
            if abs(correlation) > self.max_correlation:
                return False, f"High correlation ({correlation:.2f}) with {position['symbol']}"
        
        return True, "Position approved"
```

---

## 📊 Performance Tracking

### Multi-Asset Dashboard

```python
def generate_multi_asset_report(portfolio):
    """Generate multi-asset performance report"""
    
    report = {
        'total_equity': portfolio.get_total_equity(),
        'total_pnl': portfolio.get_total_pnl(),
        'by_asset_class': {}
    }
    
    for asset_class in ['forex', 'crypto', 'stocks', 'commodities', 'indices']:
        report['by_asset_class'][asset_class] = {
            'equity': portfolio.get_asset_class_value(asset_class),
            'pnl': portfolio.get_asset_class_pnl(asset_class),
            'positions': portfolio.get_positions(asset_class),
            'allocation': portfolio.get_allocation(asset_class)
        }
    
    return report
```

---

## 🚀 Getting Started

### 1. Choose Your Asset Classes

Start with one or two asset classes you understand:

```python
# Example: Forex and Crypto
config = {
    'asset_classes': ['forex', 'crypto'],
    'forex': {
        'broker': 'oanda',
        'symbols': ['EURUSD', 'GBPUSD', 'XAUUSD']
    },
    'crypto': {
        'broker': 'binance',
        'symbols': ['BTCUSDT', 'ETHUSDT']
    }
}
```

### 2. Configure Brokers

Set up environment variables:

```bash
# .env
OANDA_API_KEY=your_key
OANDA_ACCOUNT_ID=your_account
BINANCE_API_KEY=your_key
BINANCE_SECRET_KEY=your_secret
```

### 3. Start Paper Trading

```bash
python cli.py paper-trade --config multi_asset_config.yaml
```

---

## 📚 Resources

- [Broker Integration Guide](./API_GUIDE.md)
- [Sample Strategies](./SAMPLE_STRATEGIES.md)
- [Risk Management](./FAQ.md#risk-management)

---

*Diversify your trading with HOPEFX's multi-asset support!*
