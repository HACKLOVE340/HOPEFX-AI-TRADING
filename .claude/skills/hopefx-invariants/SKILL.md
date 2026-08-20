---
name: hopefx-invariants
description: Use when adding or changing a `verify_*` or `catastrophic_*` predicate under `invariants/`, wiring or moving an `enforce_*` call site, changing `HOPEFX_INVARIANT_MODE` or fail-closed behaviour, or when a pre-trade check refuses an order, an `EnforcementResult` returns `allowed=False`, or invariant coverage fails in CI.
---

# The HOPEFX Invariant Constitution

## Overview

`invariants/` is this platform's constitution expressed as **pure, testable
predicates** — currently **338 predicates across 34 modules**. It is the layer
that refuses an action rather than logging that the action looked wrong.

**Core principle:** predicates are pure and side-effect free; only
`invariants/enforcement.py` decides what a violation *does*. Never blur that line.

## Architecture

```
invariants/
  constitution.py   # core predicates + the Violation model + severities
  <domain>.py       # 32 domain modules: risk, execution, market, ai, governance…
  registry.py       # auto-discovers every predicate by introspection
  enforcement.py    # the ONLY module that blocks, halts, or records
  meta.py           # invariants ABOUT invariants (coverage of critical components)
```

`registry.discover_predicates()` walks the package and collects every function
named `verify_*` / `catastrophic_*` that is *defined* in its module. There is no
hand-maintained list, so **a correctly named predicate is registered the moment
you write it** — and a misnamed one is invisible.

## Quick reference

| Need | Do this |
|---|---|
| Add a check | Add `verify_<thing>()` to the right domain module in `invariants/` |
| Make it block | Add an `enforce_*` wrapper in `enforcement.py`; add its kind to `KNOWN_KINDS` |
| Count predicates | `python -c "from invariants.registry import predicate_count; print(predicate_count())"` |
| Coverage report | `python scripts/invariant_coverage.py` |
| Runtime check | `python scripts/runtime_invariant_check.py` |
| Soak test | `python scripts/invariant_soak.py` |

## Writing a predicate

Signature: take plain values, return `list[Violation]` — empty means pass.
Never raise, never log, never call I/O.

```python
def verify_capital_conservation(
    allocated: float, available: float, reserved: float, total: float, tol: float = 0.01
) -> list[Violation]:
    """allocated + available + reserved must equal total (no money created or destroyed)."""
    parts = {"allocated": allocated, "available": available, "reserved": reserved, "total": total}
    for name, val in parts.items():
        if not _is_finite_number(val):
            return [_v("No Hidden Capital", CONSTITUTIONAL, f"capital component '{name}' is non-finite ({val!r})")]
    if abs((allocated + available + reserved) - total) > tol:
        return [_v("No Hidden Capital", CONSTITUTIONAL,
                   "capital does not reconcile: allocated+available+reserved != total",
                   diff=round((allocated + available + reserved) - total, 6), **parts)]
    return []
```

Note the shape: **finite-check first, then the property**. A NaN that reaches a
comparison passes silently — `NaN > tol` is `False`. Every numeric predicate in
this package guards finiteness first. Yours must too.

## Severity decides blocking

`CONSTITUTIONAL` and `CRITICAL` block. `WARNING` does not.

```python
result.blocking  # any violation of severity CONSTITUTIONAL or CRITICAL
```

Choose `CONSTITUTIONAL` only for the named constitutional rules ("No Hidden
Capital", "No Unverified AI Decision", "No Hidden Loss"). Inventing a new
constitutional rule is a platform-governance decision, not a code change — ask.

## Enforcement modes

`HOPEFX_INVARIANT_MODE` ∈ `off` | `monitor` | `enforce`, **default `monitor`**,
re-read on every call. Per-kind overrides exist; `KNOWN_KINDS` lists the 16 kinds
(`pre_trade`, `order_authorization`, `human_approval`, `reconciliation`, `ledger`,
`exposure`, `var`, …).

`EnforcementResult` carries `allowed`, `should_halt`, `violations`, `mode`,
`reason`. `allowed=False` happens **only** in `enforce` mode with a blocking
violation (or a fail-closed checker error). Callers that refuse one action read
`allowed`; callers that trip a loop read `should_halt`.

Production wiring today: `risk/manager.py:53` imports `enforce_pre_trade`;
`api/server.py` and `api/transparency.py` expose `enforcement.status`.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Predicate raises instead of returning `Violation` | `_safe()` treats it as a checker error; fail-closed may block everything |
| Predicate does I/O or logging | Breaks purity; makes it untestable and slow in the pre-trade path |
| Naming it `check_*` or `_verify_*` | Registry never discovers it — the check silently does not exist |
| Comparing floats before a finite guard | `NaN` passes every comparison |
| Downgrading a severity to unblock a trade | Weakening a risk gate — forbidden by `CLAUDE.md` |
| Setting mode to `off` to get tests green | Disables the constitution globally; fix the violation instead |

## Red flags — stop

- "I'll just widen `tol` so reconciliation passes"
- "Set `HOPEFX_INVARIANT_MODE=off` for now"
- "Make it `WARNING` so it doesn't block"
- "Skip the finite check, the caller validates"

Each of these turns a refusal into a silent loss. If an invariant blocks a trade,
the invariant is doing its job — investigate the trade, not the invariant.
