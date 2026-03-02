# Order Flow Analysis Guide

## Overview

The HOPEFX Order Flow Analysis system provides professional-grade tools for analyzing
market microstructure, identifying institutional activity, and making data-driven
trading decisions based on real-time trade flow.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  OrderFlowDashboard                       │
│              (analysis/order_flow_dashboard.py)           │
├──────────────┬──────────────┬───────────────┬────────────┤
│ OrderFlow    │ Institutional│ Advanced      │ Time &     │
│ Analyzer     │ Flow         │ Order Flow    │ Sales      │
│ (base)       │ Detector     │ Analyzer      │ Service    │
├──────────────┴──────────────┴───────────────┴────────────┤
│              Depth of Market Service                      │
│              Streaming Service                            │
└──────────────────────────────────────────────────────────┘
```

## Components

### 1. Time & Sales Service (`data/time_and_sales.py`)

Records and analyses every executed trade (the trade tape).

```python
from data.time_and_sales import TimeAndSalesService

service = TimeAndSalesService(config={
    'max_trades': 10000,           # Circular buffer size per symbol
    'large_trade_threshold': 100,  # Minimum size for large-trade flag
    'velocity_window_minutes': 5,  # Window for velocity calculation
})

# Add a trade
trade = service.add_trade(
    symbol='XAUUSD',
    price=1950.05,
    size=250.0,
    side='buy',
    ask_price=1950.05,  # Optional: for aggressor confirmation
)

# Recent trades
trades = service.get_recent_trades('XAUUSD', n=100)

# Time-filtered trades
from datetime import datetime, timedelta
trades = service.get_trades_by_time(
    'XAUUSD',
    start_time=datetime.utcnow() - timedelta(minutes=30),
)

# Large trades
large = service.get_large_trades('XAUUSD', min_size=500)

# Velocity metrics
velocity = service.get_trade_velocity('XAUUSD')
print(f"Trades/min: {velocity.trades_per_minute}")
print(f"Buy %: {velocity.buy_trades_pct}")

# Aggressor stats
stats = service.get_aggressor_stats('XAUUSD')
print(f"Net aggression: {stats.net_aggression}")

# Price/volume histogram
histogram = service.get_trade_histogram('XAUUSD', bins=20)

# Full statistics
summary = service.get_trade_statistics('XAUUSD')
```

**Key dataclasses:**

| Class | Description |
|-------|-------------|
| `ExecutedTrade` | Individual trade record with aggressor flags |
| `TradeVelocity` | Velocity metrics: trades/min, volume/min, buy% |
| `AggressorStats` | Buy vs sell volume and count breakdown |

---

### 2. Institutional Flow Detector (`analysis/institutional_flow.py`)

Identifies institutional vs retail trading activity.

```python
from analysis.institutional_flow import InstitutionalFlowDetector

detector = InstitutionalFlowDetector(config={
    'large_order_threshold': 200,      # Institutional size threshold
    'volume_spike_multiplier': 3.0,    # Multiplier to flag volume spikes
    'iceberg_min_fills': 3,            # Min fills to identify iceberg
    'iceberg_window_seconds': 60,      # Time window for iceberg detection
    'absorption_price_pct': 0.05,      # Max price move % for absorption
})

# Feed trades
detector.add_trade('XAUUSD', price=1950.0, size=500.0, side='buy')

# Detect large institutional orders
large = detector.detect_large_orders('XAUUSD')

# Detect iceberg orders (repeated fills at same price)
icebergs = detector.detect_iceberg_orders('XAUUSD')

# Detect volume spikes
spikes = detector.detect_volume_spikes('XAUUSD')

# Detect absorption (high volume, low price movement)
absorptions = detector.detect_absorption('XAUUSD')

# Classify a single trade
classification = detector.classify_trade(price=1950.0, size=500.0, side='buy')
print(f"Classification: {classification.classification}")  # 'institutional'

# Full analysis (all signal types combined)
signals = detector.analyze_flow('XAUUSD')

# Get smart money direction
direction = detector.get_smart_money_direction('XAUUSD')
print(f"Smart money: {direction.direction}")  # 'bullish' / 'bearish' / 'neutral'
```

**Signal types:**

| Signal Type | Description |
|-------------|-------------|
| `iceberg` | Repeated fills at the same price level |
| `volume_spike` | Volume significantly above recent average |
| `absorption` | High volume with minimal price movement |
| `smart_money` | Net institutional flow direction |

---

### 3. Advanced Order Flow Analyzer (`analysis/advanced_order_flow.py`)

Professional-grade metrics for active traders.

```python
from analysis.advanced_order_flow import AdvancedOrderFlowAnalyzer

analyzer = AdvancedOrderFlowAnalyzer(config={
    'tick_size': 0.01,
    'cluster_bins': 50,
    'imbalance_threshold': 0.3,
    'oscillator_period': 100,
})

analyzer.add_trade('XAUUSD', 1950.0, 100.0, 'buy')

# Aggression metrics
metrics = analyzer.get_aggression_metrics('XAUUSD')
print(f"Aggression score: {metrics.aggression_score}")  # -100 to +100

# Volume imbalance per price level
levels = analyzer.get_volume_imbalance_by_level('XAUUSD', price_bins=20)

# Stacked imbalances (consecutive levels with same direction)
stacked = analyzer.get_stacked_imbalances('XAUUSD', min_stack_size=3)

# Delta divergence (price vs cumulative delta)
divergence = analyzer.detect_delta_divergence('XAUUSD')
if divergence:
    print(f"Divergence: {divergence.divergence_type}")

# Volume clusters (S/R levels from volume)
clusters = analyzer.get_volume_clusters('XAUUSD', current_price=1950.0)
for c in clusters:
    print(f"{c.cluster_type} @ {c.price_level} (strength={c.strength:.2f})")

# Order flow oscillator
osc = analyzer.get_order_flow_oscillator('XAUUSD')
print(f"Oscillator: {osc.value:.1f} ({osc.signal})")

# Buy/sell pressure gauges
pressure = analyzer.get_pressure_gauges('XAUUSD')
print(f"Buy pressure: {pressure['buy_pressure']:.1f}%")
```

---

### 4. Real-Time Streaming Service (`data/streaming.py`)

WebSocket-capable tick streaming with bar aggregation.

```python
from data.streaming import StreamingService, Tick, StreamEvent

service = StreamingService(config={
    'max_ticks_buffer': 10000,
    'default_timeframes': [1, 5, 15],  # minutes
    'reconnect_max_attempts': 5,
    'reconnect_base_delay': 2,
})

# Subscribe to events
def on_event(event: StreamEvent):
    if event.event_type == 'tick':
        print(f"Tick: {event.data['last']}")
    elif event.event_type == 'bar':
        print(f"Bar closed: {event.data['close']}")

service.subscribe('XAUUSD', on_event)

# Subscribe to all symbols
service.subscribe('*', on_event)

# Publish a tick (or use a broker adapter)
service.connect()
tick = Tick(
    symbol='XAUUSD',
    timestamp=datetime.utcnow(),
    bid=1950.00,
    ask=1950.10,
    last=1950.05,
    volume=100.0,
)
service.publish_tick(tick)

# Retrieve data
recent_ticks = service.get_recent_ticks('XAUUSD', n=100)
bars = service.get_bars('XAUUSD', timeframe='5m', limit=50)

# Get stats
print(service.get_stats())
```

**WebSocket endpoint:** `GET /api/stream/{symbol}/ws`

---

### 5. Order Flow Dashboard (`analysis/order_flow_dashboard.py`)

Unified view combining all components.

```python
from analysis.order_flow_dashboard import OrderFlowDashboard

# Uses global singleton instances by default
dashboard = OrderFlowDashboard()

# Get complete analysis snapshot
analysis = dashboard.get_complete_analysis('XAUUSD', lookback_minutes=60)

# Top-level summary
print(analysis['summary']['bias'])      # 'bullish' / 'bearish' / 'neutral'
print(analysis['summary']['strength'])  # 'strong' / 'moderate' / 'weak'

# Individual components
order_flow   = analysis['order_flow']
institutional = analysis['institutional']
advanced     = analysis['advanced']
time_sales   = analysis['time_and_sales']
dom          = analysis['dom']

# Quick market bias
bias = dashboard.get_market_bias('XAUUSD')

# Key S/R levels
levels = dashboard.get_key_levels('XAUUSD')
print(levels['support'])
print(levels['resistance'])
```

---

## Feeding Data to the Services

All services require trade/tick data to be fed in externally (from a broker adapter
or data feed). Here is a pattern to feed multiple services simultaneously:

```python
from data.time_and_sales import get_time_and_sales_service
from analysis.institutional_flow import get_institutional_detector
from analysis.advanced_order_flow import get_advanced_order_flow_analyzer
from analysis.order_flow import get_order_flow_analyzer
from data.streaming import get_streaming_service, Tick

ts_service = get_time_and_sales_service()
inst_detector = get_institutional_detector()
adv_analyzer = get_advanced_order_flow_analyzer()
of_analyzer = get_order_flow_analyzer()
streaming = get_streaming_service()

def on_trade(symbol: str, price: float, size: float, side: str, bid: float, ask: float):
    """Call this whenever a trade executes."""
    from datetime import datetime
    now = datetime.utcnow()

    ts_service.add_trade(symbol, price, size, side, ask_price=ask, bid_price=bid)
    inst_detector.add_trade(symbol, price, size, side)
    adv_analyzer.add_trade(symbol, price, size, side)
    of_analyzer.add_trade(symbol, price, size, side)

    # Also publish as a tick
    tick = Tick(symbol=symbol, timestamp=now, bid=bid, ask=ask, last=price, volume=size)
    streaming.publish_tick(tick)
```

## Thread Safety

All services are thread-safe. The streaming and DOM services use `threading.RLock`
internally, and the Time & Sales service's circular buffers are protected by an
`RLock` as well. You can safely call `add_trade()` and the read methods from
multiple threads concurrently.

## Performance Notes

- Trade buffers use `collections.deque` for O(1) append/pop
- All services cap buffer sizes to avoid unbounded memory growth
- The system can handle 1000+ trades/second on modern hardware
- The dashboard caches nothing - each call runs fresh analysis

## FastAPI Integration

All services expose a `create_*_router()` factory for FastAPI:

```python
from fastapi import FastAPI
from data.time_and_sales import TimeAndSalesService, create_time_and_sales_router
from analysis.institutional_flow import InstitutionalFlowDetector
from analysis.order_flow_dashboard import OrderFlowDashboard, create_dashboard_router

app = FastAPI()
ts = TimeAndSalesService()
dashboard = OrderFlowDashboard()

app.include_router(create_time_and_sales_router(ts))
app.include_router(create_dashboard_router(dashboard))
```
