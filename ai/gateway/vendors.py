# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The hosted vendors this deployment can talk to, beyond the original three.

Owner requirement, 2026-09-06: Kimi, Qwen, and whatever else the operator holds
an account for.

The reason this is a table rather than seven integrations: Moonshot (Kimi),
DeepSeek, Alibaba's Qwen, Mistral, Groq, xAI, OpenRouter and Together all speak
the OpenAI wire format — `POST {base}/chat/completions` and `GET {base}/models`
with a bearer key. So the absence of Kimi was a missing row, not a missing
integration, and one adapter parameterised by (base URL, key env) serves all of
them. A vendor that does *not* speak that format gets its own adapter, the way
Anthropic and Google already do.

**Every base URL is overridable per deployment.** Several of these vendors
publish different hosts per region — Moonshot has `.ai` and `.cn`, DashScope has
an international and a mainland endpoint — and a committed default that is right
for one region is wrong for the other. `MOONSHOT_BASE_URL` and friends exist so
that is a setting rather than a patch.

Adding a row here does not widen spend silently: `estimate_cost` charges a model
it has no price for at the highest rate it knows, so an unpriced Kimi call is
over-counted against the ceiling rather than counted as free. Add real prices to
`PRICING` when you contract with a vendor; until then the conservative direction
is the safe one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Vendor:
    """One OpenAI-compatible vendor.

    `base_url` is the API root *without* a trailing slash, so `{base}/models`
    and `{base}/chat/completions` compose cleanly.
    """

    name: str
    label: str
    base_url: str
    key_env: str
    console_url: str
    notes: str = ""

    @property
    def base_url_env(self) -> str:
        """The per-deployment override, e.g. MOONSHOT_BASE_URL."""
        return f"{self.name.upper()}_BASE_URL"


#: Keyed by provider name, which is also the key in `CREDENTIAL_ENV` and
#: `_ADAPTERS`. Those three agreeing is asserted by
#: tests/unit/test_model_vendors_and_discovery.py rather than left to review.
OPENAI_COMPATIBLE: Final[dict[str, Vendor]] = {
    "moonshot": Vendor(
        name="moonshot",
        label="Moonshot (Kimi)",
        base_url="https://api.moonshot.ai/v1",
        key_env="MOONSHOT_API_KEY",
        console_url="https://platform.moonshot.ai/console/api-keys",
        notes=(
            "Kimi. The large K2 models are mixture-of-experts in the hundreds of "
            "billions to a trillion parameters — hosted only; they do not fit on a "
            "VPS. Use this vendor for Kimi rather than the local runner."
        ),
    ),
    "qwen": Vendor(
        name="qwen",
        label="Alibaba Qwen (DashScope)",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        key_env="DASHSCOPE_API_KEY",
        console_url="https://bailian.console.alibabacloud.com/",
        notes=(
            "Set QWEN_BASE_URL to the mainland host "
            "(https://dashscope.aliyuncs.com/compatible-mode/v1) outside the "
            "international region. Qwen's open-weight models also run locally "
            "through the local runner — this row is the hosted API."
        ),
    ),
    "deepseek": Vendor(
        name="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        key_env="DEEPSEEK_API_KEY",
        console_url="https://platform.deepseek.com/api_keys",
        notes="Open-weight models; the smaller distills also run locally.",
    ),
    "mistral": Vendor(
        name="mistral",
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        key_env="MISTRAL_API_KEY",
        console_url="https://console.mistral.ai/api-keys",
    ),
    "groq": Vendor(
        name="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        console_url="https://console.groq.com/keys",
        notes="Hosts open-weight models at very low latency; useful as a fast leg.",
    ),
    "xai": Vendor(
        name="xai",
        label="xAI (Grok)",
        base_url="https://api.x.ai/v1",
        key_env="XAI_API_KEY",
        console_url="https://console.x.ai/",
    ),
    "openrouter": Vendor(
        name="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_env="OPENROUTER_API_KEY",
        console_url="https://openrouter.ai/keys",
        notes=(
            "An aggregator: one key reaches many vendors' models. Convenient, and "
            "it means prompts traverse a third party — do not enable it on a "
            "deployment that chose local-only for privacy."
        ),
    ),
    "together": Vendor(
        name="together",
        label="Together AI",
        base_url="https://api.together.xyz/v1",
        key_env="TOGETHER_API_KEY",
        console_url="https://api.together.ai/settings/api-keys",
    ),
}


def resolve_base_url(provider: str) -> str:
    """The API root for `provider`, honouring a per-deployment override.

    Raises KeyError for a provider that is not in the table. A caller asking
    about a vendor nobody declared gets a refusal, not a guessed URL — guessing
    a host for a credential is how a key ends up posted somewhere unintended.
    """
    vendor = OPENAI_COMPATIBLE[provider]
    override = (os.getenv(vendor.base_url_env, "") or "").strip().rstrip("/")
    return override or vendor.base_url


def api_key(provider: str) -> str:
    """The configured key for `provider`, or "" when it has none."""
    return (os.getenv(OPENAI_COMPATIBLE[provider].key_env, "") or "").strip()


__all__ = ["OPENAI_COMPATIBLE", "Vendor", "api_key", "resolve_base_url"]
