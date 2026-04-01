# CI/CD Pipeline

> GitHub Actions CI/CD for HOPEFX AI Trading.
> Last updated: 2026-04-01

---

## Overview

The pipeline runs on every push and pull request to `main` and `develop`:

| Job | Trigger | What it does |
|-----|---------|-------------|
| `pre-commit` | Push/PR | ruff lint + format, bandit, pre-commit hooks |
| `dependency-scan` | Push/PR | pip-audit CVE scan, Trivy supply-chain scan |
| `test` | Push/PR | pytest on Python 3.10/3.11/3.12, coverage upload |
| `docker-release` | Tag `v*` | Build + push Docker image to Docker Hub |
| `build-and-release` | Tag `v*` | Build Python package, create GitHub Release |

All workflow files are in `.github/workflows/`.

---

## Workflow Files

### CI (`ci.yml`)

Runs on every push to `main`/`develop` and every PR targeting `main`.

**Jobs:**

**`pre-commit`** — Runs all pre-commit hooks (ruff check, ruff format, bandit):
```yaml
- uses: pre-commit/action@v3.0.1
```

**`dependency-scan`** — Scans for known CVEs and supply-chain issues:
```yaml
- run: pip-audit --requirement=requirements.txt --desc || true
- uses: aquasecurity/trivy-action@v0.29.0
  with:
    scan-type: fs
    severity: CRITICAL,HIGH
```

**`test`** — Matrix test across Python 3.10, 3.11, 3.12 with PostgreSQL 16 + Redis 7:
```yaml
strategy:
  matrix:
    python-version: ["3.10", "3.11", "3.12"]
services:
  postgres:
    image: postgres:16
  redis:
    image: redis:7
```

Test command:
```yaml
- run: |
    pytest tests/ \
      -m "not slow" \
      --cov=. \
      --cov-report=xml \
      --cov-fail-under=70 \
      -v \
      --asyncio-mode=auto
```

Coverage is uploaded to Codecov on every run.

### Release (`release.yml`)

Triggers on any tag matching `v*` (e.g., `v1.17.0`).

**`build-and-release`** — Builds the Python package and creates a GitHub Release:
```yaml
- run: python -m build
- uses: actions/create-release@v1
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**`docker-release`** — Builds and pushes the Docker image to Docker Hub:
```yaml
- uses: docker/build-push-action@v5
  with:
    push: true
    tags: |
      hopefx/ai-trading:${{ steps.get_version.outputs.VERSION }}
      hopefx/ai-trading:latest
```

### Other Workflows

| File | Purpose |
|------|---------|
| `codacy.yml` | Codacy static analysis on every PR |
| `codeql.yml` | GitHub CodeQL security analysis |
| `security-scan.yml` | Additional security scanning |
| `docs.yml` | MkDocs build and deploy to GitHub Pages |
| `tests.yml` | Extended test suite (slow tests, integration) |
| `update_docs.yml` | Auto-update docs on merge to main |

---

## Required GitHub Secrets

Set these in: **Repository → Settings → Secrets and variables → Actions**

### CI Secrets (required for tests to pass)

| Secret | Description | How to generate |
|--------|-------------|----------------|
| `CI_JWT_SECRET` | JWT signing key for test runs | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CI_ENCRYPTION_KEY` | Config encryption key for test runs | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CI_KILL_SWITCH_TOKEN` | Kill switch token for test runs | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CODECOV_TOKEN` | Codecov upload token | From [codecov.io](https://codecov.io) after linking the repo |

### Release Secrets (required for releases)

| Secret | Description | Where to get it |
|--------|-------------|----------------|
| `DOCKER_USERNAME` | Docker Hub username | Your Docker Hub account |
| `DOCKER_PASSWORD` | Docker Hub access token | Docker Hub → Account Settings → Security → New Access Token |
| `PYPI_API_TOKEN` | PyPI upload token | pypi.org → Account Settings → API tokens |

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

*Last updated: 2026-04-01*
