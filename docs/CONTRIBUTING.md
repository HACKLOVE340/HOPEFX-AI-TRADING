# Contributing

## Contributor License Agreement

Before your first pull request is merged, you must agree to the [CLA](./CLA.md). The CLA enables the dual-license model (AGPL-3.0 open source + commercial). To sign, include this statement in your first PR description:

> "I have read and agree to the HOPEFX-AI-TRADING Contributor License Agreement."

---

## Development setup

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -e ".[dev]"
pre-commit install
```

---

## Workflow

1. Fork the repository and create a feature branch:
   ```bash
   git checkout -b feat/your-feature-name
   ```

2. Make changes. Add tests for new behaviour.

3. Run the full check suite before pushing:
   ```bash
   # Lint + format (ruff handles both — no black, no flake8)
   ruff check . --fix
   ruff format .

   # Tests (fast suite)
   pytest tests/ -m "not slow" -q

   # Security scan
   bandit -r . -ll
   ```

4. Commit with a conventional message (see below) and push.

5. Open a pull request. Describe what changed and why.

---

## Code style

All formatting and linting is handled by **ruff** (configured in `pyproject.toml`).
Do not use black or flake8 — they are not in the toolchain.

Key conventions:
- Line length: 100 characters
- Double quotes for strings
- Type hints required on all public function signatures
- Google-style docstrings

Pre-commit hooks run `ruff check`, `ruff format --check`, and `bandit` automatically.

---

## Testing

```bash
# Fast suite (skips slow ML training tests)
pytest tests/ -m "not slow" -q

# Full suite including ML training (~10 min)
pytest tests/ -q

# With coverage
pytest tests/ -m "not slow" --cov=. --cov-report=term-missing

# Single module
pytest tests/test_risk_calculations.py -v
```

Tests live in `tests/`. Name files `test_*.py`, name functions `test_*`. Mock all
external services (broker APIs, Redis, PostgreSQL) — tests must run offline.

---

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): subject

Optional body explaining motivation.

Closes #123
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`

Examples:
```
feat(ml): add regime-conditional feature weighting
fix(risk): correct CVaR calculation for multi-day horizon
docs(readme): update multi-symbol backtest results to N=919
test(broker): add OANDA paper fill integration tests
```

---

## Project structure

```
api/          REST endpoints (FastAPI routers)
backtest/     Backtesting engine and multi-symbol runner
brokers/      Broker connectors (OANDA, IBKR, paper, FIX)
core/         Startup factories, component registry, app state
execution/    OMS, TradeExecutor, OrderGateway, position tracker
ml/           Model training, online learner, feature engineering
risk/         RiskManager, CVaR gate, pre-trade gate, kill switch
strategies/   Strategy implementations
tests/        pytest test suite
docs/         MkDocs documentation source
```

---

## Reporting issues

Search existing issues before opening a new one. Include:
- Python version (`python --version`)
- OS
- Full error traceback
- Steps to reproduce

---

## Security vulnerabilities

Do **not** open public issues for security vulnerabilities. Email `security@hopefx.io`
with details. See [SECURITY.md](SECURITY.md) for the full disclosure policy.

---

## License

Contributions are licensed under AGPL-3.0 and may be included in commercial releases
per the [CLA](./CLA.md) and [LICENSE-COMMERCIAL.md](./LICENSE-COMMERCIAL.md).

---

## Paid Platform Context

HOPEFX is a **paid subscription platform**. The source code is open under AGPL-3.0,
but the hosted service requires a subscription. When contributing:

- Do not add features that bypass subscription checks
- Do not remove or weaken the `require_plan` middleware
- Do not add free-tier access to Pro/Elite features
- Do not commit real API keys, license keys, or subscriber data

If you are building on top of HOPEFX commercially (SaaS, white-label, proprietary),
you need a Commercial License — see [LICENSE-COMMERCIAL.md](../LICENSE-COMMERCIAL.md).

---

## Contributor License Agreement

Before your first pull request is merged, include this statement in the PR description:

> "I have read and agree to the HOPEFX-AI-TRADING Contributor License Agreement."

The CLA enables the dual-license model (AGPL-3.0 open source + commercial).
Without the CLA, your PR cannot be merged.

---

## What We Accept

- Bug fixes with regression tests
- New broker connectors (add to `brokers/`)
- New trading strategies (add to `strategies/`)
- ML feature engineering improvements (add to `ml/`)
- Documentation improvements
- Performance improvements with benchmarks

## What Requires Discussion First

Open a GitHub Issue before working on:
- Changes to the risk engine or kill switch
- Changes to the subscription/billing system
- Changes to the ML training pipeline
- New external dependencies
- Breaking API changes
- New pricing tiers or feature gates
