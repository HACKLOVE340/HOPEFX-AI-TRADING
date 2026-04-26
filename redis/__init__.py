# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
#
# This directory contains Redis server configuration files (redis.conf,
# sentinel.conf, entrypoint.sh) — it is NOT a Python package.
#
# This __init__.py forwards all imports to the real redis-py package
# installed in site-packages, preventing this config directory from
# shadowing the library when the project root is on sys.path.

from __future__ import annotations

import importlib.util
import os
import sys

_SITE_REDIS = None
for _sp in sys.path:
    # sys.path entries may be str or pathlib.Path — normalise to str.
    _sp_str = str(_sp)
    if not ("site-packages" in _sp_str or "dist-packages" in _sp_str):
        continue
    _candidate = os.path.join(_sp_str, "redis", "__init__.py")
    if os.path.isfile(_candidate):
        _SITE_REDIS = os.path.join(_sp_str, "redis")
        break

if _SITE_REDIS is None:
    raise ImportError(
        "redis-py is not installed. Run: pip install 'redis[asyncio]>=5.0.0'"
    )

# Load the real package under the canonical name so sub-imports resolve.
_spec = importlib.util.spec_from_file_location(
    "redis",
    os.path.join(_SITE_REDIS, "__init__.py"),
    submodule_search_locations=[_SITE_REDIS],
)
assert _spec and _spec.loader, "Could not build spec for real redis package"
_mod = importlib.util.module_from_spec(_spec)
# Register before exec so internal relative imports inside redis-py resolve.
sys.modules["redis"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

# Expose everything in this namespace too (supports `from redis import Redis`).
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
