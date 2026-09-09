# 0004. Bound delegation three ways, not by depth

- Status: accepted
- Date: 2026-09-09

## Context

§26 asks for runaway recursive delegation to be bounded. An agent that spawns
children that spawn children spends real money per node. Back-filled from
`AI_HUB_DECISIONS.md` Phase I4.

## Options considered

- **Depth alone.** Costs: 500 children at depth 1 are all inside a depth limit,
  and depth 4 by fan-out 8 is 4,680 nodes while breaching neither a depth nor a
  fan-out bound taken singly.
- **Depth, fan-out and total descendants, enforced separately.** Costs: three
  bounds to reason about and three to test.

## Decision

All three, separately. Enforced at `TaskGraph.add()` — creation is the last
moment at which nothing has been paid for. A breach refuses the child and keeps
the tree, because failing the tree discards finished work that was already
bought, wasting the spend the bound exists to protect.

## Consequences

Makes each failure mode visible on its own. Makes a test suite that must show
each bound doing work rather than riding behind a stricter neighbour — every one
of the three cases satisfies the other two comfortably.

## Evidence

An unknown parent is refused rather than adopted as a fresh root, which would
hand a runaway a whole new budget. `open_root()` is the only way a tree begins.
