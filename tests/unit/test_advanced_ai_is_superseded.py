# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`ml/advanced_ai.py` is superseded, kept, and pinned out of production.

698 lines, zero production callers. The reflex is "give it a caller" — the same
move that was right for `ai/agent/loop.py` and `ml/model_quality_gate.py`, both
wired in the two commits before this one. Here it is wrong, and the difference
is worth stating because the symptom is identical.

Those two were **built and never called**. This one is **superseded**: every
one of its three subsystems has a replacement that is more developed and
already wired.

| `advanced_ai.py`                    | live replacement                    | wired into                          |
|-------------------------------------|-------------------------------------|-------------------------------------|
| `PPORLAgent`, `TradingEnv`          | `ml/rl_agent.py`                    | `api/ml.py`, `ml/training_manager.py` |
| `OnlineRetrainer`                   | `ml/online_learner.py`              | `api/online_learner.py`             |
| `VectorRAGNewsSentiment`            | `ai/departments/news_intelligence.py` | `ai/awareness/watchers.py`        |

`ml/rl_agent.py` additionally carries `RLMetrics`, `RLAgentTrainer`,
`walk_forward_eval` and a `get_rl_agent()` accessor. Wiring `PPORLAgent` in
beside it would put a second, less developed PPO agent and a second online
retrainer into a live money-moving system, with no way to tell afterwards which
one acted.

So the file stays exactly as it is — nothing deleted, per the owner's standing
instruction — and this pins the two facts that make that safe:

1. **Nothing in production imports it.** If someone wires it later, this test
   fails and makes that a deliberate decision rather than a drift.
2. **The supersession claim is verified, not asserted.** Each replacement named
   in the module docstring must exist AND be imported by production code. A
   pointer to a module that was itself renamed or dropped is how a note like
   this rots into a lie, and the registry lesson (F176) is that a claim nobody
   measures is a claim nobody can trust.

One genuinely unique capability is NOT being thrown away: `VectorRAGNewsSentiment`
is embedding-based (FAISS + sentence-transformers), while the live path is the
keyword wordmap scorer. That is tracked as its own proposal, to be decided on
whether the trading VPS should carry those dependencies — not settled as a side
effect of "this file needs a caller".
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
MODULE = REPO / "ml" / "advanced_ai.py"

#: Each part of advanced_ai.py, and the module that replaced it.
SUPERSEDED_BY = {
    "PPORLAgent": "ml/rl_agent.py",
    "OnlineRetrainer": "ml/online_learner.py",
    "VectorRAGNewsSentiment": "ai/departments/news_intelligence.py",
}


def _production_files():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(("tests/", ".venv/", "scripts/")) or "__pycache__" in rel:
            continue
        yield rel, path


def _imports_of(path: pathlib.Path) -> set[str]:
    """Dotted module names this file imports.

    `from ai.departments import news_intelligence` has to count as importing
    `ai.departments.news_intelligence`, not just `ai.departments` — the first
    version of this recorded only `node.module` and so reported
    `news_intelligence.py` as having no caller when `ai/awareness/watchers.py`
    imports it in exactly that form. The `from package import submodule` shape
    is the normal way this repository reaches a department.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


class TestItIsKeptNotDeleted:
    def test_the_module_still_exists(self) -> None:
        assert MODULE.exists(), "advanced_ai.py was deleted — it is meant to be kept and marked, not removed"

    def test_it_still_imports_cleanly(self) -> None:
        # Its heavy dependencies are optional and guarded; a kept module that
        # cannot be imported is not really kept.
        import ml.advanced_ai as mod

        assert mod is not None


class TestNothingInProductionImportsIt:
    def test_it_has_no_production_caller(self) -> None:
        callers = [rel for rel, path in _production_files() if "ml.advanced_ai" in _imports_of(path)]
        assert not callers, (
            "ml/advanced_ai.py is superseded and pinned out of production, but these import it: "
            f"{callers}. If that is deliberate, this test is the place to say so — and read the "
            "module docstring first: it puts a second PPO agent next to ml/rl_agent.py."
        )


class TestTheSupersessionClaimIsVerifiedNotAsserted:
    """A note saying "superseded by X" is worth nothing if X moved."""

    @pytest.mark.parametrize(("part", "replacement"), sorted(SUPERSEDED_BY.items()))
    def test_the_named_replacement_exists(self, part: str, replacement: str) -> None:
        assert (REPO / replacement).exists(), f"{part} is documented as superseded by {replacement}, which is gone"

    @pytest.mark.parametrize(("part", "replacement"), sorted(SUPERSEDED_BY.items()))
    def test_the_named_replacement_is_itself_wired(self, part: str, replacement: str) -> None:
        # The whole argument for not wiring advanced_ai.py is that something
        # better already runs. If the replacement is ALSO uncalled, that
        # argument is gone and this needs revisiting.
        module_path = replacement.removesuffix(".py").replace("/", ".")
        callers = [
            rel
            for rel, path in _production_files()
            if rel != replacement
            and any(imp == module_path or imp.startswith(module_path + ".") for imp in _imports_of(path))
        ]
        assert callers, (
            f"{replacement} is named as what supersedes {part}, but nothing in production imports it either — "
            "the reason for leaving advanced_ai.py unwired no longer holds"
        )

    @pytest.mark.parametrize(("part", "replacement"), sorted(SUPERSEDED_BY.items()))
    def test_the_module_docstring_names_the_replacement(self, part: str, replacement: str) -> None:
        # The pointer a reader actually sees lives in the file itself, so it is
        # the one that must not drift.
        docstring = ast.get_docstring(ast.parse(MODULE.read_text(encoding="utf-8"))) or ""
        assert part in docstring, f"the module docstring does not mention {part}"
        assert replacement in docstring, f"the module docstring does not name {replacement} as {part}'s replacement"
