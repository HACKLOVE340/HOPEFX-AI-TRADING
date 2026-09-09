# 0005. Hand a child a grant instead of sharing a ledger

- Status: accepted
- Date: 2026-09-09

## Context

§24 runs agents in isolated processes. A child process cannot read the parent's
in-memory budget ledger. Back-filled from `AI_HUB_DECISIONS.md` Phase I4.

## Options considered

- **Share the ledger across the boundary** via IPC or a store. Costs: a ledger
  that must be consistent across processes is a distributed-consensus problem
  bolted onto a spend limit, and it fails open under contention.
- **Hand the child an explicit grant** and seed its empty ledger with exactly
  that. Costs: the parent must be charged `1 + grant` in full at creation, which
  looks like over-charging until you see why.

## Decision

The grant. The parent is charged `1 + grant` **in full** — charging only for the
child would let two siblings each be handed the remaining budget and each spend
it. The default grant is zero: delegation does not propagate unless the call
that created the child said so.

## Consequences

Makes the bound hold across a process boundary with no shared state. Makes a
grant an explicit argument at every delegation site, which is the point — an
implicit one is how a budget escapes.

## Evidence

A concurrency test passed before the lock existed, which is recorded in
`AI_HUB_DECISIONS.md` as a test that could not fail; the lock and a test that
does fail without it both followed.
