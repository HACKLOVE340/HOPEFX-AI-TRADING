# Contributing to HOPEFX AI Trading

---

## Branching

| Prefix | Use |
|--------|-----|
| `feature/` | New functionality |
| `fix/` | Bug fixes |
| `chore/` | Tooling, deps, CI, docs |
| `ml/` | Model training, feature engineering |
| `security/` | Security fixes (prefer private disclosure first) |

Branch off `main`. Keep branches short-lived. One concern per branch.

```bash
git checkout -b feature/my-feature
```

---

## Commit Messages

Follow the imperative mood convention. Subject line ≤ 72 characters.

```
Add GARCH(1,1) multi-step variance recursion to risk/analytics.py

Extend the existing single-step GARCH estimator to support h-step
ahead variance forecasts. Required for multi-day VaR scaling.
```

- **Subject:** imperative mood, no trailing period (`Add`, `Fix`, `Remove`, not `Added`)
- **Body:** optional; explain *why*, not *what*. Skip if the subject is self-explanatory.
- **Scope:** one logical change per commit. Avoid mixing refactors with feature work.

---

## Pull Requests

Use the PR template (`.github/PULL_REQUEST_TEMPLATE.md`). Fill in all sections.

Before opening a PR, run the full local check:

```bash
# Lint
ruff check .

# Type check (strict modules: risk/analytics, api/, ml/inference_engine)
mypy risk/analytics.py api/ ml/inference_engine.py

# Tests (mirrors CI — skips e2e and slow)
pytest -m "not e2e and not slow"

# Security pre-commit hooks
pre-commit run --all-files
```

PRs targeting `main` require:
- All CI checks green
- No new `detect-secrets` findings
- Tests added or updated for changed behaviour

---

## Code Style

See `AGENTS.md` — Coding Conventions for the full rules. Short version:

- **Python:** `black` formatter, `ruff` linter, `mypy` type checker
- **Line length:** 100 (black) / 120 (ruff)
- **Python version target:** 3.10 (matches production Docker image)
- **New modules:** include `from __future__ import annotations` at the top
- **API handlers:** `async def` only
- **TypeScript:** Prettier, PascalCase components, `use` prefix for hooks

---

## Adding New Code

Before writing anything, read `ARCHITECTURE.md` to confirm you are using the
canonical directory for your domain. The wrong directory will be rejected in
review:

| Domain | Write here | Not here |
|--------|-----------|----------|
| Backtesting | `backtesting/` | `backtest/` |
| Strategies | `strategies/` | `strategy/` |
| Data pipeline | `data_layer/` | `data/` |
| WebSocket (FastAPI) | `api/ws_live.py` | `websocket/manager.py` |

---

## Tests

All new behaviour needs a test. Place tests in the appropriate subdirectory:

| Test type | Location | Marker |
|-----------|----------|--------|
| Unit (no I/O) | `tests/unit/` | `@pytest.mark.unit` |
| Integration (Redis/DB) | `tests/integration/` | `@pytest.mark.integration` |
| End-to-end (live broker) | `tests/e2e/` | `@pytest.mark.e2e` |
| Slow (real ML training) | anywhere | `@pytest.mark.slow` |

`e2e` and `slow` tests are always skipped in CI. Do not remove those markers.

---

## Security

- Never commit `.env`, `WORDMAP.json`, or `prop_firm_mode.json`. They are
  gitignored and the `detect-secrets` pre-commit hook will block the commit.
- Do not bypass the LLM agent subprocess sandbox in `brain/llm_agent.py`.
- For security vulnerabilities, open a private GitHub Security Advisory rather
  than a public issue.

---

## Licensing

This project is AGPL-3.0. All contributions must be compatible with that
license. Commercial use requires a separate license — see `LICENSE-COMMERCIAL.md`.

By submitting a PR you confirm that your contribution is your own work and that
you agree to the Contributor License Agreement in `CLA.md`.
