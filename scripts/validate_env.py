"""Validate critical .env values before the server starts.

Called by start.bat. Exits with code 1 and a clear message on failure.
"""

import re
import sys

try:
    from dotenv import dotenv_values

    env = dotenv_values(".env")
except Exception:
    # dotenv not installed yet — skip validation, server will catch it
    sys.exit(0)

errors = []

# AUTH_RATE_LIMIT_REQUESTS must be a plain integer (e.g. 10), not a duration (e.g. "1h")
val = env.get("AUTH_RATE_LIMIT_REQUESTS", "10").strip()
if not re.fullmatch(r"[0-9]+", val):
    errors.append(
        f"AUTH_RATE_LIMIT_REQUESTS={val!r} must be a plain integer (e.g. 10), "
        "not a duration string. Fix your .env file."
    )

# AUTH_RATE_LIMIT_WINDOW_SECONDS must also be a plain integer
val2 = env.get("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60").strip()
if not re.fullmatch(r"[0-9]+", val2):
    errors.append(
        f"AUTH_RATE_LIMIT_WINDOW_SECONDS={val2!r} must be a plain integer in seconds "
        "(e.g. 60 for 1 minute, 3600 for 1 hour). Fix your .env file."
    )

if errors:
    for e in errors:
        print(f"[ERROR] {e}")
    sys.exit(1)
