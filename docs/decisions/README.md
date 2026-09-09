# Architecture Decision Records

One numbered, immutable file per decision that constrains future work.
Group 3 Chapter 6.

```bash
python scripts/adr.py --list          # what has been decided
python scripts/adr.py --check         # validate every record (runs in pre-commit)
python scripts/adr.py new "Title"     # start the next record
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

## Registration

Each record is registered in `docs/REGISTRY.toml` at **T3** — a dated record,
which claims no authority over a subject and therefore cannot collide with
another document. `python scripts/docs_registry.py --generate` picks up a new
one; set its tier, owner and state by hand.
