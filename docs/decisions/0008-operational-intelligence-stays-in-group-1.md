# 0008. Operational intelligence stays in Group 1; Group 2 owns its inputs

- Status: accepted
- Date: 2026-09-09

## Context

Group 2 Chapter 16 and Group 1 both describe reasoning over operational
telemetry. Two specifications describing the same capability is precisely the
duplication Group 3 exists to prevent.

## Options considered

- **Group 2 owns it**, because it owns operations. Costs: Group 2 would then
  specify inference, drift and confidence, which Group 1 already specifies —
  producing two definitions that diverge.
- **Group 1 owns the intelligence; Group 2 owns the inputs it consumes.** Costs:
  a reader of Group 2 must follow a reference to find how the reasoning works.

## Decision

Group 1 owns the intelligence. Group 2 owns metrics, traces, logs and change
records, and references Group 1 rather than restating it.

## Consequences

Makes one definition of inference and confidence. Makes cross-group references
load-bearing, so a broken one is a real defect rather than a broken link.

## Evidence

The classification rule in `docs/ai/BACKLOG_GROUPS.md`: an item belongs to
exactly one group, and where it touches another the owning group references the
relationship rather than copying content.
