# 0006. Treat 3D as projection, not WebGL, and make it earn its place

- Status: accepted
- Date: 2026-09-09

## Context

§21 asks for 3D and scientific models. The note on the row said "only canvas2d is
implemented", which describes what exists rather than naming a blocker.
Back-filled from `AI_HUB_DECISIONS.md` Phase I6.

## Options considered

- **WebGL.** Costs: a GPU-backed context has never been proven in this
  environment, and it holds the capability hostage to hardware.
- **A projected mesh painted back to front onto SVG polygons.** Costs: fill rate,
  and a mesh size ceiling. Painter's ordering *is* the depth buffer, so it needs
  no GPU and no dependency.

## Decision

Projection. WebGL stays honestly unavailable in `projection.ts` as an
acceleration path rather than a prerequisite. Orthographic, not perspective:
perspective renders two equal values at different heights depending on where
they sit, and on a screen whose vertical axis is a price that is a chart
misstating its own numbers.

`warrants3D` enforces the spec's "where they aid understanding" clause and
refuses more often than it accepts — a gratuitous third dimension costs
occlusion, foreshortening, and the shared baseline comparison depends on.

## Consequences

Makes 3D available on any browser. Makes every 3D request pass a test of whether
the shape between samples is the information, which will feel obstructive to
somebody who just wants a pretty chart.

## Evidence

Accepted for a genuine z = f(x, y) over two ordered, densely-sampled axes;
refused for data varying in one direction, whose depth is decoration.
