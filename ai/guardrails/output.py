# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Output validation between a model and any action it might cause.

Generalised from `news/geopolitical_llm.py` (audit F261), which established the
two rules that matter:

**Validate, never coerce.** A response the model did not produce in the
requested shape is a FAILED extraction, and the caller's fallback to a
deterministic answer is the safe result -- not a number squeezed out of whatever
came back. `"7"` must not quietly become `7`, because a model that returned a
string when asked for a number has not answered the question, and treating it as
though it had is how an unreliable reading reaches a decision.

**An uncorroborated claim gets a ceiling.** A model may not on its own reach a
tier at which the platform acts. When a deterministic source independently
agrees, the ceiling rises to meet it -- so sensitivity is not lost, and the cap
binds only when nothing corroborates.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class GuardrailViolation(RuntimeError):
    """Model output failed validation. Never fall back to another vendor for this.

    A guardrail rejection is an ANSWER, not a transport failure: retrying it on
    a second provider does not get a better result, it defeats the guardrail.
    `ai.gateway.chain.should_fall_through` encodes that.
    """


def validate_output(
    raw: str,
    *,
    required: dict[str, tuple[type, ...]] | None = None,
    ranges: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Parse `raw` into a dict, or raise GuardrailViolation.

    `required` maps a field name to the types it may be. `ranges` maps a numeric
    field to its inclusive bounds. Both are checked without coercion.
    """
    text = _FENCE.sub("", (raw or "").strip()).strip()
    match = _OBJECT.search(text)
    if not match:
        raise GuardrailViolation("no JSON object in model output")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise GuardrailViolation(f"model output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GuardrailViolation("model output is not a JSON object")

    for field, types in (required or {}).items():
        if field not in data:
            raise GuardrailViolation(f"model output missing required field {field!r}")
        value = data[field]
        # bool is a subclass of int in Python, so `True` would satisfy a numeric
        # check and read as severity 1. It is not a number the model chose.
        if isinstance(value, bool) and bool not in types:
            raise GuardrailViolation(f"field {field!r} is a boolean, not {types}")
        if not isinstance(value, types):
            raise GuardrailViolation(
                f"field {field!r} is {type(value).__name__}, not one of {[t.__name__ for t in types]} -- not coercing"
            )

    for field, (low, high) in (ranges or {}).items():
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, (int, float)) or not (low <= float(value) <= high):
            raise GuardrailViolation(f"field {field!r} out of range [{low}, {high}]: {value!r}")

    return data


def bounded_severity(*, model_value: float, corroborated_value: float, ceiling: float) -> tuple[float, bool]:
    """Cap an uncorroborated model claim. Returns (value, was_capped).

    The ceiling is the last tier at which the platform takes NO action. Above it
    a deterministic source must independently agree -- and when it does, the
    ceiling rises to that value, so a real event still acts at full strength.
    A corroborated value is never lowered.
    """
    effective_ceiling = max(ceiling, corroborated_value)
    if model_value > effective_ceiling:
        return effective_ceiling, True
    return max(model_value, corroborated_value), False


__all__ = ["GuardrailViolation", "bounded_severity", "validate_output"]
