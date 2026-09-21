# 0010. Where the decision ledger lives, and why it is not a second audit log

- Status: accepted
- Date: 2026-09-09

## Context

Group 3 Chapter 7 asks for one append-only ledger with one schema, "regardless of
who decided". Three things in this repository already record decisions in their
own shapes: `ai/gateway/audit.py` (model calls, with a hash chain),
`ai/improve/proposal.py` (AI-proposed changes), and pull requests (approvals).

The spec's own diagnosis is that this is *why* nobody can answer "what did the
platform decide today?" — so the risk is real that a fourth recorder makes it
four unanswerable questions instead of three.

## Options considered

- **Extend `ai/gateway/audit.py`.** Costs: that module records model *calls*, and
  it carries a hash chain and a retention policy shaped for that. A risk-gate
  refusal is not a model call; forcing it in either widens "call" until it means
  nothing, or adds a second entry kind the chain was not designed for.
- **Extend `ai/memory/store.py`.** Costs: memory is the operator's view of what
  the AI remembers, with `forget()`, correction and consent
  (`ai/memory/governance.py`). A governance record an operator can delete is not
  a governance record.
- **A new `ai/ledger/` package**, consuming the existing pieces rather than
  restating them: authority tiers from `ai/policy/roles.py`, calibration from
  `ai/core/calibration.py`, credential screening from `ai/guardrails/output.py`.
  Costs: a fourth place decisions are written, and the coverage KPI now has a
  denominator someone must keep honest.

## Decision

A new `ai/ledger/` package — `decisions.py` for Chapter 7, `outcomes.py` for
Chapter 8. It imports the tier list rather than restating it, so a second list
cannot drift; it delegates calibration rather than reimplementing it, so there is
one answer to "what is this actor's confidence worth"; and entries are frozen,
with an outcome attached by replacement rather than mutation.

Two rules differ deliberately from `scripts/adr.py`, and the difference is the
point:

* **One option is allowed.** An ADR with one option is justification written
  afterwards. An automated router legitimately has one candidate when the others
  are unavailable, and demanding a second would make the ledger describe a choice
  nobody had.
* **A prediction is required.** An ADR records what was decided; the ledger feeds
  Chapter 8, and without a stated expectation an observed outcome has nothing to
  be compared against.

## Consequences

Makes "what did the platform decide, and what did it refuse" a single query, and
gives `ai/core/calibration.py` the `resolve()` caller it was built for and never
had — every stated confidence was unscored, so `assess()` had nothing to assess.

Makes a fourth writer of decision-shaped records, which is only justified while
it *consumes* the other three rather than competing with them. If a later change
has the ledger keeping its own tier list or its own calibration, this decision
has been undone in substance while the file still exists.

Makes every call site responsible for not letting a governance write break the
thing it records. `risk/manager.py::_record_refusal` wraps it and logs at ERROR:
the ledger is a record, not a control.

## Evidence

`tests/unit/test_decision_ledger.py` (24), `test_ledger_outcomes.py` (20) and
`test_risk_refusals_reach_the_ledger.py` (8). The last is the one that matters:
it asserts the refusal still happens *first*, then that it is recorded, then that
a deliberately broken ledger cannot change what the money path decides — 5 of its
8 fail against the pre-wiring tree.
