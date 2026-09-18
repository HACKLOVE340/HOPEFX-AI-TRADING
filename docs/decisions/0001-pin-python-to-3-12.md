# 0001. Pin Python to 3.12

- Status: accepted
- Date: 2026-09-09

## Context

`ml/saved_models/` and `ml/rl_models/` carry committed `.pkl` and `.zip`
artifacts, loaded at inference time. A pickle written by one interpreter is not
guaranteed to load in another. `Dockerfile` runs `python:3.12-slim`.

Back-filled from `CLAUDE.md`. It is recorded because the reasoning was already
lost once: an earlier version of that file said 3.10 "matches the Docker image",
which was false in both directions — the image was already 3.12, and 3.10 was
tested by nothing. Anyone following it produced artifacts under an interpreter
neither CI nor production ever loads.

## Options considered

- **Pin 3.12 everywhere** — Dockerfile, CI, retrain workflows. Costs: a
  contributor on an older interpreter must upgrade before their first commit.
- **Support a range (3.10-3.12)** and let contributors choose. Costs: the stated
  reason for pinning is pickle compatibility, and a range abandons it while
  appearing to be generous. The artifacts are the thing that breaks, silently,
  at inference.

## Decision

Pin 3.12. CI tests 3.11 and 3.12; the retrain workflows run 3.12 so artifacts are
pickled on the interpreter that loads them in production.

## Consequences

Makes artifact loading predictable and makes the Dockerfile the single source of
the version. Makes the Dockerfile's Python a coupled change: altering it without
altering the retrain workflows in the same commit reintroduces the defect.

## Evidence

`Dockerfile` line 35 is `FROM python:3.12-slim`.
`tests/unit/test_deployment_docs_name_the_real_interpreter.py` reads the version
out of the Dockerfile and fails any deployment guide that instructs another —
which it did, twice, on 2026-09-09.
