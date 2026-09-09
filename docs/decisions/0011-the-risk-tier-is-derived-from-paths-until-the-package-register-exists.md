# 0011. Derive the change-record risk tier from paths until the package register exists

- Status: accepted
- Date: 2026-09-09

## Context

Group 2 Chapter 6 sources a change record's "packages touched" from Chapter 1's
**package ownership register**, and derives the risk tier from that. The register
does not exist — it is ranked item 10, still open — so the tier had to come from
somewhere else or the chapter could not be built at all.

## Options considered

- **Build Chapter 1's register first.** Costs: it is a High-ranked item in its
  own right, needing an owner per package and enforced import edges, and it
  blocks a change record that is otherwise ready. It would also be built with no
  consumer, which is how a register becomes a file nobody updates.
- **Derive the tier from path prefixes, and say so.** Costs: weaker than a
  register — a path table cannot express ownership, and it needs editing when a
  package is added. Worse, if it is presented as the register, Chapter 1 looks
  delivered when it is not.
- **Refuse to assign a tier at all** and require the author to state one. Costs:
  a field the author types is a field the author gets wrong under time pressure,
  and the whole point of the record is that it is generated rather than written.

## Decision

Derive from path prefixes, and name the derivation: `TIER_SOURCE = "path-prefix"`,
printed on every report, with the module docstring stating plainly that Chapter
1's register does not exist and that this table is what it will replace.

Unclassified paths are `unknown`, never `presentation`, and `unknown` requires an
expected effect exactly as `core` does.

## Consequences

Makes Chapter 6 shippable now, with the one field that matters — the prediction —
enforced today rather than after item 10.

Makes the table a thing to maintain: a package added without an entry lands in
`unknown` and demands a prediction until somebody classifies it. That is the
intended direction of the error, and it is the reason `unknown` outranks
`presentation` in `TIER_ORDER`.

Makes a claim that must not be quietly dropped. If a later change removes
`TIER_SOURCE` or the docstring's statement, this record has been reversed in
substance: the repository would then imply a register it does not have, which is
exactly the shape §E20 had to correct in §E5.

## Evidence

`tests/unit/test_change_records.py::test_the_mapping_does_not_claim_to_be_the_register`
asserts both the marker and the docstring. Running it against real history shows
the derivation working: the ledger commit reports `core` (it touches `risk/`),
the §18 commit reports `ai`, and both name `path-prefix` as the source.
