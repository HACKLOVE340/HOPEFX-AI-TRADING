# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""`GET /api/trading/account` sends null for a statistic it could not compute.

On a fresh account the endpoint used to send `win_rate: 0.0`,
`sharpe_ratio: 0.0` and `max_drawdown: 0.0`. The Dashboard scores those
figures, so the screen reported a 0.0% win rate in red, a 0.00 Sharpe in red,
and — from the same absence of trades — a 0.00% drawdown in green. Three
statistics, one cause, two failures and a success, none of them measuring
anything.

The frontend was already written for the right contract and says so.
`Dashboard.tsx`'s `has()` helper carries the comment *"a fabricated zero Sharpe
reads as a real, terrible Sharpe"*, and `types/trading.ts` documents each field
as absent until there are enough closed trades — a decision recorded under
audit #37. `MlAccuracyCard` in the same file already receives `win_rate: null`
from its own endpoint, for exactly this reason.

So the defect was one layer down: the API fabricated the zero the UI had been
carefully built to avoid, and the endpoint's own docstring claimed every field
was "required by the frontend AccountMetrics type" — the opposite of what the
type says.

`open_trades` stays `0`. It is a count, not a statistic: zero open trades is a
measurement, and rendering it as an em-dash would be its own kind of wrong.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from api.trading import get_account

#: Every field that is a statistic over closed trades.
DERIVED_STATS = ("win_rate", "sharpe_ratio", "sortino_ratio", "max_drawdown")


def _fresh_account() -> dict[str, Any]:
    """The payload for a user who has never closed a trade."""
    user = SimpleNamespace(
        sub="00000000-0000-0000-0000-000000000001",
        role="user",
        username="fresh",
        email="fresh@example.com",
    )
    result = asyncio.run(get_account(user=user))
    return result if isinstance(result, dict) else dict(result)


class TestAStatisticNobodyCouldComputeIsNull:
    @pytest.mark.parametrize("field", DERIVED_STATS)
    def test_it_is_null_not_zero(self, field: str) -> None:
        assert _fresh_account()[field] is None

    def test_the_field_is_still_present_in_the_payload(self) -> None:
        """Null and missing are different claims to a client. Null says "I
        looked and there is nothing yet"; a missing key reads as a server that
        forgot, or an older version."""
        payload = _fresh_account()
        for field in DERIVED_STATS:
            assert field in payload

    def test_the_same_absence_does_not_produce_a_pass_and_a_fail(self) -> None:
        """The shape of the original defect: win rate and Sharpe read as
        failures while drawdown read as a success, all three from having no
        trades. Whatever they are, they must agree."""
        payload = _fresh_account()
        assert len({payload[field] is None for field in DERIVED_STATS}) == 1


class TestACountOfZeroIsStillAMeasurement:
    def test_open_trades_is_zero_not_null(self) -> None:
        assert _fresh_account()["open_trades"] == 0

    def test_the_balance_is_a_real_number(self) -> None:
        """Paper mode seeds it from PAPER_STARTING_BALANCE. Nulling it would
        blank the one figure on the screen that is always knowable."""
        balance = _fresh_account()["balance"]
        assert isinstance(balance, (int, float))
        assert balance > 0

    def test_equity_is_a_real_number(self) -> None:
        assert isinstance(_fresh_account()["equity"], (int, float))


class TestTheUnitsAreTheOnesTheFrontendExpects:
    """`win_rate` and `max_drawdown` are percentages 0-100 on both paths —
    each is computed as `x / n * 100`. Pinned here because the Dashboard,
    AccountBar and RiskDashboard all multiplied by 100 a second time, which
    would have rendered a real 62.5% win rate as 6250.0%."""

    def test_win_rate_is_computed_as_a_percentage(self) -> None:
        source = (REPO / "api" / "trading.py").read_text()
        assert source.count("len(wins) / len(pnls) * 100") == 2, (
            "both the paper and live paths should compute win_rate as a percentage"
        )

    def test_max_drawdown_is_scaled_to_a_percentage(self) -> None:
        source = (REPO / "api" / "trading.py").read_text()
        assert "_dd_peak * 100" in source
        assert "_dd_peak_live * 100" in source

    def test_the_docstring_states_the_unit(self) -> None:
        """It previously stated the opposite of the type it referred to."""
        assert "percentages 0-100" in (get_account.__doc__ or "")

    def test_the_docstring_no_longer_claims_every_field_is_required(self) -> None:
        assert "all required by the frontend" not in (get_account.__doc__ or "")

    def test_the_docstring_says_which_fields_are_nullable(self) -> None:
        doc = get_account.__doc__ or ""
        for field in DERIVED_STATS:
            assert field in doc
        assert "nullable" in doc.lower()
