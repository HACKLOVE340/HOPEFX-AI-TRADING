# Documentation Review Scope (HOPEFX)

Ordered by blast radius: drift near the top misleads every contributor and every
agent working in the repo.

## Tier 1 — agent and contributor contracts

These are read before any change is made, so a stale line here causes bad work
downstream.

- `CLAUDE.md` — the high-signal subset for AI assistants
- `AGENTS.md` — the full agent guide (layout, conventions, testing, ML, workflows)
- `ARCHITECTURE.md` — canonical module map, entry points, env flags
- `CONTRIBUTING.md` — contribution workflow

Check specifically:
- Canonical vs. legacy directory table (`backtesting/` vs `backtest/`,
  `strategies/` vs `strategy/`, `data_layer/` vs `data/`) still matches reality.
- The key-entry-points table still points at files that exist.
- Stated Python version matches `Dockerfile`, `.github/workflows/ci.yml`, and the
  retrain workflows. These have drifted apart before.
- Claims about which files are gitignored match `.gitignore`. A doc that says a
  tracked file is ignored invites committing real credentials into it.

## Tier 2 — user-facing entry points

- `README.md`
- `DEPLOYMENT.md`
- `CHANGELOG.md`

Check that quickstart commands actually run, ports match the code, and the
stated project status is current.

## Tier 3 — `docs/`

Large and uneven. Prioritise:
- `docs/API_ENDPOINTS.md`, `docs/API_REFERENCE.md`, `docs/API.md` — endpoint
  tables drift as routers are mounted or renamed. Cross-check against
  `api/server.py` and the route modules.
- `docs/BACKTESTING_GUIDE.md`, `docs/DEBUGGING.md` — command accuracy.
- Dated audit files (`docs/AUDIT_*.md`) are point-in-time records. Do **not**
  "refresh" them; they are history. Flag only if one is presented as current
  guidance.

## Out of scope

- Generated docs produced by `.github/workflows/docs.yml` / `update_docs.yml` —
  fix the generator, not the output.
- Vendored skill documentation under `.claude/skills/*/` — those track their
  upstream projects; see `.claude/skills/README.md`.

## What counts as drift

1. **Broken reference** — a path, file, command, or anchor that no longer exists.
2. **Contradiction** — two documents state incompatible facts. Resolve against
   the code, then fix both.
3. **Stale claim** — was true, no longer is (version pins, status, ports, flags).
4. **Silent omission** — a documented surface exists but a new required step or
   env var is missing.

Report each finding with the file, the line, the observed fact in code, and the
proposed correction. Do not rewrite prose that is merely awkward.
