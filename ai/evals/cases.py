# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The committed eval suite.

Scoring in `ai/evals/suite.py` is exact string comparison, so every case is
written to have exactly one correct answer and that answer is a single token. A
case whose expected answer is a sentence measures a model's formatting rather
than its knowledge, and would fail the best model in the chain for putting a
full stop at the end.

**Two kinds of case, and the distinction is the point.**

*Instruction-following* cases check that the model does what it is told at all.
A model that cannot return one word when asked for one word will not respect a
tool contract either.

*Risk arithmetic* cases are marked `required`, which means `PromotionGate`
refuses promotion when they fail no matter how high the aggregate is. A model
that says a 15% drawdown is below a 10% limit is wrong in the direction that
loses money, and averaging that away against a dozen easy cases is exactly the
failure a required case exists to prevent.

This suite is deliberately small. It is a gate, not a benchmark: its job is to
catch a model that is broken or has been swapped for something weaker, and
every case costs a real model call against the budget.
"""

from __future__ import annotations

from typing import Final

from .suite import EvalCase

#: Cases whose failure blocks promotion regardless of the aggregate score.
#: Kept as a separate constant because `PromotionGate` takes the ids, and a
#: second hand-written list would be one more thing that can disagree — the
#: test suite asserts these match the cases marked `required` below.
REQUIRED_CASE_IDS: Final[tuple[str, ...]] = (
    "risk.drawdown_above_limit",
    "risk.position_exceeds_cap",
)

DEFAULT_CASES: Final[list[EvalCase]] = [
    # ── instruction following ────────────────────────────────────────────────
    EvalCase(
        id="follow.single_word",
        prompt="Reply with exactly one word and nothing else: the metal whose ticker is XAU. Answer with the metal's name only.",
        expect="gold",
    ),
    EvalCase(
        id="follow.no_prose",
        prompt="Answer with exactly one word, either YES or NO, and no punctuation: is 7 greater than 3?",
        expect="yes",
    ),
    # ── risk arithmetic: required ────────────────────────────────────────────
    EvalCase(
        id="risk.drawdown_above_limit",
        prompt=(
            "A trading account has a maximum drawdown limit of 10 percent. "
            "The account is currently down 15 percent from its peak. "
            "Answer with exactly one word, either ABOVE or BELOW: is the current "
            "drawdown above or below the limit?"
        ),
        expect="above",
        required=True,
    ),
    EvalCase(
        id="risk.position_exceeds_cap",
        prompt=(
            "An account has 100000 USD of equity and a maximum position size of "
            "5 percent of equity. A proposed position is worth 8000 USD. "
            "Answer with exactly one word, either ALLOW or REFUSE: should the "
            "risk gate allow or refuse this position?"
        ),
        expect="refuse",
        required=True,
    ),
    # ── domain comprehension ─────────────────────────────────────────────────
    EvalCase(
        id="domain.long_loses_when_price_falls",
        prompt=(
            "A trader is long XAUUSD. The price falls. Answer with exactly one "
            "word, either PROFIT or LOSS: what is the effect on the position?"
        ),
        expect="loss",
    ),
    EvalCase(
        id="domain.stop_loss_direction",
        prompt=(
            "A stop-loss on a LONG position is placed at a price. Answer with "
            "exactly one word, either ABOVE or BELOW: is that price above or "
            "below the entry price?"
        ),
        expect="below",
    ),
]


__all__ = ["DEFAULT_CASES", "REQUIRED_CASE_IDS"]
