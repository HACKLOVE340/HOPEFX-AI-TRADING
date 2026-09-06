# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The settings page can list every model this deployment can actually reach.

Owner requirement, 2026-09-06: "it pops up all the model". `ai/gateway/discovery.py`
asks each vendor; this is the read surface that puts the answer in front of an
operator, so the model chain editor offers what exists rather than what was
committed months ago.

Read-only by construction, like the rest of `api/ai_core.py`: choosing a model
is a consequential action and lives in `safe_agent_platform` behind a superadmin
2FA gate. A reporting surface that could also act would be a second, weaker door
to the same room.

Two things these tests hold to that the endpoint makes easy to get wrong:

* **Eight vendors must not mean eight serial round trips.** A settings page that
  blocks for eighty seconds is a page nobody opens, and the naive implementation
  is serial.
* **A key must never reach the response.** The endpoint reports which vendors
  are configured; "configured" is a boolean, and the credential itself has no
  business crossing the wire to a browser.
"""

from __future__ import annotations

import pytest

from ai.gateway import vendors
from ai.policy import roles as policy

pytestmark = pytest.mark.unit


def test_the_endpoint_is_classified_in_the_authorization_matrix():
    """An endpoint with no row has no declared authorization; that is a refusal."""
    capability = policy.capability_for("ai_core_models")
    assert capability is not None, "ai_core_models has no row in ai/policy/roles.py"
    assert capability.tier == policy.VIEW, "listing models is reporting, not acting"


def test_listing_models_is_readable_by_admin_and_superadmin_only():
    admitted = policy.ROLES_ADMITTED[policy.VIEW]
    assert admitted == frozenset({"admin", "superadmin"})


@pytest.mark.asyncio
async def test_the_endpoint_reports_every_known_provider(monkeypatch):
    from api import ai_core

    for vendor in vendors.OPENAI_COMPATIBLE.values():
        monkeypatch.delenv(vendor.key_env, raising=False)
    monkeypatch.setattr(ai_core, "_discover", lambda provider=None: _fake_results())

    payload = await ai_core.ai_core_models(provider=None, _=object())
    names = {row["provider"] for row in payload["providers"]}
    assert "moonshot" in names and "qwen" in names
    assert "ollama" in names


@pytest.mark.asyncio
async def test_no_api_key_ever_appears_in_the_response(monkeypatch):
    from api import ai_core

    secret = "sk-do-not-leak-this-value"  # pragma: allowlist secret
    monkeypatch.setenv(vendors.OPENAI_COMPATIBLE["moonshot"].key_env, secret)
    monkeypatch.setattr(ai_core, "_discover", lambda provider=None: _fake_results())

    payload = await ai_core.ai_core_models(provider=None, _=object())
    assert secret not in repr(payload)


@pytest.mark.asyncio
async def test_a_single_provider_can_be_asked_for(monkeypatch):
    from api import ai_core

    seen: list[str | None] = []

    def fake(provider=None):
        seen.append(provider)
        return _fake_results()

    monkeypatch.setattr(ai_core, "_discover", fake)
    await ai_core.ai_core_models(provider="moonshot", _=object())
    assert seen == ["moonshot"]


def test_discovery_runs_concurrently_not_one_vendor_after_another():
    """Eight vendors at a ten-second timeout is eighty seconds, served serially."""
    import inspect

    from api import ai_core

    source = inspect.getsource(ai_core._discover)
    assert "ThreadPoolExecutor" in source or "gather" in source, (
        "model discovery fans out to every configured vendor; doing it serially "
        "makes the settings page unopenable when one vendor is slow"
    )


def _fake_results():
    from ai.gateway.discovery import VendorModels

    rows = {
        name: VendorModels(provider=name, label=v.label, configured=False, notes=v.notes)
        for name, v in vendors.OPENAI_COMPATIBLE.items()
    }
    rows["ollama"] = VendorModels(provider="ollama", label="Local (Ollama)", configured=True)
    return rows


@pytest.mark.asyncio
async def test_a_broken_local_runtime_does_not_take_down_the_chain_page(monkeypatch, caplog):
    """The failure branch, executed.

    It was added with an undefined `logger` and every test still passed, because
    nothing made the branch run. A handler that has never executed is not a
    handler — see .claude/skills/hopefx-dead-controls.
    """
    import logging as _logging

    from api import ai_core

    def boom():
        raise RuntimeError("runtime module unavailable")

    monkeypatch.setattr("ai.local_model.get_local_model_runtime", boom)
    with caplog.at_level(_logging.WARNING):
        status = ai_core._local_runtime_status()

    assert status["started"] is False
    assert status["refusal"] == "status_unavailable"
    assert any("local runtime status unavailable" in r.getMessage() for r in caplog.records)
