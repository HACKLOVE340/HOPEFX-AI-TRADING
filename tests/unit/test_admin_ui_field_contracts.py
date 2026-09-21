# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_admin_ui_field_contracts.py
===========================================
Three more admin defects, two of them the same shape as the audit trail.

**The Sec. Infra section would not load at all.**

    ⚠ Section "Sec. Infra" failed to load
    undefined is not an object (evaluating 'i.hsm_type.toUpperCase')

``GET /security-infra/hsm`` returns ``type``; the page reads ``hsm_type``. It
also reads ``hsm.keys``, ``hsm.initialized`` and ``hsm.key_count``, none of
which the endpoint sent. The ``HSMStatus`` interface declared all four, so
TypeScript raised nothing — the response is read untyped.

**The Antivirus tab printed the word "undefined" at the user.**

``av.yara_rules_loaded`` was never sent, and ``String(undefined)`` is
``"undefined"``. ``clamav_available`` was never sent either, so the tile read
``N/A`` regardless of whether ClamAV was running. Both facts are known —
``security/antivirus.py`` tracks them — they were simply not reported.

**Selecting the Elite plan always failed.**

    Invalid plan. Must be one of: ['enterprise', 'free', 'professional', 'starter']

``api/superadmin/users.py`` carried a hand-written set that had drifted from
``SubscriptionTier``, which has had ``ELITE`` all along — with a price, its own
``/api/billing/elite/*`` endpoints, and a place in the dropdown.
``api/billing.py`` carried a *second* hand-written copy that did include it, so
the same plan was valid on one endpoint and rejected on another. Both now
derive from the enum.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SECTION = _ROOT / "frontend/src/pages/superadmin/SecurityInfraSection.tsx"


# ── HSM: the crash ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["hsm_type", "initialized", "key_count", "keys"])
def test_the_hsm_endpoint_sends_every_field_the_panel_reads(field):
    import inspect

    from api.superadmin.security_infra import get_hsm_status

    assert f'"{field}"' in inspect.getsource(get_hsm_status), f"the panel reads {field}; the API does not send it"


@pytest.mark.parametrize("field", ["type", "keys_managed"])
def test_the_original_field_names_are_kept(field):
    """Renaming instead of aliasing would break any existing consumer."""
    import inspect

    from api.superadmin.security_infra import get_hsm_status

    assert f'"{field}"' in inspect.getsource(get_hsm_status)


def test_the_hsm_aliases_carry_the_same_value():
    import inspect

    from api.superadmin.security_infra import get_hsm_status

    src = inspect.getsource(get_hsm_status)
    assert '"hsm_type": hsm_type' in src
    assert '"key_count": key_count' in src


def test_the_panel_cannot_crash_on_a_missing_hsm_field():
    """The field-name mismatch is fixed, but an unguarded read is what turned it
    into a section that would not render at all."""
    from tests.support.source_text import code_only

    src = code_only(_SECTION)
    assert "hsm.hsm_type.toUpperCase()" not in src, "the unguarded read is back"
    assert "hsm.keys.map" not in src, "hsm.keys is read without a guard again"
    assert "(hsm.keys ?? [])" in src


def test_the_hsm_interface_marks_the_fields_optional():
    """Optional types are what turned the second unguarded read (hsm.keys.map)
    from a runtime crash into a compile error."""
    src = _SECTION.read_text()
    start = src.index("interface HSMStatus")
    body = src[start : src.index("}", start)]
    for field in ("hsm_type", "initialized", "keys"):
        assert f"{field}?:" in body, f"{field} is declared as always present"


# ── Antivirus: the literal "undefined" ───────────────────────────────────────


@pytest.mark.parametrize("field", ["clamav_available", "yara_rules_loaded"])
def test_the_antivirus_endpoint_sends_what_the_tiles_read(field):
    import inspect

    from api.superadmin.security_infra import get_antivirus_status

    assert f'"{field}"' in inspect.getsource(get_antivirus_status)


def test_the_antivirus_status_uses_the_real_availability_flags():
    """These are knowable — security/antivirus.py sets them at import — and were
    simply never surfaced."""
    import inspect

    from api.superadmin.security_infra import get_antivirus_status

    src = inspect.getsource(get_antivirus_status)
    assert "CLAMD_AVAILABLE" in src
    assert "YARA_AVAILABLE" in src


def test_the_availability_flags_exist_under_those_names():
    """CLAMD_AVAILABLE, not CLAMAV_AVAILABLE — the first draft of the fix
    imported a name that does not exist."""
    import security.antivirus as av

    assert hasattr(av, "CLAMD_AVAILABLE")
    assert hasattr(av, "YARA_AVAILABLE")


def test_no_tile_can_render_the_word_undefined():
    """`String(undefined)` is "undefined", and that is what the user saw."""
    from tests.support.source_text import code_only

    src = code_only(_SECTION)
    assert "value: av.yara_rules_loaded," not in src, "the unguarded read is back"
    assert "av.yara_rules_loaded ?? '—'" in src
    assert "(av.files_scanned ?? 0).toLocaleString()" in src


def test_the_antivirus_status_never_raises_when_the_scanner_is_missing():
    """The endpoint must survive an environment with neither engine installed —
    which is this sandbox, and any deployment that has not installed them."""
    import asyncio
    import inspect

    from api.superadmin.security_infra import get_antivirus_status

    src = inspect.getsource(get_antivirus_status)
    assert "except Exception" in src

    result = asyncio.run(get_antivirus_status(user=None))
    assert result["clamav_available"] is False
    assert result["yara_rules_loaded"] == 0


# ── Plans: one enum, not three ───────────────────────────────────────────────


def test_elite_is_a_real_tier():
    """The premise. If ELITE is ever removed the dropdown should lose it too."""
    from monetization.pricing import SubscriptionTier

    assert "elite" in {t.value for t in SubscriptionTier}


def test_the_superadmin_plan_endpoint_accepts_every_tier():
    """It rejected elite, so the dropdown's Elite option always failed."""
    import inspect

    from api.superadmin.users import set_user_plan

    src = inspect.getsource(set_user_plan)
    assert "SubscriptionTier" in src, "the plan set is hand-written again"
    assert '{"free", "starter", "professional", "enterprise"}' not in src


def test_the_billing_plan_endpoint_uses_the_same_source():
    import inspect

    from api.billing import change_subscription_plan

    src = inspect.getsource(change_subscription_plan)
    assert "SubscriptionTier" in src


def test_both_endpoints_accept_exactly_the_same_plans():
    """The defect was two hand-maintained copies of one enum, one stale."""
    import inspect

    from api.billing import change_subscription_plan
    from api.superadmin.users import set_user_plan

    marker = "valid_plans = {t.value for t in SubscriptionTier}"
    assert marker in inspect.getsource(set_user_plan)
    assert marker in inspect.getsource(change_subscription_plan)


def test_the_plan_dropdown_offers_only_plans_the_backend_accepts():
    """The other half of the contract.

    Scoped to the "Change Plan" control specifically. A file-wide scan also
    picks up the status filter (active / banned / pending / inactive), which
    are not plans — a first draft of this test failed on exactly that and would
    have been "fixed" by widening the allow-list until it asserted nothing.
    """
    import re

    from monetization.pricing import SubscriptionTier

    users_section = _ROOT / "frontend/src/pages/superadmin/UsersSection.tsx"
    if not users_section.exists():
        pytest.skip("UsersSection.tsx not present")

    src = users_section.read_text()
    anchor = src.index("Change Plan")
    block = src[anchor : src.index("]}", anchor)]
    offered = set(re.findall(r"value:\s*'([a-z_]+)'", block))

    assert offered, "the Change Plan dropdown has no options — the anchor moved"
    valid = {t.value for t in SubscriptionTier}
    assert offered <= valid, f"the dropdown offers plans the backend will reject: {sorted(offered - valid)}"
    assert "elite" in offered, "Elite disappeared from the dropdown — check it is still a tier"
