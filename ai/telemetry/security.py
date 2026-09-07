# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Security events, counted from the controls that produced them. §22.

**Zero denials and no audit trail are different, and one of them is
reassuring.** A refusal count of 0 with no tool bus attached says "nothing has
been refused"; what is true is "nothing was watching". So an absent source is
reported as absent, with the reason, exactly like a host metric whose probe
could not run.

Counted from the live objects rather than from a separate ledger: a second
tally beside the audit trail is free to drift from it, and the drift would be
in the direction of looking calmer than the system is.
"""

from __future__ import annotations

from typing import Any

from ai.telemetry.reading import absent, measured


def security_events(*, tool_bus: Any = None) -> dict[str, Any]:
    """Refusals at the tool layer, and whether the output guardrail is armed."""
    return {
        "tool_denials": _tool_denials(tool_bus),
        "output_guardrail": _output_guardrail(),
    }


def _tool_denials(tool_bus: Any) -> dict[str, Any]:
    if tool_bus is None:
        return absent(
            "tool_denials",
            "no tool bus was provided, so refusals were not counted; zero denials and no audit trail "
            "are different facts and only one of them is reassuring",
        ).as_dict()
    try:
        audit = tool_bus.audit()
    except Exception as exc:
        return absent("tool_denials", f"the audit trail could not be read: {type(exc).__name__}: {exc}").as_dict()
    denied = sum(1 for entry in audit if not entry.get("allowed", True))
    return measured("tool_denials", float(denied)).as_dict()


def _output_guardrail() -> dict[str, Any]:
    """Whether the credential scanner has anything registered to look for.

    Reported as a count rather than a boolean: the shape-based patterns always
    run, and this number is the additional, deployment-specific values it has
    been told about. Zero is a real and meaningful answer here.
    """
    from ai.guardrails.output import known_secret_count

    return measured("registered_credentials", float(known_secret_count())).as_dict()


__all__ = ["security_events"]
