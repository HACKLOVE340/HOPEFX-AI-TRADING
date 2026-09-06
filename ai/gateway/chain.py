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
        # An adapter bug, not a vendor's answer. Listed explicitly rather than
        # left unknown because `GatewayClient` already advances to the next leg
        # when an adapter raises an unexpected exception -- without this row the
        # same bug halted the chain when it arrived as a ProviderError and
        # continued it when it arrived raw, which is two behaviours for one
        # fault.
        "adapter_error",
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


DEFAULT_LOCAL_MODEL: Final = "llama3"


def _configured_legs(config: dict, role: str) -> list[ChainLeg] | None:
    """The ordered chain a superadmin saved for `role`, or None.

    Returns None -- not an empty list -- for anything malformed, so the caller
    degrades to the committed default rather than to no model at all. An editor
    that can produce a chain with no legs is an editor that can take the AI
    offline through a typo.
    """
    raw = config.get("llm_chain")
    if not isinstance(raw, dict):
        if raw not in (None, "", {}):
            logger.warning("model chain: llm_chain is not a mapping (%r); ignoring it", type(raw).__name__)
        return None

    entries = raw.get(role)
    if entries is None:
        return None
    if not isinstance(entries, list) or not entries:
        logger.warning("model chain: llm_chain[%r] is empty or not a list; using the default chain", role)
        return None

    legs: list[ChainLeg] = []
    for entry in entries:
        if not isinstance(entry, dict):
            logger.warning("model chain: llm_chain[%r] holds a non-object leg; using the default chain", role)
            return None
        try:
            legs.append(ChainLeg(str(entry.get("provider", "")), str(entry.get("model", ""))))
        except ValueError as exc:
            logger.warning("model chain: llm_chain[%r] has an invalid leg (%s); using the default chain", role, exc)
            return None
    return legs


def _local_leg(config: dict) -> ChainLeg:
    """The optional on-hardware leg. Its identifier is configurable; its position is not."""
    model = str(config.get("llm_local_model", "") or "").strip() or DEFAULT_LOCAL_MODEL
    return ChainLeg(LOCAL_PROVIDER, model)


def _truthy(value: object) -> bool:
    """Config arrives from JSON, a form, or an env var; "false" is not True."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def resolve_chain(role: str) -> tuple[ChainLeg, ...]:
    """The ordered chain for `role`, honouring stored settings.

    An unknown role raises rather than silently resolving to something: picking
    a model for a caller who asked for a role nobody defined is exactly the kind
    of quiet default this module exists to remove.

    Precedence, most specific first:

    1. `llm_local_only` -- the privacy mode. A ceiling, not a preference: it
       overrides an explicitly configured hosted chain, because a deployment
       that must not egress prompts must not egress them by way of a setting
       somebody else edited.
    2. `llm_chain[role]` -- the ordered per-role editor (plan Task 14).
    3. `llm_provider`/`llm_model` and `llm_fallback_*` -- the original two
       fields, which apply to `reasoning` only. Kept working because they are
       what D8's fix bound, and a superadmin's saved settings must not stop
       taking effect because a newer field exists.
    4. The committed defaults.

    `llm_local_enabled` then appends the local leg LAST, never first.
    """
    if role not in DEFAULT_CHAINS:
        raise ValueError(f"unknown model role: {role!r}; expected one of {sorted(DEFAULT_CHAINS)}")

    config = _stored_config()

    if _truthy(config.get("llm_local_only")):
        # No hosted leg at all -- not even as a fallback, which would egress
        # exactly when the operator is least watching.
        return (_local_leg(config),)

    legs = _configured_legs(config, role)
    if legs is None:
        legs = list(DEFAULT_CHAINS[role])
        if role == "reasoning":
            primary = _leg_from(config, "llm_provider", "llm_model")
            fallback = _leg_from(config, "llm_fallback_provider", "llm_fallback_model")
            if primary is not None:
                legs = [primary] + [leg for leg in legs if leg != primary]
            if fallback is not None:
                legs = [legs[0]] + [fallback] + [leg for leg in legs[1:] if leg != fallback]

    if _truthy(config.get("llm_local_enabled")) and not any(leg.provider == LOCAL_PROVIDER for leg in legs):
        legs = [*legs, _local_leg(config)]

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
    "DEFAULT_LOCAL_MODEL",
    "LOCAL_PROVIDER",
    "ChainLeg",
    "resolve_chain",
    "resolve_embedding_model",
    "should_fall_through",
]
