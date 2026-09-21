# 0013. `data/` owns streaming and serving; `data_layer/` owns access

- Status: accepted
- Date: 2026-09-09

## Context

Decision A2, open since the Group 2 backlog was written. Two packages hold
market-data code and the boundary between them is documented nowhere:

| Package | LOC | Production importers | What is in it |
|---|---:|---:|---|
| `data_layer/` | 19,610 | 86 | orchestrator, tick store, feed adapters |
| `data/` | 6,259 | 20 | price engine, scheduler, depth-of-market, tick feed, time-and-sales, streaming, macro feed |
| `market_data/` | 4,031 | 6 | broker-side feeds |

This is not theoretical. Three documents once described `data/` as legacy data
files, which told contributors to put tick-feed and depth-of-market work in
`data_layer/` — splitting one subsystem across two packages (F216). CLAUDE.md
records that it declined to invent a boundary (F217), which was right at the
time and left the defect class live.

## Options considered

- **Split by role, recorded as a decision, moving no code.** `data/` owns
  streaming and serving; `data_layer/` owns access. Costs: two packages remain
  where a newcomer might expect one, and the rule has to be read rather than
  inferred from the tree.
- **Merge everything into `data_layer/`.** One package, nothing to remember.
  Costs: touches 106 production importers for zero behaviour change — a large
  diff through the trading path to fix a documentation problem, on a platform
  whose own rules prefer targeted changes over broad rewrites.
- **Leave it undecided.** Costs: the defect class stays live. Contributors keep
  guessing, and each guess is a subsystem split a little further.

## Decision

Split by role, as a rule rather than a refactor.

* **`data/`** — live streaming and serving. `real_time_price_engine.py`,
  `scheduler.py`, `depth_of_market.py`, `tick_feed.py`, `time_and_sales.py`,
  `streaming.py`, `feeds/macro.py`. Constructed in `core/startup_factories.py`,
  mounts three HTTP routers via `core/router_registry.py`.
* **`data_layer/`** — market-data access. The orchestrator, the tick store, the
  feed adapters. The canonical public surface:
  `data_layer.orchestrator`, `data_layer.tick_store`, `data_layer.feeds.*`.
* **`market_data/`** — broker-side feeds, e.g. `mt5_live_feed.py`.

This is a description of what the code already does, not a new architecture.
That is precisely why it is safe to adopt today.

## Consequences

Makes "which package does this belong in?" answerable, which closes the defect
class F216 named. Costs one paragraph in CLAUDE.md and nothing else.

Leaves three packages where a reader might expect one, so the rule must stay
visible in the routing table or it will be re-litigated. It is also the input
Group 2 item 22 needed, and it narrows what the package register (item 10) has
to decide for these three.

Does **not** authorise moving existing code between them. A module that is on
the wrong side of this line stays there until someone has a reason beyond
tidiness — the importer count is the cost, and it has not changed.

## Evidence

The LOC and importer figures above are measured, and recorded in CLAUDE.md's
canonical-versus-legacy section. F216 and F217 in the audit record the defect
and the earlier refusal to invent a boundary without the owner.
