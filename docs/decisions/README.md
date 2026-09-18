# Architecture Decision Records

One numbered, immutable file per decision that constrains future work.
Group 3 Chapter 6.

```bash
python scripts/adr.py --list          # what has been decided, and how it turned out
python scripts/adr.py --check         # validate every record and outcome (runs in pre-commit)
python scripts/adr.py new "Title"     # start the next record
python scripts/adr.py outcome 7       # start (or find) 0007's outcome
```

## What belongs here

A decision where a reasonable engineer might later ask *"why on earth is it like
this?"* — and where at least two paths were genuinely considered.

**An ADR with one option is not an ADR.** If only one path was on the table the
record documents an implementation, not a decision, and belongs in a T2
reference instead. `adr.py --check` enforces this.

## Why not keep using `docs/ai/AI_HUB_DECISIONS.md`

That file is a good document and not a system, and Group 3 names its three
limits exactly: it cannot be pointed at from a code comment, it cannot be
superseded in part, and it grows without bound. It stays — the narrative is
worth reading — but a decision anyone will cite as precedent gets a number here.

## The rules, and the defect behind each

| Rule | Why |
|---|---|
| Two options minimum | One option is justification written after the fact |
| Every section, none empty | An empty heading is what a template leaves behind, and it passes a naive check |
| Immutable once accepted | A record that can be rewritten is a record of what we *currently believe* we decided |
| A supersede must resolve | "Superseded by 0042" pointing at nothing tells a reader their answer exists somewhere |
| Gapless numbering | So `see 0007` is stable for ever, and a gap cannot hide a deleted record |

The only edit an accepted record may carry is its status becoming
`superseded by NNNN`. The supersede itself is a **new** record — see 0007 → 0009,
which is a decision this repository genuinely reversed once its premise turned
out to be false.

Immutability is checked against git rather than a hash manifest: a manifest is a
second file to edit, and the history is already authoritative.

## The other half — `outcomes/`

A record says what was chosen. `outcomes/NNNN.md` says what happened.

`GROUP4_CONSTITUTION.md` Chapter 9 asks for a Decision Registry **and** a
Decision Ledger, across seven fields. The five above are the registry; **actual
outcome** and **lessons** are the ledger, and until 2026-09-13 nothing asked for
either — so every record was a minute and none was memory.

It could not be a section inside the record: an accepted record is immutable, and
buying the second half by relaxing the first would have destroyed the only
evidence of what was known at the time. So the outcome is a second, deliberately
mutable file keyed by number. **ADR 0020** records that choice and the two
options it beat.

| Rule | Why |
|---|---|
| Every `accepted` or `superseded` record owes an outcome | A `proposed` record is owed nothing — nothing has happened yet |
| `## Expected`, `## Actual outcome`, `## Lessons`, none empty | Same reason as the record's sections |
| `pending` is counted separately from `observed` | Eighteen placeholders must not read as a complete ledger |
| `pending` needs `- Review by: YYYY-MM-DD`, and an overdue one **fails** | An obligation that never falls due is a measurement that cannot fail |
| Outcome files are mutable, and that is the point | You come back and write in them. The *record* stays immutable |

**Write `## Expected` as something a reader can go and test.** That is what makes
the entry worth having. Restating a decision's `## Consequences` as a number or a
command turned up two decisions that had been recorded and never applied — 0014's
nightly test tier does not exist, and 0016's registry re-subjecting was never
made. Both were checkable in seconds and both were false; the entries whose
expectation was prose found nothing.

```bash
python scripts/adr.py --list     # every decision, with observed / pending / no outcome
pytest tests/unit/test_adr_outcome_ledger.py -q
```

## Registration

Each record is registered in `docs/REGISTRY.toml` at **T3** — a dated record,
which claims no authority over a subject and therefore cannot collide with
another document. `python scripts/docs_registry.py --generate` picks up a new
one; set its tier, owner and state by hand.
