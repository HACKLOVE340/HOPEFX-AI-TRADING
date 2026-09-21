# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Root conftest.py — ensures both the project root and src/ are on sys.path
so that namespace packages (hopefx, src/hopefx) merge correctly.
"""

import os
import sys
from pathlib import Path

_repo_root = Path(__file__).parent
_src_dir = Path(_repo_root) / "src"

# Add src/ so that src/hopefx/* merges into the hopefx namespace package.
#
# `str(...)` matters: sys.path entries are documented as strings, and inserting
# Path objects breaks any consumer that does string operations on them. It broke
# the whole test job — hypothesis's scrutineer runs `p.endswith(".zip")` over
# sys.path at import time, so `AttributeError: 'PosixPath' object has no
# attribute 'endswith'` aborted collection for test_property_based.py and
# test_risk_properties.py, and pytest exits non-zero on a collection error
# before running anything (170 deselected, 0 run).
for _p in (_repo_root, _src_dir):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Reduce XGBoost n_estimators from 300→50 during test runs so the full suite
# completes within the 120s pytest timeout.  Production training is unaffected
# because this env var is only set when pytest is running.
os.environ.setdefault("CI_FAST", "1")


# ── Keep the developer's .env out of the test session ─────────────────────────
# ``app.py`` calls ``load_dotenv(override=False)`` at module import, which is
# correct for production — app.py is the entrypoint. Several test modules do
# ``from app import app`` at module scope, so that load happens during pytest
# **collection**: before any test runs, and therefore before any per-test
# environment snapshot is taken. A per-test restore cannot undo pollution that
# predates every snapshot, so the values stayed for the whole session.
#
# What that cost: ``.env`` sets ``PAPER_RAISE_ON_STALE=true`` and
# ``PaperTradingBroker`` reads it once in ``__init__``, so every paper order in
# the session raised ``StalePriceError`` and ``POST /api/trading/order``
# returned 400 instead of 201 — but only when the polluting module was collected
# first, and only on a machine that has a ``.env`` at all.
#
# That last part is the reason this was expensive to find. ``.env`` is
# gitignored; CI has none. The same commit passed in CI and failed locally,
# which reads as "your machine is broken" rather than "an import leaked".
#
# Neutralising ``load_dotenv`` for the session is the fix rather than unsetting
# one variable, because it covers whatever ``.env`` gains next. It also makes
# local runs match CI, which is the only environment the suite is specified
# against: a test that needs a value must set it explicitly.
#
# This must run before any test module is imported. Root conftest.py is loaded
# first by pytest, and patching ``dotenv.load_dotenv`` here means app.py's
# ``from dotenv import load_dotenv`` picks up the no-op.
def _disable_dotenv_for_tests() -> None:
    try:
        import dotenv
    except ImportError:  # python-dotenv absent: nothing to neutralise
        return

    def _noop(*_args, **_kwargs) -> bool:
        """Stand-in for load_dotenv during tests. Returns False: "nothing loaded"."""
        return False

    dotenv.load_dotenv = _noop
    # main_impl is what `from dotenv import load_dotenv` resolves through in
    # some versions; patch both so neither import style escapes.
    main = getattr(dotenv, "main", None)
    if main is not None and hasattr(main, "load_dotenv"):
        main.load_dotenv = _noop


_disable_dotenv_for_tests()


def _disable_pydantic_env_file_for_tests() -> None:
    """Stop pydantic-settings reading the developer's ``.env``.

    ``_disable_dotenv_for_tests`` above closes ``dotenv.load_dotenv``.
    pydantic-settings never calls it: ``DotEnvSettingsSource`` opens the file
    named by ``model_config["env_file"]`` itself. So ``config.settings.Settings``
    kept reading ``.env`` after F241 was "fixed", and two tests in
    ``tests/unit/test_core.py`` passed or failed according to a gitignored file —
    green in every fresh-worktree verification, because a worktree has no
    ``.env``, and red under CI.

    The repository's own ``.env`` carries a bare ``BROKER=``; ``Settings.broker``
    is a nested model, so pydantic tries to JSON-parse the empty string and
    raises ``SettingsError``. Nothing about that is a defect in the code under
    test.

    Setting ``env_file`` to None leaves every other settings source intact —
    real environment variables still apply, which is how tests configure things
    deliberately.
    """
    try:
        from pydantic_settings import BaseSettings
    except ImportError:  # pydantic-settings absent: nothing to neutralise
        return

    def _clear(cls: type) -> None:
        config = getattr(cls, "model_config", None)
        if isinstance(config, dict) and config.get("env_file") is not None:
            config["env_file"] = None
        for subclass in cls.__subclasses__():
            _clear(subclass)

    # Import for the side effect of defining the settings classes, so the walk
    # below reaches them. A project without this module simply has nothing to do —
    # but say so rather than swallowing it, because a silent failure here means
    # the whole suite quietly goes back to reading the developer's .env.
    try:
        import config.settings  # noqa: F401
    except Exception as exc:  # pragma: no cover - reported, never hidden
        print(
            f"conftest: could not import config.settings ({exc}); settings classes defined there will still read .env",
            file=sys.stderr,
        )

    _clear(BaseSettings)


_disable_pydantic_env_file_for_tests()


def _ensure_spa_index_for_tests() -> None:
    """Provide a minimal ``static/index.html`` when the real build is absent.

    Three tests assert that a non-API path is served the SPA shell rather than
    JSON, and that an unmatched ``/api/...`` path returns a 404 whose body names
    the route. Both behaviours live in the catch-all route that
    ``core/page_routes.py`` registers, and that route is only mounted when
    ``static/index.html`` exists.

    ``static/`` is a Vite build output and is gitignored (``.gitignore:28``); no
    workflow builds it before pytest runs. So the tests passed on any machine
    that had once run the frontend build and failed everywhere else -- CI
    included, on every branch, not only this one. That is the same shape as the
    rest of this audit: a check whose result depends on something other than the
    thing it claims to test.

    A four-line placeholder is enough to exercise the routing, which is what the
    tests are actually about. If a real build is present it is left completely
    alone, and anything created here is removed at the end of the session so a
    developer's tree is not left with a stub that a later build would have to
    overwrite.
    """
    import atexit

    index = Path(__file__).parent / "static" / "index.html"
    if index.exists():
        return  # a real build is present; never touch it

    created_dir = not index.parent.exists()
    try:
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(
            "<!doctype html><title>HOPEFX test SPA shell</title>"
            "<div id=root></div><!-- placeholder written by conftest; not a build artifact -->",
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - reported, never hidden
        print(f"conftest: could not create the SPA test shell ({exc})", file=sys.stderr)
        return

    @atexit.register
    def _cleanup() -> None:
        try:
            index.unlink(missing_ok=True)
            if created_dir:
                index.parent.rmdir()
        except OSError:
            pass


_ensure_spa_index_for_tests()
