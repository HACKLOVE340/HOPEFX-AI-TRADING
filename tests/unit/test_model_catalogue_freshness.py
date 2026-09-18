"""Task 15 — the model defaults go stale silently unless something checks.

`ai/gateway/chain.py::DEFAULT_CHAINS` shipped `gpt-4o` and
`claude-3-5-sonnet-20241022` -- two 2024 models -- as the committed defaults in
September 2026 (audit D8). Nothing noticed, because nothing could: the
identifiers were hard-coded in a module, where going stale is silent and fixing
it needs a redeploy.

Choosing good defaults today does not fix that. These two assertions do:

* every default appears in `docs/ai/MODEL_CATALOGUE.md` under the same
  provider -- a default the catalogue has never heard of is one nobody
  reviewed;
* every `reviewed_on` is within 180 days -- the row goes stale on a schedule
  and the build says so, rather than a person having to remember.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ai.gateway.chain import DEFAULT_CHAINS

_CATALOGUE = Path("docs/ai/MODEL_CATALOGUE.md")

#: A row goes stale after this long. Long enough not to be noise, short enough
#: that a model generation cannot pass unreviewed.
MAX_AGE_DAYS = 180

#: `| `model` | provider | role | position | YYYY-MM-DD | notes |`
_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*([a-z0-9_-]+)\s*\|[^|]*\|[^|]*\|\s*(\d{4}-\d{2}-\d{2})\s*\|",
    re.MULTILINE,
)


def _rows() -> list[tuple[str, str, date]]:
    text = _CATALOGUE.read_text(encoding="utf-8")
    return [(model, provider, date.fromisoformat(reviewed)) for model, provider, reviewed in _ROW.findall(text)]


def test_the_catalogue_parses() -> None:
    """A catalogue this test cannot read asserts nothing about anything."""
    assert _CATALOGUE.exists(), f"{_CATALOGUE} is missing"
    rows = _rows()
    assert len(rows) >= len({leg.model for legs in DEFAULT_CHAINS.values() for leg in legs}), (
        "the catalogue has fewer rows than there are distinct default models; "
        "the table format probably changed and this test is now reading nothing"
    )


def test_every_default_model_is_in_the_catalogue() -> None:
    """A routing default nobody catalogued is a default nobody reviewed."""
    catalogued = {(model, provider) for model, provider, _ in _rows()}
    missing = sorted(
        f"{leg.model} ({leg.provider}) for role {role}"
        for role, legs in DEFAULT_CHAINS.items()
        for leg in legs
        if (leg.model, leg.provider) not in catalogued
    )
    assert not missing, (
        "these chain defaults are not in docs/ai/MODEL_CATALOGUE.md: "
        f"{missing}. Add a row with today's reviewed_on in the same commit "
        "that changes DEFAULT_CHAINS."
    )


@pytest.mark.parametrize("row", _rows(), ids=lambda row: f"{row[0]}@{row[1]}")
def test_no_catalogue_row_is_stale(row: tuple[str, str, date]) -> None:
    """The check D8 was missing: a review date that expires on its own."""
    model, provider, reviewed = row
    age_days = (datetime.now(UTC).date() - reviewed).days
    assert age_days <= MAX_AGE_DAYS, (
        f"{model} ({provider}) was last reviewed {age_days} days ago, over the "
        f"{MAX_AGE_DAYS}-day limit. Open the vendor's current model list, confirm "
        "the identifier still resolves and the role still fits, then update "
        "reviewed_on. Bumping the date without doing the check is worse than "
        "letting this fail."
    )


def test_a_review_date_is_never_in_the_future() -> None:
    """A future date would hold a row 'fresh' indefinitely."""
    today = datetime.now(UTC).date()
    ahead = sorted(f"{model} ({reviewed})" for model, _, reviewed in _rows() if reviewed > today)
    assert not ahead, f"reviewed_on is in the future for: {ahead}"
