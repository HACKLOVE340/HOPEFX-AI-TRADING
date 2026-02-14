# Security Best Practices

## Overview

This document outlines the security improvements and best practices implemented in the HOPEFX AI Trading application.

## Environment Variables

### Required Variables

The following environment variables **must** be set for the application to function securely:

#### Configuration Encryption
- `CONFIG_ENCRYPTION_KEY`: Master encryption key for securing API credentials and database passwords
  - Minimum length: 32 characters
  - Should be randomly generated and kept secure
  - Example: Generate with `python -c "import secrets; print(secrets.token_hex(32))"`

#### Optional Security Variables
- `CONFIG_SALT`: Salt for PBKDF2 key derivation (optional, but recommended)
  - If not set, a derived salt will be used (allows backward compatibility)
  - For new installations, set this to a random value
  - Example: Generate with `python -c "import secrets; print(secrets.token_hex(16))"`

#### Application Environment
- `APP_ENV`: Application environment (`development`, `staging`, `production`)
  - Defaults to `development` if not set

### Setting Environment Variables

#### Linux/macOS
```bash
export CONFIG_ENCRYPTION_KEY="your-secure-32-char-min-key-here"
export CONFIG_SALT="your-random-salt-here"
export APP_ENV="production"
```

#### Windows (PowerShell)
```powershell
$env:CONFIG_ENCRYPTION_KEY="your-secure-32-char-min-key-here"
$env:CONFIG_SALT="your-random-salt-here"
$env:APP_ENV="production"
```

#### Using .env file
Create a `.env` file in the project root (never commit this file):
```
CONFIG_ENCRYPTION_KEY=your-secure-32-char-min-key-here
CONFIG_SALT=your-random-salt-here
APP_ENV=production
```

## Security Enhancements

### 1. Encryption Key Derivation (Fixed)

**Issue:** Previously used hardcoded static salt for PBKDF2 key derivation
**Fix:** Now uses environment-specific salt or a derived salt for backward compatibility

```python
# Old (INSECURE):
salt=b'hopefx_ai_trading'  # Static, publicly known

# New (SECURE):
salt = os.getenv('CONFIG_SALT')  # Environment-specific
if not salt:
    # Fallback for backward compatibility
    salt_bytes = hashlib.sha256(self.master_key.encode()).digest()[:16]
```

### 2. Password Hashing (Fixed)

**Issue:** Previously used plain SHA256 for password hashing (vulnerable to rainbow tables)
**Fix:** Now uses PBKDF2-HMAC-SHA256 with random salt

```python
# Old (INSECURE):
hash = hashlib.sha256(password.encode()).hexdigest()

# New (SECURE):
# Generates random salt and uses PBKDF2 with 100,000 iterations
hash = encryption_manager.hash_password(password)
# Verify with:
is_valid = encryption_manager.verify_password(password, hash)
```

### 3. Thread Safety (Fixed)

**Issue:** Cache statistics were not thread-safe, causing race conditions
**Fix:** Added threading.Lock() for all statistics operations

```python
# All stats operations now protected:
with self._stats_lock:
    self.stats.total_hits += 1
```

### 4. Redis Connection Resilience (Fixed)

**Issue:** Single connection attempt without retry
**Fix:** Implemented retry logic with configurable attempts and delays

```python
# Now supports:
MarketDataCache(
    host='localhost',
    port=6379,
    max_retries=3,
    retry_delay=1.0
)
```

## Best Practices

### 1. Credential Storage
- **Never** commit credentials to version control
- Use environment variables or secure secret management
- Rotate credentials regularly
- Use different credentials for different environments

### 2. API Keys
- Store encrypted in configuration files
- Never log API keys or secrets
- Use sandbox/testnet keys for development
- Implement key rotation policies

### 3. Database Security
- Use SSL/TLS for database connections (enabled by default)
- Use parameterized queries (SQLAlchemy handles this)
- Encrypt sensitive data at rest
- Regular security audits

### 4. Production Deployment
```bash
# Generate secure keys
export CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export CONFIG_SALT=$(python -c "import secrets; print(secrets.token_hex(16))")

# Set production environment
export APP_ENV=production

# Disable debug mode
export DEBUG=false
```

### 5. Monitoring and Logging
- Never log sensitive data (passwords, API keys, etc.)
- Implement audit logging for sensitive operations
- Monitor for suspicious activity
- Regular security log reviews

## Migration Guide

### For Existing Installations

If you have existing encrypted configuration data:

1. **Backward Compatibility Mode** (default)
   - Don't set `CONFIG_SALT`
   - Application will use derived salt from master key
   - Existing encrypted data will decrypt correctly

2. **New Secure Mode** (recommended)
   ```bash
   # Generate new salt
   export CONFIG_SALT=$(python -c "import secrets; print(secrets.token_hex(16))")
   
   # Re-encrypt your configuration
   python -c "
   from config.config_manager import ConfigManager
   manager = ConfigManager()
   config = manager.load_config()
   manager.save_config(config)
   "
   ```

### For New Installations

Set all security environment variables before first run:
```bash
export CONFIG_ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export CONFIG_SALT=$(python -c "import secrets; print(secrets.token_hex(16))")
export APP_ENV=development
```

## Security Checklist

- [ ] `CONFIG_ENCRYPTION_KEY` set and secured
- [ ] `CONFIG_SALT` set for new installations
- [ ] `.env` file added to `.gitignore`
- [ ] Production uses `APP_ENV=production`
- [ ] Database SSL/TLS enabled
- [ ] API keys encrypted in configuration
- [ ] Credentials rotated regularly
- [ ] Security monitoring enabled
- [ ] Logs reviewed for sensitive data leaks
- [ ] Regular security audits scheduled

## Reporting Security Issues

If you discover a security vulnerability, please email security@hopefx.ai (DO NOT open a public issue).

## References

- [OWASP Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
- [NIST Password Guidelines](https://pages.nist.gov/800-63-3/sp800-63b.html)
- [Python Cryptography Documentation](https://cryptography.io/)
