# 0003. Track prop_firm_mode.json with placeholder credentials

- Status: accepted
- Date: 2026-09-09

## Context

`prop_firm_mode.json` carries prop-firm limits and connection settings. CI needs
a config to load. Back-filled from `CLAUDE.md`, which previously said the file
was gitignored — and the file's own `_comment` said so too. Both were wrong, and
the error invites putting real credentials in a tracked file.

## Options considered

- **Track it with placeholders only**, credentials in environment variables.
  Costs: a reader must know the placeholders are placeholders, and the file
  ships `enabled: true` with the FTMO ruleset, so a fresh deployment starts with
  those limits active.
- **Gitignore it** and have CI generate one. Costs: the generated config drifts
  from the real shape, so CI stops testing the thing that runs; and two
  documents already claimed this was the arrangement when it was not.

## Decision

Track it, placeholders only, credentials in environment variables.

## Consequences

Makes CI load the real config shape. Makes the active-by-default FTMO ruleset a
thing a fresh deployment inherits, which must be stated wherever the file is
described.

## Evidence

`.gitignore` does not list it; `detect-secrets` scans it on every commit.
