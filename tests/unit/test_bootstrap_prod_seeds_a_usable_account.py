# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_bootstrap_prod_seeds_a_usable_account.py
=========================================================
Every fresh production deployment created a superadmin nobody could log in as,
and reported success.

``scripts/bootstrap_prod.py`` is the documented final step of a deploy. It did::

    ok, msg, user_id = svc.register(...)
    ...
    user = session.query(User).filter_by(id=user_id).first()
    if user:
        user.is_email_verified = True

``AuthService.register`` returns ``(success, message, email_verify_token)`` —
its docstring says so. The third value is a token, not an id::

    register() -> 'SOh7t2TzTA…' (a 43-char token_urlsafe value)
    stored id  -> '17cda109-a7ac-4f2b-9d43-9db72ebc5618'          (uuid)

So ``filter_by(id=<token>)`` matched nothing, ``if user:`` was always False, and
the verification flag was never set. The ``if`` swallowed it — no exception, no
log line — and the script went on to print "Superadmin seeded successfully".

In production that is fatal rather than cosmetic. ``REQUIRE_EMAIL_VERIFICATION``
defaults to **true** when ``APP_ENV=production`` (auth/service.py), so
``register`` creates the account ``PENDING_VERIFICATION``, and ``login`` checks
both ``is_email_verified`` and ``status == ACTIVE``::

    login() -> (False, 'Please verify your email before logging in.', None)

No verification email is sent during deployment bootstrap, so there was no way
through. The deployment looked complete and the platform was unreachable.

The test that matters is the last one: seed, then **log in**. The bug survived
because the script checked that it had run the fix-up, not that the fix-up had
worked — so this asserts on the outcome, through the real ``AuthService``.

Run in a subprocess because ``_REQUIRE_EMAIL_VERIFICATION`` is read at module
import time from ``APP_ENV``; reloading it inside the test session would depend
on import order.
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts/bootstrap_prod.py"

_EMAIL = "superadmin@hopefx.test"
_PASSWORD = "Sup3r!AdminPassw0rd-xyz"  # pragma: allowlist secret — test fixture


def _seed_and_login(tmp_path: pathlib.Path, **overrides: str) -> dict:
    """Create a schema, run the real bootstrap, then attempt a real login."""
    db = tmp_path / "seed.db"
    driver = textwrap.dedent(f"""
        import json, sys
        sys.path.insert(0, {str(_ROOT)!r})

        from database.models import Base
        from database.connection import SessionLocal
        Base.metadata.create_all(SessionLocal.kw["bind"])

        import importlib.util
        spec = importlib.util.spec_from_file_location("bp", {str(_SCRIPT)!r})
        bp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bp)

        seeded_rc = 0
        try:
            bp.main()
        except SystemExit as exc:
            seeded_rc = exc.code or 0

        from auth.service import AuthService
        svc = AuthService(session_factory=SessionLocal)
        ok, msg, _tok = svc.login(email={_EMAIL!r}, password={_PASSWORD!r})
        user = svc.get_user_by_email({_EMAIL!r})
        print("RESULT" + json.dumps({{
            "seed_rc": seeded_rc,
            "login_ok": bool(ok),
            "login_msg": str(msg),
            "verified": bool(getattr(user, "is_email_verified", False)) if user else None,
            "status": getattr(user, "status", None) if user else None,
            "role": getattr(user, "role", None) if user else None,
        }}))
    """)
    env = {
        "PATH": "/usr/bin:/bin",
        "APP_ENV": "production",
        "DATABASE_URL": f"sqlite:///{db}",
        "SECURITY_JWT_SECRET": "j" * 48,
        "BOOTSTRAP_SUPERADMIN_EMAIL": _EMAIL,
        "BOOTSTRAP_SUPERADMIN_PASSWORD": _PASSWORD,
        **overrides,
    }
    proc = subprocess.run(
        [sys.executable, "-c", driver],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env=env,
        timeout=300,
        check=False,
    )
    marker = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT")]
    assert marker, f"driver produced no result\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-3000:]}"
    return json.loads(marker[-1][len("RESULT") :])


# ── The property that was violated ───────────────────────────────────────────


def test_the_seeded_superadmin_can_actually_log_in(tmp_path):
    """The whole point of the script. Everything else is a means to this."""
    result = _seed_and_login(tmp_path)
    assert result["seed_rc"] == 0, "seeding reported failure"
    assert result["login_ok"] is True, f"seeded account cannot log in: {result['login_msg']}"


def test_the_account_is_verified_and_active(tmp_path):
    """login() gates on both, and register() sets neither when verification is
    required."""
    result = _seed_and_login(tmp_path)
    assert result["verified"] is True
    assert result["status"] == "active"


def test_it_keeps_the_superadmin_role(tmp_path):
    """Fixing the verification must not quietly change what the account is."""
    assert _seed_and_login(tmp_path)["role"] == "superadmin"


def test_it_works_where_the_bug_lived(tmp_path):
    """APP_ENV=production is what makes REQUIRE_EMAIL_VERIFICATION default true.

    Under development the account is auto-verified by register() and the defect
    is invisible, which is why it reached production untouched.
    """
    result = _seed_and_login(tmp_path, APP_ENV="production", REQUIRE_EMAIL_VERIFICATION="true")
    assert result["login_ok"] is True, result["login_msg"]


# ── The specific mistake, pinned by shape ────────────────────────────────────


def test_the_registration_token_is_not_treated_as_a_user_id():
    """register()'s third value is an email verification token."""
    src = _SCRIPT.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.targets[0], ast.Tuple):
            continue
        call = node.value
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "register":
            names = [getattr(el, "id", "") for el in node.targets[0].elts]
            assert "user_id" not in names, f"register() unpacked as {names} — the third value is a token"
            return
    pytest.fail("no `... = svc.register(...)` assignment found")


def _code_only(path: pathlib.Path) -> str:
    """Source with comments and docstrings removed.

    The comment above the fix quotes the broken expression verbatim, so a naive
    substring search finds the bug in its own explanation.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            node.value.value = ""
    return ast.unparse(tree)


def test_the_account_is_looked_up_by_email():
    """The only identifier the script actually holds."""
    code = _code_only(_SCRIPT)
    assert "filter_by(email=email)" in code
    assert "filter_by(id=user_id)" not in code


def test_register_still_returns_a_token_third():
    """If this contract ever changes, the fix above needs revisiting — better to
    fail here than to silently mis-seed again."""
    doc = (_ROOT / "auth/service.py").read_text()
    assert "Returns (success, message, email_verify_token)" in doc


# ── Failure must be loud ─────────────────────────────────────────────────────


def test_it_refuses_to_report_success_for_an_unusable_account(tmp_path):
    """The defect survived because the script confirmed it had run the fix-up,
    not that the fix-up had worked. A post-check must exist and must exit
    non-zero.
    """
    src = _SCRIPT.read_text()
    assert "Not reporting success" in src
    tail = src.split("filter_by(email=email)", 1)[1]
    assert "sys.exit(1)" in tail, "nothing fails the script when the account is unusable"


def test_seeding_twice_is_still_idempotent(tmp_path):
    """Documented behaviour: re-running must not fail a redeploy."""
    first = _seed_and_login(tmp_path)
    assert first["seed_rc"] == 0
    second = _seed_and_login(tmp_path)
    assert second["seed_rc"] == 0
    assert second["login_ok"] is True
