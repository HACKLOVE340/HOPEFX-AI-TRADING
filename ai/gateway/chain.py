# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The model chain: which model answers, and which one answers when it cannot.

**Model identifiers are data, never code.** Every chain below is a *default*
written into config and editable by a superadmin at runtime. This is not a style
preference: the committed defaults still named `gpt-4o` and
`claude-3-5-sonnet-20241022` -- two 2024 models -- in September 2026, because
anything hard-coded in a module goes stale silently and needs a redeploy to fix.

Before this module the settings existed and did nothing. `llm_provider`,
`llm_model`, `llm_fallback_provider` and `llm_fallback_model` were declared in
the settings form, carried in PlatformConfigBody, defaulted in
api/superadmin/platform.py, round-tripped through the config store -- and read
by no runtime code at all. Backend selection happened in
`api/brain.py::_detect_llm_backend` from environment variables, which never
consults the store. A superadmin could set the primary and fallback model, save,
and change nothing.

The fallback did not exist as behaviour either: one provider failure became a
502 without a second leg being tried.

See docs/audit/plans/2026-09-05-ai-core.md Part 1A for the reasoning behind the
default ordering, including why the reasoning chain's second leg is a different
vendor rather than a cheaper model from the same one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainLeg:
    """One model in a role's ordered chain."""

    provider: str
    model: str

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("a chain leg needs both a provider and a model")


#: Ordered fallback chains per role. First entry is the primary.
#:
#: `reasoning`'s second leg is deliberately a different vendor. The tempting
#: choice is a cheaper model from the primary's own family -- same API, one-line
#: change -- but it shares that vendor's control plane, authentication and
#: status page, so in the incident a fallback exists for both legs fail together
#: and the fallback is decorative. Vendor diversity is what makes it real.
DEFAULT_CHAINS: Final[dict[str, tuple[ChainLeg, ...]]] = {
    "reasoning": (
        ChainLeg("anthropic", "claude-opus-5"),
        ChainLeg("openai", "gpt-5.5"),
        ChainLeg("google", "gemini-3.1-pro"),
    ),
    "fast": (
        ChainLeg("anthropic", "claude-sonnet-5"),
        ChainLeg("anthropic", "claude-haiku-4-5-20251001"),
        ChainLeg("google", "gemini-3.5-flash"),
    ),
    "vision": (
        ChainLeg("google", "gemini-3.5-flash"),
        ChainLeg("anthropic", "claude-opus-5"),
    ),
    "embedding": (
        ChainLeg("openai", "text-embedding-3-large"),
        ChainLeg("google", "gemini-embedding"),
    ),
}

#: Local inference is optional and never a primary. It joins a chain only when a
#: superadmin enables it, and then as the last leg -- or as the only leg under an
#: explicit local-only privacy mode for a deployment that must not egress
#: prompts. Capability drops sharply; the UI has to say so.
LOCAL_PROVIDER: Final = "ollama"

#: Reasons that mean "this leg could not answer" -- try the next one.
_TRANSPORT_FAILURES: Final[frozenset[str]] = frozenset(
    {
        "connection_error",
        "timeout",
        "rate_limited",
        "server_error",
        "overloaded",
        "provider_unavailable",
    }
)

#: Reasons that ARE an answer. Retrying these on another vendor does not get a
#: better result, it launders a failure into a different one -- and for a
#: guardrail rejection it actively defeats the guardrail.
_ANSWERS: Final[frozenset[str]] = frozenset(
    {
        "guardrail_rejected",
        "refusal",
        "budget_exceeded",
        "bad_request",
        "invalid_request",
        "content_filtered",
    }
)


def should_fall_through(reason: str) -> bool:
    """True when `reason` means the next leg should be tried.

    Unknown reasons do NOT fall through. A reason this module has not been
    taught is not evidence that retrying is safe, and silently retrying an
    unrecognised refusal on a second vendor is the failure mode this predicate
    exists to prevent.
    """
    normalised = (reason or "").strip().lower()
    if normalised in _ANSWERS:
        return False
    if normalised in _TRANSPORT_FAILURES:
        return True
    logger.warning("should_fall_through: unrecognised reason %r; refusing to fall through", reason)
    return False


def _stored_config() -> dict:
    """The platform config as stored, or {} when it cannot be read.

    Isolated so tests can substitute it, and so a config-store outage degrades
    to the committed defaults rather than to no model at all.
    """
    try:
        from api.superadmin.platform import _load_platform_config

        return _load_platform_config() or {}
    except Exception as exc:  # a config read must never be fatal here
        logger.warning("model chain: could not read stored config (%s); using defaults", exc)
        return {}


def resolve_chain(role: str) -> tuple[ChainLeg, ...]:
    """The ordered chain for `role`, honouring stored settings.

    An unknown role raises rather than silently resolving to something: picking
    a model for a caller who asked for a role nobody defined is exactly the kind
    of quiet default this module exists to remove.
    """
    if role not in DEFAULT_CHAINS:
        raise ValueError(f"unknown model role: {role!r}; expected one of {sorted(DEFAULT_CHAINS)}")

    legs = list(DEFAULT_CHAINS[role])
    if role != "reasoning":
        # Only the reasoning role is operator-configurable today; the settings
        # form exposes exactly one primary and one fallback.
        return tuple(legs)

    config = _stored_config()
    primary = _leg_from(config, "llm_provider", "llm_model")
    fallback = _leg_from(config, "llm_fallback_provider", "llm_fallback_model")

    if primary is not None:
        legs = [primary] + [leg for leg in legs if leg != primary]
    if fallback is not None:
        legs = [legs[0]] + [fallback] + [leg for leg in legs[1:] if leg != fallback]
    return tuple(legs)


def _leg_from(config: dict, provider_key: str, model_key: str) -> ChainLeg | None:
    provider = str(config.get(provider_key, "") or "").strip()
    model = str(config.get(model_key, "") or "").strip()
    if not provider or not model:
        return None
    return ChainLeg(provider, model)


def resolve_embedding_model() -> ChainLeg:
    """The embedding model, honouring `llm_embedding_model` when set."""
    config = _stored_config()
    model = str(config.get("llm_embedding_model", "") or "").strip()
    default = DEFAULT_CHAINS["embedding"][0]
    return ChainLeg(default.provider, model) if model else default


__all__ = [
    "DEFAULT_CHAINS",
    "LOCAL_PROVIDER",
    "ChainLeg",
    "resolve_chain",
    "resolve_embedding_model",
    "should_fall_through",
]
