# 0018. A module unit tests import may not be excluded from coverage

- Status: accepted
- Date: 2026-09-10
- Supersedes, in part: the `.coveragerc` convention of recording measured
  coverage in a comment beside an exclusion

## Context

`.coveragerc`'s `[run] omit` list carried a stated reason on most of its
entries: *"requires full app context; covered by integration/e2e tests, not
unit tests."*

That reason was checked three times and was false all three:

| When | Module | What was actually true |
|---|---|---|
| §E37 | `core/router_registry.py` | nine unit tests exercised `register_routers` directly |
| §E47 | `core/startup_factories.py` | 59 unit tests across two files |
| §E49 | **18 of 23** concrete entries | `execution/engine.py` had 11 unit tests, `brokers/oanda.py` 7, `execution/fix_adapter.py` 6 |

The first two were found by accident — a commit happened to touch the file and
the gate blocked it. Nobody was checking. Eighteen at once is not a run of bad
luck; the list was an accumulation that nothing re-examined, and each entry
inherited a justification written for a different file.

**What an exclusion costs, and why it is worse than recorded debt.** A recorded
module in `docs/COVERAGE_UNMEASURABLE.txt` reports its real number on every
commit that touches it, and the gate **blocks** the moment it reaches the floor,
with one instruction: delete the line. An excluded module reports nothing. It
can show neither debt nor progress, and it blocks any commit that touches it
with a diagnosis that points at a missing import which is not missing — which is
how `SKIP_COVERAGE_GATE=1` gets typed.

On this repository the excluded set included `execution/fix_adapter.py`,
`execution/engine.py`, `core/decision/HOPEFXDecisionEngine.py`,
`core/risk/advanced_engine.py` and the four OANDA broker files. That is the
order path, the central decision pipeline, a risk engine, and the broker for the
next live-trading milestone — the code that moves the money, with a coverage
figure nobody could see.

An earlier pass had already improved part of this: it replaced the false
justification on `execution/*` with the modules' **measured** coverage, written
into a `.coveragerc` comment. That was right in spirit and is what this decision
builds on. Its limitation is mechanical — a number in a comment has no pressure
behind it. It goes stale in silence, and nothing blocks when the module clears
the floor.

## Options considered

- **Keep the exclusions, keep annotating them with measured numbers.** Costs:
  the numbers are snapshots maintained by hand; nothing detects drift; nothing
  blocks on success. It is the status quo of the earlier pass, and the reason
  five of the six figures in that comment were already stale.

- **Lift the false entries, record the real numbers as debt.** Costs: 19
  modules join `COVERAGE_UNMEASURABLE.txt` and the list gets visibly longer —
  which reads like a regression and is the opposite. Nothing about the code
  changed; the debt was always there, and it is now countable.

- **Lift them and require each to reach 80% first.** Costs: a project of
  unknown size on `execution/execution.py` at 17.75%, blocking unrelated work.
  ADR 0017 exists precisely so pre-existing debt can be recorded rather than
  blocking, provided it is evidenced.

- **Delete the omit list entirely.** Costs: `core/acceleration/gpu_engine.py`
  genuinely requires CUDA, which CI does not have. A rule that ignores a real
  constraint gets bypassed wholesale.

## Decision

**A module that unit tests import may not be excluded from coverage.** If unit
tests reach it, its coverage is measurable, and an exclusion is hiding a number
rather than acknowledging an impossibility.

An exclusion may remain only when its reason is a property of the **machine** or
of the module's **dependencies** — never a claim about the test suite, which is
the claim that kept turning out false. Each surviving entry is listed in
`DELIBERATE` in `tests/unit/test_coveragerc_exclusions_are_honest.py`, and that
test **re-checks on every run** that no unit test has started importing it. An
allowlist nobody re-checks becomes a permission list.

Everything else moves to `docs/COVERAGE_UNMEASURABLE.txt` under ADR 0017, with
its measured number, where the ratchet acts on it.

This is enforced, not documented: `test_coveragerc_exclusions_are_honest.py`
fails on any entry a unit test imports — including via
`patch("module.attribute")`, since patching by string imports the module, which
is how `core/metrics.py` reached the deliberate list on the first pass of this
very audit.

## Consequences

**Easier.** The money path has a visible coverage figure for the first time.
Raising any of these modules past 80% now produces a blocking instruction to
delete its line, so progress is recorded rather than invisible.

**Harder, deliberately.** Adding an exclusion now requires a reason that
survives an automated check. "Covered by integration tests" is no longer
assertable about a module unit tests import.

**Visibly worse before better.** `COVERAGE_UNMEASURABLE.txt` grows by 19 lines.
That is nineteen numbers that previously did not exist, not nineteen new
problems.

**The risk this accepts.** The gate checks whether unit tests *import* a module,
not whether they *meaningfully exercise* it. A module imported once and never
called would pass this check while its exclusion stays morally false. The
mitigation is the per-module coverage gate itself: once lifted, the real number
is visible, and a number near zero says exactly that.

## Evidence

```bash
# The audit that forced this — 18 of 23 concrete entries had unit importers.
pytest tests/unit/test_coveragerc_exclusions_are_honest.py -q

# The surviving exclusions, re-checked every run:
#   core/acceleration/gpu_engine.py   CUDA hardware, absent in CI
#   ml/rl_agent.py                    heavy optional deps, no unit importer
#   core/background_tasks.py          no unit importer
#   core/email_webhook.py             no unit importer
```

Two related findings from the same audit, both showing the list was inherited
rather than reasoned: `core/acceleration/__init__.py` was excluded as
"hardware-dependent" while `tests/unit/test_core_acceleration.py` imports it
without a GPU (it guards on `HAS_TORCH`); and `core/metrics.py` was reached by
`patch("core.metrics.SHARPE_N_TRADES")`, a form no import-statement search
finds.
