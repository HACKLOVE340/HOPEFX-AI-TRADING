# HOPEFX AI Trading API Guide

> **Version:** 1.0.0 | **Last Updated:** February 2026

A comprehensive developer guide for integrating with the HOPEFX AI Trading API.

---

## 📋 Table of Contents

1. [Getting Started](#getting-started)
2. [Authentication](#authentication)
3. [API Endpoints](#api-endpoints)
4. [WebSocket Streaming](#websocket-streaming)
5. [Rate Limits](#rate-limits)
6. [Error Handling](#error-handling)
7. [Code Examples](#code-examples)
8. [SDKs and Libraries](#sdks-and-libraries)

---

## Getting Started

### Base URL

```
Development: http://localhost:5000
Production:  https://api.hopefx.com/v1
```

### API Documentation

Interactive API documentation is available at:
- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`
- **OpenAPI Schema:** `/openapi.json`

### Quick Start

```bash
# Start the API server
python app.py

# Test the API is running
curl http://localhost:5000/health
```

---

## Authentication

### API Key Authentication

Include your API key in the request header:

```http
Authorization: Bearer YOUR_API_KEY
```

### Getting Your API Key

1. Register at the HOPEFX dashboard
2. Navigate to Settings → API Keys
3. Generate a new API key
4. Store it securely (you won't see it again)

### Example Request

```bash
curl -X GET "http://localhost:5000/api/v1/portfolio" \
  -H "Authorization: Bearer your_api_key_here" \
  -H "Content-Type: application/json"
```

---

## API Endpoints

### System Endpoints

#### Health Check
```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "production",
  "components": {
    "api": "healthy",
    "database": "healthy",
    "cache": "healthy",
    "config": "healthy"
  }
}
```

#### System Status
```http
GET /status
```

**Response:**
```json
{
  "application": "HOPEFX AI Trading",
  "version": "1.0.0",
  "environment": "production",
  "config_loaded": true,
  "database_connected": true,
  "cache_connected": true,
  "api_configs": 3
}
```

### Trading Endpoints

#### Place Order
```http
POST /api/v1/orders
```

**Request Body:**
```json
{
  "symbol": "XAUUSD",
  "side": "buy",
  "type": "market",
  "quantity": 0.1,
  "stop_loss": 1900.00,
  "take_profit": 1950.00
}
```

**Response:**
```json
{
  "order_id": "ord_123abc",
  "status": "filled",
  "symbol": "XAUUSD",
  "side": "buy",
  "type": "market",
  "quantity": 0.1,
  "fill_price": 1925.50,
  "timestamp": "2026-02-15T10:30:00Z"
}
```

#### Get Open Positions
```http
GET /api/v1/positions
```

**Response:**
```json
{
  "positions": [
    {
      "position_id": "pos_456def",
      "symbol": "XAUUSD",
      "side": "long",
      "quantity": 0.1,
      "entry_price": 1925.50,
      "current_price": 1930.00,
      "unrealized_pnl": 45.00,
      "stop_loss": 1900.00,
      "take_profit": 1950.00
    }
  ]
}
```

#### Close Position
```http
DELETE /api/v1/positions/{position_id}
```

**Response:**
```json
{
  "position_id": "pos_456def",
  "status": "closed",
  "exit_price": 1930.00,
  "realized_pnl": 45.00,
  "closed_at": "2026-02-15T11:00:00Z"
}
```

### Market Data Endpoints

#### Get Current Price
```http
GET /api/v1/market/{symbol}/price
```

**Response:**
```json
{
  "symbol": "XAUUSD",
  "bid": 1929.50,
  "ask": 1930.00,
  "spread": 0.50,
  "timestamp": "2026-02-15T10:30:00Z"
}
```

#### Get OHLCV Data
```http
GET /api/v1/market/{symbol}/ohlcv?timeframe=1H&limit=100
```

**Parameters:**
- `timeframe`: 1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W
- `limit`: Number of candles (max 1000)
- `start`: Start timestamp (ISO 8601)
- `end`: End timestamp (ISO 8601)

**Response:**
```json
{
  "symbol": "XAUUSD",
  "timeframe": "1H",
  "data": [
    {
      "timestamp": "2026-02-15T10:00:00Z",
      "open": 1925.00,
      "high": 1932.50,
      "low": 1923.00,
      "close": 1930.00,
      "volume": 12500
    }
  ]
}
```

### Strategy Endpoints

#### List Strategies
```http
GET /api/v1/strategies
```

**Response:**
```json
{
  "strategies": [
    {
      "id": "smc_ict",
      "name": "SMC/ICT Strategy",
      "description": "Smart Money Concepts trading strategy",
      "status": "active",
      "performance": {
        "win_rate": 0.65,
        "profit_factor": 1.8,
        "total_trades": 150
      }
    }
  ]
}
```

#### Start Strategy
```http
POST /api/v1/strategies/{strategy_id}/start
```

**Request Body:**
```json
{
  "symbol": "XAUUSD",
  "timeframe": "1H",
  "risk_per_trade": 0.02,
  "max_positions": 3
}
```

#### Stop Strategy
```http
POST /api/v1/strategies/{strategy_id}/stop
```

### Portfolio Endpoints

#### Get Portfolio Summary
```http
GET /api/v1/portfolio
```

**Response:**
```json
{
  "balance": 10000.00,
  "equity": 10500.00,
  "margin_used": 500.00,
  "free_margin": 10000.00,
  "margin_level": 2100.00,
  "unrealized_pnl": 500.00,
  "realized_pnl_today": 250.00
}
```

#### Get Trade History
```http
GET /api/v1/portfolio/history?start=2026-01-01&end=2026-02-15
```

### Backtesting Endpoints

#### Run Backtest
```http
POST /api/v1/backtest
```

**Request Body:**
```json
{
  "strategy_id": "smc_ict",
  "symbol": "XAUUSD",
  "timeframe": "1H",
  "start_date": "2025-01-01",
  "end_date": "2026-01-01",
  "initial_capital": 10000,
  "parameters": {
    "risk_per_trade": 0.02
  }
}
```

**Response:**
```json
{
  "backtest_id": "bt_789xyz",
  "status": "completed",
  "results": {
    "total_trades": 245,
    "winning_trades": 160,
    "losing_trades": 85,
    "win_rate": 0.653,
    "profit_factor": 1.82,
    "sharpe_ratio": 1.45,
    "max_drawdown": 0.12,
    "total_return": 0.35,
    "final_equity": 13500.00
  }
}
```

---

## WebSocket Streaming

### Connection

```javascript
const ws = new WebSocket('ws://localhost:5000/ws');

ws.onopen = () => {
  // Subscribe to price updates
  ws.send(JSON.stringify({
    action: 'subscribe',
    channel: 'prices',
    symbols: ['XAUUSD', 'EURUSD']
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Price update:', data);
};
```

### Channels

| Channel | Description |
|---------|-------------|
| `prices` | Real-time price updates |
| `trades` | Trade execution notifications |
| `signals` | Strategy signals |
| `alerts` | Custom alerts |
| `portfolio` | Portfolio updates |

### Message Format

```json
{
  "channel": "prices",
  "symbol": "XAUUSD",
  "data": {
    "bid": 1929.50,
    "ask": 1930.00,
    "timestamp": "2026-02-15T10:30:00.123Z"
  }
}
```

---

## Rate Limits

| Endpoint Type | Limit |
|---------------|-------|
| Public endpoints | 100 requests/minute |
| Authenticated endpoints | 300 requests/minute |
| Trading endpoints | 60 requests/minute |
| WebSocket connections | 5 concurrent |

### Rate Limit Headers

```http
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 295
X-RateLimit-Reset: 1708000000
```

---

## Error Handling

### Error Response Format

```json
{
  "error": {
    "code": "INVALID_ORDER",
    "message": "Insufficient margin for order",
    "details": {
      "required_margin": 1000.00,
      "available_margin": 500.00
    }
  }
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `UNAUTHORIZED` | 401 | Invalid or missing API key |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `NOT_FOUND` | 404 | Resource not found |
| `INVALID_REQUEST` | 400 | Malformed request |
| `INVALID_ORDER` | 400 | Order validation failed |
| `INSUFFICIENT_MARGIN` | 400 | Not enough margin |
| `MARKET_CLOSED` | 400 | Market is closed |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Server error |

---

## Code Examples

### Python

```python
import requests

BASE_URL = "http://localhost:5000"
API_KEY = "your_api_key"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Get portfolio
response = requests.get(f"{BASE_URL}/api/v1/portfolio", headers=headers)
portfolio = response.json()
print(f"Balance: ${portfolio['balance']}")

# Place order
order = {
    "symbol": "XAUUSD",
    "side": "buy",
    "type": "market",
    "quantity": 0.1
}
response = requests.post(f"{BASE_URL}/api/v1/orders", json=order, headers=headers)
print(f"Order placed: {response.json()}")
```

### JavaScript/Node.js

```javascript
const axios = require('axios');

const BASE_URL = 'http://localhost:5000';
const API_KEY = 'your_api_key';

const client = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Authorization': `Bearer ${API_KEY}`,
    'Content-Type': 'application/json'
  }
});

// Get portfolio
async function getPortfolio() {
  const response = await client.get('/api/v1/portfolio');
  console.log('Balance:', response.data.balance);
}

// Place order
async function placeOrder() {
  const order = {
    symbol: 'XAUUSD',
    side: 'buy',
    type: 'market',
    quantity: 0.1
  };
  const response = await client.post('/api/v1/orders', order);
  console.log('Order placed:', response.data);
}
```

### cURL

```bash
# Health check
curl http://localhost:5000/health

# Get portfolio
curl -X GET "http://localhost:5000/api/v1/portfolio" \
  -H "Authorization: Bearer YOUR_API_KEY"

# Place order
curl -X POST "http://localhost:5000/api/v1/orders" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","side":"buy","type":"market","quantity":0.1}'
```

---

## SDKs and Libraries

### Official SDKs

| Language | Package | Installation |
|----------|---------|--------------|
| Python | `hopefx-sdk` | `pip install hopefx-sdk` |
| JavaScript | `@hopefx/sdk` | `npm install @hopefx/sdk` |
| Go | `go-hopefx` | `go get github.com/hopefx/go-hopefx` |

### Community Libraries

- **Ruby:** `hopefx-ruby`
- **PHP:** `hopefx/php-sdk`
- **C#:** `HopeFX.SDK`

---

## Best Practices

### 1. Error Handling
Always handle errors gracefully:

```python
try:
    response = client.place_order(order)
except InsufficientMarginError as e:
    logger.error(f"Insufficient margin: {e}")
except RateLimitError as e:
    time.sleep(e.retry_after)
    response = client.place_order(order)
```

### 2. Rate Limiting
Implement exponential backoff:

```python
import time

def make_request_with_retry(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except RateLimitError:
            wait_time = 2 ** attempt
            time.sleep(wait_time)
    raise Exception("Max retries exceeded")
```

### 3. WebSocket Reconnection
Handle disconnections:

```javascript
function connect() {
  const ws = new WebSocket('ws://localhost:5000/ws');
  
  ws.onclose = () => {
    console.log('Disconnected. Reconnecting in 5s...');
    setTimeout(connect, 5000);
  };
  
  return ws;
}
```

### 4. Secure API Keys
Never expose API keys in client-side code:

```python
import os

API_KEY = os.environ.get('HOPEFX_API_KEY')
if not API_KEY:
    raise ValueError("HOPEFX_API_KEY environment variable not set")
```

---

## Support

- **Documentation:** https://docs.hopefx.com
- **API Status:** https://status.hopefx.com
- **Discord:** https://discord.gg/hopefx
- **Email:** api-support@hopefx.com

---

*This API guide is part of the HOPEFX AI Trading Framework documentation.*
