# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Every superadmin capability is gated server-side, and stays that way.

`docs/audit/AI_CORE_SPEC_INTAKE.md` §4 adopts this as an acceptance criterion
for both the AI Core page and hive chat:

> Every superadmin-only capability is enforced **server-side**, and there is a
> test that a `trader`-role token receives 403 from each such endpoint.

with the precedent for why it cannot be assumed: **F198** — route-level
assumptions failing in practice — and **F209**, two pages sharing a feature gate
while serving very different surfaces for two years.

The good news, verified here rather than asserted: all 220 endpoints under
`api/superadmin/` already carry a role dependency. This test exists so the
221st cannot be added without one. Role gating that lives only in the SPA is
not gating, and a single endpoint added in a hurry is all it takes.

Scanned with `ast`, not a regex: the dependency appears in a default argument
value, which a line-oriented pattern reads inconsistently, and the nuclear
controls reach it through a *wrapper* dependency rather than naming the base
one — a narrower check reported those seven as unguarded when they are in fact
the most strictly guarded endpoints in the package.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SUPERADMIN_DIR = Path(__file__).resolve().parents[2] / "api" / "superadmin"

# Dependencies that establish superadmin identity, directly or by wrapping it.
# `require_superadmin_2fa` depends on `_require_superadmin` and additionally
# demands a TOTP-verified token — it is stricter, not looser.
GUARD_NAMES = ("_require_superadmin", "require_superadmin_2fa", "require_role")


def _route_functions():
    """Yield (file, function node) for every @router.<method> handler."""
    for path in sorted(SUPERADMIN_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorated = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "router"
                for d in node.decorator_list
            )
            if decorated:
                yield path.name, node


def test_the_scan_actually_finds_the_endpoints():
    """A scanner that matches nothing agrees with every assertion below. Assert
    the harness is live before asserting what it found."""
    found = list(_route_functions())
    assert len(found) > 150, f"the endpoint scan found only {len(found)} handlers — the pattern is wrong"


def test_every_superadmin_endpoint_requires_a_role():
    unguarded = []
    for filename, node in _route_functions():
        signature = ast.unparse(node.args)
        if not any(guard in signature for guard in GUARD_NAMES):
            unguarded.append(f"{filename}::{node.name}")

    assert not unguarded, (
        "superadmin endpoints with no server-side role dependency — a trader-role token reaches them:\n  "
        + "\n  ".join(unguarded)
    )


def test_the_nuclear_controls_additionally_require_2fa():
    """Halt, resume, hedge and risk-override move money or stop the platform.
    A stolen access token without a TOTP-verified claim must not reach them."""
    nuclear = [node for filename, node in _route_functions() if filename == "nuclear_controls.py"]
    assert nuclear, "nuclear_controls.py exposes no endpoints — has it moved?"

    for node in nuclear:
        signature = ast.unparse(node.args)
        assert "require_superadmin_2fa" in signature, (
            f"nuclear_controls::{node.name} does not require a 2FA-verified superadmin token"
        )


def test_model_mutating_ml_endpoints_additionally_require_2fa():
    """rollback_model bypasses quality gates and deploy_model force-promotes a
    version into live trading — both mutate the model actually deciding
    trades. A stolen access token without a TOTP-verified claim must not
    reach them, the same as nuclear_controls."""
    targets = {"rollback_model", "deploy_model"}
    found = {node.name: node for filename, node in _route_functions() if filename == "ml_ai.py" and node.name in targets}
    assert found.keys() == targets, f"expected to find {targets}, found {sorted(found)} — have they moved or been renamed?"

    for name, node in found.items():
        signature = ast.unparse(node.args)
        assert "require_superadmin_2fa" in signature, f"ml_ai::{name} does not require a 2FA-verified superadmin token"


def test_the_guard_rejects_a_token_without_two_factor():
    """The dependency itself, not just its presence in a signature."""
    from fastapi import HTTPException

    from api.superadmin._shared import require_superadmin_2fa

    class _User:
        two_factor_verified = False
        sub = "root"
        role = "superadmin"

    with pytest.raises(HTTPException) as excinfo:
        require_superadmin_2fa(user=_User())
    assert excinfo.value.status_code == 403


def test_the_guard_accepts_a_two_factor_verified_superadmin():
    """A gate that refuses everything is indistinguishable from a working one
    until somebody tries to use it."""
    from api.superadmin._shared import require_superadmin_2fa

    class _User:
        two_factor_verified = True
        sub = "root"
        role = "superadmin"

    assert require_superadmin_2fa(user=_User()) is not None
