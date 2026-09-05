# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Which vendors this deployment can actually reach — as booleans, never keys.

`ai.gateway.chain` says which model *should* answer. This module says which
vendor *could*, and the two are different things worth being able to see apart:
a chain whose second and third legs have no credentials has a fallback on paper
and one leg in practice, which is exactly the condition the fallback exists to
survive. The AI Core page reports it for that reason.

**A credential's presence is reported; its value never leaves this process.**
`credentialed_providers()` returns names, `reachability()` returns booleans, and
neither ever returns, logs, or embeds the key itself. The env var *names* are
public — they are already in `.env.example` — so naming them is safe and makes
an unconfigured deployment diagnosable without anyone reading a secret.
"""

from __future__ import annotations

import os
from typing import Final

#: Provider name -> the env vars any one of which credentials it. Ollama is
#: credentialed by a base URL rather than a key: local inference has no vendor
#: account, which is precisely why it is optional and never a primary leg.
CREDENTIAL_ENV: Final[dict[str, tuple[str, ...]]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "ollama": ("OLLAMA_BASE_URL",),
}


def is_credentialed(provider: str) -> bool:
    """True when at least one of `provider`'s credential vars is set and non-empty."""
    return any(os.getenv(name, "").strip() for name in CREDENTIAL_ENV.get(provider, ()))


def credentialed_providers() -> frozenset[str]:
    """Every provider this deployment holds a credential for."""
    return frozenset(name for name in CREDENTIAL_ENV if is_credentialed(name))


def reachability() -> dict[str, bool]:
    """Every known provider mapped to whether it is credentialed.

    Reported for all of them, not only the configured ones: "google is not
    configured" is the answer to why the third leg never answers, and omitting
    it turns a diagnosable gap into a silent one.
    """
    return {name: is_credentialed(name) for name in CREDENTIAL_ENV}


def local_inference_enabled() -> bool:
    """Whether the optional on-hardware provider is configured at all."""
    return is_credentialed("ollama")


__all__ = [
    "CREDENTIAL_ENV",
    "credentialed_providers",
    "is_credentialed",
    "local_inference_enabled",
    "reachability",
]
