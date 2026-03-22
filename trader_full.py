# Vortex Prime Trading System

## Layer 1: LiveDataPipeline
- **MT5 WebSocket**: Reconnection, tick validation.
- **Redis cache**: Latency tracking.

## Layer 2: OrderGateway
- **Market/Limit Orders**: Fills, rejects, cancellations.
- **Slippage tracking**: Monitor orders for slippage.
- **Commission management**: Keep track of trading fees.

## Layer 3: EnsembleStrategy
- **Indicators**: EMA9, EMA21, RSI14, MACD, Bollinger Bands.
- **Modeling**: RandomForest voting approach for trade decision-making.

## Layer 4: MLPredictor
- **Feature engineering**: Utilizing `pandas_ta` for technical analysis.
- **RandomForest**: Model for predicting price movements.
- **Lazy-loading**: Optimize resource usage.

## Layer 5: RiskManager
- **Position sizing**: Adhere to 1-2% risk per trade.
- **ATR stops**: Adaptive trading stops based on volatility.
- **Trailing stops**: Lock in profits while letting the trade run.
- **Max drawdown pause**: Stop trading after specified loss.
- **Low-capital mode**: Adjust risk parameters accordingly.

## Layer 6: StateManager
- **Persistence**: Use Redis and SQLAlchemy for trade data.
- **Snapshots**: Capture equity state over time.
- **Crash recovery**: Handle application failures gracefully.

## Layer 7: AlertManager
- **Notifications**: Telegram integration and FastAPI dashboard alarms.

## Layer 8: NewsFilter
- **Events**: Pause trading during high-impact news events from Forex Factory.

## Layer 9: ForwardTestHarness
- **Async loop**: Run 24/7 to simulate market conditions with real ticks.
- **Signal generation**: Generate signals for paper trading.
- **Detection**: Identify overfitting in strategies.

## Layer 10: Security
- **Fernet encryption**: Secure sensitive information.
- **Rate limiting**: Prevent abuse of API usage.
- **Input sanitization**: Ensure safe data handling with no pickle.

## Additional Features
- **APP_ENV toggle**: Switch between live demo and backtest modes.
- **.env credential injection**: Load credentials securely from environment.
- **MT5 broker rules**: Functionality for nano lots and trading rates.
- **Slippage simulation**: Incorporate a range of 0.5-2 pips.
- **Docker-compose ready**: Simplified deployment process.
- **Error handling**: Extensive use of try/except for reliability.
- **Documentation**: Comprehensive docstrings to assist users.