# 0012. The change-record gate warns rather than blocks

- Status: accepted
- Date: 2026-09-09

## Context

Group 2 Chapter 6 requires a stated expected effect for `core`-tier changes and
sets the KPI at 100%. Implemented literally, that is a `commit-msg` hook which
refuses any commit touching the trading path, CI configuration or an
unclassified package without an `Expected-Effect:` trailer.

Measured against this session's own history, that would have refused 4 of the
last 12 commits. It is a real change to how the owner commits, on a repository
where the owner is the only committer.

## Options considered

- **Block, per the chapter.** Costs: every trading-path commit stops until a
  prediction is typed. The chapter's target is met by construction — and a gate
  that interrupts the owner's own workflow is the kind that gets bypassed, which
  is how `SKIP_COVERAGE_GATE=1` becomes habitual. §E20 is this repository's own
  example of a gate switched off rather than satisfied.
- **Warn, and measure.** Costs: the KPI will sit below 100% and the chapter's
  target is not met. A gate that only warns is a gate people learn to scroll
  past — the objection is real and this record does not pretend otherwise.
- **Warn for now, block after a grace period.** Costs: a date nobody is
  accountable for, which arrives while somebody is mid-incident. This repository
  has ratchets, not deadlines, for exactly that reason.

## Decision

**Warn.** The owner chose this on 2026-09-09 when asked directly.

Three things keep it from being decorative, and each is asserted in
`tests/unit/test_change_record_gate_injections.py`:

1. the warning names the exact trailer to add, so acting on it is cheaper than
   ignoring it;
2. `CHANGE_RECORD_ENFORCE=1` turns the same finding into a block with no code
   change, so the policy is configuration and can be switched on in CI, for one
   branch, or permanently, without reopening this;
3. `--report` measures the KPI over a git range, so "is anyone writing
   predictions?" is a number rather than an opinion. **A warning whose effect is
   never measured is exactly what the objection is about.**

`validate()` is unchanged by the policy. It reports the problem either way: the
decision is about the exit code, never about the truth.

## Consequences

Makes the record's adoption voluntary and therefore visible — the first
`--report` reads **20% (1 of 5)**, which is a real starting number rather than a
target met by force.

Makes the KPI a thing to watch. If coverage does not rise, the warning is being
scrolled past and the honest response is to enforce, not to lower the target.
That is what option three would have scheduled and what this leaves to
observation instead.

Makes `docs/GATE_EVIDENCE.toml` carry a caveat it did not before: this gate is
discovered and counted like the others, and unlike the others it does not block
by default. Recorded in its `injected` note, because a ledger implying twenty-five
blocking gates when one is advisory is the same fabrication the ledger exists to
prevent.

## Evidence

    python -m deployment.change_records --report --range HEAD~12..HEAD
    changes 12 · needing a prediction 5 · with one 1 · coverage 20%

Six tests cover the policy directly: warn by default, the warning's content, the
switch being named in it, enforcement blocking, enforcement not blocking a
compliant change, and `validate()` reporting the problem regardless.
