# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""No module in `.coveragerc`'s omit list is one that unit tests already import.

The list carries a stated reason — "requires full app context; covered by
integration/e2e tests, not unit tests". Twice that reason turned out to be
false, and each time the discovery was accidental:

* `core/router_registry.py` (§E37) — nine unit tests already exercised
  `register_routers` directly.
* `core/startup_factories.py` (§E47) — 59 unit tests between two files.

A third look found **18 of 23** concrete entries had unit tests importing them,
`execution/engine.py` with eleven and `execution/fix_adapter.py` with six. The
exclusions were not a policy; they were an accumulation.

**An exclusion is worse than recorded debt.** A recorded module reports a number
and the ratchet pushes on it. An excluded one reports nothing, can show neither
debt nor progress, and blocks any commit that touches it with a diagnosis
pointing at a missing import that is not missing. On the money path —
`fix_adapter`, `engine`, `oanda` — that is a coverage figure nobody can see for
the code that moves the money.

This test is the ratchet on the omit list itself, so the next false
justification cannot be added quietly. It does not forbid exclusions: it
forbids excluding a module that unit tests demonstrably reach.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG = REPO / ".coveragerc"

#: Entries kept deliberately, each with a reason that is a property of the
#: MACHINE or of the module's dependencies rather than a claim about the test
#: suite — the kind of claim that turned out false three times.
#:
#: Every one of these is asserted below to have no unit importer, so if a unit
#: test ever starts importing one, this allowlist stops being true and the
#: entry has to be re-argued rather than inherited.
DELIBERATE: frozenset[str] = frozenset(
    {
        "core/acceleration/gpu_engine.py",
        "ml/rl_agent.py",
        "core/background_tasks.py",
        "core/email_webhook.py",
    }
)


def _omit_entries() -> list[str]:
    text = CONFIG.read_text()
    block = text.split("omit", 1)[1].split("\n[", 1)[0]
    return [line.strip() for line in block.splitlines() if re.fullmatch(r"[\w./-]+\.py", line.strip() or "x x")]


def _unit_importers(module_path: str) -> list[str]:
    """Unit-test files importing this module, by every form Python allows.

    The third form is the one that hides: `from ai.memory import governance`
    names the package, so a search for `from ai.memory.governance import`
    misses it entirely.
    """
    dotted = module_path[:-3].replace("/", ".").removesuffix(".__init__")
    pkg, _, leaf = dotted.rpartition(".")
    patterns = [
        rf"from\s+{re.escape(dotted)}\s+import",
        rf"import\s+{re.escape(dotted)}\b",
        # `patch("core.metrics.SHARPE_N_TRADES")` imports the module too. An
        # import statement is not the only way a test reaches code, and this
        # form is exactly how `core/metrics.py` slipped into the deliberate
        # list on the first pass.
        rf"""patch\(\s*['"]{re.escape(dotted)}[.'"]""",
    ]
    if pkg:
        patterns.append(rf"from\s+{re.escape(pkg)}\s+import\s+[^\n]*\b{re.escape(leaf)}\b")

    found: set[str] = set()
    for pattern in patterns:
        out = subprocess.run(
            ["rg", "-l", "--no-messages", pattern, str(REPO / "tests" / "unit")],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        ).stdout
        found |= {line for line in out.strip().split("\n") if line}
    return sorted(found)


class TestTheHarnessIsLive:
    """Every assertion below is a search returning nothing. If the search is
    broken, they all pass against a config nobody read."""

    def test_the_config_exists_and_has_an_omit_list(self):
        assert CONFIG.exists()
        assert _omit_entries(), "no concrete entries parsed — the assertions below would be vacuous"

    def test_the_importer_search_finds_a_module_it_should(self):
        """A positive control: `risk/manager.py` is not omitted and is
        certainly imported by unit tests."""
        assert _unit_importers("risk/manager.py"), "the importer search found nothing it should have"


class TestNoExclusionContradictsTheTestSuite:
    @pytest.mark.parametrize("entry", _omit_entries())
    def test_an_omitted_module_is_not_one_unit_tests_import(self, entry):
        if entry in DELIBERATE:
            pytest.skip(f"{entry} is a deliberate exclusion; asserted separately")

        importers = _unit_importers(entry)

        assert not importers, (
            f"{entry} is excluded from coverage, but {len(importers)} unit test file(s) import it: "
            f"{importers[:3]}. An exclusion is not a measurement — lift it and record the real "
            f"number under ADR 0017, or add it to DELIBERATE with a reason that is not a claim "
            f"about the test suite."
        )


class TestTheDeliberateListStaysTrue:
    """An allowlist nobody re-checks becomes a permission list. These are
    checked every run."""

    @pytest.mark.parametrize("entry", sorted(DELIBERATE))
    def test_it_is_still_in_the_omit_list(self, entry):
        assert entry in _omit_entries(), f"{entry} is allowlisted here but no longer excluded — drop it from DELIBERATE"

    @pytest.mark.parametrize("entry", sorted(DELIBERATE))
    def test_it_still_has_no_unit_importer(self, entry):
        importers = _unit_importers(entry)

        assert not importers, (
            f"{entry} was allowlisted because no unit test reaches it, and now {len(importers)} do: "
            f"{importers[:3]}. The reason it was excluded has expired — lift it and measure."
        )
