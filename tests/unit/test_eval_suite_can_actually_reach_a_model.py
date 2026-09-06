# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The eval suite's real path to a model, which nothing had ever run.

`ai/evals/runner.py::_gateway_ask` is the default asker — the one used in
production, by the `/evals/run` endpoint and by the promotion gate that depends
on its score. Every existing test in `test_eval_runner.py` passes `ask=`, so
that function had never been executed. Measured, before this file existed:

    >>> run_default_suite().score
    0.0

It called `GatewayClient.complete(...)`, a method that does not exist — the
class exposes `call_sync` — and passed `operator=` to `ModelRequest`, which has
no such field. It also constructed `GatewayClient()` with no providers, so even
with the call fixed it could reach no vendor.

The damage is not that it raised. It is that `run_suite` marks a raising case
FAILED rather than aborting — correct behaviour, since a model being
unreachable is a result about that model — so six exceptions became a 0.00
score, the promotion gate refused `score_below_bar`, and an operator reading
the report concluded the MODEL was failing every case.

A control that exists, is wired, is documented accurately, and cannot succeed.

These tests fail on the pre-fix tree: the suite scores 0.0 there no matter what
the vendor says.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Adapter:
    """A vendor that answers every eval case correctly."""

    supports_images = False
    supports_streaming = False

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, *, model, prompt, timeout_s, **_kw):
        self.prompts.append(prompt)

        class _R:
            text = ""
            cost_usd, tokens_in, tokens_out = 0.0001, 4, 2

        _R.text = _ANSWERS.get(prompt, "unknown")
        return _R()


#: The committed suite's own expected answers, keyed by prompt, so this test
#: measures the plumbing rather than restating the cases.
_ANSWERS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from ai.evals.cases import DEFAULT_CASES
    from ai.gateway import audit, breakers, budget

    _ANSWERS.clear()
    _ANSWERS.update({c.prompt: c.expect for c in DEFAULT_CASES})

    budget.reset_for_testing()
    audit.reset_for_testing()
    breakers.reset_for_testing()
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)
    yield
    budget.reset_for_testing()
    audit.reset_for_testing()
    breakers.reset_for_testing()


@pytest.fixture
def vendor(monkeypatch):
    """Put a working vendor behind the gateway's provider discovery."""
    adapter = _Adapter()
    monkeypatch.setattr(
        "ai.gateway.adapters.build_providers",
        lambda: {"anthropic": adapter, "openai": adapter, "google": adapter, "ollama": adapter},
    )
    return adapter


# ── the defect ────────────────────────────────────────────────────────────────


def test_the_default_asker_reaches_the_model_at_all(vendor):
    """No `ask=` injection. This is the production path."""
    from ai.evals.cases import DEFAULT_CASES
    from ai.evals.runner import _gateway_ask

    answer = _gateway_ask(DEFAULT_CASES[0])
    assert answer, "the default asker returned nothing"
    assert vendor.prompts, "the default asker never reached a vendor"


def test_the_committed_suite_can_score_above_zero(vendor):
    """The measured symptom: 0.00 against a vendor answering every case right."""
    from ai.evals.runner import run_default_suite

    report = run_default_suite()
    assert report.score == 1.0, f"scored {report.score} against a vendor that answers correctly"
    assert not report.failed_case_ids


def test_a_wrong_answer_is_still_a_failure(vendor):
    """The fix must not make the suite pass everything — which would be a worse
    defect than scoring zero, because the gate would then permit on no evidence."""
    _ANSWERS.update(dict.fromkeys(_ANSWERS, "definitely wrong"))
    from ai.evals.runner import run_default_suite

    report = run_default_suite()
    assert report.score == 0.0
    assert len(report.failed_case_ids) == report.total


def test_an_unreachable_vendor_still_scores_zero_rather_than_raising(monkeypatch):
    """A model being unavailable is a result about that model. The suite must
    not abort — that behaviour is right, and is what hid this defect."""
    monkeypatch.setattr("ai.gateway.adapters.build_providers", dict)
    from ai.evals.runner import run_default_suite

    report = run_default_suite()
    assert report.score == 0.0
    assert report.total > 0


# ── the eval run is a spender, and has to look like one ───────────────────────


def test_eval_spend_is_attributed_to_the_eval_operator(vendor):
    """Not to whoever clicked. Eval spend is a system cost with its own ceiling,
    and an operator's allowance should not be consumed by a suite run."""
    from ai.gateway import budget
    from ai.evals.runner import EVAL_OPERATOR, run_default_suite

    run_default_suite()
    assert budget.spent(EVAL_OPERATOR) > 0.0, "an eval run charged nobody"


def test_an_eval_run_is_audited_like_any_other_model_call(vendor):
    from ai.gateway import audit
    from ai.evals.runner import run_default_suite

    run_default_suite()
    assert audit.records(), "a suite of paid model calls left no audit trail"


def test_the_ceiling_binds_on_an_eval_run(vendor):
    """Otherwise the one path that makes six calls in a row is the one path
    that can run past the budget."""
    from ai.gateway import budget
    from ai.evals.runner import run_default_suite

    budget.set_limits(per_operator_usd=0.0, global_usd=0.0)
    report = run_default_suite()
    # Refused calls are failures, not exceptions — the suite still reports.
    assert report.score == 0.0
    assert not vendor.prompts, "the budget ceiling did not stop the eval run"
