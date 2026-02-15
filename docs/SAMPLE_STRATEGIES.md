# HOPEFX Sample Trading Strategies

> Ready-to-use trading strategies with explanations and example code

---

## 📋 Table of Contents

1. [Strategy Overview](#strategy-overview)
2. [Getting Started](#getting-started)
3. [Trend Following Strategies](#trend-following-strategies)
4. [Mean Reversion Strategies](#mean-reversion-strategies)
5. [Momentum Strategies](#momentum-strategies)
6. [Advanced Strategies](#advanced-strategies)
7. [ML-Based Strategies](#ml-based-strategies)
8. [Strategy Best Practices](#strategy-best-practices)

---

## Strategy Overview

HOPEFX includes 12+ built-in strategies ready for backtesting and live trading.

| Strategy | Category | Timeframe | Complexity |
|----------|----------|-----------|------------|
| MA Crossover | Trend | 1H-1D | Beginner |
| EMA Crossover | Trend | 15m-4H | Beginner |
| MACD | Momentum | 1H-4H | Beginner |
| RSI Divergence | Reversal | 1H-4H | Intermediate |
| Bollinger Bands | Volatility | 15m-1H | Intermediate |
| Breakout | Momentum | 4H-1D | Intermediate |
| SMC/ICT | Institutional | 15m-4H | Advanced |
| Ichimoku | Trend | 1H-1D | Advanced |
| Mean Reversion | Statistical | 5m-1H | Advanced |
| ML Prediction | AI | All | Expert |

---

## Getting Started

### Basic Strategy Structure

All strategies inherit from `BaseStrategy`:

```python
from strategies.base import BaseStrategy, Signal
from typing import Optional
import pandas as pd

class MyStrategy(BaseStrategy):
    """
    Custom trading strategy.
    
    Parameters:
        - param1: Description
        - param2: Description
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.name = "My Strategy"
        self.version = "1.0.0"
        
        # Strategy parameters
        self.param1 = self.config.get('param1', 20)
        self.param2 = self.config.get('param2', 50)
    
    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        """
        Generate trading signal from market data.
        
        Args:
            data: DataFrame with OHLCV columns
            
        Returns:
            Signal object or None
        """
        if len(data) < self.param2:
            return None
            
        # Your strategy logic here
        if self._should_buy(data):
            return Signal(
                action='buy',
                symbol=self.config.get('symbol', 'XAUUSD'),
                strength=0.8,
                stop_loss=self._calculate_stop_loss(data, 'buy'),
                take_profit=self._calculate_take_profit(data, 'buy'),
                reason="Buy signal generated"
            )
        
        if self._should_sell(data):
            return Signal(
                action='sell',
                symbol=self.config.get('symbol', 'XAUUSD'),
                strength=0.8,
                stop_loss=self._calculate_stop_loss(data, 'sell'),
                take_profit=self._calculate_take_profit(data, 'sell'),
                reason="Sell signal generated"
            )
        
        return None
    
    def _should_buy(self, data: pd.DataFrame) -> bool:
        """Check buy conditions."""
        # Implement your buy logic
        return False
    
    def _should_sell(self, data: pd.DataFrame) -> bool:
        """Check sell conditions."""
        # Implement your sell logic
        return False
```

### Running a Strategy

```python
from strategies import get_strategy
from brokers import BrokerFactory

# Load strategy
strategy = get_strategy('ma_crossover', {
    'fast_period': 20,
    'slow_period': 50,
    'symbol': 'XAUUSD',
    'timeframe': '1H'
})

# Connect broker
broker = BrokerFactory.create('paper_trading')

# Run strategy
while True:
    data = broker.get_market_data('XAUUSD', '1H', limit=100)
    signal = strategy.generate_signal(data)
    
    if signal:
        broker.execute_signal(signal)
```

---

## Trend Following Strategies

### 1. Simple Moving Average Crossover

**Concept:** Buy when fast MA crosses above slow MA, sell when it crosses below.

```python
# strategies/ma_crossover.py
from strategies.base import BaseStrategy, Signal
import pandas as pd

class MACrossoverStrategy(BaseStrategy):
    """
    Simple Moving Average Crossover Strategy
    
    Classic trend-following strategy that generates:
    - BUY signal when fast SMA crosses above slow SMA
    - SELL signal when fast SMA crosses below slow SMA
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.name = "MA Crossover"
        
        # Parameters
        self.fast_period = self.config.get('fast_period', 20)
        self.slow_period = self.config.get('slow_period', 50)
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        if len(data) < self.slow_period + 1:
            return None
        
        # Calculate SMAs
        data['fast_sma'] = data['close'].rolling(self.fast_period).mean()
        data['slow_sma'] = data['close'].rolling(self.slow_period).mean()
        
        # Get last two values for crossover detection
        fast_curr = data['fast_sma'].iloc[-1]
        fast_prev = data['fast_sma'].iloc[-2]
        slow_curr = data['slow_sma'].iloc[-1]
        slow_prev = data['slow_sma'].iloc[-2]
        
        # Bullish crossover
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            return Signal(
                action='buy',
                symbol=self.config.get('symbol'),
                strength=0.7,
                stop_loss=data['low'].tail(20).min(),
                take_profit=data['close'].iloc[-1] + 2 * (data['close'].iloc[-1] - data['low'].tail(20).min()),
                reason=f"Bullish MA crossover: {self.fast_period}/{self.slow_period}"
            )
        
        # Bearish crossover
        if fast_prev >= slow_prev and fast_curr < slow_curr:
            return Signal(
                action='sell',
                symbol=self.config.get('symbol'),
                strength=0.7,
                stop_loss=data['high'].tail(20).max(),
                take_profit=data['close'].iloc[-1] - 2 * (data['high'].tail(20).max() - data['close'].iloc[-1]),
                reason=f"Bearish MA crossover: {self.fast_period}/{self.slow_period}"
            )
        
        return None
```

**Configuration:**
```yaml
strategy: ma_crossover
params:
  fast_period: 20
  slow_period: 50
  symbol: XAUUSD
  timeframe: 1H
risk:
  risk_per_trade: 0.02
  max_positions: 2
```

### 2. EMA Crossover with Trend Filter

**Concept:** EMA crossover with ADX trend strength filter.

```python
# strategies/ema_crossover_adx.py
class EMACrossoverADX(BaseStrategy):
    """
    EMA Crossover with ADX Trend Filter
    
    Only takes signals when trend strength (ADX) is strong.
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.fast_ema = self.config.get('fast_ema', 9)
        self.slow_ema = self.config.get('slow_ema', 21)
        self.adx_period = self.config.get('adx_period', 14)
        self.adx_threshold = self.config.get('adx_threshold', 25)
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        # Calculate EMAs
        data['fast_ema'] = data['close'].ewm(span=self.fast_ema).mean()
        data['slow_ema'] = data['close'].ewm(span=self.slow_ema).mean()
        
        # Calculate ADX
        adx = self._calculate_adx(data)
        
        # Only trade when trend is strong
        if adx.iloc[-1] < self.adx_threshold:
            return None
        
        # Check for crossover
        if self._bullish_crossover(data):
            return Signal(action='buy', symbol=self.config.get('symbol'))
        
        if self._bearish_crossover(data):
            return Signal(action='sell', symbol=self.config.get('symbol'))
        
        return None
```

### 3. Ichimoku Cloud Strategy

**Concept:** Complete trading system using Ichimoku indicators.

```python
# strategies/ichimoku_strategy.py
from charting.indicators import IchimokuCloud

class IchimokuStrategy(BaseStrategy):
    """
    Ichimoku Cloud Trading Strategy
    
    Signals:
    - BUY: Price above cloud, Tenkan > Kijun, Chikou confirms
    - SELL: Price below cloud, Tenkan < Kijun, Chikou confirms
    """
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        # Calculate Ichimoku
        ichimoku = IchimokuCloud()
        components = ichimoku.calculate_with_hlc(
            data['high'].tolist(),
            data['low'].tolist(),
            data['close'].tolist()
        )
        
        current_price = data['close'].iloc[-1]
        tenkan = components['tenkan_sen'][-1]
        kijun = components['kijun_sen'][-1]
        span_a = components['senkou_span_a'][-1] if components['senkou_span_a'] else 0
        span_b = components['senkou_span_b'][-1] if components['senkou_span_b'] else 0
        
        cloud_top = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)
        
        # Bullish: Price above cloud + TK cross bullish
        if current_price > cloud_top and tenkan > kijun:
            return Signal(
                action='buy',
                symbol=self.config.get('symbol'),
                strength=0.85,
                reason="Bullish Ichimoku: Price above cloud, TK bullish"
            )
        
        # Bearish: Price below cloud + TK cross bearish
        if current_price < cloud_bottom and tenkan < kijun:
            return Signal(
                action='sell',
                symbol=self.config.get('symbol'),
                strength=0.85,
                reason="Bearish Ichimoku: Price below cloud, TK bearish"
            )
        
        return None
```

---

## Mean Reversion Strategies

### 4. Bollinger Bands Mean Reversion

**Concept:** Buy when price touches lower band, sell at upper band.

```python
# strategies/bollinger_bands.py
class BollingerBandsStrategy(BaseStrategy):
    """
    Bollinger Bands Mean Reversion Strategy
    
    Trades price returning to the mean after touching bands.
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.period = self.config.get('period', 20)
        self.std_dev = self.config.get('std_dev', 2.0)
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        # Calculate Bollinger Bands
        sma = data['close'].rolling(self.period).mean()
        std = data['close'].rolling(self.period).std()
        
        upper_band = sma + (self.std_dev * std)
        lower_band = sma - (self.std_dev * std)
        
        current_price = data['close'].iloc[-1]
        prev_price = data['close'].iloc[-2]
        
        # Buy signal: Price crosses below lower band then bounces
        if prev_price <= lower_band.iloc[-2] and current_price > lower_band.iloc[-1]:
            return Signal(
                action='buy',
                symbol=self.config.get('symbol'),
                strength=0.75,
                stop_loss=lower_band.iloc[-1] - (std.iloc[-1] * 0.5),
                take_profit=sma.iloc[-1],  # Target the mean
                reason="BB lower band bounce"
            )
        
        # Sell signal: Price crosses above upper band then reverses
        if prev_price >= upper_band.iloc[-2] and current_price < upper_band.iloc[-1]:
            return Signal(
                action='sell',
                symbol=self.config.get('symbol'),
                strength=0.75,
                stop_loss=upper_band.iloc[-1] + (std.iloc[-1] * 0.5),
                take_profit=sma.iloc[-1],  # Target the mean
                reason="BB upper band rejection"
            )
        
        return None
```

### 5. RSI Mean Reversion

**Concept:** Trade oversold/overbought conditions with confirmation.

```python
# strategies/rsi_reversal.py
class RSIReversalStrategy(BaseStrategy):
    """
    RSI Reversal Strategy with Divergence Detection
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.rsi_period = self.config.get('rsi_period', 14)
        self.oversold = self.config.get('oversold', 30)
        self.overbought = self.config.get('overbought', 70)
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        from charting.indicators import RSI
        
        rsi = RSI('RSI', self.rsi_period)
        rsi_values = rsi.calculate(data['close'].tolist())
        
        if len(rsi_values) < 2:
            return None
        
        current_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2]
        
        # Bullish reversal from oversold
        if prev_rsi < self.oversold and current_rsi > self.oversold:
            # Confirmation: check for bullish divergence
            if self._check_bullish_divergence(data, rsi_values):
                return Signal(
                    action='buy',
                    symbol=self.config.get('symbol'),
                    strength=0.8,
                    reason=f"RSI reversal from oversold ({current_rsi:.1f}) with bullish divergence"
                )
        
        # Bearish reversal from overbought
        if prev_rsi > self.overbought and current_rsi < self.overbought:
            if self._check_bearish_divergence(data, rsi_values):
                return Signal(
                    action='sell',
                    symbol=self.config.get('symbol'),
                    strength=0.8,
                    reason=f"RSI reversal from overbought ({current_rsi:.1f}) with bearish divergence"
                )
        
        return None
    
    def _check_bullish_divergence(self, data, rsi_values):
        """Check for bullish divergence (lower low in price, higher low in RSI)"""
        # Look back 10 bars
        if len(rsi_values) < 10:
            return False
        
        price_low = min(data['low'].tail(10))
        price_prev_low = min(data['low'].tail(20).head(10))
        rsi_low = min(rsi_values[-10:])
        rsi_prev_low = min(rsi_values[-20:-10]) if len(rsi_values) >= 20 else rsi_low
        
        # Price made lower low but RSI made higher low
        return price_low < price_prev_low and rsi_low > rsi_prev_low
```

---

## Momentum Strategies

### 6. MACD Strategy

**Concept:** Trade MACD line and signal line crossovers.

```python
# strategies/macd_strategy.py
from charting.indicators import MACD

class MACDStrategy(BaseStrategy):
    """
    MACD Crossover Strategy
    
    Uses MACD line/signal line crossovers with histogram confirmation.
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.fast = self.config.get('fast_period', 12)
        self.slow = self.config.get('slow_period', 26)
        self.signal = self.config.get('signal_period', 9)
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        macd = MACD('MACD', self.fast, self.slow, self.signal)
        result = macd.calculate(data['close'].tolist())
        
        macd_line = result['macd']
        signal_line = result['signal']
        histogram = result['histogram']
        
        if len(histogram) < 2:
            return None
        
        # Bullish crossover: MACD crosses above signal
        if (macd_line[-2] <= signal_line[-2] and 
            macd_line[-1] > signal_line[-1] and
            histogram[-1] > histogram[-2]):  # Histogram expanding
            return Signal(
                action='buy',
                symbol=self.config.get('symbol'),
                strength=0.7,
                reason="Bullish MACD crossover"
            )
        
        # Bearish crossover: MACD crosses below signal
        if (macd_line[-2] >= signal_line[-2] and 
            macd_line[-1] < signal_line[-1] and
            histogram[-1] < histogram[-2]):  # Histogram contracting
            return Signal(
                action='sell',
                symbol=self.config.get('symbol'),
                strength=0.7,
                reason="Bearish MACD crossover"
            )
        
        return None
```

### 7. Breakout Strategy

**Concept:** Trade price breakouts from consolidation ranges.

```python
# strategies/breakout.py
class BreakoutStrategy(BaseStrategy):
    """
    Price Breakout Strategy
    
    Identifies consolidation and trades breakouts with volume confirmation.
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.lookback = self.config.get('lookback', 20)
        self.volume_threshold = self.config.get('volume_threshold', 1.5)
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        if len(data) < self.lookback:
            return None
        
        # Calculate range
        high = data['high'].tail(self.lookback).max()
        low = data['low'].tail(self.lookback).min()
        avg_volume = data['volume'].tail(self.lookback).mean()
        
        current_price = data['close'].iloc[-1]
        current_volume = data['volume'].iloc[-1]
        
        # Volume confirmation
        volume_confirmed = current_volume > (avg_volume * self.volume_threshold)
        
        # Bullish breakout
        if current_price > high and volume_confirmed:
            range_size = high - low
            return Signal(
                action='buy',
                symbol=self.config.get('symbol'),
                strength=0.8,
                stop_loss=high - (range_size * 0.5),  # Below breakout level
                take_profit=current_price + range_size,  # Measured move
                reason=f"Bullish breakout above {high:.2f} with volume"
            )
        
        # Bearish breakout
        if current_price < low and volume_confirmed:
            range_size = high - low
            return Signal(
                action='sell',
                symbol=self.config.get('symbol'),
                strength=0.8,
                stop_loss=low + (range_size * 0.5),
                take_profit=current_price - range_size,
                reason=f"Bearish breakout below {low:.2f} with volume"
            )
        
        return None
```

---

## Advanced Strategies

### 8. SMC/ICT Smart Money Concepts

**Concept:** Trade like institutions using market structure analysis.

```python
# strategies/smc_ict.py
class SMCICTStrategy(BaseStrategy):
    """
    Smart Money Concepts / Inner Circle Trader Strategy
    
    Identifies:
    - Order blocks (supply/demand zones)
    - Fair value gaps (FVG)
    - Liquidity sweeps
    - Market structure breaks
    """
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        # Identify market structure
        structure = self._identify_structure(data)
        
        # Find order blocks
        order_blocks = self._find_order_blocks(data)
        
        # Find fair value gaps
        fvgs = self._find_fair_value_gaps(data)
        
        # Check for liquidity sweep
        sweep = self._check_liquidity_sweep(data)
        
        current_price = data['close'].iloc[-1]
        
        # Bullish setup: 
        # - Bullish market structure
        # - Price at bullish order block
        # - Recent liquidity sweep below
        if (structure == 'bullish' and 
            self._price_at_bullish_ob(current_price, order_blocks) and
            sweep == 'bullish'):
            return Signal(
                action='buy',
                symbol=self.config.get('symbol'),
                strength=0.9,
                reason="SMC bullish setup: OB entry after liquidity sweep"
            )
        
        # Bearish setup
        if (structure == 'bearish' and 
            self._price_at_bearish_ob(current_price, order_blocks) and
            sweep == 'bearish'):
            return Signal(
                action='sell',
                symbol=self.config.get('symbol'),
                strength=0.9,
                reason="SMC bearish setup: OB entry after liquidity sweep"
            )
        
        return None
    
    def _identify_structure(self, data: pd.DataFrame) -> str:
        """Identify market structure (HH/HL = bullish, LH/LL = bearish)"""
        highs = data['high'].tail(50)
        lows = data['low'].tail(50)
        
        # Find swing points
        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)
        
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            # Higher highs and higher lows = bullish
            if (swing_highs[-1] > swing_highs[-2] and 
                swing_lows[-1] > swing_lows[-2]):
                return 'bullish'
            # Lower highs and lower lows = bearish
            if (swing_highs[-1] < swing_highs[-2] and 
                swing_lows[-1] < swing_lows[-2]):
                return 'bearish'
        
        return 'ranging'
    
    def _find_order_blocks(self, data: pd.DataFrame) -> list:
        """Find bullish and bearish order blocks"""
        order_blocks = []
        
        for i in range(2, len(data) - 1):
            # Bullish OB: Last down candle before up move
            if (data['close'].iloc[i] < data['open'].iloc[i] and  # Down candle
                data['close'].iloc[i+1] > data['open'].iloc[i+1] and  # Up candle follows
                data['close'].iloc[i+1] > data['high'].iloc[i]):  # Closes above
                order_blocks.append({
                    'type': 'bullish',
                    'high': data['high'].iloc[i],
                    'low': data['low'].iloc[i],
                    'index': i
                })
            
            # Bearish OB: Last up candle before down move
            if (data['close'].iloc[i] > data['open'].iloc[i] and  # Up candle
                data['close'].iloc[i+1] < data['open'].iloc[i+1] and  # Down candle follows
                data['close'].iloc[i+1] < data['low'].iloc[i]):  # Closes below
                order_blocks.append({
                    'type': 'bearish',
                    'high': data['high'].iloc[i],
                    'low': data['low'].iloc[i],
                    'index': i
                })
        
        return order_blocks
```

### 9. Fibonacci Retracement Strategy

**Concept:** Trade pullbacks to Fibonacci levels in trending markets.

```python
# strategies/fibonacci_strategy.py
from charting.indicators import FibonacciRetracement

class FibonacciStrategy(BaseStrategy):
    """
    Fibonacci Retracement Strategy
    
    Trades pullbacks to key Fibonacci levels (38.2%, 50%, 61.8%)
    """
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        # Find recent swing high and low
        swing_high, swing_low = FibonacciRetracement.auto_detect_swings(
            data['high'].tolist(),
            data['low'].tolist(),
            lookback=50
        )
        
        # Calculate Fibonacci levels
        levels = FibonacciRetracement.calculate_levels(
            swing_high, swing_low, is_uptrend=True
        )
        
        current_price = data['close'].iloc[-1]
        
        # Check if price is at a Fibonacci level
        fib_382 = levels['38.2%']
        fib_500 = levels['50.0%']
        fib_618 = levels['61.8%']
        
        tolerance = (swing_high - swing_low) * 0.02  # 2% tolerance
        
        # Trend must be up (price was recently at swing high)
        is_uptrend = data['high'].tail(10).max() >= swing_high * 0.98
        
        if is_uptrend:
            # Buy at 61.8% (strongest level)
            if abs(current_price - fib_618) < tolerance:
                return Signal(
                    action='buy',
                    symbol=self.config.get('symbol'),
                    strength=0.85,
                    stop_loss=levels['78.6%'],
                    take_profit=swing_high,
                    reason="Fibonacci 61.8% retracement in uptrend"
                )
            
            # Buy at 50%
            if abs(current_price - fib_500) < tolerance:
                return Signal(
                    action='buy',
                    symbol=self.config.get('symbol'),
                    strength=0.75,
                    stop_loss=levels['61.8%'],
                    take_profit=swing_high,
                    reason="Fibonacci 50% retracement in uptrend"
                )
        
        return None
```

---

## ML-Based Strategies

### 10. LSTM Price Prediction

**Concept:** Use neural network to predict next candle direction.

```python
# strategies/ml_prediction.py
class MLPredictionStrategy(BaseStrategy):
    """
    Machine Learning Prediction Strategy
    
    Uses trained LSTM model to predict price direction.
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        self.model = self._load_model()
        self.confidence_threshold = self.config.get('confidence_threshold', 0.7)
    
    def _load_model(self):
        """Load pre-trained model"""
        from ml.models import load_model
        model_path = self.config.get('model_path', 'models/xauusd_lstm.h5')
        return load_model(model_path)
    
    def _prepare_features(self, data: pd.DataFrame):
        """Prepare features for model input"""
        features = pd.DataFrame()
        
        # Technical indicators as features
        features['returns'] = data['close'].pct_change()
        features['sma_20'] = data['close'].rolling(20).mean() / data['close']
        features['sma_50'] = data['close'].rolling(50).mean() / data['close']
        features['rsi'] = self._calculate_rsi(data['close'], 14) / 100
        features['volatility'] = data['close'].rolling(20).std() / data['close']
        
        return features.dropna()
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        features = self._prepare_features(data)
        
        if len(features) < 50:
            return None
        
        # Get prediction
        X = features.tail(50).values.reshape(1, 50, -1)
        prediction = self.model.predict(X)[0]
        
        # prediction[0] = probability of up
        # prediction[1] = probability of down
        
        prob_up = prediction[0]
        prob_down = prediction[1]
        
        if prob_up > self.confidence_threshold:
            return Signal(
                action='buy',
                symbol=self.config.get('symbol'),
                strength=float(prob_up),
                reason=f"ML predicts UP with {prob_up:.1%} confidence"
            )
        
        if prob_down > self.confidence_threshold:
            return Signal(
                action='sell',
                symbol=self.config.get('symbol'),
                strength=float(prob_down),
                reason=f"ML predicts DOWN with {prob_down:.1%} confidence"
            )
        
        return None
```

---

## Strategy Best Practices

### 1. Risk Management

Always implement proper risk management:

```python
class RiskManagedStrategy(BaseStrategy):
    def execute_with_risk(self, signal: Signal):
        # Check daily loss limit
        if self.daily_loss > self.max_daily_loss:
            return None
        
        # Calculate position size
        risk_amount = self.capital * self.risk_per_trade
        stop_distance = abs(signal.entry - signal.stop_loss)
        position_size = risk_amount / stop_distance
        
        # Apply position limit
        position_size = min(position_size, self.max_position_size)
        
        return self.broker.execute(signal, position_size)
```

### 2. Backtesting First

Always backtest before live trading:

```python
from backtesting import BacktestEngine

engine = BacktestEngine()
results = engine.run(
    strategy=MyStrategy(),
    data=historical_data,
    initial_capital=10000
)

print(f"Win Rate: {results.win_rate:.1%}")
print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
print(f"Max Drawdown: {results.max_drawdown:.1%}")
```

### 3. Paper Trading

Test with paper trading before real money:

```python
from brokers import PaperTradingBroker

broker = PaperTradingBroker(initial_balance=10000)
strategy = MyStrategy(config)

for data in market_data_stream:
    signal = strategy.generate_signal(data)
    if signal:
        broker.execute(signal)
```

### 4. Logging and Monitoring

Always log your trades:

```python
import logging

logger = logging.getLogger('strategy')

def generate_signal(self, data):
    signal = self._analyze(data)
    
    if signal:
        logger.info(f"Signal: {signal.action} {signal.symbol}")
        logger.info(f"Reason: {signal.reason}")
        logger.info(f"Strength: {signal.strength}")
    
    return signal
```

---

## Getting Help

- **Discord:** `#trading-strategies` channel
- **GitHub:** Submit issues or discussions
- **Documentation:** [docs/](../docs/)

---

*These sample strategies are for educational purposes. Always backtest and paper trade before using real money.*
