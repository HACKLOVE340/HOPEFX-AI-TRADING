"""The endpoint that withdraws money must consult the AML gate.

`compliance/aml.py::check_withdrawal` enforces a single-transaction cap, a daily
withdrawal count, a daily volume limit and sanctions/PEP screening. It is built
correctly and wired correctly — `core/startup_factories.py::init_aml` hands it a
session factory through the registered `aml` component — and it was never
consulted. Proved by running it directly against a populated ledger: a 40,000
withdrawal was refused by the 10,000 single cap, and a 100 withdrawal was
refused after six same-day rows by the 5-per-day rule. The gate works. Nothing
called it.

Its only production call site was `payments/wallet.py::debit_wallet`, inside a
class no production module uses (WALLET-DEAD), and `POST /payments/withdraw`
checked KYC through a dependency, a minimum amount and a rate limit, then
returned.

No money left unscreened, because that endpoint is documented NOT YET PERSISTED
and disburses nothing. That is exactly why the gate belongs here now: the day
`FIAT_PROVIDER` is configured and the endpoint is made real, it would have
disbursed without ever touching the gate — and the gate would still have looked
wired to anyone reading startup.

Registered as AML-UNREACHED.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def _user(sub: str = "user-123", email: str = "test@hopefx.io") -> SimpleNamespace:
    return SimpleNamespace(sub=sub, email=email, role="user")


class _SpyGate:
    """Records what it was asked, and answers however the test says."""

    def __init__(self, allowed: bool = True, reason: str = "") -> None:
        self.calls: list[dict] = []
        self._allowed = allowed
        self._reason = reason

    def check_withdrawal(self, user_id, amount, kyc_status="unverified", currency="USD"):
        self.calls.append({"user_id": user_id, "amount": amount, "kyc_status": kyc_status, "currency": currency})
        return SimpleNamespace(allowed=self._allowed, reason=self._reason, risk_score=0.0, flags=[])


async def _withdraw(req, user=None):
    from api.payments import fiat_withdraw

    return await fiat_withdraw(req, user=user or _user(), _rl=None)


def _request(amount: float = 500.0):
    from api.payments import FiatWithdrawRequest

    return FiatWithdrawRequest(amount=amount, destination="bank_account")


class TestTheGateIsConsulted:
    @pytest.mark.asyncio
    async def test_a_withdrawal_reaches_the_aml_gate(self):
        """The whole finding, in one assertion."""
        spy = _SpyGate(allowed=True)
        with patch("compliance.aml.get_aml_gate", return_value=spy):
            await _withdraw(_request(500.0))

        assert spy.calls, "the withdrawal endpoint never consulted the AML gate"
        call = spy.calls[0]
        assert call["user_id"] == "user-123"
        assert call["amount"] == Decimal("500.0"), (
            f"the gate was passed {call['amount']!r} — it compares against Decimal limits, "
            "so a float here reintroduces the drift the gate's thresholds avoid"
        )

    @pytest.mark.asyncio
    async def test_the_amount_is_decimal_not_float(self):
        """`Decimal(str(x))`, never `Decimal(x)` — a float inherits its binary error."""
        spy = _SpyGate(allowed=True)
        with patch("compliance.aml.get_aml_gate", return_value=spy):
            await _withdraw(_request(1234.56))

        assert spy.calls[0]["amount"] == Decimal("1234.56")


class TestARefusalStopsTheWithdrawal:
    @pytest.mark.asyncio
    async def test_a_blocked_withdrawal_is_refused_with_the_gate_s_reason(self):
        from fastapi import HTTPException

        spy = _SpyGate(allowed=False, reason="Daily withdrawal limit of 5 transactions reached")
        with patch("compliance.aml.get_aml_gate", return_value=spy):
            with pytest.raises(HTTPException) as exc:
                await _withdraw(_request(500.0))

        assert exc.value.status_code == 403
        assert "Daily withdrawal limit" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_an_allowed_withdrawal_still_returns_its_reference(self):
        """The gate must not break the path it is guarding."""
        spy = _SpyGate(allowed=True)
        with patch("compliance.aml.get_aml_gate", return_value=spy):
            result = await _withdraw(_request(500.0))

        assert result["status"] == "pending"
        assert result["reference"].startswith("WDR-")


class TestAnUnavailableGateFailsClosedInProduction:
    """Rule 3: fail closed on anything that spends. Mirrors `require_kyc`, which
    guards the same endpoint and rejects in production when its compliance
    manager is missing rather than waving the request through."""

    @pytest.mark.asyncio
    async def test_production_refuses_when_the_gate_cannot_be_reached(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("HOPEFX_REQUIRE_AML_STRICT", raising=False)
        with patch("compliance.aml.get_aml_gate", side_effect=RuntimeError("not initialised")):
            with pytest.raises(HTTPException) as exc:
                await _withdraw(_request(500.0))

        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_development_passes_through_when_nothing_is_wired(self, monkeypatch):
        """Tests and local runs wire no AML gate; that must not block them."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv("HOPEFX_REQUIRE_AML_STRICT", raising=False)
        with patch("compliance.aml.get_aml_gate", side_effect=RuntimeError("not initialised")):
            result = await _withdraw(_request(500.0))

        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_the_strict_flag_overrides_the_environment(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("HOPEFX_REQUIRE_AML_STRICT", "true")
        with patch("compliance.aml.get_aml_gate", side_effect=RuntimeError("not initialised")):
            with pytest.raises(HTTPException) as exc:
                await _withdraw(_request(500.0))

        assert exc.value.status_code == 503


class TestTheRealGateRefusesThroughTheEndpoint:
    """A spy proves the call happened. This proves the refusal is real.

    Same gate, same limits, a real session factory — driven through the
    endpoint rather than called directly.
    """

    @pytest.fixture()
    def real_gate(self, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from compliance.aml import AMLGate
        from database.models import Base

        engine = create_engine(f"sqlite:///{tmp_path}/aml.db")
        Base.metadata.create_all(engine)
        return AMLGate(session_factory=sessionmaker(bind=engine))

    @pytest.mark.asyncio
    async def test_a_withdrawal_over_the_single_cap_is_refused(self, real_gate):
        from fastapi import HTTPException

        from compliance.aml import SINGLE_WITHDRAWAL_CAP

        over = float(SINGLE_WITHDRAWAL_CAP) + 1
        with patch("compliance.aml.get_aml_gate", return_value=real_gate):
            with pytest.raises(HTTPException) as exc:
                await _withdraw(_request(over))

        assert exc.value.status_code == 403
        assert "single-transaction cap" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_a_withdrawal_under_every_limit_is_allowed(self, real_gate):
        """The positive control: the gate must not refuse everything.

        Without this, a gate that raised on every call would make the test
        above pass while blocking the whole product.
        """
        with patch("compliance.aml.get_aml_gate", return_value=real_gate):
            result = await _withdraw(_request(500.0))

        assert result["status"] == "pending"


class TestTheExistingChecksStillRun:
    @pytest.mark.asyncio
    async def test_the_minimum_is_still_enforced_before_the_gate(self, monkeypatch):
        """A sub-minimum withdrawal is rejected on its own terms, not as an AML block."""
        from fastapi import HTTPException

        monkeypatch.setenv("FIAT_MIN_WITHDRAWAL_USD", "10.0")
        spy = _SpyGate(allowed=True)
        with patch("compliance.aml.get_aml_gate", return_value=spy):
            with pytest.raises(HTTPException) as exc:
                await _withdraw(_request(1.0))

        assert exc.value.status_code == 422
        assert not spy.calls, "the gate was consulted for a request that was never valid"
