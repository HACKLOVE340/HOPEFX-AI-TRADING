# 0020. The decision ledger is a second artefact, not an amendment

- Status: accepted
- Date: 2026-09-13

## Context

`GROUP4_CONSTITUTION.md` Chapter 9 requires two things, not one:

> Maintain an Architecture Decision Registry and Decision Ledger recording
> context, alternatives, evidence, decision, expected outcome, actual outcome and
> lessons.

Seven fields. `scripts/adr.py` enforced five — context, options, decision,
consequences, evidence — and nothing asked for **actual outcome** or **lessons**.
Measured on 2026-09-13: 0 of 19 records carried either. The chapter's own
sentence says why that matters: *"a decision record that stops at 'decision' is a
minute; one that returns to compare expectation against result is memory."*

The constraint that makes this awkward is Group 3 Chapter 3, enforced by
`adr.py::immutability_problems` against git: **an accepted record is immutable
but for its status line.** So "come back later and write what happened" cannot be
an edit to the record — the mechanism that would carry the ledger is the one
thing the registry forbids.

## Options considered

- **A second artefact keyed by decision number** — `docs/decisions/outcomes/NNNN.md`,
  deliberately mutable, validated by the same gate. Costs: two files per decision
  instead of one, and a reader must open both to get the whole story; one more
  directory for `docs_registry.py` to account for.
- **An explicitly permitted amendment section** — an `## Outcome` heading inside
  the record that `immutability_problems` is taught to ignore. Costs: the
  immutability rule acquires an exception, and every future reader of that rule
  has to learn where the line is. It also makes the diff of an accepted record
  legitimately non-empty, so the git-based check can no longer say "this file
  changed, therefore something is wrong" — it must reason about *which part*
  changed, which is exactly the kind of check that silently stops working.
- **Do nothing and rely on the `Expected-Effect:` commit trailer** (ADR 0012).
  Costs: the trailer is the *expected* half only, nothing reads it back, and it
  is keyed to a commit rather than to a decision — so it cannot answer "how did
  0014 turn out".

## Decision

**The second artefact.** `docs/decisions/outcomes/NNNN.md`, one per decision that
was actually taken, carrying `## Expected`, `## Actual outcome` and `## Lessons`.

Immutability stays absolute, with no exception to argue about later. The record
says what was known when the choice was made and never changes; the outcome says
what happened and changes as more happens. Two artefacts because they have two
different truth conditions — that is the reason, not tidiness.

Three rules stop it from becoming a box to tick, and each is an instance of a
defect this repository has already shipped:

1. **`pending` is not `observed`.** A decision taken four days ago has no
   observable outcome, and demanding one manufactures a placeholder. So a
   pending entry is honest and is counted separately — eighteen placeholders
   must not read as a complete ledger.
2. **A pending review comes due.** `- Review by: YYYY-MM-DD` is mandatory while
   pending, and a date in the past fails `adr.py --check`. An obligation that
   never falls due is a measurement that cannot fail
   (`.claude/skills/hopefx-dead-controls`, shape 3).
3. **A `proposed` record is owed nothing.** Nothing has happened yet.

The gate's teeth are scoped as the `adr-check` hook already scopes them: it runs
on commits touching `docs/decisions/`. An overdue review therefore blocks
decision-record work rather than every commit in the repository. That is
deliberately weaker than a repo-wide ratchet and deliberately stronger than ADR
0012's pure warning, and it is the one part of this record most likely to need
revisiting — if reviews go overdue and nobody notices, the honest response is to
widen the hook's scope, not to lower the standard.

## Consequences

Makes "how did 0014 turn out?" a question with a file to open, and makes the
answer falsifiable — writing the eighteen back-fill entries immediately surfaced
two decisions that were **recorded and never applied** (0014's nightly tier does
not exist; 0016's re-subjecting was never made in `docs/REGISTRY.toml`). Neither
was visible from the registry, because a registry records intent.

Makes a second file per decision, and a reader who opens only the record gets the
decision without its result. The record's number is the key, so the outcome is
one predictable path away, but it is a real cost.

Makes the ledger's own honesty measurable: `adr.py --check` prints
`N observed, M pending`, and `tests/unit/test_adr_outcome_ledger.py` asserts that
observed outnumbers pending — so back-filling placeholders cannot close this.

## Evidence

```bash
python scripts/adr.py --list       # every decision, with how it turned out
python scripts/adr.py --check      # 0 problems, and the observed/pending split
python scripts/correction_register.py --id ADR-LEDGER
pytest tests/unit/test_adr_outcome_ledger.py -q
```

Measured before this record: 0 of 19 records carried an actual outcome or
lessons, and `REQUIRED_SECTIONS` asked for neither. The two findings the
back-fill surfaced are measured in `outcomes/0014.md` and `outcomes/0016.md`.
