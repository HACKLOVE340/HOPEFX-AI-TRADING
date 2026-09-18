# 0016. Root documents are authoritative; ARCHITECTURE is re-subjected

- Status: accepted
- Date: 2026-09-09

## Context

`scripts/docs_registry.py --check` reports three subjects claimed by two
documents each — the last contested subjects in the registry:

| Subject | Root | `docs/` |
|---|---:|---:|
| architecture | `ARCHITECTURE.md` 199 lines | `docs/architecture.md` 600 |
| contributing | `CONTRIBUTING.md` 159 | `docs/CONTRIBUTING.md` 375 |
| deployment | `DEPLOYMENT.md` 684 | `docs/DEPLOYMENT.md` 842 |

Group 3 Chapter 1 opened on exactly this: duplicate contracts where nothing
marks which is authoritative.

## Options considered

- **Root wins for all three.** Costs: the `docs/` copies are longer in every
  pair, so length must not be mistaken for authority — and it is not, since
  `docs/DEPLOYMENT.md` still carries the v1.17 Python claim corrected in the
  root copy on 2026-09-09.
- **`docs/` wins for all three.** Costs: GitHub surfaces the root
  `CONTRIBUTING.md` in its pull-request UI regardless of what a registry says,
  so this option makes the tool and the register disagree permanently.
- **Merge each pair.** Truly one document per subject. Costs: three careful
  merges, each risking dropped content, and it discards a split that is
  deliberate — see the decision below.

## Decision

**Root is authoritative for `contributing` and `deployment`.**

* `CONTRIBUTING.md` — GitHub links it from the PR UI. The authoritative copy has
  to be the one a contributor is actually shown.
* `DEPLOYMENT.md` — corrected on 2026-09-09; the `docs/` copy still states
  "Python 3.10, 3.11, or 3.12" against a 3.12-only production image.

**`architecture` is not a duplicate and is re-subjected.** `ARCHITECTURE.md`
opens by saying it documents canonical module locations and resolves naming
ambiguities, and points at `docs/architecture.md` for the full system
architecture. Two documents, two subjects, one of them mislabelled in the
registry. `ARCHITECTURE.md` takes the subject `architecture_module_map`.

## Consequences

Takes the registry's contested-subject count from 3 to 0 and closes Group 3
item 8.

Makes the longer `docs/` copies of contributing and deployment subordinate.
They are not deleted — the owner's standing instruction is that nothing is
removed — so each is marked `superseded` in the registry with its successor
named, and carries a line at the top pointing at the authoritative copy. A
subordinate document with no such line is the thing that caused this collision.

Re-subjecting `ARCHITECTURE.md` means a search for "architecture" now finds
`docs/architecture.md`. That is the intended answer, and the module map is
reached from CLAUDE.md's routing table where a contributor actually looks.

## Evidence

    docs_registry.py --check   ->  3 contested subjects (baselined)
    ARCHITECTURE.md:3          ->  "For the full system architecture see
                                    docs/architecture.md. This file documents
                                    canonical module locations..."
    docs/DEPLOYMENT.md:3       ->  "Python 3.10, 3.11, or 3.12 required"
    DEPLOYMENT.md:3            ->  "Python 3.12 required (matches python:3.12-slim)"
