# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The paths no AI-proposed change may touch, and why a config cannot lower them.

## The defect this file was written against

`SelfHealer.apply_config` REPLACED the protected-path list with whatever the
config supplied, and `HealingConfigBody.protected_paths` is a Pydantic field
defaulting to `""`. So the first time a superadmin saved the auto-healing
config from the dashboard without typing anything into that box, all thirty
protected paths were erased on the live healer — `risk/manager.py`,
`execution/engine.py`, `kill_switch.py`, `auth/jwt.py` — and became
auto-patchable by AI-generated code.

Reproduced before the fix, by execution:

    >>> h = SelfHealer(); h._is_protected("risk/manager.py")
    True
    >>> h.apply_config({"aggressiveness": "high"})
    >>> h._is_protected("risk/manager.py")
    False

## Why a floor, and not a longer default list

A longer default has the same shape: whatever sets it can unset it. The vault
is a FLOOR — configuration may add to it and can never subtract from it, so
there is no message, config file, Redis value or dashboard field that turns a
protected path into a patchable one.

## What the floor covers that the old list did not

The old list protected what the AI could break. It did not protect what the AI
could use to stop being stopped: the self-healer that verifies patch
signatures, the approval policy that requires two humans, the tool permission
registry, the constitutional invariants, the guardrails that fence untrusted
input — and the vault itself. A containment an AI can propose to widen is not
a containment.

These fail on the pre-fix tree: `ai.vault` does not exist there, and
`apply_config` erases the list.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── the floor cannot be lowered ───────────────────────────────────────────────


def test_a_config_that_does_not_mention_protected_paths_does_not_erase_them():
    """The exact live path: the dashboard's PUT sends the field's `""` default."""
    from security.self_healer import SelfHealer

    healer = SelfHealer()
    assert healer._is_protected("risk/manager.py")

    healer.apply_config({"aggressiveness": "high"})
    assert healer._is_protected("risk/manager.py"), "a config save erased the protected-path list"
    assert healer._is_protected("execution/engine.py")
    assert healer._is_protected("kill_switch.py")
    assert healer._is_protected("auth/jwt.py")


def test_an_explicit_empty_protected_paths_still_cannot_lower_the_floor():
    """Someone clearing the box on purpose is the same request, typed."""
    from security.self_healer import SelfHealer

    healer = SelfHealer()
    healer.apply_config({"protected_paths": ""})
    assert healer._is_protected("risk/manager.py")

    healer.apply_config({"protected_paths": ["something/else.py"]})
    assert healer._is_protected("risk/manager.py")
    assert healer._is_protected("something/else.py"), "configuration may still ADD paths"


def test_the_vault_protects_what_stops_the_ai_not_only_what_it_could_break():
    from ai.vault import protected

    for path in (
        "security/self_healer.py",
        "security/ai_repair_sandbox.py",
        "ai/policy/roles.py",
        "ai/guardrails/input.py",
        "ai/guardrails/output.py",
        "ai/tools/bus.py",
        "core/ai_tool_permissions.py",
        "api/security/fixes.py",
        "api/superadmin/auto_healing.py",
        "invariants/enforcement.py",
    ):
        assert protected.is_protected(path), f"{path} is not in the vault"


def test_the_vault_protects_the_vault():
    """A containment an AI can propose to widen is not a containment."""
    from ai.vault import protected

    assert protected.is_protected("ai/vault/protected.py")
    assert protected.is_protected("ai/vault/__init__.py")
    assert protected.is_protected("tests/unit/test_the_vault_holds_when_config_does_not.py")


def test_the_gates_that_prove_the_controls_work_are_protected():
    """A patch that edits the test is a patch that removes the control."""
    from ai.vault import protected

    assert protected.is_protected("tests/unit/test_ai_tool_bus.py")
    assert protected.is_protected(".github/workflows/ci.yml")
    assert protected.is_protected(".pre-commit-config.yaml")


# ── refusal is by path, before content ────────────────────────────────────────


def test_a_protected_path_is_refused_before_the_content_is_looked_at():
    """No amount of clean-looking diff makes a protected path allowable."""
    from ai.vault import protected

    verdict = protected.review("risk/manager.py", source="# a completely harmless comment\n")
    assert verdict.allowed is False
    assert "protected" in verdict.reason
    assert verdict.inspected_content is False, "content was inspected on a path that should never get that far"


def test_an_unprotected_path_is_allowed_and_says_the_content_still_has_to_pass():
    from ai.vault import protected

    verdict = protected.review("docs/notes.md", source="anything")
    assert verdict.allowed is True


# ── fail closed on anything that will not resolve ─────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "risk/../../etc/passwd",
        "/etc/passwd",
        "",
        "   ",
        "risk/manager.py\x00.txt",
    ],
)
def test_a_path_that_does_not_resolve_inside_the_repository_is_refused(path):
    """Every path-allowlist defect is this one: the unresolvable case defaulted
    to allowed, because the check was written for the paths somebody imagined."""
    from ai.vault import protected

    verdict = protected.review(path, source="x")
    assert verdict.allowed is False, f"{path!r} was allowed"
    assert verdict.reason, "a refusal always says why"


def test_a_symlink_pointing_out_of_the_tree_is_refused(tmp_path, monkeypatch):
    from ai.vault import protected

    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n")
    link = _ROOT / "docs" / "_vault_symlink_probe.py"
    try:
        link.symlink_to(outside)
        verdict = protected.review("docs/_vault_symlink_probe.py", source="x = 2\n")
        assert verdict.allowed is False
        assert "outside" in verdict.reason or "symlink" in verdict.reason
    finally:
        link.unlink(missing_ok=True)


# ── no way to turn it off ─────────────────────────────────────────────────────


def test_the_vault_reads_no_environment_variable():
    """`HEAL_ALLOW_UNSIGNED_PATCHES` is the right shape for a dev convenience.

    The vault has no equivalent, because an environment variable is precisely
    what an attacker who reached the host would set.
    """
    source = (_ROOT / "ai" / "vault" / "protected.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"getenv", "environ"}:
            pytest.fail(f"the vault reads the environment at line {node.lineno}")
        if isinstance(node, ast.Name) and node.id in {"getenv", "environ"}:
            pytest.fail(f"the vault reads the environment at line {node.lineno}")


def test_the_floor_is_immutable_at_the_python_level():
    """A module-level list would let any importer append or clear it."""
    from ai.vault import protected

    assert isinstance(protected.FLOOR, tuple)
    with pytest.raises((AttributeError, TypeError)):
        protected.FLOOR.append("x")  # type: ignore[attr-defined]


# ── the repair sandbox refuses before it validates ────────────────────────────


def test_the_repair_sandbox_refuses_a_protected_target_without_running_anything():
    from security.ai_repair_sandbox import validate_repair_for_target

    result = validate_repair_for_target("x = 1\n", target_path="risk/manager.py")
    assert result.accepted is False
    assert any("protected" in code for code in result.reason_codes), result.reason_codes


def test_the_repair_sandbox_still_validates_content_on_an_unprotected_target():
    from security.ai_repair_sandbox import validate_repair_for_target

    bad = validate_repair_for_target("import os\n", target_path="scratch/thing.py")
    assert bad.accepted is False
    assert any("banned_import" in code for code in bad.reason_codes), bad.reason_codes


# ── the healer's own gate consults the floor ──────────────────────────────────


def test_the_healer_protects_the_floor_even_for_a_path_not_in_its_own_list():
    from security.self_healer import SelfHealer

    healer = SelfHealer()
    assert healer._is_protected("security/self_healer.py"), (
        "the healer would auto-patch the module that verifies patch signatures"
    )
    assert healer._is_protected("ai/policy/roles.py"), "the healer would auto-patch the policy requiring two approvers"


# ── the registry ──────────────────────────────────────────────────────────────


def test_the_vault_rows_are_live_and_filed_outside_the_specification():
    """Section "S", not §28.

    These rows are an owner request from 2026-09-07. The specification never
    named them, and filing them under a number would claim it did.
    """
    from ai.hub import capabilities

    assert capabilities.verify().discrepancies == ()

    rows = {c.id: c for c in capabilities.by_section("S")}
    assert rows, "the owner-requested track is not in the registry at all"
    for row in ("improve.vault", "improve.path_before_content", "improve.sandbox_target_check"):
        assert rows[row].state == "live", f"{row} is {rows[row].state}"

    # The rest of the track is named and not yet built, which is the whole
    # point of a registry: a capability absent from it does not exist.
    for row in (
        "improve.code_walker",
        "improve.finding_to_proposal",
        "improve.always_awake",
        "improve.honest_cycle_report",
    ):
        assert rows[row].state == "planned"
        assert rows[row].evidence == "", "a planned row carrying evidence reads as progress"
