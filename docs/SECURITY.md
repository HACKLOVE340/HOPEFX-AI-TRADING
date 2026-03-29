# Security Policy

## Supported Versions

| Version | Security Updates |
|---------|-----------------|
| 1.16.x (current) | ✅ Active |
| 1.15.x | ✅ Critical fixes only |
| < 1.15 | ❌ Unsupported — upgrade to current |

---

## Security Controls

### Authentication & Authorisation
| Control | Status | Detail |
|---------|--------|--------|
| JWT access + refresh tokens | ✅ Implemented | HS256, configurable expiry |
| RBAC (user / trader / admin / superadmin) | ✅ Implemented | All sensitive routes gated |
| TOTP 2FA | ✅ Implemented | Full setup / verify / disable flow |
| bcrypt password hashing | ✅ Implemented | Cost factor 12 |
| Per-IP rate limiting | ✅ Implemented | Redis-backed, in-memory fallback |
| JWT secret rotation | ✅ Env-var driven | `SECURITY_JWT_SECRET` |

### Network & Transport
| Control | Status | Detail |
|---------|--------|--------|
| HTTPS enforcement | ⚠️ Infrastructure layer | Uvicorn serves HTTP; TLS terminated at reverse proxy / load balancer |
| CORS wildcard guard | ✅ Implemented (V15) | Startup validator rejects `ALLOWED_ORIGINS=*` in production |
| X-Forwarded-For spoofing | ✅ Fixed (V15) | Header only accepted from `TRUSTED_PROXY_IPS` |
| CORS origin validation | ✅ Implemented | `MOBILE_CORS_ORIGINS` validated to https:// only |

### Data Protection
| Control | Status | Detail |
|---------|--------|--------|
| SQL injection | ✅ SQLAlchemy ORM | Parameterised queries throughout |
| PII scrubbing in logs | ✅ Implemented | 15 field names scrubbed before Sentry/log output |
| Config encryption | ✅ Fernet + keyring | `CONFIG_ENCRYPTION_KEY` required in production |
| Hardcoded credentials | ✅ Fixed | `docker-compose.yml` uses `${VAR:?error}` |
| Secrets in `.env` | ⚠️ Template has `CHANGE_ME` markers | Startup validator rejects placeholder values |

### CI/CD & Supply Chain
| Control | Status | Detail |
|---------|--------|--------|
| TruffleHog secret scanning | ✅ CI | `.github/workflows/security-scan.yml` |
| Trivy container scanning | ✅ CI | SARIF output, uploaded to GitHub Security |
| CodeQL SAST | ✅ CI | Python + Actions, weekly + on push |
| bandit static analysis | ✅ CI | Report-only (never blocks merge) |
| pip-audit / safety | ✅ CI | Dependency CVE scanning |

### Monitoring
| Control | Status | Detail |
|---------|--------|--------|
| Sentry error tracking | ✅ Implemented | Set `SENTRY_DSN` in production `.env` |
| Prometheus metrics | ✅ Implemented | 41 metrics, Grafana dashboards |
| ML fallback alert | ✅ Implemented | Sentry fatal + Discord when `advanced_oos.pkl` fails |
| Online learner persistence | ✅ Implemented | `SklearnOnlineLearner` state persisted to `ml/saved_models/online_learner_{symbol}.pkl`; loaded at startup |

---

## Known Limitations

1. **HTTPS not enforced at app level** — TLS must be terminated at the infrastructure layer (nginx, AWS ALB, Cloudflare). Do not expose port 8000 directly to the internet.
2. **`ALLOWED_ORIGINS` default is `http://localhost:3000`** — must be set to your production domain before deploying. The startup validator rejects `*` in production.
3. **Sentry DSN optional in dev** — set `SENTRY_DSN` in production `.env` or error tracking is disabled.
4. **Online learner pickle files** — `ml/saved_models/online_learner_*.pkl` are serialised with Python's `pickle`. Do not load these files from untrusted sources. They are written only by the application itself and should not be exposed via any API endpoint.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues privately:

1. Go to the repository **Security** tab → **"Report a vulnerability"** (GitHub private advisory).
2. Include: affected version, reproduction steps, impact assessment, and any suggested fix.
3. You will receive an acknowledgement within 48 hours.
4. Critical vulnerabilities (RCE, auth bypass, credential exposure) will be patched within 7 days.
5. A CVE will be requested for confirmed vulnerabilities with CVSS ≥ 7.0.

We follow responsible disclosure: reporters are credited in the release notes unless they prefer anonymity.

---

## Security Configuration Checklist (Production)

```bash
# Required — startup validator will reject placeholder values
SECURITY_JWT_SECRET=<48-char random>        # python -c "import secrets; print(secrets.token_urlsafe(48))"
CONFIG_ENCRYPTION_KEY=<48-char random>
HOPEFX_KILL_SWITCH_TOKEN=<48-char random>
DATABASE_URL=postgresql://user:pass@host:5432/db
REDIS_URL=redis://host:6379/0

# Required — startup validator rejects * in production
ALLOWED_ORIGINS=https://your-domain.com

# Recommended
SENTRY_DSN=https://...@sentry.io/...
TRUSTED_PROXY_IPS=10.0.0.1,10.0.0.2      # your load balancer IPs
APP_ENV=production
```

Generate all secrets at once:

```bash
python scripts/manage_secrets.py generate
python scripts/manage_secrets.py validate
```
