# CI/CD Pipeline

> GitHub Actions CI/CD for HOPEFX AI Trading.
> Last updated: 2026-07-14

---

## Overview

The pipeline runs on every push and pull request:

1. **Lint** — ruff check + ruff format
2. **Security** — bandit + pip-audit
3. **Test** — pytest (2,560 tests)
4. **Build** — Docker image
5. **Deploy** — staging on merge to `main`, production on tag

---

## GitHub Actions Workflow

The main workflow is at `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

env:
  PYTHON_VERSION: "3.12"
  IMAGE_NAME: ghcr.io/${{ github.repository_owner }}/hopefx-ai-trading

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install ruff
      - run: ruff check .
      - run: ruff format --check .

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install bandit pip-audit
      - run: bandit -r api/ auth/ brokers/ ml/ risk/ core/ -ll -q
      - run: pip-audit --requirement requirements.txt

  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
    env:
      APP_ENV: test
      DATABASE_URL: sqlite:///./test.db
      REDIS_URL: redis://localhost:6379/0
      SECURITY_JWT_SECRET: ${{ secrets.CI_JWT_SECRET }}
      CONFIG_ENCRYPTION_KEY: ${{ secrets.CI_ENCRYPTION_KEY }}
      HOPEFX_KILL_SWITCH_TOKEN: ${{ secrets.CI_KILL_SWITCH_TOKEN }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: alembic upgrade head
      - run: pytest tests/ -q --tb=short --ignore=tests/integration/test_redis.py
      - uses: codecov/codecov-action@v4
        with:
          token: ${{ secrets.CODECOV_TOKEN }}

  build:
    needs: [lint, security, test]
    runs-on: ubuntu-latest
    outputs:
      image: ${{ steps.meta.outputs.tags }}
      digest: ${{ steps.build.outputs.digest }}
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{version}}
            type=sha,prefix=sha-
      - uses: docker/build-push-action@v5
        id: build
        with:
          context: .
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy-staging:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to staging
        run: |
          kubectl set image deployment/hopefx \
            app=${{ needs.build.outputs.image }} \
            --namespace hopefx-staging
          kubectl rollout status deployment/hopefx \
            --namespace hopefx-staging \
            --timeout=5m
        env:
          KUBECONFIG_DATA: ${{ secrets.STAGING_KUBECONFIG }}

  deploy-production:
    needs: build
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/v')
    environment: production
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to production
        run: |
          helm upgrade --install hopefx helm/hopefx/ \
            --namespace hopefx \
            --set image.tag=${{ github.ref_name }} \
            --atomic \
            --timeout 10m
        env:
          KUBECONFIG_DATA: ${{ secrets.PRODUCTION_KUBECONFIG }}
```

---

## Required GitHub Secrets

Set these in your repository: **Settings → Secrets and variables → Actions**

| Secret | Description |
|--------|-------------|
| `CI_JWT_SECRET` | JWT secret for test runs (any 32+ char string) |
| `CI_ENCRYPTION_KEY` | Encryption key for test runs |
| `CI_KILL_SWITCH_TOKEN` | Kill switch token for test runs |
| `CODECOV_TOKEN` | Codecov upload token (from codecov.io) |
| `STAGING_KUBECONFIG` | Base64-encoded kubeconfig for staging cluster |
| `PRODUCTION_KUBECONFIG` | Base64-encoded kubeconfig for production cluster |

Generate CI secrets:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Encode kubeconfig:
```bash
cat ~/.kube/config | base64 -w 0
```

---

## Kubernetes Deployments

### Staging (`k8s/staging-deployment.yaml`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hopefx
  namespace: hopefx-staging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hopefx
  template:
    metadata:
      labels:
        app: hopefx
    spec:
      containers:
        - name: app
          image: ghcr.io/hacklove340/hopefx-ai-trading:main
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: hopefx-config
          env:
            - name: SECURITY_JWT_SECRET
              valueFrom:
                secretKeyRef:
                  name: hopefx-secrets
                  key: SECURITY_JWT_SECRET
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: hopefx-secrets
                  key: DATABASE_URL
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
```

### Production (`k8s/production-deployment.yaml`)

Same as staging but with:
- `replicas: 3`
- `namespace: hopefx`
- Image tag pinned to the release version (not `main`)
- Resource limits set

---

## Release Process

```bash
# 1. Ensure all tests pass on main
git checkout main && git pull

# 2. Tag the release
git tag -a v1.17.0 -m "Release v1.17.0"
git push origin v1.17.0

# 3. The deploy-production job runs automatically
# Monitor at: github.com/HACKLOVE340/HOPEFX-AI-TRADING/actions

# 4. Verify production
curl https://your-domain.com/health
```

---

## Running CI Locally

```bash
# Install act (GitHub Actions local runner)
brew install act   # macOS
# or: https://github.com/nektos/act

# Run the test job locally
act push -j test \
  --secret CI_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))") \
  --secret CI_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
  --secret CI_KILL_SWITCH_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")
```

Or run the checks directly:
```bash
# Lint
ruff check . && ruff format --check .

# Security
bandit -r api/ auth/ brokers/ ml/ risk/ core/ -ll -q
pip-audit --requirement requirements.txt

# Tests
APP_ENV=test DATABASE_URL=sqlite:///./test.db \
  SECURITY_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))") \
  CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
  HOPEFX_KILL_SWITCH_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))") \
  pytest tests/ -q --tb=short
```

---

## Codacy Integration

Codacy runs static analysis on every PR. Configuration is in `.codacy.yml`.

The Codacy badge in the README reflects the current code quality grade.
Target: Grade A (< 5 issues per 1,000 lines of code).

---

## Coverage

Coverage is reported to Codecov on every push to `main`.

Target: > 80% line coverage.

```bash
# Generate coverage report locally
pytest tests/ --cov=. --cov-report=html -q
open htmlcov/index.html
```
