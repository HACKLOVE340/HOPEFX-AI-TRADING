---
name: hopefx-dead-controls
version: 1.0.0
description: Use when adding, reviewing, or trusting any safety control in HOPEFX — a gate, guard, kill switch, health probe, alert, coverage report, or "is it safe" check — and whenever a control looks correct but you have not traced that it runs. Also use when a test suite goes green after you disable or tighten a control, when a scan or report claims success, when a `try`/`except` swallows the only evidence a control fired, and when writing the regression test for any of these.
---

# Controls that exist and never run

## Overview

A 249-finding audit of this repository found one defect shape more often than
any other, across unrelated subsystems written at different times:

> **A control that exists, is documented accurately, and is never invoked —
> or returns success for work that did not happen.**

It is not a bug in the control. The control is usually well written. The defect
lives in the *wiring*, the *guard condition*, or the *report*. That makes it
invisible to code review, invisible to the type checker, and — this is the part
that matters — **invisible to the test suite, which goes green precisely
because the control is off**.

Read `references/catalogue.md` for the confirmed instances with file and line
evidence. Read it before arguing that a control here is fine; every entry
looked fine.

## The rule

**Never conclude a control works because you read it. Execute the path.**

Reading tells you the control exists. Only execution tells you it runs.

## Four recurring sub-shapes

### 1. The guard that can never open

A condition that gates the control is never true in practice.

```python
# execution/engine.py, before the fix (F84)
if orchestrator._started and not orchestrator.is_safe_to_trade():
    return  # refuse
```

`_started` is False in every unit test and during startup, so the data-layer
safety check was skipped in exactly the condition it existed for.

```python
# notifications/alert_engine.py, before the fix (F159)
singleton = get_alert_engine()          # returns THIS AlertEngine
if singleton is not None and singleton is not self:
    await singleton.send_alert(...)     # unreachable
```

The guard and the delivery were the same branch. Emergency stops, drawdown
breaches and circuit-breaker trips were log lines for the life of the module.

**What to do:** for every `if` that stands between an event and its control,
name a concrete runtime state in which the branch is taken. If you cannot, the
control is dead. Write the test that puts the system in that state.

### 2. Success reported for work that did not happen

```python
# risk/orchestrator.py, before the fix (F81)
self._hedge_active = True            # set BEFORE the broker call
result = await broker.place_order(...)
except Exception as exc:
    logger.error("Hedge order failed: %s", exc)
self._hedge_positions.append(HedgePosition(order_id=order_id))   # anyway
```

State was mutated before the work, and the failure path fell through to the
success path. The account was unhedged while every dashboard said "hedged", and
the duplicate-activation guard then latched so no retry was possible.

**What to do:** mutate state *after* the work, from its result. A function that
performs an external action returns whether it happened, and its caller reports
that, not a constant `"ok"`.

### 3. A measurement that cannot fail

```python
# scripts/invariant_coverage.py, before the fix (F176)
CRITICAL_COMPONENTS = {"order_execution": {"protected": True, ...}, ...}
print("FULL COVERAGE ✅" if not errors else ...)
```

`coverage_counts()` counted hand-typed `True` literals. It inspected no code,
called no predicate and probed no component, so the report could not print
anything else — while three of the components it certified were, at that
moment, provably unprotected.

**What to do:** a report must distinguish what it *measured* from what it was
*told*. If nothing was probed, the output says so in the same breath as the
number. Keep the declaration — it is a legitimate statement of intent — and
delete only the claim.

### 4. The evidence swallowed by `except`

```python
except Exception as exc:
    logger.debug("...failed: %s", exc)   # DEBUG is off in production
```

Three alert call sites passed keyword arguments the target does not accept
(F248). Every call raised `TypeError` into a handler that logged at DEBUG or
WARNING, so a tripped Sharpe circuit breaker, an automatic model rollback and a
position-drift halt each notified nobody, for as long as the code existed.

**What to do:** a handler around a safety action logs at ERROR and says what
did not happen. `except Exception: pass` on a control path is a silent failure
by construction — if the action must never crash the caller, that is a reason
to log louder, not quieter.

## Tests that assert the defect

**When you fix a dead control, expect its tests to turn red — and read them
before you "fix" them.** In this audit, three separate suites encoded the
defect as the requirement:

| Test name | What it asserted |
|---|---|
| `test_orchestrator_not_started_skips_check` | The data-layer gate is *not* run when the orchestrator has not started (F246) |
| `test_no_broker_still_activates` | A hedge is recorded when there is no broker to place it (F252) |
| `test_broker_close_failure_still_deactivates` | A hedge that could not be closed is dropped from tracking (F252) |

Each was green, deliberate, and describing a defect.

**A suite cannot tell you a control is off. It reports the absence of the
control as success.**

So when a test goes red under your fix, the question is never "how do I make
this pass". It is: *does this test describe behaviour anyone would want?* If
not, rewrite the assertion and say in the docstring what it used to claim. If
you cannot tell, that uncertainty belongs in your report to the user.

Two related traps:

- **A mock with no spec agrees with every call.** `MagicMock().send_alert(title=…)`
  accepts arguments the real method rejects. Use `create_autospec(RealClass)`
  for anything whose signature the production call depends on (F242, F248).
- **A checker that reads prose is not reading code.** `security/code_analyzer.py`'s
  `nan_leak` rule scanned docstrings and `#` comments as if they were source
  (F255). Within the same session, `scripts/verify_skill_claims.py` — written to
  confirm that fix — reported four correct files as broken, because each carries
  a comment quoting the defect it fixed. Strip prose with the analyzer's own
  `_build_docstring_lines` / `_strip_string_literals` rather than writing a
  fifth regex (F257).
- **A text match tests how code is written; call it instead.** The same script
  grepped for `HOPEFX_INVARIANT_MODE", "monitor"` and called a true claim stale:
  the default is real, it just arrives via `_DEFAULT_MODE = MODE_MONITOR`.
  Assert behaviour where you can run it.
- **A harness that never ran agrees with every assertion.** A code-analyzer test
  writing its sample into pytest's `tmp_path` was silently exempt, because the
  analyzer skips paths containing `/test` and `tmp_path` is named after the
  running test. Every "this must still be flagged" case passed against a
  scanner that never executed (F255). Assert that your harness is live before
  asserting what it found.

## When a measurement suddenly looks alarming, suspect the measurement

Held four times in this audit (F229, F236, F244, and a 187-failure scare that
was a missing gitignored build artifact). Before reporting that a change broke
187 tests, verify the two runs differ only by the change:

```bash
# Fresh worktrees, and copy static/ in — it is gitignored, and without it
# the SPA tests fail for reasons unrelated to anything you changed.
git worktree add --detach /tmp/wt-head HEAD
cp -r static /tmp/wt-head/static
```

Diff failure **sets**, never counts.

## Practical checks

```bash
# Is this control reachable from a caller at all?
grep -rn "enforce_wallet_movement\|is_safe_to_trade" --include="*.py" . | grep -v "^./tests/"

# Does the repo's own analyzer still scan clean? (0 findings is the gate)
.venv/bin/python -c "from security.code_analyzer import scan_codebase; print(len(scan_codebase()))"

# What does the invariant registry actually measure, versus declare?
python scripts/invariant_coverage.py

# Red-green a fix without trusting memory: stash the source, run the new tests.
git stash push -- path/to/fixed.py && pytest tests/unit/test_new.py -q; git stash pop

# Are this skill's own claims still true of the codebase?
python scripts/verify_skill_claims.py
```

## Not for this skill

- Choosing *what* an invariant should assert — see `../hopefx-invariants/SKILL.md`.
- Decimal/float boundaries and tolerance widening — see `../hopefx-money-precision/SKILL.md`.
- Root-causing a failure you can already reproduce — see `../systematic-debugging/SKILL.md`.
- Claiming work is done — see `../verification-before-completion/SKILL.md`.

This skill is about the control you have *not* seen fail, because nothing has
ever made it run.
