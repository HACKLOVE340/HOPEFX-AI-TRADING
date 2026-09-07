# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Vision — §11's vision agent: shown a picture, never sent to take one.

`ai/vision/detect.py:interpret` has existed since the vision endpoint landed.
What was missing is an agent that can be asked about an image from within
`ai/agent/loop.py` — and the reason it was left staged rather than wired
immediately is the distinction this module is built around.

## Being shown a frame and going to get one are different acts

An operator handing over a screenshot has decided to. A camera opened on their
behalf, by a model deciding mid-loop that a look would help, is a camera opened
on a trading desk by something nobody instructed. §25's consent gate exists for
the second case, and this department has no path to it at all: `describe_image`
takes the images as an argument, and nothing reachable from this module can
capture one. `tests/unit/test_departments_cluster_c.py` asserts that by parsing
the file, because a module that explains what it must not do contains the words
it must not call.

## Consent is checked before the pixels are read, not after

The order matters and is tested separately. Checking after decoding means the
frame is already in this process when the refusal is written — the refusal is
then a record of something that already happened. `api/safe_agent_platform.py`
had this exact inversion and it was moved for the same reason.

Camera consent gates this even though the operator supplied the image, because
the operator supplying one frame is not standing consent for a model to read
every frame it is handed for the rest of the session.

## Everything is READ_ONLY

`vision_status` returns booleans about configuration and consent. It never
returns a key, a URL with a token in it, or a base64 frame — an agent output
travels into a model prompt and into an audit record, and both are places a
frame of somebody's desk should not end up.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The sensor §25 knows this by. Named once so a typo cannot silently check a
#: sensor that does not exist and be granted by default.
SENSOR = "camera"


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def describe_image(*, operator: str, images: tuple[Any, ...] = (), hint: str = "", **_: Any) -> dict[str, Any]:
    """Interpret images the caller supplies. Never captures anything.

    `images` is a required argument in practice: an empty tuple is refused
    rather than treated as a cue to go and find one.
    """
    from ai.privacy import consent

    # Before the images are touched. See the module docstring.
    decision = consent.check(operator, SENSOR)
    if not decision.allowed:
        return _unavailable(
            f"camera consent is not held for {operator}: {decision.reason or 'it has not been granted'}",
        )

    supplied = tuple(images or ())
    if not supplied:
        return _unavailable(
            "no image was supplied; this agent interprets a frame it is given and cannot capture one",
        )

    try:
        from ai.vision.detect import interpret

        detection = interpret(supplied, operator=operator, hint=hint)
    except Exception as exc:
        logger.warning("vision_ops: interpretation failed: %s", exc)
        return _unavailable(f"the image could not be interpreted: {type(exc).__name__}: {exc}")

    return {"available": True, "detection": detection}


def vision_status(*, operator: str, **_: Any) -> dict[str, Any]:
    """Whether vision can run at all, and whether consent is held. Booleans only."""
    configured = False
    reason = ""
    try:
        from ai.gateway.adapters import build_providers

        configured = bool(build_providers())
    except Exception as exc:
        reason = f"vendor configuration could not be read: {type(exc).__name__}"

    granted = False
    consent_reason = ""
    try:
        from ai.privacy import consent

        decision = consent.check(operator, SENSOR)
        granted = bool(decision.allowed)
        consent_reason = decision.reason or ""
    except Exception as exc:  # pragma: no cover - consent never raises by design
        consent_reason = f"consent could not be read: {type(exc).__name__}"

    return {
        "available": True,
        "vendor_configured": configured,
        "vendor_reason": reason,
        "camera_consent": granted,
        "consent_reason": consent_reason,
        # Stated rather than left to be inferred from the two booleans above,
        # because "we could run but you have not agreed" and "you agreed but
        # nothing is configured" need different next moves from the operator.
        "can_interpret": configured and granted,
    }


__all__ = ["SENSOR", "describe_image", "vision_status"]
