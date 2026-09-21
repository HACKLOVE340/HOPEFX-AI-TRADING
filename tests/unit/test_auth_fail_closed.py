# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_auth_fail_closed.py
===================================
Two places where auth defaulted toward permission instead of away from it.

`require_kyc` also guards fiat withdrawal, so a compliance manager that failed to
wire — bad config, import error, partial startup — silently disabled identity
checks on money leaving the platform, with nothing in the response to say so.

`TokenPayload.role` defaulted to "user", which outranks "starter" in the role
hierarchy, so a token missing the claim was granted more than a real starter-tier
customer.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.auth import _LOWEST_ROLE, _ROLE_RANK, TokenPayload, require_kyc


def _request(app_state=None):
    """A request whose app carries (or does not carry) an app_state."""
    request = MagicMock()
    request.app.state.app_state = app_state
    return request


def _user(role: str = "user") -> TokenPayload:
    return TokenPayload(sub="u1", role=role)


class TestRoleDefaultsToLeastPrivilege:
    def test_missing_role_claim_gets_the_lowest_rank(self):
        assert TokenPayload(sub="u1").role == _LOWEST_ROLE

    def test_the_default_does_not_outrank_a_real_customer(self):
        """The bug: "user" (rank 1) sat above "starter" (rank 0)."""
        assert _ROLE_RANK[TokenPayload(sub="u1").role] == min(_ROLE_RANK.values())

    def test_lowest_role_is_derived_from_the_hierarchy(self):
        assert _ROLE_RANK[_LOWEST_ROLE] == min(_ROLE_RANK.values())


class TestRequireKycFailsClosedInProduction:
    def test_missing_compliance_manager_is_rejected(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        state = MagicMock()
        state.compliance_manager = None

        with pytest.raises(HTTPException) as exc:
            require_kyc(_request(state), _user())
        assert exc.value.status_code == 503

    def test_app_state_import_failure_is_rejected(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")

        with patch.dict("sys.modules", {"core.app_state": None}):
            with pytest.raises(HTTPException) as exc:
                require_kyc(_request(None), _user())
        assert exc.value.status_code == 503

    def test_unapproved_user_is_rejected(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        state = MagicMock()
        state.compliance_manager.is_kyc_approved.return_value = False

        with pytest.raises(HTTPException) as exc:
            require_kyc(_request(state), _user())
        assert exc.value.status_code == 403

    def test_approved_user_passes(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        state = MagicMock()
        state.compliance_manager.is_kyc_approved.return_value = True

        assert require_kyc(_request(state), _user()).sub == "u1"

    @pytest.mark.parametrize("role", ["admin", "superadmin"])
    def test_operators_remain_exempt(self, role, monkeypatch):
        """Staff do not submit identity documents to trade on their own platform."""
        monkeypatch.setenv("APP_ENV", "production")
        state = MagicMock()
        state.compliance_manager = None

        assert require_kyc(_request(state), _user(role)).role == role


class TestRequireKycStaysPermissiveInDevelopment:
    def test_missing_manager_passes_outside_production(self, monkeypatch):
        """Test and embedded apps wire no compliance manager."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv("HOPEFX_REQUIRE_KYC_STRICT", raising=False)
        state = MagicMock()
        state.compliance_manager = None

        assert require_kyc(_request(state), _user()).sub == "u1"

    def test_strict_flag_overrides_a_non_production_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("HOPEFX_REQUIRE_KYC_STRICT", "true")
        state = MagicMock()
        state.compliance_manager = None

        with pytest.raises(HTTPException):
            require_kyc(_request(state), _user())

    def test_strict_flag_can_be_disabled_in_production(self, monkeypatch):
        """Escape hatch for a deployment with no compliance layer at all."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("HOPEFX_REQUIRE_KYC_STRICT", "false")
        state = MagicMock()
        state.compliance_manager = None

        assert require_kyc(_request(state), _user()).sub == "u1"
