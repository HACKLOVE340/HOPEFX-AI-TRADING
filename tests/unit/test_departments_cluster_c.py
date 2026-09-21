# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Phase H3 — §11's last three agents: system, vision and memory.

Two were staged with the same note shape — the capability exists, "it is not
yet an agent on the bus" — and one was planned outright. Cluster B established
what an agent is here: a department in one table that drives the directory, the
permission registry and the bus registration together, with actions that can be
*asked* things.

## Why every action in this cluster is READ_ONLY, and why that is not the
## starting point it looks like

Cluster B's docstring already says it for voice and notification: an agent that
could synthesise on its own initiative can talk to somebody who did not ask it
to, and an agent that could notify is a spam generator with a review process.

Both of those are louder versions of the two refusals this cluster turns on:

* **The vision agent may be shown a picture. It may not go and take one.**
  Opening a camera on an operator's own initiative-free behalf is a different
  act from interpreting a frame they handed over, and §25's consent gate is
  about the first. So `describe_image` takes images as an argument, checks
  consent before decoding them, and there is no path from this department to a
  capture — asserted structurally below, not promised in a docstring.

* **The memory agent may read and may not forget.** §16's right to be
  forgotten is an operator's right, not an agent's capability. An agent that
  could call `governance.forget` is a memory hole with a permission tier, and
  the operator whose history it erased would have no way to know it happened.

Both are checked by parsing the modules, the way `ai/bus/` and `ai/improve/`
are, because a module that discusses what it must not do contains the words it
must not call.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from ai import departments
from core.ai_tool_permissions import ToolRisk

CLUSTER_C = ("system_ops", "vision_ops", "memory_ops")

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _module(name: str) -> ast.Module:
    return ast.parse((_ROOT / "ai" / "departments" / f"{name}.py").read_text(encoding="utf-8"))


def _called_names(tree: ast.Module) -> set[str]:
    """Every dotted name that appears in a call position."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        parts: list[str] = []
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        if parts:
            found.add(".".join(reversed(parts)))
    return found


def _imported_modules(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


class TestTheyExistAsDepartments:
    def test_all_three_are_registered(self) -> None:
        for key in CLUSTER_C:
            assert key in departments.DEPARTMENTS, f"{key} is not in the department table"

    def test_every_action_is_read_only(self) -> None:
        # See the module docstring. This is the whole cluster's safety property,
        # and a single non-read-only action added later fails here rather than
        # shipping.
        for key in CLUSTER_C:
            for action in departments.DEPARTMENTS[key].actions:
                assert action.risk is ToolRisk.READ_ONLY, f"{key}.{action.name} is {action.risk}, not READ_ONLY"

    def test_every_action_has_a_handler(self) -> None:
        # Cluster A deliberately declares two unimplemented actions. This
        # cluster declares none: every action here is answerable today, so a
        # missing handler would be an omission rather than a decision.
        for key in CLUSTER_C:
            for action in departments.DEPARTMENTS[key].actions:
                assert action.handler is not None, f"{key}.{action.name} has no handler"

    def test_each_action_is_permitted(self) -> None:
        registry = departments.permission_registry()
        for key in CLUSTER_C:
            for action in departments.DEPARTMENTS[key].actions:
                review = registry.review(action.name)
                assert review.allowed, f"{action.name} is callable and refused: {review.reason}"


class TestTheVisionAgentCannotTakeAPicture:
    def test_it_names_no_capture_api(self) -> None:
        tree = _module("vision_ops")
        called = _called_names(tree)
        imported = _imported_modules(tree)
        forbidden_calls = {"cv2.VideoCapture", "VideoCapture", "getUserMedia", "picamera.PiCamera"}
        assert not (called & forbidden_calls), f"vision_ops calls a capture API: {called & forbidden_calls}"
        forbidden_imports = {"cv2", "picamera", "imageio"}
        assert not (imported & forbidden_imports), f"vision_ops imports {imported & forbidden_imports}"

    def test_describe_image_refuses_without_consent(self) -> None:
        from ai.privacy import consent
        from ai.departments import vision_ops

        consent.reset_for_testing()
        out = vision_ops.describe_image(operator="alice", images=("data:image/png;base64,AAA",))
        assert out["available"] is False
        assert "consent" in out["reason"].lower()

    def test_it_checks_consent_before_it_touches_the_image(self) -> None:
        # Order matters and is the reason this is a separate test: decoding
        # first and checking second means the frame has already been read into
        # this process by the time the refusal is written.
        from ai.departments import vision_ops

        source = (_ROOT / "ai" / "departments" / "vision_ops.py").read_text(encoding="utf-8")
        body = source[source.index("def describe_image") :]
        consent_at = body.index("consent.check")
        # `interpret` is the only thing here that reads the pixels.
        interpret_at = body.index("interpret(")
        assert consent_at < interpret_at, "describe_image reads the image before it checks consent"
        assert vision_ops.describe_image is not None

    def test_vision_status_reports_configuration_without_leaking_keys(self) -> None:
        from ai.departments import vision_ops

        out = vision_ops.vision_status(operator="alice")
        rendered = repr(out)
        assert "sk-" not in rendered
        for value in out.values():
            assert not isinstance(value, str) or len(value) < 400


class TestTheMemoryAgentCannotForget:
    def test_it_calls_nothing_that_erases(self) -> None:
        tree = _module("memory_ops")
        called = _called_names(tree)
        erasers = {
            "forget",
            "governance.forget",
            "tiers.forget_operator",
            "forget_operator",
            "revoke_all",
            "store.reset_for_testing",
            "end_session",
            "correct",
        }
        assert not (called & erasers), f"memory_ops calls something that erases or edits: {called & erasers}"

    def test_it_declares_no_action_whose_name_promises_a_write(self) -> None:
        names = {a.name for a in departments.DEPARTMENTS["memory_ops"].actions}
        for name in names:
            assert not any(verb in name for verb in ("forget", "delete", "erase", "write", "correct", "approve")), (
                f"{name} names a write in a read-only department"
            )

    def test_recall_is_scoped_to_the_operator_who_asked(self) -> None:
        # The precedent is a P0 in `ai/jobs/runner.py`: one operator's prompt
        # reaching another operator's screen. Recall is the same shape with a
        # longer memory.
        from ai.memory import tiers
        from ai.departments import memory_ops

        tiers.reset_for_testing()
        tiers.remember("session", operator="alice", kind="note", value="alice's secret", source="test")
        tiers.remember("session", operator="bob", kind="note", value="bob's secret", source="test")

        out = memory_ops.recall_memory(operator="alice")
        rendered = repr(out)
        assert "alice's secret" in rendered
        assert "bob's secret" not in rendered

    def test_describe_retention_says_how_to_be_forgotten_without_doing_it(self) -> None:
        from ai.memory import tiers
        from ai.departments import memory_ops

        tiers.reset_for_testing()
        tiers.remember("session", operator="alice", kind="note", value="kept", source="test")
        out = memory_ops.describe_retention(operator="alice")
        assert "forget" in repr(out).lower()
        # Still there. Describing the right is not exercising it.
        assert tiers.recall("session", operator="alice")


class TestTheSystemAgentReportsWhatWasMeasured:
    def test_host_resources_keeps_an_unmeasured_reading_unmeasured(self) -> None:
        # §22's rule, and the one F176 lost: an absent number must not arrive as
        # a zero. The agent must not flatten the Reading into a bare float.
        from ai.departments import system_ops

        out = system_ops.host_resources(operator="alice")
        assert "readings" in out
        for name, reading in out["readings"].items():
            assert "measured" in reading, f"{name} lost its measured flag"
            if not reading["measured"]:
                assert reading["value"] is None, f"{name} is unmeasured and carries a value"
                assert reading["reason"], f"{name} is unmeasured with no reason"

    def test_it_names_what_it_could_not_measure_separately(self) -> None:
        from ai.departments import system_ops

        out = system_ops.host_resources(operator="alice")
        assert "unmeasured" in out, "a caller should not have to infer absence from the readings"

    def test_service_health_reports_reachability_without_keys(self) -> None:
        from ai.departments import system_ops

        out = system_ops.service_health(operator="alice")
        rendered = repr(out)
        assert "sk-" not in rendered and "api_key" not in rendered

    def test_recent_failures_distinguishes_none_from_unknown(self) -> None:
        # "No failures" and "nobody counted" are different facts, and one value
        # for both hides the second — the same distinction `Delivery.fanout`
        # and `Reading.measured` already make.
        from ai.departments import system_ops

        out = system_ops.recent_failures(operator="alice")
        assert "measured" in out or "unmeasured" in out


class TestTheDirectoryStaysHonest:
    def test_the_permission_version_moved_with_the_action_set(self) -> None:
        # Three new departments' worth of actions is exactly the change an
        # unversioned permission set cannot be audited across.
        assert "cluster-c" in departments.PERMISSIONS_VERSION

    @pytest.mark.parametrize("key", CLUSTER_C)
    def test_each_says_what_it_is_for(self, key: str) -> None:
        department = departments.DEPARTMENTS[key]
        assert department.title
        assert department.status
        assert department.agents
        for action in department.actions:
            assert action.summary, f"{key}.{action.name} has no summary"
