# 0002. Commit model artefacts and the built dashboard

- Status: accepted
- Date: 2026-09-09

## Context

`ml/saved_models/*.pkl`, `ml/rl_models/*.zip` and `dashboard/dist/` are binary
build outputs living in git, which every instinct says to remove. Back-filled
from `CLAUDE.md`, where the note reads "Don't clean these up" — an instruction
without its reasoning, which is the shape that gets overridden.

## Options considered

- **Commit them**, whitelisted in `.gitignore` and checksum-verified in CI.
  Costs: repository size, and binary diffs nobody can read.
- **Build them at deploy time** from a training run and an `npm run build`.
  Costs: the server cannot serve the UI without a Node toolchain present, and a
  model artifact rebuilt at deploy is not the artifact that was tested — the
  inference path would run against weights no test ever saw.

## Decision

Commit them. Whitelist in `.gitignore`, verify checksums in CI.

## Consequences

Makes a deployment reproducible and makes the served UI byte-identical to the
tested one. Makes the repository larger, and makes a rebuilt asset show up as an
unreadable diff on every rebuild — which is why `check-added-large-files`
inspects only newly *added* paths.

## Evidence

`.gitignore` carries the whitelist deliberately; CI verifies the checksums.
Contrast 0007: the hand-landmark model is NOT committed, and the difference in
reasoning is recorded there.
