# Minimal conftest for bug-fix regression tests.
# Avoids the heavy top-level conftest.py which requires pandas, aiohttp, etc.
import os
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("STARTUP_GATE", "false")
