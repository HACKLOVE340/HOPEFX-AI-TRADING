# Security Guide

> Last updated: 2026-04-01

This document covers all security-relevant configuration, known fixes applied,
and the responsible disclosure process.

---

## Secrets Management

### Required Secrets

Three secrets must be set before the application will start in any environment:

| Variable | Purpose | Minimum Length |
|----------|---------|----------------|
| `SECURITY_JWT_SECRET` | Signs all JWT tokens | 32 characters |
| `CONFIG_ENCRYPTION_KEY` | Encrypts config vault (Fernet) | 32 characters |
| `HOPEFX_KILL_SWITCH_TOKEN` | Authenticates kill switch API calls | 32 characters |

Generate each with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

`config/startup_validator.py` calls `sys.exit(1)` at boot if any of these are
missing, empty, or set to known placeholder values (`CHANGE_ME`, `your_secret`, etc.).

### Secret Rotation

To rotate `SECURITY_JWT_SECRET`:
1. Generate a new secret
2. Update `.env` (or your secrets manager)
3. Restart the application — all existing JWT tokens are immediately invalidated
4. Users must log in again

To rotate `CONFIG_ENCRYPTION_KEY`:
1. Decrypt all vault entries with the old key first
2. Update the key
3. Re-encrypt all vault entries with the new key
4. Restart

### Secrets in Production

Never store secrets in:
- `.env` files committed to git (`.env` is in `.gitignore`)
- Docker Compose `environment:` blocks in plain text
- Kubernetes ConfigMaps

Use instead:
- **Docker Compose:** `env_file: .env` (file not committed)
- **Kubernetes:** `secretKeyRef` from a `Secret` object
- **Cloud:** AWS Secrets Manager, GCP Secret Manager, Azure Key Vault
- **Self-hosted:** HashiCorp Vault (wired via `config/vault.py`)

Validate secrets before deploying:
```bash
python scripts/manage_secrets.py validate
```

---

## Authentication

### JWT Configuration

All API endpoints (except `/health`, `/docs`, `/openapi.json`) require a valid JWT.

Token lifetime is controlled by:
```bash
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30    # default: 30 minutes
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7       # default: 7 days
```

Tokens are signed with HS256 using `SECURITY_JWT_SECRET`.

### Getting a Token

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}'
```

Response:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

Use the token in subsequent requests:
```bash
curl http://localhost:8000/api/signals/latest \
  -H "Authorization: Bearer eyJ..."
```

### Password Hashing

Passwords are hashed with `bcrypt` (cost factor 12). The `fake_hash_password`
backdoor that existed in earlier versions has been removed. See `auth/routes.py`.

Pinned versions:
```
bcrypt==4.1.3
PyJWT==2.8.0
cryptography==42.0.8
passlib==1.7.4
```

---

## CORS Configuration

CORS is configured via environment variables. Never use `allow_origins=["*"]`
with `allow_credentials=True` — this violates the CORS spec and enables
credential theft.

```bash
# Comma-separated list of allowed origins
ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com

# Mobile API origins (separate allowlist)
MOBILE_CORS_ORIGINS=https://mobile.yourdomain.com
```

`allow_credentials` is `False` by default. Only set it to `True` if you
explicitly need cookie-based auth and have a restricted origin allowlist.

---

## API Rate Limiting

Rate limiting is applied per IP and per authenticated user.

Default limits (configurable in `.env`):
```bash
RATE_LIMIT_DEFAULT=100/minute          # unauthenticated
RATE_LIMIT_AUTHENTICATED=1000/minute   # authenticated users
RATE_LIMIT_TRADING=10/minute           # order placement endpoints
RATE_LIMIT_ML=30/minute                # ML inference endpoints
```

Rate limit headers are returned on every response:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1720000060
```

When the limit is exceeded, the API returns `429 Too Many Requests`.

---

## HTTPS / TLS

The application itself does not terminate TLS. Use a reverse proxy:

**Nginx (recommended):**
```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Set `TRUSTED_PROXY_IPS` to your Nginx IP so the application trusts
`X-Forwarded-For` headers:
```bash
TRUSTED_PROXY_IPS=127.0.0.1
```

**Let's Encrypt (free TLS):**
```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com
```

---

## Kubernetes Secrets

Never put credentials in `k8s/k8s-configmap.yaml`. Use a `Secret` object:

```bash
kubectl create secret generic hopefx-secrets \
  --from-literal=SECURITY_JWT_SECRET=your_secret \
  --from-literal=CONFIG_ENCRYPTION_KEY=your_key \
  --from-literal=HOPEFX_KILL_SWITCH_TOKEN=your_token \
  --from-literal=DATABASE_URL=postgresql://... \
  --from-literal=REDIS_URL=redis://...
```

The deployment (`k8s/k8s-deployment.yaml`) wires all credentials via
`secretKeyRef`. Optional secrets use `optional: true` so missing keys
don't crash pod startup.

---

## Sentry PII Scrubbing

Sentry is configured to scrub sensitive data before sending events.
The `before_send` hook in `monitoring/sentry_config.py` removes these
field names from all event payloads:

```
password, token, secret, api_key, authorization, credit_card,
ssn, account_number, routing_number, private_key, access_token,
refresh_token, jwt, bearer, oanda_token, ibkr_password
```

Health check and metrics endpoints are filtered from Sentry transactions
to avoid quota waste.

---

## Watchlist and Chat Route Protection

Both routes previously had no authentication:

- `api/watchlist.py` — user watchlists were publicly readable
- `api/chat.py` — unprotected LLM endpoint (unlimited OpenAI bill risk)

Both now require a valid JWT. Any request without `Authorization: Bearer <token>`
returns `401 Unauthorized`.

---

## Vault (Config Encryption)

`config/vault.py` encrypts sensitive config values at rest using Fernet
symmetric encryption (AES-128-CBC + HMAC-SHA256).

```python
from config.vault import Vault

vault = Vault()
vault.set("oanda_token", "your_secret_token")
token = vault.get("oanda_token")
```

The vault key is derived from `CONFIG_ENCRYPTION_KEY`. If `secure_delete()`
fails (e.g., keyring unavailable), it now raises `VaultError` instead of
silently swallowing the error. `_fernet` is zeroed in `finally` to prevent
key material lingering in memory.

---

## Security Scanning

The CI pipeline runs these checks on every push:

```bash
# Bandit — Python security linter
bandit -r api/ auth/ brokers/ ml/ risk/ -ll

# pip-audit — known CVEs in dependencies
pip-audit

# TruffleHog — secrets in git history
trufflehog git file://. --only-verified
```

Run locally:
```bash
pip install bandit pip-audit
bandit -r . -ll --exclude venv,tests
pip-audit
```

---

## Responsible Disclosure

If you discover a security vulnerability:

1. **Do not** open a public GitHub Issue
2. Email the details to the repository owner via GitHub's private vulnerability reporting:
   [github.com/HACKLOVE340/HOPEFX-AI-TRADING/security/advisories/new](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/security/advisories/new)
3. Include: description, reproduction steps, impact assessment, suggested fix
4. Allow 90 days for a fix before public disclosure

We will acknowledge receipt within 48 hours and provide a fix timeline.

---

## Two-Factor Authentication (2FA)

TOTP-based 2FA is available on Professional and above. It is **required** for all
admin accounts.

### Enable 2FA

```bash
# Step 1 — generate TOTP secret
POST /api/auth/2fa/enable
Authorization: Bearer <token>

# Response includes a QR code URL and backup codes
# {"qr_url": "otpauth://totp/HOPEFX:user@...", "backup_codes": [...]}

# Step 2 — verify with your authenticator app
POST /api/auth/2fa/verify
Authorization: Bearer <token>
{"code": "123456"}
```

### Login with 2FA

```bash
# Step 1 — password login returns a partial token
POST /api/auth/login
{"username": "user", "password": "pass"}
# {"requires_2fa": true, "partial_token": "..."}

# Step 2 — complete with TOTP code
POST /api/auth/2fa/complete
{"partial_token": "...", "code": "123456"}
# {"access_token": "...", "token_type": "bearer"}
```

### Backup Codes

Backup codes are generated when 2FA is enabled. Each code is single-use.
Store them securely — they cannot be retrieved after initial generation.

```bash
# Regenerate backup codes (invalidates old ones)
POST /api/auth/2fa/backup-codes/regenerate
Authorization: Bearer <token>
```

---

## Audit Log

All security-relevant actions are logged to the audit log (`audit/logger.py`).

### What is logged

| Event | Fields |
|-------|--------|
| Login (success/failure) | user_id, IP, timestamp, user_agent |
| 2FA enable/disable | user_id, timestamp |
| Password change | user_id, timestamp |
| Kill switch activate/deactivate | user_id, reason, timestamp |
| Subscription change | user_id, old_plan, new_plan, timestamp |
| License key activation | user_id, key_hash, plan, timestamp |
| Admin action | admin_id, action, target_user_id, timestamp |
| API key creation/revocation | user_id, key_id, timestamp |

### Query the audit log

```bash
# Via API (admin only)
curl http://localhost:8000/api/admin/audit-log?user_id=123&limit=50 \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Direct (PostgreSQL)
psql hopefx_db -c "
SELECT timestamp, user_id, action, details
FROM audit_log
WHERE timestamp > NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC
LIMIT 50;"
```

### Audit log retention

Audit logs are retained for 1 year in production. They are append-only —
no audit log entry can be modified or deleted via the API.

---

## Subscription Token Security

The `HOPEFX_LICENSE_KEY` is a subscription token that gates all trading endpoints.
It must be protected like any other secret.

### Storage

- **Development:** `.env` file (never commit to git — `.gitignore` covers `.env`)
- **Production:** Environment variable injected by your secrets manager (Vault, AWS Secrets Manager, k8s Secret)
- **Never:** hardcoded in source code, logged, or returned in API responses

### Validation

The license key is validated:
1. At application startup (blocks start if invalid in production)
2. Every 24 hours at runtime (logs warning if expiring within 7 days)
3. On every request to a gated endpoint (cached for 60 seconds)

### Key format

```
HOPEFX-{TIER}-{RANDOM_8}-{CHECKSUM_4}
Example: HOPEFX-PRO-A7B9C2D4-X8Y2
```

The checksum prevents typos. The tier is embedded so the server can verify
the plan without a database lookup on every request.

### Kill Switch Token

The `HOPEFX_KILL_SWITCH_TOKEN` is separate from the JWT to prevent a compromised
user token from triggering an emergency stop. It must be:
- At least 32 characters
- Stored separately from the JWT secret
- Rotated if you suspect compromise (restart required after rotation)

```bash
# Rotate the kill switch token
python -c "import secrets; print(secrets.token_hex(32))"
# Update HOPEFX_KILL_SWITCH_TOKEN in .env and restart
```

---

## Security Checklist (Pre-Production)

### Secrets
- [ ] `SECURITY_JWT_SECRET` is ≥ 32 chars and not a placeholder
- [ ] `CONFIG_ENCRYPTION_KEY` is ≥ 32 chars and not a placeholder
- [ ] `HOPEFX_KILL_SWITCH_TOKEN` is ≥ 32 chars and not a placeholder
- [ ] `HOPEFX_LICENSE_KEY` is set and valid (`python scripts/manage_secrets.py validate`)
- [ ] No secrets in git history (`trufflehog git file://. --only-verified`)

### Infrastructure
- [ ] `DATABASE_URL` points to PostgreSQL (not SQLite)
- [ ] `ALLOWED_ORIGINS` is set to explicit `https://` domains (not `*`)
- [ ] `APP_ENV=production`
- [ ] `SENTRY_DSN` is set
- [ ] TLS is terminated at the reverse proxy (Nginx + Let's Encrypt)
- [ ] `TRUSTED_PROXY_IPS` is set to your load balancer IPs
- [ ] Alembic migrations applied: `alembic upgrade head`

### Access Control
- [ ] Admin accounts have 2FA enabled
- [ ] Kill switch token stored in secrets manager (not `.env` on disk)
- [ ] API rate limiting active (check `X-RateLimit-Remaining` header)
- [ ] Audit log enabled and queryable

### Scanning
- [ ] `bandit` reports no HIGH severity issues
- [ ] `pip-audit` reports no known CVEs
- [ ] Codacy grade A (check repository Security tab)

Run the full pre-deploy validation:
```bash
python scripts/manage_secrets.py validate
python deployment_guide.py
```
