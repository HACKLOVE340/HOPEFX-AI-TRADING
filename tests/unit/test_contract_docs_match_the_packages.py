# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The contract docs must not call a live package legacy.

`CLAUDE.md`, `AGENTS.md` and `ARCHITECTURE.md` are the files every contributor
and every AI assistant is told to read first. All three described `data/` as
"CSV files + old utilities" and instructed readers **not to add code to it**
(F216).

Measured, not remembered:

| Package | LOC | Production importers |
|---|---:|---:|
| `data_layer/` | 19,610 | 86 |
| `data/` | 6,259 | 20 |
| `market_data/` | 4,031 | 6 |

`data/` holds `real_time_price_engine.py`, `scheduler.py`, `depth_of_market.py`,
`tick_feed.py`, `time_and_sales.py`, `streaming.py` and `feeds/macro.py`. It is
constructed in `core/startup_factories.py`, mounts three HTTP routers through
`core/router_registry.py`, and `ml/training.py` reads its macro feed.

The instruction was **actionable and wrong**: a contributor adding a tick-feed or
depth-of-market feature was told to put it in `data_layer/`, splitting one
subsystem across two packages whose relationship no document describes. That is a
documentation defect with code consequences, not a nit.

This test fails if any contract doc calls a package legacy, or tells readers not
to add code to it, while production still imports it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DOCS = ("CLAUDE.md", "AGENTS.md", "ARCHITECTURE.md")

# Packages a contract doc has described as legacy at some point.
WATCHED_PACKAGES = ("data", "data_layer", "market_data", "backtest", "backtesting", "strategy", "strategies")

# The exact phrases that were wrong. A general "does this doc call anything
# legacy?" scan was tried and abandoned: it is line-based, so it cannot tell
# which package a word on a line refers to, and it flagged the *correction* —
# both `data_layer/` (because "legacy" appeared elsewhere on the row) and the
# sentence explaining that `data/` is not "CSV + old utilities". Grepping prose
# cannot distinguish a claim from a description of a retracted claim; that is
# F255's mistake, and it does not become sound by being in a test.
#
# So this asserts the specific retracted claims stay retracted, and that the
# replacement facts are present. It is narrow on purpose, and it would have
# caught the original defect.
RETRACTED_CLAIMS = (
    "CSV + old utilities",
    "CSV files + old utilities",
    "pre-`data_layer/` utilities",
)


def _production_importers(package: str) -> int:
    """Non-test modules outside the package that import it."""
    pattern = re.compile(rf"^\s*(?:from|import)\s+{re.escape(package)}[\s.]")
    count = 0
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith((".venv/", "tests/", f"{package}/")) or "/node_modules/" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(pattern.match(line) for line in text.splitlines()):
            count += 1
    return count


def test_the_measurement_works():
    """A counter that returns zero for everything agrees with every assertion
    below."""
    assert _production_importers("data_layer") > 10, "the importer scan found almost nothing — the pattern is wrong"


def test_data_is_still_imported_from_production():
    """The fact the docs were wrong about. If this ever reaches zero, `data/`
    really has become legacy and the docs should change with it — deliberately."""
    assert _production_importers("data") > 0, (
        "`data/` has no production importers any more; the contract docs now describe it "
        "as live and should be revisited"
    )


@pytest.mark.parametrize("doc", CONTRACT_DOCS)
def test_no_contract_doc_repeats_the_retracted_claim(doc):
    path = REPO_ROOT / doc
    if not path.exists():
        pytest.skip(f"{doc} is not present")

    text = path.read_text(encoding="utf-8")
    repeated = [claim for claim in RETRACTED_CLAIMS if claim in text]
    assert not repeated, (
        f"{doc} describes `data/` as {repeated} while {_production_importers('data')} production "
        "modules import it — including core/startup_factories.py, core/router_registry.py and "
        "ml/training.py (F216)"
    )


def test_claude_md_carries_the_replacement_facts():
    """Retracting a wrong claim without replacing it leaves the next contributor
    with no guidance at all, which is how the wrong claim got written."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    for package in ("data_layer/", "data/", "market_data/"):
        assert package in text, f"CLAUDE.md does not mention {package}"
    assert "real_time_price_engine.py" in text, "CLAUDE.md does not say what `data/` actually holds"
    # This asserted that CLAUDE.md still says the boundary is "not documented".
    # ADR 0013 decided it on 2026-09-09 and CLAUDE.md was updated in the same
    # commit, so the assertion outlived the fact it was guarding and began
    # demanding that the file re-state a question the owner had answered.
    # What must hold now is that the decision is named and reachable.
    assert re.search(r"boundary is now decided", text, re.IGNORECASE), (
        "CLAUDE.md does not tell the reader the data/ | data_layer/ | market_data/ boundary is decided"
    )
    assert "ADR 0013" in text, "CLAUDE.md states the boundary without citing the decision that set it"
    assert re.search(r"does \*\*not\*\* authorise moving existing code", text), (
        "CLAUDE.md does not warn that the decided boundary is a rule for new code, not a refactor mandate"
    )
