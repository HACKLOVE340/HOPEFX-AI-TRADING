# Universal Broker & Prop Firm Connectivity Guide

## Overview

The HOPEFX AI Trading Framework now supports **UNIVERSAL BROKER CONNECTIVITY**, allowing you to connect to:

- **ANY MT5-compatible broker** (retail brokers, prop firms, institutional)
- **Multiple asset classes** (Forex, Stocks, Crypto, Futures, Options)
- **All major prop firms** (FTMO, TopstepTrader, The5ers, MyForexFunds, etc.)
- **Traditional brokers** (Interactive Brokers, OANDA, Alpaca, Binance)

## Supported Brokers

### 1. MetaTrader 5 (MT5) - Universal Connector ⭐

**Works with ANY MT5 broker worldwide!**

Supported brokers include (but not limited to):
- IC Markets
- Pepperstone
- XM
- FXCM
- Tickmill
- RoboForex
- Admiral Markets
- FBS
- HotForex
- Any other MT5-compatible broker

```python
from brokers import BrokerFactory

# Connect to ANY MT5 broker
config = {
    'server': 'ICMarkets-Demo',  # Your broker's server
    'login': 12345678,            # Your account number
    'password': 'your_password'   # Your password
}

broker = BrokerFactory.create_broker('mt5', config)
broker.connect()
```

### 2. Prop Firms

#### FTMO
```python
config = {
    'login': 12345678,
    'password': 'ftmo_password',
    'challenge_type': 'demo'  # or 'live'
}
broker = BrokerFactory.create_broker('ftmo', config)
```

#### TopstepTrader
```python
config = {
    'login': 12345678,
    'password': 'topstep_password',
    'server': 'TopstepTrader-Server01',
    'account_type': 'combine'  # or 'funded'
}
broker = BrokerFactory.create_broker('topstep', config)
```

#### The5ers
```python
config = {
    'login': 12345678,
    'password': 'the5ers_password',
    'program': 'high_stakes'  # or 'boot_camp', 'instant_funding'
}
broker = BrokerFactory.create_broker('the5ers', config)
```

#### MyForexFunds
```python
config = {
    'login': 12345678,
    'password': 'mff_password',
    'account_size': 100000
}
broker = BrokerFactory.create_broker('myforexfunds', config)
```

### 3. Interactive Brokers (Multi-Asset)

Supports: Stocks, Options, Futures, Forex, Bonds, Crypto

```python
config = {
    'host': '127.0.0.1',
    'port': 7497,  # Paper: 7497, Live: 7496
    'client_id': 1,
    'paper': True
}
broker = BrokerFactory.create_broker('ib', config)
```

### 4. OANDA (Forex)

```python
config = {
    'api_key': 'your-oanda-token',
    'account_id': 'your-account-id',
    'environment': 'practice'  # or 'live'
}
broker = BrokerFactory.create_broker('oanda', config)
```

### 5. Binance (Cryptocurrency)

```python
config = {
    'api_key': 'your-binance-api-key',
    'api_secret': 'your-binance-secret',
    'testnet': True  # or False for live
}
broker = BrokerFactory.create_broker('binance', config)
```

### 6. Alpaca (US Stocks)

```python
config = {
    'api_key': 'your-alpaca-key',
    'api_secret': 'your-alpaca-secret',
    'paper': True  # or False for live
}
broker = BrokerFactory.create_broker('alpaca', config)
```

## How to Connect to ANY Broker

### Step 1: Identify Broker Platform

1. **MT5-based broker?** → Use `mt5` connector
2. **Prop firm?** → Use specific prop firm connector or `mt5`
3. **Interactive Brokers?** → Use `ib` connector
4. **Other brokers?** → Check if already supported

### Step 2: Get Connection Details

For MT5 brokers, you need:
- **Server name** (e.g., "ICMarkets-Demo", "YourBroker-Live")
- **Login** (account number)
- **Password**

### Step 3: Create Configuration

```python
config = {
    'server': 'YOUR_BROKER_SERVER',
    'login': YOUR_ACCOUNT_NUMBER,
    'password': 'YOUR_PASSWORD'
}
```

### Step 4: Connect

```python
from brokers import BrokerFactory

broker = BrokerFactory.create_broker('mt5', config)
if broker.connect():
    print("Connected successfully!")
    account = broker.get_account_info()
    print(f"Balance: ${account.balance}")
```

## Trading Examples

### Place a Market Order

```python
from brokers import OrderSide, OrderType

order = broker.place_order(
    symbol="EURUSD",
    side=OrderSide.BUY,
    quantity=0.01,  # 0.01 lots = 1 micro lot
    order_type=OrderType.MARKET
)
```

### Place a Limit Order with SL/TP

```python
order = broker.place_order(
    symbol="GBPUSD",
    side=OrderSide.BUY,
    quantity=0.1,
    order_type=OrderType.LIMIT,
    price=1.2500,
    stop_loss=1.2450,
    take_profit=1.2600
)
```

### Get Positions

```python
positions = broker.get_positions()
for pos in positions:
    print(f"{pos.symbol}: {pos.side} {pos.quantity} @ {pos.entry_price}")
    print(f"P&L: ${pos.unrealized_pnl:.2f}")
```

### Close Position

```python
broker.close_position("EURUSD")  # Close full position
broker.close_position("GBPUSD", quantity=0.05)  # Partial close
```

## Multi-Broker Trading

Connect to multiple brokers simultaneously:

```python
# Connect to retail broker
mt5_config = {
    'server': 'ICMarkets-Demo',
    'login': 12345,
    'password': 'pass1'
}
mt5_broker = BrokerFactory.create_broker('mt5', mt5_config)
mt5_broker.connect()

# Connect to prop firm
ftmo_config = {
    'login': 67890,
    'password': 'pass2',
    'challenge_type': 'demo'
}
ftmo_broker = BrokerFactory.create_broker('ftmo', ftmo_config)
ftmo_broker.connect()

# Connect to stocks broker
alpaca_config = {
    'api_key': 'key',
    'api_secret': 'secret',
    'paper': True
}
alpaca_broker = BrokerFactory.create_broker('alpaca', alpaca_config)
alpaca_broker.connect()

# Now trade on all simultaneously!
mt5_broker.place_order("EURUSD", OrderSide.BUY, 0.01)
ftmo_broker.place_order("GBPUSD", OrderSide.BUY, 0.01)
alpaca_broker.place_order("AAPL", OrderSide.BUY, 10)
```

## Prop Firm Features

### FTMO Compliance Checking

```python
ftmo = BrokerFactory.create_broker('ftmo', config)
ftmo.connect()

# Get FTMO rules
rules = ftmo.get_ftmo_rules()
print(f"Max daily loss: {rules['max_daily_loss']}")
print(f"Profit target: {rules['profit_target']}")

# Check compliance
compliance = ftmo.check_ftmo_compliance()
if compliance['compliant']:
    print("✓ Trading within FTMO rules")
else:
    print("✗ Violating FTMO rules!")
    print(f"Total loss: {compliance['total_loss_percent']:.2f}%")
```

## Available Broker Types

List all supported brokers:

```python
from brokers import BrokerFactory

brokers = BrokerFactory.list_brokers()
print("Available brokers:")
for broker_type in brokers:
    print(f"  - {broker_type}")
```

Output:
```
Available brokers:
  - paper
  - oanda
  - binance
  - alpaca
  - mt5
  - ib
  - interactive_brokers
  - ftmo
  - topstep
  - topsteptrader
  - the5ers
  - myforexfunds
  - mff
```

## Troubleshooting

### MT5 Connection Issues

1. **MT5 terminal must be installed** on your system
2. **Enable algorithmic trading** in MT5 terminal (Tools → Options → Expert Advisors)
3. **Verify server name** (check in MT5: File → Login to Trade Account)
4. **Check login credentials** are correct

### Interactive Brokers Issues

1. **IB Gateway or TWS must be running**
2. **Enable API connections** in IB Gateway/TWS settings
3. **Check port number** (Paper: 7497, Live: 7496)
4. **Verify client ID** is unique

### Prop Firm Issues

1. **Use correct server** (check prop firm dashboard)
2. **Verify account is active** (not expired)
3. **Check password** (reset if needed)
4. **Ensure MT5 terminal** is installed and working

## Installation

Install required packages:

```bash
# All brokers
pip install -r requirements.txt

# MT5 only (Windows/Linux)
pip install MetaTrader5

# Interactive Brokers only
pip install ib_insync
```

## Security Best Practices

1. **Never hardcode credentials** in your code
2. **Use environment variables**:
   ```python
   import os
   config = {
       'login': int(os.getenv('MT5_LOGIN')),
       'password': os.getenv('MT5_PASSWORD'),
       'server': os.getenv('MT5_SERVER')
   }
   ```

3. **Use separate accounts** for testing (demo/paper)
4. **Start with small positions** when going live
5. **Monitor prop firm rules** to avoid violations

## Summary

✅ **Universal MT5 Connector** - Connect to ANY MT5 broker  
✅ **Prop Firm Support** - FTMO, TopstepTrader, The5ers, MyForexFunds  
✅ **Multi-Asset Trading** - Forex, Stocks, Crypto, Futures  
✅ **Multi-Broker** - Connect to multiple brokers simultaneously  
✅ **Easy Integration** - Simple factory pattern  
✅ **Production Ready** - Full error handling and logging  

The framework now supports **universal broker connectivity** just like MT5, allowing you to trade with ANY broker or prop firm!
