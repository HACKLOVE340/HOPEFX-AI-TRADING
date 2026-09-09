# 0014. Run the `slow` and `e2e` tiers nightly, not per-PR

- Status: accepted
- Date: 2026-09-09

## Context

Decision A3. `pytest -m "slow or e2e"` collects **209 tests**. Both markers are
deselected in CI, always — so those 209 have never gated anything. They look
like coverage in the file tree and protect nothing.

Measured on 2026-09-09: 21,971 tests collected in total, 209 of them in this
tier.

## Options considered

- **Nightly, on a schedule.** Costs: a fixed daily CI spend, and a failure is
  found up to 24 hours after the commit that caused it rather than at review.
- **On every pull request.** Costs: 209 integration-heavy tests on every push.
  The feedback loop slows for every contributor on every change, and CI minutes
  scale with commit volume rather than with time.
- **Leave them skipped.** Costs: nothing to run, and 209 tests that exist purely
  as documentation. Worse than deleting them, because a reader counts them as
  protection.

## Decision

Nightly. The tier runs once a day on a schedule, not on pull requests.

## Consequences

Makes the 209 real: integration drift is caught within a day instead of never.
Keeps per-PR feedback at its current speed, which is what makes the fast suite
worth having.

Makes a new failure mode to design for — a nightly that fails and is ignored is
the same dead control in a different costume. The run must report somewhere a
person reads, and a persistent failure has to be treated as a broken build
rather than as weather.

Costs a fixed daily CI spend rather than one scaling with commit volume, which
is the trade being made.

## Evidence

    pytest -m "slow or e2e" --collect-only -q
    209/21971 tests collected (21762 deselected)

`.github/workflows/` deselects both markers in every job today.
