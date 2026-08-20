# CI Pipeline Reference (HOPEFX)

What runs on a pull request, so you can map a red check to a local reproduction.

## Workflows

| Workflow | File | What it gates |
|----------|------|---------------|
| CI | `.github/workflows/ci.yml` | pre-commit, dependency scan, mypy, unit/integration tests, Alembic smoke |
| Tests | `.github/workflows/tests.yml` | pytest matrix, coverage, auth coverage, env consistency, docker-compose structure |
| CodeQL | `.github/workflows/codeql.yml` | static security analysis |
| Security scan | `.github/workflows/security-scan.yml` | bandit / secret scanning |
| Docker smoke | `.github/workflows/docker-smoke.yml`, `docker-compose-smoke-test.yml` | image builds and boots |
| Lockfile | `.github/workflows/lockfile.yml` | dependency lockfile integrity |
| Docs | `.github/workflows/docs.yml`, `update_docs.yml` | generated docs stay in sync |

## Python versions

CI tests **3.11 and 3.12**. Production and the `Dockerfile` run **3.12**; the
retrain workflows also run 3.12 so model artifacts are pickled on the same
interpreter that loads them in production. A failure on only one matrix leg is
usually a real version-specific bug, not a flake.

## Reproducing a red check locally

| Failing job | Local command |
|-------------|---------------|
| `pre-commit` | `pre-commit run --all-files` |
| `typecheck` | `mypy api/` / `mypy risk/` / `mypy ml/` — the workflow runs these per-package, and `risk/analytics.py` + `risk/advanced_analytics.py` under `--strict` |
| `test` | `pytest -m "not slow and not e2e"` |
| Coverage gate | `pytest --cov=. --cov-report=term-missing` |
| `env-consistency` | `pytest tests/system/test_env_consistency.py` |
| Frontend | `cd frontend && npm ci && npm run typecheck && npm run build && npm test` |
| Dependency scan | `pip-audit -r requirements-ci.txt` |

`e2e` and `slow` markers are always skipped in CI — a test that only fails under
those markers is not what turned the check red.

## Environment-dependent tests

Tests that need a live broker, Redis, or network must be marked
(`requires_redis`, `integration`, `e2e`) or skipped on a missing env var:

```python
@pytest.mark.skipif(not os.getenv("OANDA_API_KEY"), reason="needs live broker credentials")
def test_live_order_path(): ...
```

Never unmark, skip, or delete a test to make CI green.

## Hard rules for this repository

- This is a money-moving system. **Never weaken a risk gate, kill switch, or
  staleness/drift check** to satisfy a failing test — fix the test or the code.
- Do not commit with `--no-verify`. The hooks (ruff, bandit, detect-secrets,
  check-merge-conflict) are the gate that keeps lint regressions and conflict
  markers out.
- `test-results.xml` is a CI artifact — never commit it.
- Model artifacts under `ml/saved_models/` and `ml/rl_models/`, and
  `dashboard/dist/`, are intentionally committed. A diff touching them is not
  automatically wrong.
