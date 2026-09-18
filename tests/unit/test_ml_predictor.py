# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`ml/predictor.py` — the legacy import path for the predictor singleton.

The module is a pure alias for `ml.advanced_predictor`, and its docstring states
the contract it exists to hold: a caller importing `get_predictor` from here
receives *the same singleton* as one importing it from the canonical module.

It measured 0% and is production-reachable — `api/superadmin/reliability.py:202`
imports `get_predictor` from this path.

An alias is the easiest thing in a codebase to "tidy up" into a wrapper that
constructs its own instance. That edit would leave both import paths working,
both returning an `AdvancedPredictor`, and every existing test passing, while
two halves of the system quietly trained and predicted against different objects.
So the tests below assert object identity rather than type or truthiness.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import ml.advanced_predictor as canonical
import ml.predictor as alias


class TestTheAliasIsTheSameObjectNotACopy:
    """Identity, not equality. `is`, never `==` or `isinstance`."""

    def test_get_predictor_is_the_canonical_function(self) -> None:
        assert alias.get_predictor is canonical.get_predictor

    def test_advanced_predictor_is_the_canonical_class(self) -> None:
        assert alias.AdvancedPredictor is canonical.AdvancedPredictor

    def test_hybrid_ensemble_predictor_is_the_canonical_class(self) -> None:
        assert alias.HybridEnsemblePredictor is canonical.HybridEnsemblePredictor

    def test_both_paths_return_one_shared_instance(self) -> None:
        """The contract the module exists for, exercised rather than inspected.

        A wrapper that constructed its own predictor would pass every test
        above that checks a type, and fail this one.
        """
        assert alias.get_predictor() is canonical.get_predictor()

    def test_the_singleton_survives_repeated_calls(self) -> None:
        """A factory dressed as a singleton hands a fresh, untrained model to
        whichever caller happens to ask second."""
        assert alias.get_predictor() is alias.get_predictor()


class TestThePublicSurface:
    def test_all_names_it_exports_are_importable_from_here(self) -> None:
        """`__all__` is a promise to `from ml.predictor import *`. A name listed
        there and absent is an ImportError at a caller's startup."""
        for name in alias.__all__:
            assert hasattr(alias, name), f"__all__ promises {name!r} and the module does not define it"

    def test_it_exports_exactly_the_three_documented_names(self) -> None:
        assert set(alias.__all__) == {"AdvancedPredictor", "HybridEnsemblePredictor", "get_predictor"}

    def test_it_adds_no_logic_of_its_own(self) -> None:
        """ "This module exists so legacy import paths continue to work without
        duplicating any logic." Every exported name must therefore come from the
        canonical module, not be defined here."""
        for name in alias.__all__:
            assert getattr(alias, name) is getattr(canonical, name), (
                f"{name} is not the canonical object — the alias has grown logic"
            )
