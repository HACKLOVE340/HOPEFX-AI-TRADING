# Order Flow API Reference

## Base URL

All endpoints are prefixed with the router prefix shown below.

---

## Time & Sales API (`/api/timesales`)

### `GET /api/timesales/{symbol}/recent`

Get the most recent trades for a symbol.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `n` | int | 100 | Number of trades to return |

**Response:** Array of `ExecutedTrade` objects.

```json
[
  {
    "timestamp": "2024-01-01T10:00:00.000000",
    "symbol": "XAUUSD",
    "price": 1950.05,
    "size": 100.0,
    "side": "buy",
    "trade_id": null,
    "is_aggressive_buy": true,
    "is_aggressive_sell": false,
    "is_large_trade": false
  }
]
```

---

### `GET /api/timesales/{symbol}/large`

Get large trades above a size threshold.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_size` | float | configured threshold | Minimum trade size |
| `lookback_minutes` | int | 60 | Lookback window |

---

### `GET /api/timesales/{symbol}/velocity`

Get trade velocity metrics.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `window_minutes` | int | 5 | Rolling window |

**Response:**
```json
{
  "symbol": "XAUUSD",
  "trades_per_minute": 12.5,
  "volume_per_minute": 625.0,
  "avg_trade_size": 50.0,
  "buy_trades_pct": 62.0,
  "sell_trades_pct": 38.0
}
```

---

### `GET /api/timesales/{symbol}/aggressor`

Get buy vs sell aggressor statistics.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lookback_minutes` | int | 60 | Lookback window |

**Response:**
```json
{
  "symbol": "XAUUSD",
  "total_trades": 150,
  "buy_trades": 93,
  "sell_trades": 57,
  "buy_volume": 4650.0,
  "sell_volume": 2850.0,
  "buy_pct": 62.0,
  "sell_pct": 38.0,
  "net_aggression": 0.24
}
```

---

### `GET /api/timesales/{symbol}/histogram`

Get price/volume distribution histogram.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bins` | int | 20 | Number of price bins |
| `lookback_minutes` | int | 60 | Lookback window |

---

### `GET /api/timesales/{symbol}/statistics`

Get comprehensive trade statistics.

---

### `GET /api/timesales/stats`

Get service-level statistics (symbols tracked, trade counts).

---

## Order Flow API (`/api/orderflow`)

### `GET /api/orderflow/{symbol}/profile`

Get volume profile for a symbol.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `buckets` | int | 50 | Number of price buckets |

**Response:** `VolumeProfile` object with POC, VAH, VAL and per-level data.

---

### `GET /api/orderflow/{symbol}/analysis`

Get complete order flow analysis.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lookback_minutes` | int | 60 | Analysis window |

**Response:** `OrderFlowAnalysis` object including delta, imbalance, S/R levels, signal.

---

### `GET /api/orderflow/{symbol}/footprint`

Get footprint chart data.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeframe` | str | "5m" | Bar timeframe |
| `bars` | int | 20 | Number of bars |

---

### `GET /api/orderflow/{symbol}/levels`

Get key support/resistance levels from order flow.

---

### `GET /api/orderflow/{symbol}/delta`

Get cumulative delta for a symbol.

---

## Depth of Market API (`/api/dom`)

### `GET /api/dom/{symbol}`

Get order book for a symbol.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `levels` | int | 10 | Number of levels |

---

### `GET /api/dom/{symbol}/analysis`

Get comprehensive order book analysis (spread, imbalance, market bias).

---

### `GET /api/dom/{symbol}/visualization`

Get DOM ladder visualization data.

---

### `GET /api/dom/{symbol}/history`

Get historical order book snapshots.

---

### `GET /api/dom/{symbol}/imbalance`

Get current order book imbalance (-1 to +1).

---

## Streaming API (`/api/stream`)

### `GET /api/stream/stats`

Get streaming service statistics.

---

### `GET /api/stream/{symbol}/ticks`

Get recent ticks.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `n` | int | 100 | Number of ticks |

---

### `GET /api/stream/{symbol}/bars/{timeframe}`

Get aggregated OHLCV bars.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Number of bars |

**Example:** `GET /api/stream/XAUUSD/bars/5m?limit=50`

---

### `WebSocket /api/stream/{symbol}/ws`

Real-time WebSocket stream for a symbol.

**Message format:**
```json
{
  "event_type": "tick",
  "symbol": "XAUUSD",
  "timestamp": "2024-01-01T10:00:00.000000",
  "data": {
    "bid": 1950.00,
    "ask": 1950.10,
    "last": 1950.05,
    "volume": 100.0,
    "mid": 1950.05,
    "spread": 0.1
  }
}
```

Event types: `tick`, `bar`, `connected`, `disconnected`.

---

## Dashboard API (`/api/dashboard`)

### `GET /api/dashboard/{symbol}/complete`

Get complete order flow analysis combining all subsystems.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lookback_minutes` | int | 60 | Analysis window |

**Response:**
```json
{
  "symbol": "XAUUSD",
  "timestamp": "2024-01-01T10:00:00",
  "lookback_minutes": 60,
  "order_flow": { ... },
  "institutional": {
    "signals": [...],
    "smart_money_direction": { ... },
    "signal_count": 3
  },
  "advanced": {
    "aggression_metrics": { ... },
    "volume_clusters": [...],
    "delta_divergence": { ... },
    "order_flow_oscillator": { ... },
    "stacked_imbalances": [...],
    "pressure_gauges": { ... }
  },
  "time_and_sales": {
    "statistics": { ... },
    "velocity": { ... },
    "aggressor_stats": { ... }
  },
  "dom": { ... },
  "summary": {
    "bias": "bullish",
    "strength": "moderate",
    "supporting_signals": ["order_flow:bullish", "oscillator:bullish"],
    "bullish_count": 2,
    "bearish_count": 0
  }
}
```

---

### `GET /api/dashboard/{symbol}/bias`

Get high-level market bias summary.

**Response:**
```json
{
  "bias": "bullish",
  "strength": "moderate",
  "supporting_signals": ["order_flow:bullish"],
  "bullish_count": 1,
  "bearish_count": 0
}
```

---

### `GET /api/dashboard/{symbol}/levels`

Get key support/resistance levels.

---

## Data Models

### `ExecutedTrade`
| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | datetime | Execution time |
| `symbol` | str | Trading symbol |
| `price` | float | Execution price |
| `size` | float | Trade size |
| `side` | str | 'buy' or 'sell' |
| `trade_id` | str? | Unique ID (optional) |
| `is_aggressive_buy` | bool | Lifted the ask |
| `is_aggressive_sell` | bool | Hit the bid |
| `is_large_trade` | bool | Above size threshold |

### `FlowSignal`
| Field | Type | Description |
|-------|------|-------------|
| `symbol` | str | Trading symbol |
| `timestamp` | datetime | Detection time |
| `signal_type` | str | 'iceberg', 'volume_spike', 'absorption' |
| `strength` | str | 'strong', 'moderate', 'weak' |
| `direction` | str | 'bullish', 'bearish', 'neutral' |
| `price_level` | float | Price where signal detected |
| `volume` | float | Volume at signal |
| `details` | dict | Additional context |

### `AggressionMetrics`
| Field | Type | Description |
|-------|------|-------------|
| `buy_aggression` | float | Buy volume % (0-100) |
| `sell_aggression` | float | Sell volume % (0-100) |
| `aggression_score` | float | Net score (-100 to +100) |
| `dominant_side` | str | 'buyers', 'sellers', 'neutral' |
| `aggression_strength` | str | 'strong', 'moderate', 'weak' |

### `VolumeCluster`
| Field | Type | Description |
|-------|------|-------------|
| `price_level` | float | Cluster price |
| `total_volume` | float | Total volume at level |
| `buy_volume` | float | Buy-side volume |
| `sell_volume` | float | Sell-side volume |
| `cluster_type` | str | 'support', 'resistance', 'neutral' |
| `strength` | float | Relative strength (0-1) |

### `DeltaDivergence`
| Field | Type | Description |
|-------|------|-------------|
| `divergence_type` | str | 'bullish' or 'bearish' |
| `price_direction` | str | 'up', 'down', 'flat' |
| `delta_direction` | str | 'up', 'down', 'flat' |
| `strength` | float | Divergence strength (0-1) |
| `confidence` | float | Signal confidence (0-1) |
