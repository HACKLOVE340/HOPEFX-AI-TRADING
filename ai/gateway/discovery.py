# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Ask each vendor which models it has, instead of committing a list.

Owner requirement, 2026-09-06: "make sure this app can accept external API ...
and it pops up all the model."

Before this, a superadmin editing the model chain chose from whatever was
committed in `DEFAULT_CHAINS`. A vendor shipping a new model meant a code
change, and a model being retired meant a chain that resolved to a leg the
vendor no longer served — discoverable only when it started failing.

Three properties this module holds to, all of them learned from defects in this
repository:

**Not configured is not the same as no models.** A vendor with no key returns
`configured=False` and no error. Reporting "0 models" for an unconfigured vendor
is how "google is not configured" becomes "google has nothing", which is the
diagnosable gap turned silent.

**A malformed payload is empty, never an exception.** A vendor changing its
response shape must not take down the settings page that lists every other
vendor.

**An error never echoes the key.** A vendor exception can quote the request
headers, and those carry the bearer token — the same reason
`ai/gateway/adapters.py` refuses to chain its ProviderError from the vendor's
exception. The reason code is ours; the vendor's string is not repeated.

The HTTP call is injected so tests exercise the parsing and the guards without
reaching the network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from ai.gateway import vendors

logger = logging.getLogger(__name__)

Fetch = Callable[[str, dict], Any]

DISCOVERY_TIMEOUT_S: Final = 10.0

#: The local runner is listed alongside the hosted vendors because from the
#: operator's seat it is one more place models come from — and it is the one
#: place where "which models are present" is a question about this machine.
LOCAL_PROVIDER: Final = "ollama"


@dataclass(frozen=True)
class VendorModels:
    """What one vendor answered.

    `configured` and `error` are separate on purpose: no key, a reachable vendor
    with no models, and a vendor that failed are three different states, and
    collapsing them into an empty list is what makes an outage look like a
    preference.
    """

    provider: str
    label: str
    configured: bool
    models: tuple[str, ...] = ()
    error: str | None = None
    notes: str = ""
    console_url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "label": self.label,
            "configured": self.configured,
            "models": list(self.models),
            "error": self.error,
            "notes": self.notes,
            "console_url": self.console_url,
        }


def parse_models(provider: str, payload: Any) -> tuple[str, ...]:
    """Model identifiers out of a vendor's listing. Anything unexpected is ()."""
    try:
        if provider == LOCAL_PROVIDER:
            entries = (payload or {}).get("models") or []
            names = [str(e.get("name", "")).strip() for e in entries if isinstance(e, dict)]
        else:
            entries = (payload or {}).get("data") or []
            names = [str(e.get("id", "")).strip() for e in entries if isinstance(e, dict)]
    except (AttributeError, TypeError):
        logger.warning("model discovery: %s returned an unrecognised payload shape", provider)
        return ()
    return tuple(name for name in names if name)


def _default_fetch(url: str, headers: dict) -> Any:
    import httpx

    response = httpx.get(url, headers=headers, timeout=DISCOVERY_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def _safe_reason(exc: BaseException) -> str:
    """A reason code of ours, never the vendor's string.

    The vendor's message can contain the request headers, and those carry the
    key — `ai/gateway/adapters.py` documents the same trap on the completion
    path. Only the exception *type* crosses this boundary.
    """
    name = type(exc).__name__
    lowered = name.lower()
    if "timeout" in lowered:
        return "timeout"
    if "connect" in lowered or "transport" in lowered:
        return "connection_error"
    return f"unavailable ({name})"


def list_models(provider: str, *, fetch: Fetch | None = None) -> VendorModels:
    """Which models `provider` currently serves."""
    fetch = fetch or _default_fetch

    if provider == LOCAL_PROVIDER:
        from ai.local_model import configured_models

        try:
            from ai.gateway.adapters import OllamaAdapter

            url = OllamaAdapter().probe_url
            payload = fetch(url, {})
        except Exception as exc:
            logger.warning("model discovery: local runner unreachable (%s)", _safe_reason(exc))
            return VendorModels(
                provider=LOCAL_PROVIDER,
                label="Local (Ollama)",
                configured=True,
                error=_safe_reason(exc),
                notes=(
                    "Configured to warm: " + ", ".join(configured_models()) + ". "
                    "Not reachable — is the runtime started? See LOCAL_MODEL_AUTOSTART."
                ),
            )
        return VendorModels(
            provider=LOCAL_PROVIDER,
            label="Local (Ollama)",
            configured=True,
            models=parse_models(LOCAL_PROVIDER, payload),
            notes="Runs on this machine. Add models with LOCAL_MODEL_NAMES.",
        )

    vendor = vendors.OPENAI_COMPATIBLE[provider]
    key = vendors.api_key(provider)
    if not key:
        return VendorModels(
            provider=provider,
            label=vendor.label,
            configured=False,
            notes=vendor.notes,
            console_url=vendor.console_url,
        )

    url = f"{vendors.resolve_base_url(provider)}/models"
    try:
        payload = fetch(url, {"authorization": f"Bearer {key}"})
    except Exception as exc:
        reason = _safe_reason(exc)
        logger.warning("model discovery: %s failed (%s)", provider, reason)
        return VendorModels(
            provider=provider,
            label=vendor.label,
            configured=True,
            error=reason,
            notes=vendor.notes,
            console_url=vendor.console_url,
        )

    return VendorModels(
        provider=provider,
        label=vendor.label,
        configured=True,
        models=parse_models(provider, payload),
        notes=vendor.notes,
        console_url=vendor.console_url,
    )


def discover_all(*, fetch: Fetch | None = None) -> dict[str, VendorModels]:
    """Every known provider, configured or not.

    Unconfigured vendors are included deliberately: the settings page needs to
    offer them, and "this vendor exists and you hold no key for it" is the
    answer to why a chain leg never runs.
    """
    results = {name: list_models(name, fetch=fetch) for name in vendors.OPENAI_COMPATIBLE}
    results[LOCAL_PROVIDER] = list_models(LOCAL_PROVIDER, fetch=fetch)
    return results


__all__ = ["VendorModels", "discover_all", "list_models", "parse_models"]
