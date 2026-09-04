# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
`.env.example` must not contradict a deliberate code default.

`scripts/bootstrap_dev.py` generates `.env` from `.env.example`, so a flag
enabled in the template is enabled for every developer and every fresh
deployment.

`FEATURE_ONLINE_LEARNING` had `default=False` in `config/feature_flags.py` and
`=true` in the template (F215). Its own description reads: *"Gate: 90-day paper
run (any supported broker) with >= 500 fills. Enable with
FEATURE_ONLINE_LEARNING=true after gate passes."* So the template shipped every
deployment in the exact state the flag forbids, with unvalidated online learning
blended into live signals.

Stated narrowly on purpose. Six EXPERIMENTAL flags are enabled in the template;
five have `default=True` in code and agree with it. "Six experimental flags are
on" would have been alarming and wrong. One contradicts a deliberate `False`,
and it is the consequential one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / ".env.example"

#: Flags the template may set differently from the code default, each with a
#: written reason.
#:
#: The two directions are not equally dangerous, and the distinction is the
#: whole point of this file. Turning something ON that the code defaults OFF
#: ships every deployment past a decision someone made deliberately — that is
#: F215. Turning something OFF that the code defaults ON is conservative: a
#: developer template that does not enable billing or payments is doing the
#: right thing.
#:
#: These three are the conservative direction. They are listed rather than
#: silently permitted so the list stays reviewable.
_DELIBERATE_OVERRIDES: dict[str, str] = {
    "FEATURE_BILLING_SUBSCRIPTION": (
        "Template disables what the code enables — the safe direction. A fresh "
        "developer environment should not start with subscription billing live."
    ),
    "FEATURE_PAYMENTS": (
        "Template disables what the code enables — the safe direction. Payments "
        "off by default in a generated .env avoids a dev environment touching "
        "real payment rails."
    ),
    "FEATURE_GRAPHQL_API": (
        "Template disables what the code enables — the safe direction. Reduces "
        "the surface a fresh deployment exposes without being asked to."
    ),
}

_LINE = re.compile(r"^\s*(FEATURE_[A-Z0-9_]+)\s*=\s*([^#\s]+)", re.MULTILINE)


def _truthy(text: str) -> bool:
    return text.strip().strip("\"'").lower() in ("1", "true", "yes", "on")


def _template_flags() -> dict[str, bool]:
    if not _TEMPLATE.exists():
        pytest.skip(".env.example not found")
    return {m.group(1): _truthy(m.group(2)) for m in _LINE.finditer(_TEMPLATE.read_text(encoding="utf-8"))}


def _code_defaults() -> dict[str, bool]:
    """Read the defaults through the flags object's own registry().

    The descriptors live on the class, and getattr() would invoke ``__get__``
    and hand back the *current* boolean rather than the declared default.
    registry() exists precisely to expose the raw metadata.
    """
    from config.feature_flags import flags

    return {
        meta["env_var"]: bool(meta["default"])
        for meta in flags.registry().values()
        if str(meta.get("env_var", "")).startswith("FEATURE_")
    }


def test_the_template_sets_flags_this_test_can_read():
    """Guard the guard: a regex that matches nothing would pass everything."""
    assert _template_flags(), ".env.example has no FEATURE_* lines — the pattern is wrong"


def test_the_code_defines_flags_this_test_can_read():
    assert _code_defaults(), "no _FeatureDef with a FEATURE_* env_var was found"


def test_no_template_flag_contradicts_its_code_default():
    template = _template_flags()
    defaults = _code_defaults()

    contradictions = [
        f"{name}: code default={defaults[name]} but .env.example={template[name]}"
        for name in sorted(template)
        if name in defaults and template[name] != defaults[name] and name not in _DELIBERATE_OVERRIDES
    ]

    # The dangerous direction, checked separately and never exemptible: a
    # template that ENABLES what the code disables walks every deployment past a
    # deliberate decision. An exemption here would defeat the file.
    enabled_beyond_code = [
        name
        for name in sorted(template)
        if name in defaults and template[name] and not defaults[name]
    ]
    assert not enabled_beyond_code, (
        "The template ENABLES flags the code deliberately defaults to False. This "
        "is the F215 shape and is never exemptible:\n  " + "\n  ".join(enabled_beyond_code)
    )

    assert not contradictions, (
        "The template ships a state the code deliberately rejects. bootstrap_dev.py "
        "generates .env from this file, so every fresh deployment inherits it:\n  "
        + "\n  ".join(contradictions)
    )


def test_online_learning_is_off_in_the_template():
    """Named explicitly: this is the one that was wrong, and it is gated on a
    90-day paper run with 500 fills."""
    assert _template_flags().get("FEATURE_ONLINE_LEARNING") is False


def test_every_override_has_a_reason():
    """An exception without a written justification is a loophole."""
    for name, reason in _DELIBERATE_OVERRIDES.items():
        assert reason.strip(), f"{name} is exempted with no reason given"
