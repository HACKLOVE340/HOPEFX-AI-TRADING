# CI/CD Pipeline

> GitHub Actions CI/CD for HOPEFX AI Trading.
> Last updated: 2026-07-14

---

## Overview

The pipeline runs on every push and pull request to `main` and `develop`.
All workflow files are in `.github/workflows/`.

| Workflow file | Trigger | Jobs |
|---------------|---------|------|
| `ci.yml` | Push/PR to `main`/`develop` | `pre-commit`, `dependency-scan`, `test` (matrix 3.11/3.12), `frontend`, `e2e` |
| `release.yml` | Tag `v*` | `build-and-release` (PyPI), `docker-release` (Docker Hub) |
| `retrain.yml` | Weekly Sunday 02:00 UTC + manual dispatch | `smoke-validate`, `full-retrain` (50Y walk-forward) |
| `security-scan.yml` | Push/PR | Additional security scanning |
| `codeql.yml` | Push/PR | GitHub CodeQL security analysis |
| `codacy.yml` | Push/PR | Codacy static analysis |
| `docs.yml` | Push to `main` | MkDocs build and deploy to GitHub Pages |
| `update_docs.yml` | Merge to `main` | Auto-update docs |
| `tests.yml` | Push/PR | Extended test suite (slow tests, integration) |
| `fortify.yml` | Push/PR | Fortify security scan |
| `summary.yml` | Push/PR | CI summary report |

---

## Workflow Details

### `ci.yml` — Main CI

Runs on every push to `main`/`develop` and every PR targeting `main`.
Uses `concurrency` to cancel in-progress runs on the same branch.

**`pre-commit`** — Runs all pre-commit hooks (ruff check, ruff format, bandit).
All action SHAs are pinned for supply-chain safety.

**`dependency-scan`** — CVE scan + supply-chain scan:
```bash
pip-audit --requirement=requirements.txt --desc || true
trivy fs --severity CRITICAL,HIGH .
```
CVEs are reported but do not block merges — tracked in the security dashboard.

**`test`** — Matrix across Python 3.11 and 3.12 with PostgreSQL 16 + Redis 7 services.

Coverage gates enforced in CI:
| Module | Minimum coverage |
|--------|-----------------|
| Overall (`auth`, `risk`, `brokers`, `execution`, `ml`, `config`, `kill_switch`, `compliance`, `analytics`, `backtesting`) | 70% |
| `risk/` | 90% |
| `execution/` | 90% |
| `kill_switch.py` | 90% |
| `brokers/` | 90% |
| `compliance/` | 90% |

Coverage is uploaded to Qlty on every run (Python 3.11 matrix leg only).

**`frontend`** — TypeScript type check + unit tests in `frontend/` via `npm ci && npm run typecheck && npm run test`.

**`e2e`** — End-to-end tests (see `ci.yml` for full configuration).

### `release.yml` — Release

Triggers on any tag matching `v*` (e.g., `v1.17.0`).

**`build-and-release`** — Builds the Python package and creates a GitHub Release with auto-generated release notes. Publishes to PyPI via OIDC Trusted Publishing when `vars.PUBLISH_TO_PYPI == 'true'` (no long-lived `PYPI_API_TOKEN` secret required).

**`docker-release`** — Builds and pushes the Docker image to Docker Hub. Runs after `build-and-release` succeeds.

### `retrain.yml` — ML Walk-Forward Retrain

Runs weekly (Sunday 02:00 UTC) and on manual dispatch.

| Job | When | What |
|-----|------|------|
| `smoke-validate` | Every trigger | Runs `scripts/retrain_horizon5.py --smoke` — validates pipeline without downloading data (~5 min) |
| `full-retrain` | Schedule or `mode=full` dispatch | Runs `scripts/retrain_model.py --advanced --years 50 --oos-years 8` — full 50-year walk-forward retrain (~2 hours) |

On full retrain success, updated model artefacts (`registry.json`, `advanced_training_report.json`, `feature_stats.json`, `feature_importances.json`) are committed back to the branch automatically.

On failure, a GitHub Issue is created automatically with labels `ml`, `automated`, `retrain-failure`.

---

## Required GitHub Secrets

Set these in: **Repository → Settings → Secrets and variables → Actions**

### CI Secrets (required for tests to pass)

The CI workflow uses these env vars directly — they are not named `CI_*` in the workflow:

| Secret name | Maps to env var | How to generate |
|-------------|----------------|----------------|
| `SECURITY_JWT_SECRET` | `SECURITY_JWT_SECRET` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CONFIG_ENCRYPTION_KEY` | `CONFIG_ENCRYPTION_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CONFIG_SALT` | `CONFIG_SALT` | `python -c "import secrets; print(secrets.token_hex(16))"` |
| `QLTY_COVERAGE_TOKEN` | Coverage upload to Qlty | From [qlty.sh](https://qlty.sh) after linking the repo |

### Release Secrets (required for releases)

| Secret | Description | Where to get it |
|--------|-------------|----------------|
| `DOCKER_USERNAME` | Docker Hub username | Your Docker Hub account |
| `DOCKER_PASSWORD` | Docker Hub access token | Docker Hub → Account Settings → Security → New Access Token |

PyPI publishing uses OIDC Trusted Publishing — no `PYPI_API_TOKEN` secret required. Enable in PyPI project settings: Trusted Publisher → GitHub Actions. Set `vars.PUBLISH_TO_PYPI = true` in repository variables to activate.

### Deployment Secrets (required for Kubernetes deploy)

| Secret | Description | How to generate |
|--------|-------------|----------------|
| `STAGING_KUBECONFIG` | Base64-encoded kubeconfig for staging | `cat ~/.kube/config \| base64 -w 0` |
| `PRODUCTION_KUBECONFIG` | Base64-encoded kubeconfig for production | `cat ~/.kube/config \| base64 -w 0` |

### Optional Secrets

| Secret | Description |
|--------|-------------|
| `SENTRY_DSN` | Sentry error tracking DSN |
| `SLACK_WEBHOOK_URL` | Slack notification webhook |
| `CODACY_PROJECT_TOKEN` | Codacy project token (auto-configured via Codacy app) |

---

## Setting Up Secrets

### Step 1 — Generate CI secrets

```bash
# Run this locally and copy the output into GitHub Secrets
python -c "
import secrets
print('CI_JWT_SECRET:', secrets.token_hex(32))
print('CI_ENCRYPTION_KEY:', secrets.token_hex(32))
print('CI_KILL_SWITCH_TOKEN:', secrets.token_hex(32))
"
```

### Step 2 — Add to GitHub

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add each secret from the table above

### Step 3 — Verify CI passes

Push a commit to `main` or open a PR and check the Actions tab. All three jobs
(`pre-commit`, `dependency-scan`, `test`) must pass before merging.

---

## Docker Image

The Docker image is built from `Dockerfile` in the repository root.

### Image Tags

| Tag | When created | Use case |
|-----|-------------|---------|
| `hopefx/ai-trading:latest` | Every release tag | Production (latest stable) |
| `hopefx/ai-trading:v1.17.0` | Release tag `v1.17.0` | Pinned production deploy |

### Pull the image

```bash
docker pull hopefx/ai-trading:latest

# Or pin to a specific version
docker pull hopefx/ai-trading:v1.17.0
```

### Run with Docker Compose

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env — set SECURITY_JWT_SECRET, HOPEFX_LICENSE_KEY, etc.

# Start full stack
docker compose up -d

# Check status
docker compose ps
docker compose logs -f app
```

---

## Release Process

```bash
# 1. Ensure all tests pass on main
git checkout main && git pull
# Check: github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions — all green

# 2. Update CHANGELOG.md with the new version

# 3. Tag the release (triggers docker-release and build-and-release jobs)
git tag -a v1.17.0 -m "Release v1.17.0"
git push origin v1.17.0

# 4. Monitor the release jobs
# github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions

# 5. Verify the Docker image was pushed
docker pull hopefx/ai-trading:v1.17.0

# 6. Verify production (after deploying the new image)
curl https://your-domain.com/health
```

---

## Running CI Locally

Run the same checks that CI runs, without pushing:

```bash
# Install act (GitHub Actions local runner)
# macOS: brew install act
# Linux: https://github.com/nektos/act

# Run the test job locally
act push -j test \
  --secret CI_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))") \
  --secret CI_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
  --secret CI_KILL_SWITCH_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")
```

Or run the checks directly without `act`:

```bash
# Pre-commit hooks
pre-commit run --all-files

# Lint
ruff check api/ auth/ brokers/ config/ core/ execution/ ml/ risk/ strategies/
ruff format --check api/ auth/ brokers/ config/ core/ execution/ ml/ risk/ strategies/

# Security scan
bandit -r api/ auth/ brokers/ config/ core/ execution/ ml/ risk/ strategies/ -ll -q

# Dependency scan
pip-audit --requirement requirements.txt --desc

# Tests (fast suite)
APP_ENV=test \
  DATABASE_URL=sqlite:///./test.db \
  REDIS_URL=redis://localhost:6379/0 \
  SECURITY_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))") \
  CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
  HOPEFX_KILL_SWITCH_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))") \
  pytest tests/ -m "not slow" -q --tb=short

# Coverage report
pytest tests/ -m "not slow" --cov=. --cov-report=html -q
open htmlcov/index.html
```

---

## Code Quality

### Codacy

Codacy runs static analysis on every PR. Configuration is in `.codacy.yml`.

The Codacy badge in the README reflects the current code quality grade.
Target: Grade A (fewer than 5 issues per 1,000 lines of code).

### CodeQL

GitHub CodeQL scans for security vulnerabilities on every push to `main`.
Results appear in the **Security** tab of the repository.

### Coverage

Coverage is reported to Codecov on every push to `main`.

Target: > 70% line coverage (enforced with `--cov-fail-under=70`).

```bash
# Generate coverage report locally
pytest tests/ -m "not slow" --cov=. --cov-report=html -q
open htmlcov/index.html
```

---

## Kubernetes Deployment

### Staging

Staging deploys automatically on merge to `main` (when `STAGING_KUBECONFIG` is set):

```bash
kubectl set image deployment/hopefx \
  app=hopefx/ai-trading:main \
  --namespace hopefx-staging
kubectl rollout status deployment/hopefx \
  --namespace hopefx-staging \
  --timeout=5m
```

### Production

Production deploys on release tags via Helm:

```bash
helm upgrade --install hopefx helm/hopefx/ \
  --namespace hopefx \
  --set image.tag=v1.17.0 \
  --atomic \
  --timeout 10m
```

See `helm/hopefx/values.yaml` for all configurable parameters.

### Kubernetes Manifests

Staging manifest: `k8s/staging-deployment.yaml`
Production manifest: `k8s/production-deployment.yaml`

Key differences between staging and production:
- Production uses `replicas: 3`, staging uses `replicas: 1`
- Production image tag is pinned to the release version, staging uses `main`
- Production has resource limits set, staging uses defaults

---

## Troubleshooting CI

| Issue | Cause | Fix |
|-------|-------|-----|
| `Secret not found` | Secret not added to GitHub | Add the secret in Settings → Secrets → Actions |
| `pip-audit` fails | Known CVE in a dependency | Check if a patched version exists; update `requirements.txt` |
| Tests fail on Python 3.10 but pass on 3.12 | Syntax or API incompatibility | Check for 3.11+ syntax (e.g., `match`, `tomllib`) |
| Coverage below 70% | New code without tests | Add tests for the new code |
| Docker push fails | `DOCKER_PASSWORD` expired | Regenerate Docker Hub access token |
| Codacy grade drops | New issues introduced | Fix issues flagged in the PR Codacy comment |
| `alembic upgrade head` fails in CI | Migration conflict | Check `alembic history` for branching |

---

---

## Pre-commit Hooks

Pre-commit hooks run locally on every `git commit`. They mirror the CI checks so
failures are caught before pushing.

Install once after cloning:
```bash
pip install pre-commit
pre-commit install
```

Hooks configured in `.pre-commit-config.yaml`:

| Hook | What it checks |
|------|---------------|
| `ruff` | Lint — PEP 8, unused imports, undefined names |
| `ruff-format` | Format — consistent style (replaces black) |
| `bandit` | Security — common Python security issues |
| `check-yaml` | YAML syntax validity |
| `end-of-file-fixer` | Trailing newlines |
| `trailing-whitespace` | Trailing spaces |

Run all hooks manually (without committing):
```bash
pre-commit run --all-files
```

If a hook fails on commit, fix the reported issues and `git add` the changes before
committing again. Do not use `--no-verify` to bypass hooks.

---

## Branch Strategy

| Branch | Purpose | CI runs | Auto-deploy |
|--------|---------|---------|-------------|
| `main` | Production-ready code | Full CI | Staging (if `STAGING_KUBECONFIG` set) |
| `develop` | Integration branch | Full CI | No |
| `feat/*` | Feature branches | Full CI | No |
| `fix/*` | Bug fix branches | Full CI | No |
| `docs/*` | Documentation only | Full CI | No |

All merges to `main` require a passing CI run and at least one approving review.
Direct pushes to `main` are blocked.

---

## Dependency Updates

Keep dependencies current to avoid CVE accumulation:

```bash
# Check for outdated packages
pip list --outdated

# Check for known CVEs
pip-audit --requirement requirements.txt --desc

# Update a specific package
pip install --upgrade package-name
pip freeze > requirements.txt
```

Open a separate PR per dependency update. Do not bundle multiple dependency updates
in a single PR — it makes rollback harder.

---

*Last updated: 2026-07-14*
