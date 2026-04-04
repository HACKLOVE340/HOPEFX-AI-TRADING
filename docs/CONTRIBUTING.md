# Contributing

> HOPEFX AI Trading is a paid subscription platform licensed under AGPL-3.0.
> Read this document fully before opening a pull request.
> Last updated: 2026-07-14

---

## Contents

1. [Paid Platform Context](#paid-platform-context)
2. [Contributor License Agreement](#contributor-license-agreement)
3. [Commercial License Note](#commercial-license-note)
4. [Development Setup](#development-setup)
5. [Workflow](#workflow)
6. [Code Style](#code-style)
7. [Testing](#testing)
8. [Commit Messages](#commit-messages)
9. [Project Structure](#project-structure)
10. [What We Accept](#what-we-accept)
11. [Reporting Issues](#reporting-issues)
12. [Security Vulnerabilities](#security-vulnerabilities)

---

## Paid Platform Context

HOPEFX is a **commercial paid subscription platform**. The source code is open under
AGPL-3.0, but the hosted service requires a subscription ($1,800–$10,000/month).

When contributing, you must understand and respect this model:

- **Do not** add features that bypass subscription checks
- **Do not** remove or weaken the `require_plan` middleware in `monetization/subscription.py`
- **Do not** add free-tier access to Professional/Enterprise/Elite features
- **Do not** commit real API keys, license keys, broker tokens, or subscriber data
- **Do not** add backdoors, debug overrides, or hardcoded credentials
- **Do not** change pricing, tier names, or commission rates without a maintainer discussion

Contributions that violate these rules will be closed without review.

If you are building on top of HOPEFX commercially (SaaS, white-label, proprietary product),
you need a Commercial License — see [LICENSE-COMMERCIAL.md](../LICENSE-COMMERCIAL.md).

---

## Contributor License Agreement

Before your first pull request is merged, you must agree to the
[Contributor License Agreement](../CLA.md).

The CLA enables the dual-license model: AGPL-3.0 open source + commercial.
Without the CLA, your PR cannot be merged regardless of code quality.

**To sign:** Include this exact statement in your first PR description:

> "I have read and agree to the HOPEFX-AI-TRADING Contributor License Agreement."

The CLA grants HOPEFX the right to include your contribution in commercial releases
while you retain copyright over your contribution.

---

## Commercial License Note

The AGPL-3.0 license requires that any software that uses HOPEFX as a network service
must also be released under AGPL-3.0. If you want to:

- Build a proprietary SaaS product on top of HOPEFX
- White-label HOPEFX without disclosing your source code
- Sell HOPEFX as part of a closed-source product
- Deploy HOPEFX for clients without releasing your modifications

You need a **Commercial License**. See [LICENSE-COMMERCIAL.md](../LICENSE-COMMERCIAL.md).
The Elite subscription plan includes the Commercial License.

Contact sales@hopefx.io for commercial licensing enquiries.

---

## Development Setup

```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -e ".[dev]"
pre-commit install
```

Verify the setup:
```bash
pre-commit run --all-files
pytest tests/ -m "not slow" -q
```

Both must pass before you start making changes.

---

## Workflow

1. **Fork** the repository and create a feature branch:
   ```bash
   git checkout -b feat/your-feature-name
   ```
   Branch naming: `feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`

2. **Make changes.** Add tests for all new behaviour. Update documentation if the
   change affects user-facing behaviour.

3. **Run the full check suite** before pushing:
   ```bash
   # Lint + format
   ruff check . --fix
   ruff format .

   # Fast test suite
   pytest tests/ -m "not slow" -q

   # Security scan
   bandit -r api/ auth/ brokers/ ml/ risk/ core/ -ll -q

   # Dependency scan
   pip-audit --requirement requirements.txt
   ```

4. **Commit** with a conventional message (see [Commit Messages](#commit-messages)).

5. **Open a pull request.** The PR description must:
   - Explain what changed and why
   - Reference any related issues (`Closes #123`)
   - Include the CLA statement if this is your first PR
   - Include test results if adding a new feature

6. **CI must pass.** All three CI jobs (`pre-commit`, `dependency-scan`, `test`) must
   be green before a maintainer will review.

---

## Code Style

All formatting and linting is handled by **ruff** (configured in `pyproject.toml`).
Do not use black or flake8 — they are not in the toolchain.

Key conventions:
- Line length: 100 characters
- Double quotes for strings
- Type hints required on all public function signatures
- Google-style docstrings on all public classes and functions
- No `print()` statements — use `logging.getLogger(__name__)`

Pre-commit hooks run `ruff check`, `ruff format --check`, and `bandit` automatically
on every commit. Fix any issues before pushing.

---

## Testing

```bash
# Fast suite (skips slow ML training tests — runs in ~2 min)
pytest tests/ -m "not slow" -q

# Full suite including ML training (~10 min)
pytest tests/ -q

# With coverage report
pytest tests/ -m "not slow" --cov=. --cov-report=term-missing -q

# Single module
pytest tests/test_risk_calculations.py -v

# Single test
pytest tests/test_risk_calculations.py::test_cvar_gate_blocks_order -v
```

### Test Requirements

- All new features must have unit tests
- All bug fixes must have a regression test that fails before the fix and passes after
- Tests must run offline — mock all external services (broker APIs, Redis, PostgreSQL)
- Tests must not use real API keys, real broker accounts, or real money
- Test files: `tests/test_*.py`. Test functions: `test_*`

### Test Markers

```python
@pytest.mark.slow          # Skipped in fast suite (ML training, long backtests)
@pytest.mark.integration   # Requires running services (Redis, PostgreSQL)
@pytest.mark.broker        # Requires broker credentials (never run in CI)
```

### Coverage Target

Line coverage target: **70%** (enforced in CI with `--cov-fail-under=70`).
New code should aim for 90%+ coverage.

---

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): subject line (max 72 chars)

Optional body explaining motivation. Wrap at 100 chars.
Focus on WHY, not WHAT (the diff shows what changed).

Closes #123
Co-authored-by: Your Name <email@example.com>
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`, `security`

**Scopes:** `ml`, `risk`, `broker`, `api`, `auth`, `backtest`, `execution`, `monetization`,
`mobile`, `docs`, `ci`, `deps`

**Examples:**
```
feat(ml): add regime-conditional feature weighting

Weights features by detected market regime (ranging/trending/volatile).
Improves OOS accuracy by 1.2% on XAUUSD H1 (N=1260, p=0.003).

Closes #247

fix(risk): correct CVaR calculation for multi-day horizon

The previous implementation used a 1-day horizon for all positions.
Multi-day positions now use sqrt(T) scaling per Basel III methodology.

docs(setup): add subscription validation step to SETUP_GUIDE.md

test(broker): add OANDA paper fill integration tests

Mocks the OANDA v20 REST API to test order placement, fill handling,
and position reconciliation without a real broker account.
```

---

## Project Structure

```
app.py                  FastAPI application entry point, lifespan, router registration
kill_switch.py          Hardware kill switch — system-wide halt, persists to disk
validation.py           Order and input validation

── Core ──────────────────────────────────────────────────────────────────────
api/                    FastAPI routers (50+ files, registered via core/router_registry.py)
auth/                   JWT authentication, bcrypt, 2FA (TOTP)
core/                   ComponentRegistry, startup factories, signal engine, event bus
config/                 Pydantic settings, feature flags (57 flags), vault, startup validator

── Trading Engine ────────────────────────────────────────────────────────────
brain/                  HOPEFXBrain — regime detection, strategy orchestration
strategies/             BaseStrategy + 10 built-ins + StrategyBrain (ML consensus)
execution/              OMS, TradeExecutor, OrderGateway, SmartRouter, FIX adapter
risk/                   RiskManager, CVaR gate, pre-trade gate, kill switch, VaR/EWMA
brokers/                BrokerConnector (ABC) + OANDA, IBKR, Alpaca, Binance, MT5, paper

── Data Layer ────────────────────────────────────────────────────────────────
data_layer/             MarketDataOrchestrator — single source of truth for all price data
data/                   Historical data, OHLCV scheduler, macro CSVs
market_data/            Nuclear streamer, IBKR/MT5 live feeds, order book
data_feed/              Feed handler, Redis cache, validation

── ML Pipeline ───────────────────────────────────────────────────────────────
ml/                     Model training, live inference, online learner, macro features
                        advanced_oos.pkl — 176-feature XGBoost ensemble (66.4% OOS)
backtest/               Walk-forward engine, multi-symbol backtest, transaction costs
backtesting/            Full backtesting framework (engine, metrics, walk-forward, plots)
research/               LSTM/Transformer/TCN, RL agent, drift detection (feature-flagged)

── Platform Services ─────────────────────────────────────────────────────────
monetization/           Subscription tiers, require_plan, plan_gate, Stripe, license keys
payments/               Stripe, Flutterwave, crypto, wallet
social/                 Copy trading, leaderboards, profiles
notifications/          Telegram, Discord, email alerts
monitoring/             Prometheus metrics, health checks, Sentry config
compliance/             AML, KYC, regulatory reporting, FIA compliance
security/               Encryption, vault, rate limiting, audit logging, LLM security wrapper
whitelabel/             White-label branding, API auth, rate limiting config

── Infrastructure ────────────────────────────────────────────────────────────
database/               SQLAlchemy models, Alembic migrations
cache/                  Redis cache layer, in-memory fallback
dashboard/              React + Vite web dashboard (dashboard/src/)
frontend/               TypeScript frontend (npm ci && npm run test)
mobile/                 PWA, push notifications, React Native API client
mobile-app/             Expo React Native app scaffold
k8s/                    Kubernetes manifests (deployment, service, ingress, RBAC)
helm/                   Helm chart (helm/hopefx/)
grafana/                4 dashboards, 27 panels, provisioning config
nginx/                  Reverse proxy config
redis/                  Redis master/replica/sentinel config
k6/                     Load tests (6 scenarios)
locust/                 Load tests (3 user classes)
scripts/                Operational scripts (retrain, validate, manage secrets, backfill)
tests/                  pytest test suite (2,560+ tests)
docs/                   MkDocs documentation source
```

---

## What We Accept

**Without prior discussion:**
- Bug fixes with regression tests
- New broker connectors (add to `brokers/`, implement `BrokerConnector` ABC from `brokers/base.py`)
- New trading strategies (add to `strategies/`, implement `BaseStrategy` ABC from `strategies/base.py`)
- ML feature engineering improvements (add to `ml/advanced_features.py` or `ml/features_extended.py`)
- Documentation improvements and corrections
- Performance improvements with benchmarks
- Test coverage improvements
- Dependency updates (open a separate PR per dependency)

**Requires a GitHub Issue discussion first:**
- Changes to the risk engine or kill switch
- Changes to the subscription/billing system or `require_plan` middleware
- Changes to the ML training pipeline or model architecture
- New external dependencies (justify why existing deps cannot be used)
- Breaking API changes (must include migration guide)
- New pricing tiers or feature gates
- Changes to the database schema (must include Alembic migration)
- Changes to authentication or security middleware

**Not accepted:**
- Features that bypass subscription checks
- Removal of the `require_plan` decorator from any endpoint
- Hardcoded credentials or API keys
- Code that sends user data to third-party services without disclosure
- Changes that weaken security (rate limiting, JWT validation, CORS)
- Proprietary dependencies that conflict with AGPL-3.0

---

## Reporting Issues

Search existing issues before opening a new one.

Include in your issue:
- Python version (`python --version`)
- Operating system and version
- Full error traceback (use a code block)
- Steps to reproduce (minimal reproduction case preferred)
- What you expected vs what happened

For feature requests, explain the use case and why existing functionality does not cover it.

---

## Security Vulnerabilities

**Do not open public issues for security vulnerabilities.**

Report security issues via GitHub's private vulnerability reporting:
Repository → Security → Report a vulnerability

Or email security@hopefx.io with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

We aim to acknowledge security reports within 48 hours and provide a fix within 14 days
for critical issues. See [SECURITY.md](SECURITY.md) for the full disclosure policy.

---

*Last updated: 2026-07-14*
