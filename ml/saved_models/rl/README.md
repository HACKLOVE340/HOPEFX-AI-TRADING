# ml/saved_models/rl/

Saved weights for the live forex RL agent (`ml/rl_agent.py`).

## Expected files after training

| File | Description |
|------|-------------|
| `hopefx_ppo.zip` | Stable-Baselines3 PPO model — trained on `ForexTradingEnv` (XAU_USD H1) |
| `tb_logs/` | TensorBoard training logs |

## How to train

```bash
from ml.rl_agent import RLAgentTrainer
from brokers.oanda_stream import OANDAStream

broker = OANDAStream(api_key=..., account_id=..., instruments=["XAU_USD"])
await broker.__aenter__()
await broker.connect()

trainer = RLAgentTrainer(candle_source=broker)
metrics = await trainer.train(symbol="XAU_USD", timeframe="H1", timesteps=100_000)
# Model saved to ml/saved_models/rl/hopefx_ppo.zip
```

## How to enable in production

Once `hopefx_ppo.zip` exists, the agent loads automatically in `ml/rl_agent.py`
via `RLAgent.load()`. No additional configuration required.

## Note

This directory is intentionally empty until the first training run completes.
The `ml/rl_models/` directory holds the **nuclear supervisor** PPO agent
(`nuclear_decision_ppo.zip`) — a separate model for geopolitical risk response.
This directory is for the **live trading** PPO agent.
