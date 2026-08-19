# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_training_manager_dispatch.py
============================================
`TrainingManager._dispatch_training` could not train two of the four models it
claimed to handle, and advertised two more it cannot dispatch at all.

    if model == "advanced_oos":
        from ml.train_advanced import retrain_advanced_predictor   # not defined
    if model == "lstm_signal":
        from ml.lstm_signal_layer import retrain_lstm              # not defined

Neither symbol exists. `ml/train_advanced.py` exposes a CLI `main()` and no
programmatic entry point; `ml/lstm_signal_layer.py` is inference-only —
`_load`, `_build_sequence`, `predict`, `stats`, `is_available` — with no
training code anywhere in it. Unlike most of the defects in this backlog these
imports are **unguarded**, so each raised `ImportError` straight into
`_run_training`'s handler, which marked the job "failed" and stored the message.
The retrain feature has therefore never worked for those two model types.

A third problem sat beside it: `_KNOWN_MODELS` lists six models —
`advanced_oos`, `lstm_signal`, `rl_ppo`, `hybrid_ensemble`, `rf_macro`,
`xgb_macro` — while `_dispatch_training` branches on only four. `rf_macro` and
`xgb_macro` pass the caller's membership check and then fall through to
`raise ValueError("Unknown model for training: ...")`, which is confusing
precisely because the caller was told they were known.

What changed:

* `ml.train_advanced.main()` now takes an optional argv list, so it can be
  driven programmatically, and `retrain_advanced_predictor()` wraps it with the
  production settings AGENTS.md documents (`--years 50 --oos-years 4
  --stacking`). This is the real fix — `advanced_oos` can now be retrained.

* `lstm_signal`, `rf_macro` and `xgb_macro` raise a clear, actionable error
  naming why they cannot be trained, instead of an ImportError about a symbol
  nobody will find or a "Unknown model" for a model that was just advertised as
  known. The LSTM has no training code and, per AGENTS.md's model table, has
  never been trained; inventing a trainer for it is not a rename and is not
  done here.

These tests never execute a training run — a production retrain is 10-60
minutes. They check the entry point exists and is callable, and that the
undispatchable models fail in a way an operator can act on.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_train_advanced_exposes_a_programmatic_entry_point():
    """The name _dispatch_training imports must exist."""
    from ml import train_advanced

    assert hasattr(train_advanced, "retrain_advanced_predictor"), (
        "ml.train_advanced has no retrain_advanced_predictor — TrainingManager's "
        "advanced_oos job raises ImportError on every run"
    )
    assert callable(train_advanced.retrain_advanced_predictor)


def test_main_accepts_an_argv_list_so_it_can_be_driven_in_process():
    """parse_args(None) reads sys.argv, which a worker thread must not depend on."""
    from ml.train_advanced import main

    params = inspect.signature(main).parameters
    assert "argv" in params, "main() cannot be called programmatically without an argv parameter"
    assert params["argv"].default is None, "argv must default to None so CLI behaviour is unchanged"


def test_retrain_advanced_predictor_does_not_require_arguments():
    """_dispatch_training calls it with no arguments."""
    from ml.train_advanced import retrain_advanced_predictor

    for name, p in inspect.signature(retrain_advanced_predictor).parameters.items():
        assert p.default is not inspect.Parameter.empty, f"parameter {name!r} has no default"


def test_dispatch_no_longer_imports_symbols_that_do_not_exist():
    """Regression: both imports were unguarded and raised on every run."""
    from ml.training_manager import TrainingManager

    source = inspect.getsource(TrainingManager._dispatch_training)
    assert "from ml.lstm_signal_layer import retrain_lstm" not in source, (
        "retrain_lstm does not exist in ml.lstm_signal_layer, which is inference-only"
    )


def test_lstm_signal_fails_with_an_actionable_message():
    """It cannot be trained; say so rather than raising ImportError."""
    from ml.training_manager import TrainingManager

    mgr = TrainingManager.__new__(TrainingManager)
    with pytest.raises(Exception) as excinfo:
        mgr._dispatch_training("lstm_signal")

    message = str(excinfo.value).lower()
    assert not isinstance(excinfo.value, ImportError), "still failing on a missing symbol"
    assert "lstm" in message
    assert any(word in message for word in ("no training", "not trained", "inference")), (
        f"message does not tell the operator why: {excinfo.value!r}"
    )


@pytest.mark.parametrize("model", ["rf_macro", "xgb_macro"])
def test_advertised_but_undispatchable_models_say_so(model: str):
    """_KNOWN_MODELS lists them, so 'Unknown model' is the wrong answer."""
    from ml.training_manager import _KNOWN_MODELS, TrainingManager

    assert model in _KNOWN_MODELS, "fixture assumption: the model is advertised as known"

    mgr = TrainingManager.__new__(TrainingManager)
    with pytest.raises(Exception) as excinfo:
        mgr._dispatch_training(model)

    message = str(excinfo.value).lower()
    assert "unknown model" not in message, (
        f"{model} is listed in _KNOWN_MODELS but reported as unknown — the caller was told it was known"
    )
    assert model in message


def test_a_genuinely_unknown_model_still_reports_unknown():
    """The other half of the pair, so the check above cannot pass by always failing."""
    from ml.training_manager import TrainingManager

    mgr = TrainingManager.__new__(TrainingManager)
    with pytest.raises(ValueError, match="Unknown model"):
        mgr._dispatch_training("not_a_real_model")
