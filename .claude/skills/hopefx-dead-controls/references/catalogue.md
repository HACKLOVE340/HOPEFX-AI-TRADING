# Confirmed instances

Every entry was found by reading code that looked correct, then executing it.
Severity is the audit's. "Fixed in" names the finding that closed it.

## Guards that could never open

| ID | Location | The guard | What it meant |
|----|----------|-----------|---------------|
| F84 | `execution/engine.py` | `if orchestrator._started and not orchestrator.is_safe_to_trade()` | `_started` is False during startup and in every unit test, so the data-layer safety gate was skipped in exactly the condition it existed for. Removing the conjunct turned **twelve** execution tests red at once — they had all been routing through an inert check. |
| F159 | `notifications/alert_engine.py` | `if singleton is not None and singleton is not self` | `notifications` re-exports `get_alert_engine` from `notifications.alert_engine`, so the "singleton" *was* this AlertEngine. The guard and the delivery were one branch; every critical alert stopped at the log line. |
| F214 | `core/signal_engine.py` | phase gate computed into a health dict | The Phase-3 readiness value was calculated, stored, displayed — and gated nothing. |

## Success reported for work that did not happen

| ID | Location | What it claimed | What was true |
|----|----------|-----------------|---------------|
| F81 | `risk/orchestrator.py` | `_hedge_active = True`, `HedgePosition` appended | Set before the broker call and appended after a swallowed exception. Account unhedged, dashboards "hedged", retry latched off. |
| F252 | `risk/orchestrator.py` | `_hedge_positions.clear()` on deactivate | Cleared unconditionally, so a close the venue rejected dropped the position from tracking while the short stayed open — a live, **untracked** short. |
| F219 | `mobile/push_notifications.py` | `return True` | Returned True with FCM disabled and zero registered tokens. |
| F160 | `infrastructure/health_engine.py` | `"status": "ok"` | Read from configuration, not from any live probe. |
| F250 | `api/superadmin/alerting.py` | `sent_channels = rule["channels"]` | Echoed the rule's *config* after a send that reached nothing. The button that exists to verify alert delivery reported success on every channel, every time. |
| F184 | self-healer | `_run_tests() -> True` on `FileNotFoundError` | "Could not test" recorded as "tests passed", on the gate that admits a patch. |
| F247 | `notifications/__init__.py` | `async def send_alert(...)` | The body was a single `logger.log` call. `sl_tp_monitor` raised "CLOSE FAILURE — MANUAL INTERVENTION REQUIRED" through it. |

## Measurements that could not fail

| ID | Location | Why |
|----|----------|-----|
| F176 | `scripts/invariant_coverage.py` | Printed `FULL COVERAGE ✅` by counting hand-typed `True` literals in a manifest. Certified `market_data_feed` as protected while F84 was live, `order_execution` while F142 was live, `kill_switch` as alerted while F159 was live. |
| F255 | `security/code_analyzer.py` | The `nan_leak` rule scanned docstrings and `#` comments as if they were code. The `in_doc` exemption it needed already existed and was passed to a *different* rule — the same shape, inside the analyzer. |

## Evidence swallowed by `except`

| ID | Location | Handler | Consequence |
|----|----------|---------|-------------|
| F240 | `execution/sl_tp_monitor.py` | `AttributeError` on `pos.id` per poll | The stop-loss monitor checked nothing, every poll, silently. |
| F248 | `core/position_reconciler.py`, `ml/performance_monitor.py`, `ml/sharpe_circuit_breaker.py` | `except Exception` at WARNING and DEBUG | All three passed kwargs `send_alert` does not accept, and two never awaited the coroutine. Position drift, model rollback and a tripped circuit breaker notified nobody. |
| F145 | `ml/__init__.py` | `scaler.transform` failure logged at DEBUG | The **unscaled** frame was then passed to the base learners — a raw price where the model expects a z-score. |

## Tests that asserted the defect

| ID | Test | Assertion |
|----|------|-----------|
| F246 | `test_orchestrator_not_started_skips_check` | "When `orchestrator._started` is False, safety check is not run." |
| F246 | `test_skips_when_is_safe_to_trade_raises_value_error` | A raise is "non-fatal" and the order proceeds. |
| F252 | `test_no_broker_still_activates` | A hedge is recorded with `order_id is None` when no broker exists. |
| F252 | `test_broker_order_failure_still_activates` | A rejected order still sets `_hedge_active`. |
| F252 | `test_broker_close_failure_still_deactivates` | A hedge that could not be closed is cleared from tracking. |

Four further tests in the same class opened a hedge with **no broker at all**
and asserted it was open — not asserting the defect deliberately, just relying
on it.

## Harnesses that never ran

| ID | Where | Why it passed vacuously |
|----|-------|-------------------------|
| F244 | fresh-worktree verification | `static/` is a gitignored build artifact; without it four SPA tests fail for reasons unrelated to the change. `WITHOUT → 3 failed`, `WITH → 50 passed`. |
| F245 | `data_layer/__init__.py` | The package shadows its own submodule with an instance, so `monkeypatch.setattr("data_layer.orchestrator", ...)` reaches nothing. Patch `sys.modules["data_layer.orchestrator"]`. |
| F255 | analyzer rule tests | The analyzer skips paths containing `/test`; pytest's `tmp_path` is named after the running test, so every sample was exempt and each "must still be flagged" case passed against a scanner that never ran. |
| F242 | alert and ML tests | Bare `MagicMock` accepted calls the real object rejects. `create_autospec` is the fix. |
| F256 | F120's own fix | Ten targeted tests passed against code that propagated NaN, because none of them fed it a NaN. The repo's own gate caught it. |

## Corrections worth keeping

Three times, the alarming reading was the measurement, not the code:

- **F229 / F236 / F244** — a suite that "broke 187 tests" differed from its
  baseline by a missing gitignored artifact, not by the change.
- **F243** — an isolation "leak at the endpoint layer" was stale Redis state
  from a previous run, found only by running the failing test alone.
- **F254** — an assertion that a correct EMA weights the newest bar above the
  oldest. It does not: a 20-bar EMA at α=0.1 leaves its seed `(1-α)**19` =
  13.5%, above the newest bar's 10%. The code was right and the assertion was
  wrong. Check what the reference implementation does before deciding which
  side to change.
