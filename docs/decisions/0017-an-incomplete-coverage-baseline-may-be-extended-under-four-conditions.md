# 0017. An incomplete coverage baseline may be extended, under four conditions

- Status: accepted
- Date: 2026-09-10

## Context

`docs/COVERAGE_UNMEASURABLE.txt` records modules below the per-module coverage
floor so that touching them reports debt instead of blocking. Its header said
the list **may only shrink**.

That stopped being true on 2026-09-09, and by 2026-09-10 five entries had been
added anyway — each with a note explaining why. The note added with the third
batch states the cause plainly:

> THE BASELINE IS INCOMPLETE. It was adopted from a subset of the repository,
> so any module outside that subset blocks the first commit that touches it,
> however small the change — which turns the ratchet from "debt may only
> shrink" into "you may not touch an untested file", and makes recording the
> debt the only way through.

A module outside the seed is **not new debt**. It was already below the floor;
it is unrecorded only because the seed never looked at it. The seed was static
by design — "every module whose resolved test file never mentions it" — because
measuring all 539 candidates takes about two hours.

The sixth case forced the rule to be written down. `api/ws_live.py` measures
34% and was outside the seed, so the gate blocked a finished, tested security
fix: `LiveConnectionManager.subscribe()` added any channel name it was handed
without checking who was asking, and the support desk needed a channel only
operators could join. The module is 2,425 lines; the fix is 40.

A rule that everyone breaks with an apology is not a rule, and a header that
contradicts its own file teaches readers to skim both.

## Options considered

- **Keep "may only shrink" and honour it.** Every commit touching an unseeded
  module must first raise it past 80%. Costs: for `api/ws_live.py` that is ~500
  statements to reach a 40-line fix. In practice the escape is
  `SKIP_COVERAGE_GATE=1`, which skips the gate for *every* file in the commit
  rather than recording one honest number — strictly worse, and invisible in
  review. The rule's real effect is to select for the louder bypass.

- **Keep "may only shrink" and keep quietly breaking it.** Costs: this is the
  status quo — five undocumented-by-policy additions, each individually
  justified in a comment nobody reads before adding a sixth. The header stays
  false. A successor cannot tell a legitimate recording from an allowlist entry,
  which is precisely how a ratchet stops being one.

- **Drop the constraint; entries may be added freely.** Costs: the list becomes
  an allowlist. Any module can be recorded to silence the gate, and no evidence
  distinguishes "this was already in debt" from "I did not want to write tests".

- **Adopt the complete baseline now** (`pre_commit_coverage.py --adopt`).
  Costs: about two hours of measurement, and it would legitimise the current
  debt in one step rather than case by case — but it does not answer what
  happens the *next* time the seed and reality disagree, and the same question
  returns with the next module.

## Decision

**The list shrinks by default. It may grow only when all four of these hold,
and the entry records them:**

1. the module was **already below the floor before the change** — proven on a
   clean tree or a worktree, not asserted;
2. the change **does not lower** its coverage;
3. the **measured number** is written beside the entry; and
4. the **owner has agreed**, or this ADR is cited as the standing agreement.

Growth under those four is recording pre-existing debt. Growth without them is
an allowlist, and the difference is evidence.

The header of `docs/COVERAGE_UNMEASURABLE.txt` is corrected to say this, so the
file stops contradicting itself.

**Adopting a complete baseline remains the real fix** and stays filed. This ADR
governs the interim, and it also governs what happens after adoption whenever a
module is found outside whatever set was measured.

## Consequences

**Easier.** A small fix to a large, poorly-tested module can land with its debt
recorded and visible, instead of being abandoned or pushed through with
`SKIP_COVERAGE_GATE=1` — which is the outcome the constraint was producing.

**Harder, deliberately.** Condition 1 requires a measurement on a clean tree,
so "it was already bad" has to be shown rather than claimed. Condition 2 means
a change that lowers coverage cannot be recorded at all — that is new debt and
still blocks.

**Unchanged.** Every entry keeps its pressure: a recorded module that reaches
the floor **blocks** with one instruction — delete the line. That is what makes
this a ratchet rather than a permission list, and nothing here weakens it.
Verified by `tests/unit/test_coverage_gate_ratchet.py`.

**The risk this accepts.** The four conditions are a policy, not a mechanism —
the gate cannot check them. A future entry could satisfy the letter and not the
spirit. The mitigation is that each entry states its evidence in the file, where
a reviewer sees it, and that this ADR names what evidence is required.

## Evidence

`api/ws_live.py`, the entry that forced this:

```bash
# Condition 1 — already below the floor, before the change.
git worktree add --detach /tmp/wt-base b932dd2
cd /tmp/wt-base && python scripts/pre_commit_coverage.py api/ws_live.py
#   FAIL api/ws_live.py: coverage 34% < 80% threshold

# Condition 2 — the change raises it.
python scripts/pre_commit_coverage.py api/ws_live.py
#   DEBT api/ws_live.py: 35% < 80% ... Not permission — raise it and delete the line.
```

Condition 3: recorded in the file as `34% -> 35%`, dated.
Condition 4: owner decision, `docs/ai/MASTER_OUTSTANDING.md` §A6, option 1.

The pressure still exists — a recorded module at or above the floor blocks:

```bash
pytest tests/unit/test_coverage_gate_ratchet.py -q      # 18 tests
```

Two related findings from the same day, both showing the gate's exclusions were
accidents rather than decisions: `core/router_registry.py` was excluded by
`.coveragerc` under a justification that was false when written (§E37), and the
gate reported that exclusion as a fault in the test (fixed in the same commit).
