# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Paths that no AI-originated change may modify, whatever the approval says.

## The defect this exists to close

`SelfHealer` kept thirty protected paths and `apply_config` REPLACED that list
with whatever the config supplied. `HealingConfigBody.protected_paths` is a
Pydantic field defaulting to `""`. So the first save of the auto-healing config
from the superadmin dashboard — with the protected-paths box left as it comes,
which is empty — erased all thirty on the live healer. Measured, not inferred:

    >>> h = SelfHealer(); h._is_protected("risk/manager.py")
    True
    >>> h.apply_config({"aggressiveness": "high"})
    >>> h._is_protected("risk/manager.py")
    False

`risk/manager.py`, `execution/engine.py`, `kill_switch.py` and `auth/jwt.py`
were then auto-patchable by AI-generated code.

## Why a floor rather than a better default

A default is a value, and whatever sets a value can unset it. A floor is not
overridable by construction: `apply_config` may ADD paths and the floor is
consulted regardless, so no config file, Redis value, dashboard field or model
output turns a protected path into a patchable one.

There is also no environment variable here, deliberately. `HEAL_ALLOW_UNSIGNED_PATCHES`
is the right shape for a development convenience; a switch that disables the
containment is a different thing, and an environment variable is precisely what
an attacker who reached the host would set. A test parses this module and fails
if it ever reads the environment.

## What the floor covers that the old list did not

The old list protected what the AI could break: brokers, risk, execution, auth.
It did not protect what the AI could use to **stop being stopped** — the
self-healer that verifies patch signatures, the policy requiring two approvers
one of whom is a superadmin, the tool permission registry, the constitutional
invariants, the guardrails that fence untrusted input, the CI that runs the
tests, the tests themselves, and this module.

A containment an AI can propose to widen is not a containment.

## Refusal is by path, and it happens first

`review()` decides on the path before anything looks at the content, and says
so: `Verdict.inspected_content` is False on a protected path. A content check
that ran first could, in principle, be talked into a verdict; a path check
cannot be, because it never reads the argument that carries the persuasion.

## Fail closed on anything that will not resolve

A traversal, an absolute path, a NUL byte, a symlink leaving the tree, an empty
string: all REFUSED. Every path-allowlist defect in the wild is the same one —
the unresolvable case fell through to allowed, because the check was written
for the paths somebody had imagined.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Final

#: Repository root. Resolved once, from this file's own location, so it does
#: not depend on the working directory of whatever is asking.
_ROOT: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[2]

#: A tuple, not a list: a module-level list is appendable and clearable by any
#: importer, which would make the floor exactly as overridable as the default
#: it replaces.
#:
#: An entry ending in `/` is a directory prefix; anything else matches the exact
#: relative path. Both are matched against a repo-relative POSIX path.
FLOOR: Final[tuple[str, ...]] = (
    # ── what the AI could break ───────────────────────────────────────────────
    # Live-trading execution.
    "live_trading.py",
    "hopefx_engine.py",
    "run.py",
    "app.py",
    "execution/",
    "brokers/",
    "kill_switch.py",
    # Risk, sizing, and the gates that refuse a trade.
    "risk/",
    "risk_manager.py",
    "core/live_trading_gate.py",
    "core/decision/",
    "resilience/service_circuit_breakers.py",
    # Credentials and sessions.
    "auth/",
    "core/security/",
    "security/",
    # Model artifacts and inference gating.
    "ml/models/",
    "ml/saved_models/",
    "ml/rl_models/",
    "ml/inference_engine.py",
    "ml/registry.py",
    "config/secrets/",
    "data_feed/engine.py",
    # ── what the AI could use to stop being stopped ───────────────────────────
    # The containment itself.
    "ai/vault/",
    # The gates every agent action passes.
    "ai/tools/bus.py",
    "ai/policy/",
    "ai/guardrails/",
    "core/ai_tool_permissions.py",
    "invariants/",
    # The bus, because a message path that could be rewritten becomes one.
    "ai/bus/",
    # The approval surface: who may approve, and what is queued for approval.
    "api/security/",
    "api/superadmin/",
    "api/auth.py",
    "api/ai_control_plane.py",
    # The registry that reports what is built, and its evidence resolver.
    "ai/hub/capabilities.py",
    # ── what proves any of the above still works ──────────────────────────────
    "tests/",
    "conftest.py",
    "pytest.ini",
    ".github/",
    ".pre-commit-config.yaml",
    ".secrets.baseline",
    "requirements.txt",
    "requirements-ci.txt",
    "Dockerfile",
    "pyproject.toml",
)


@dataclass(frozen=True)
class Verdict:
    """Whether a change to one path may proceed, and why.

    `inspected_content` records whether the content was looked at, so a test can
    assert the ordering rather than trust it.
    """

    allowed: bool
    reason: str = ""
    inspected_content: bool = False


def _relative(path: str) -> str | None:
    """A repo-relative POSIX path, or None if it will not resolve inside the tree.

    None is the fail-closed answer, and every caller treats it as refusal.
    """
    if not isinstance(path, str):
        return None
    candidate = path.strip()
    if not candidate:
        return None
    if "\x00" in candidate:
        return None

    raw = pathlib.Path(candidate)
    if raw.is_absolute():
        # An absolute path inside the tree is still expressible; anything else
        # is out of scope by definition.
        try:
            resolved = raw.resolve()
        except (OSError, RuntimeError):
            return None
    else:
        try:
            resolved = (_ROOT / raw).resolve()
        except (OSError, RuntimeError):
            return None

    try:
        relative = resolved.relative_to(_ROOT)
    except ValueError:
        # Traversal, or a symlink whose target lives outside the repository.
        return None
    return relative.as_posix()


def is_protected(path: str) -> bool:
    """Whether `path` is in the vault.

    A path that will not resolve inside the repository counts as protected: the
    only safe answer for something this module cannot identify.
    """
    relative = _relative(path)
    if relative is None:
        return True
    for entry in FLOOR:
        if entry.endswith("/"):
            if relative == entry.rstrip("/") or relative.startswith(entry):
                return True
        elif relative == entry:
            return True
    return False


def review(path: str, *, source: str = "") -> Verdict:
    """Decide on `path` BEFORE anything reads `source`.

    `source` is accepted so callers have one call site rather than two, and is
    deliberately never read on a refusal — `inspected_content` says which
    happened.
    """
    relative = _relative(path)
    if relative is None:
        return Verdict(
            allowed=False,
            reason=(
                f"refused: {path!r} does not resolve to a file inside the repository "
                "(traversal, absolute path, or a symlink leaving the tree)"
            ),
        )
    if is_protected(relative):
        return Verdict(
            allowed=False,
            reason=(
                f"refused: {relative} is protected — no AI-originated change may modify it, "
                "and no configuration or approval can lower that"
            ),
        )
    return Verdict(
        allowed=True,
        reason=f"{relative} is not in the vault; its content still has to pass every other gate",
        inspected_content=bool(source),
    )


def floor_for(existing: tuple[str, ...] | list[str] | None = None) -> tuple[str, ...]:
    """The floor, plus whatever `existing` adds. Never less than the floor.

    This is the shape `SelfHealer.apply_config` uses: configuration contributes
    additions and cannot subtract.
    """
    extra = tuple(p.strip() for p in (existing or ()) if isinstance(p, str) and p.strip())
    return FLOOR + tuple(p for p in extra if p not in FLOOR)
