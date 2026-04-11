# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/test_scanner.py
========================
Scans the entire codebase for test files and categorises them.

Categories
----------
unit        — tests/unit/, test_unit/, *_unit_test.py
api         — test_api*, test_auth*, test_billing*, test_payments*, test_whitelabel*
broker      — test_broker*, test_ibkr*, test_oanda*, test_order_gateway*
risk        — test_risk*, test_circuit*, test_cvar*, test_prop*, test_kill_switch*
ml          — test_ml*, test_model*, test_train*, test_sharpe*, test_signal*
security    — test_security*, test_secrets*, test_jwt*, test_auth_pentest*, test_auto_heal*
performance — test_k6*, test_load*, test_locust*, k6/
e2e         — tests/e2e/, test_e2e*, test_full_pipeline*, test_production_wiring*
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc
PROJECT_ROOT = Path(__file__).parent.parent

# ── Category rules (ordered — first match wins) ───────────────────────────────

_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ('e2e', [
        r'tests/e2e/',
        r'test_e2e',
        r'test_full_pipeline',
        r'test_production_wiring',
        r'test_connect_to_life',
        r'test_production_readiness',
        r'test_proof_artifacts',
    ]),
    ('performance', [
        r'test_k6',
        r'test_load',
        r'test_kill_switch_load',
        r'k6/',
        r'locust/',
    ]),
    ('security', [
        r'test_security',
        r'test_secrets',
        r'test_jwt',
        r'test_auth_pentest',
        r'test_auto_heal',
        r'test_deployment_gates',
        r'test_smoke_critical',
    ]),
    ('ml', [
        r'test_ml',
        r'test_model',
        r'test_train',
        r'test_sharpe',
        r'test_signal',
        r'test_brain',
        r'test_anomaly',
        r'test_adaptive_edge',
        r'test_advanced_patterns',
        r'test_all_strategies',
        r'test_analytics',
        r'test_analysis',
    ]),
    ('risk', [
        r'test_risk',
        r'test_circuit',
        r'test_cvar',
        r'test_prop',
        r'test_kill_switch',
        r'test_pre_trade',
        r'test_paper_trading',
        r'test_execution',
        r'test_portfolio',
        r'test_backtest',
        r'test_backtesting',
    ]),
    ('broker', [
        r'test_broker',
        r'test_ibkr',
        r'test_oanda',
        r'test_order_gateway',
        r'test_connector',
        r'test_copy_trading',
        r'test_market_data',
        r'test_macro',
        r'test_mcc_signal',
    ]),
    ('api', [
        r'tests/integration/',
        r'test_api',
        r'test_auth',
        r'test_billing',
        r'test_payments',
        r'test_whitelabel',
        r'test_marketplace',
        r'test_social',
        r'test_validation',
        r'test_v17',
        r'test_new_components',
        r'test_comprehensive',
        r'test_critical_paths',
        r'test_integration',
    ]),
    ('unit', [
        r'tests/unit/',
        r'test_unit/',
        r'unit/',
    ]),
]

_EXCLUDE_DIRS = {
    '__pycache__', '.git', 'node_modules', '.venv', 'venv',
    'dist', 'build', '.mypy_cache', '.pytest_cache',
}


def _categorise(rel_path: str) -> str:
    """Return the category key for a test file path."""
    norm = rel_path.replace('\\', '/')
    for category, patterns in _CATEGORY_PATTERNS:
        for pat in patterns:
            if re.search(pat, norm):
                return category
    return 'unit'  # default bucket


def _is_test_file(path: Path) -> bool:
    name = path.name
    return (
        path.suffix == '.py'
        and (
            name.startswith('test_')
            or name.endswith('_test.py')
            or name.endswith('_tests.py')
        )
    )


def _count_test_functions(path: Path) -> int:
    """Count def test_ functions in a file without importing it."""
    try:
        text = path.read_text(errors='replace')
        return len(re.findall(r'^\s*(?:async\s+)?def\s+test_', text, re.MULTILINE))
    except OSError:
        return 0


def scan_tests(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """
    Walk the project tree and return a categorised test index.

    Returns
    -------
    {
        "total": int,
        "files": int,
        "by_category": {"unit": int, "api": int, ...},
        "file_list": [{"path": str, "category": str, "test_count": int}],
        "last_indexed": ISO-8601 string,
    }
    """
    by_category: dict[str, int] = {k: 0 for k, _ in _CATEGORY_PATTERNS}
    by_category['unit'] = 0  # ensure default bucket exists
    file_list: list[dict[str, Any]] = []
    total_tests = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded dirs in-place
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            if not _is_test_file(fpath):
                continue
            try:
                rel = str(fpath.relative_to(root))
            except ValueError:
                rel = str(fpath)

            category = _categorise(rel)
            count = _count_test_functions(fpath)
            total_tests += count
            by_category[category] = by_category.get(category, 0) + count
            file_list.append({'path': rel, 'category': category, 'test_count': count})

    return {
        'total': total_tests,
        'files': len(file_list),
        'by_category': by_category,
        'file_list': file_list,
        'last_indexed': datetime.now(UTC).isoformat(),
    }


# ── Persistent index (Redis + disk) ──────────────────────────────────────────

_INDEX_PATH = PROJECT_ROOT / 'data' / 'test_index.json'
_REDIS_KEY = 'heal:test_index'


def _load_cached_index() -> dict[str, Any] | None:
    """Load the last-saved index from disk."""
    try:
        if _INDEX_PATH.exists():
            return json.loads(_INDEX_PATH.read_text())
    except Exception as exc:
        logger.debug('test_scanner: disk cache read failed: %s', exc)
    return None


def _save_index(index: dict[str, Any]) -> None:
    """Persist index to disk and Redis."""
    try:
        _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _INDEX_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(index, indent=2))
        tmp.replace(_INDEX_PATH)
    except Exception as exc:
        logger.warning('test_scanner: disk save failed: %s', exc)

    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            rc.set(_REDIS_KEY, json.dumps(index), ex=3600)
    except Exception as exc:
        logger.debug('test_scanner: redis save failed: %s', exc)


def get_test_index(force_rescan: bool = False) -> dict[str, Any]:
    """
    Return the test index, using the cached version unless force_rescan=True.
    Adds last_run / last_run_passed / last_run_failed from Redis if available.
    """
    if not force_rescan:
        # Try Redis first (fastest)
        try:
            from cache.redis_client import get_redis_client
            rc = get_redis_client()
            if rc:
                raw = rc.get(_REDIS_KEY)
                if raw:
                    return json.loads(raw)
        except Exception:
            pass
        # Fall back to disk
        cached = _load_cached_index()
        if cached:
            return _enrich_with_run_stats(cached)

    # Full scan
    index = scan_tests()
    _save_index(index)
    return _enrich_with_run_stats(index)


def _enrich_with_run_stats(index: dict[str, Any]) -> dict[str, Any]:
    """Attach last test-run stats from Redis if available."""
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            raw = rc.get('heal:last_test_run')
            if raw:
                run = json.loads(raw)
                index['last_run'] = run.get('ts')
                index['last_run_passed'] = run.get('passed')
                index['last_run_failed'] = run.get('failed')
    except Exception:
        pass
    return index


def record_test_run(passed: int, failed: int, status: str = 'ok') -> None:
    """Called by the healer after running tests to persist run stats."""
    payload = {
        'ts': datetime.now(UTC).isoformat(),
        'passed': passed,
        'failed': failed,
        'status': status,
    }
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            rc.set('heal:last_test_run', json.dumps(payload), ex=86400)
            rc.rpush('heal:test_run_history', json.dumps(payload))
            rc.ltrim('heal:test_run_history', -100, -1)
    except Exception as exc:
        logger.debug('test_scanner: record_test_run failed: %s', exc)


def get_test_run_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return the last N test run records."""
    try:
        from cache.redis_client import get_redis_client
        rc = get_redis_client()
        if rc:
            raw = rc.lrange('heal:test_run_history', -limit, -1)
            return [json.loads(r) for r in reversed(raw)]
    except Exception as exc:
        logger.debug('test_scanner: get_test_run_history: %s', exc)
    return []


# ── Background async re-index ─────────────────────────────────────────────────

_reindex_lock: bool = False


async def async_reindex(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """
    Run a full test scan in a thread pool so it doesn't block the event loop.
    Uses a simple lock to prevent concurrent scans.
    """
    global _reindex_lock
    if _reindex_lock:
        logger.info('test_scanner: reindex already running, skipping')
        cached = _load_cached_index()
        return cached or {'total': 0, 'files': 0, 'by_category': {}, 'last_indexed': None}

    _reindex_lock = True
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        index = await loop.run_in_executor(None, lambda: scan_tests(root))
        _save_index(index)
        logger.info('test_scanner: async reindex complete — %d tests in %d files',
                    index['total'], index['files'])
        return _enrich_with_run_stats(index)
    finally:
        _reindex_lock = False


# ── Pytest runner (sync, for use in subprocess or thread) ────────────────────

def run_category_tests(
    categories: list[str],
    timeout_sec: int = 600,
    parallel: bool = True,
    per_suite_timeout: int = 120,
) -> dict[str, Any]:
    """
    Run pytest for the given category list synchronously.
    Returns {passed, failed, errors, duration_sec, output, success}.
    """
    import subprocess  # nosec B404
    import time

    index = get_test_index(force_rescan=False)
    file_list: list[dict[str, Any]] = index.get('file_list', [])

    paths = [
        e['path'] for e in file_list
        if e.get('category') in categories and Path(PROJECT_ROOT / e['path']).exists()
    ][:200]

    if not paths:
        return {
            'passed': 0, 'failed': 0, 'errors': 0,
            'duration_sec': 0, 'output': 'No test files found for categories: ' + str(categories),
            'success': True,
        }

    cmd = [
        'python', '-m', 'pytest',
        '--tb=short', '-q', '--no-header',
        f'--timeout={per_suite_timeout}',
    ]
    if parallel:
        cmd += ['-n', 'auto']
    cmd += paths

    t0 = time.time()
    try:
        result = subprocess.run(  # nosec B603
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        duration = round(time.time() - t0, 2)
        output = result.stdout + result.stderr
        passed, failed, errors = _parse_pytest_summary(output)
        success = result.returncode == 0
        record_test_run(passed, failed, 'ok' if success else 'failed')
        return {
            'passed': passed, 'failed': failed, 'errors': errors,
            'duration_sec': duration, 'output': output[-4000:],
            'success': success, 'returncode': result.returncode,
        }
    except subprocess.TimeoutExpired:
        duration = round(time.time() - t0, 2)
        record_test_run(0, 0, 'timeout')
        return {
            'passed': 0, 'failed': 0, 'errors': 0,
            'duration_sec': duration, 'output': f'Test run timed out after {timeout_sec}s',
            'success': False, 'returncode': -1,
        }
    except FileNotFoundError:
        return {
            'passed': 0, 'failed': 0, 'errors': 0,
            'duration_sec': 0, 'output': 'pytest not found in PATH',
            'success': False, 'returncode': -1,
        }
    except Exception as exc:
        return {
            'passed': 0, 'failed': 0, 'errors': 0,
            'duration_sec': 0, 'output': str(exc),
            'success': False, 'returncode': -1,
        }


def _parse_pytest_summary(output: str) -> tuple[int, int, int]:
    """Extract passed/failed/error counts from pytest output."""
    import re
    passed = failed = errors = 0
    m = re.search(r'(\d+) passed', output)
    if m:
        passed = int(m.group(1))
    m = re.search(r'(\d+) failed', output)
    if m:
        failed = int(m.group(1))
    m = re.search(r'(\d+) error', output)
    if m:
        errors = int(m.group(1))
    return passed, failed, errors
