---
name: hopefx-fix-bridge
description: Use when changing `brokers/ibkr_fix_bridge.py` or `execution/fix_adapter.py` — FIX 4.4 session config, SenderCompID/TargetCompID, sequence numbers or the session store, logon/logout and ResetOnLogon, heartbeats, reconnect, XAUUSD symbol mapping, order routing, or fill reports; or when FIX logon fails, sequence numbers mismatch, or round-trip latency trips the circuit breaker.
---

# IBKR FIX 4.4 Bridge

## Overview

`brokers/ibkr_fix_bridge.py` (366 lines) wires the generic
`execution/fix_adapter.py` to an IBKR FIX Gateway session for low-latency XAUUSD
execution.

```
IBKRFIXBridge
  └── FIXAdapter (execution/fix_adapter.py)
        └── quickfix session → IBKR FIX Gateway
```

**Core principle:** a FIX session is *stateful across process restarts*.
Sequence numbers on disk are part of your program state. Most FIX bugs are
really state-lifetime bugs.

## Quick reference

| Concern | Where |
|---|---|
| Session parameters | `IBKRFIXConfig` (all env-overridable) |
| quickfix config text | `IBKRFIXConfig.generate_quickfix_cfg()` → temp file |
| Paper vs live detection | `IBKRFIXConfig.is_paper` — `port in (4002, 7497)` |
| Lifecycle | `bridge.start()` / `bridge.stop()`, or use it as a context manager |
| Construction from env | `IBKRFIXBridge.from_env(kill_switch=...)` |
| Tests | `tests/unit/test_ibkr_fix_bridge.py` (bridge) · `tests/unit/test_execution_fix_adapter.py` (adapter, with a FIX 4.4 stand-in) |

### Ports carry the paper/live distinction

| Port | Meaning |
|---|---|
| 4001 | FIX Gateway **live** |
| 4002 | FIX Gateway **paper** (default) |
| 7496 | TWS **live** |
| 7497 | TWS **paper** |

`is_paper` is derived purely from the port. **Changing `IBKR_FIX_PORT` changes
whether real money moves.** There is no second confirmation — treat that env var
with the same care as a credential.

## Environment

| Var | Default | Notes |
|---|---|---|
| `IBKR_FIX_SENDER_COMP_ID` | `HOPEFX` | your IBKR username / assigned comp ID |
| `IBKR_FIX_TARGET_COMP_ID` | `IBFX` | IBKR FIX Gateway |
| `IBKR_HOST` | `127.0.0.1` | |
| `IBKR_FIX_PORT` | `4002` | **paper by default — see above** |
| `IBKR_FIX_USERNAME` / `_PASSWORD` | `""` | never hardcode; env only |
| `IBKR_FIX_STORE_PATH` | `$TMPDIR/ibkr_fix_store` | **sequence numbers live here** |
| `IBKR_FIX_LOG_PATH` | `$TMPDIR/ibkr_fix_logs` | FIX message log |

Non-env defaults: `heartbeat_interval=30`, `reconnect_interval=10`,
`reset_on_logon=True`, `reset_on_logout=False`, `reset_on_disconnect=False`,
`latency_threshold_ms=100.0`.

## The sequence-number trap

`store_path` defaults under `tempfile.gettempdir()`. In a container that is
**ephemeral**: the store vanishes on restart, so the session restarts at seq 1.

Today `reset_on_logon=True` makes that survivable — both sides reset. But the
moment anyone sets `reset_on_logon=False` (which is what you want for true
session continuity and gap-fill), a tmpdir store becomes a live outage: IBKR
expects seq N, you send seq 1, the session is rejected.

**If you change `reset_on_logon`, you must also move `IBKR_FIX_STORE_PATH` to a
persistent volume in the same change.** They are one decision, not two.

## Latency is a safety control, not a metric

The docstring targets **<50 ms round trip**, and `latency_threshold_ms=100.0`
opens a circuit breaker. That threshold is passed into `FIXAdapter` at
construction. Raising it does not make execution faster — it widens the window in
which a degraded session keeps sending orders. Treat it like a risk limit.

`IBKRFIXBridge` also takes a `kill_switch`. Any new order path you add must
remain behind it; a FIX path that bypasses the kill switch is a direct route to
uncontrolled loss.

## Quantities and prices are `float` here

`FIXOrder` carries `quantity: float` and `price: float`:

```python
report = await bridge.place_order(FIXOrder(
    symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0,
    ord_type=FIXOrdType.LIMIT, price=1950.00,
))
```

That is the wire representation, and FIX transmits decimal strings anyway — but
it means the `Decimal` guarantees held in `execution/oms.py` are already gone by
the time an order reaches this module. **REQUIRED BACKGROUND:** use
`hopefx-money-precision` before changing any arithmetic on these fields.

## Symbol mapping

`_map_symbol()` translates to IBKR's FIX convention — `XAUUSD` with
`SecType=CMDTY`. Other venues in `brokers/` use different conventions for the
same instrument. Never assume a symbol string is portable across adapters; map
at the adapter edge.

## The exception quickfix actually raises

`quickfix.FieldNotFound` derives from `quickfix.FIXException`, which derives
from `Exception`. It is **not** an `AttributeError`, `TypeError`, `ValueError`
or `KeyError`, and `FieldMap::getField` throws it for every absent tag —
including optional ones like `Text` (58) on a bare Logout.

Every handler in `execution/fix_adapter.py` used to name only those four
builtins, so against the production backend the one exception each of them
existed to catch went straight past it. Two of those handlers are on the money
path: a report that cannot be read must reject the caller's pending future, and
a handler that dies first leaves `send_order` to wait out its full 30-second
timeout instead.

Use `_fix_absent_errors()` in any new handler that reads a field:

```python
except (AttributeError, TypeError, ValueError, *_fix_absent_errors()) as exc:
```

And read the key you need to *report* the failure — `ClOrdID` — before anything
else that can fail, or the rejection is filed under `<unknown>` and the
dispatcher drops it as unsolicited.

None of this is visible in CI: `requirements-ci.txt` cannot build the C
extension, so CI runs the simulation backend where nothing raises. Test the
quickfix path with the stand-in in `tests/unit/test_execution_fix_adapter.py`.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Changing `reset_on_logon` without a persistent store | Logon rejected on next restart |
| Raising `latency_threshold_ms` to stop breaker trips | Degraded session keeps trading |
| Hardcoding comp IDs or credentials | Secrets in a tracked file; `detect-secrets` will block, and rightly |
| Testing against port 4001/7496 | That is **live**; use 4002/7497 |
| Adding an order path that skips `kill_switch` | Removes the stop of last resort |
| Assuming `stop()` flushes state | Verify the store path before relying on restart continuity |
| Catching only builtins around a `getField` | `FieldNotFound` is not one; the handler never runs |
| Testing only under CI's simulation backend | Nothing raises there — the production backend is untested by construction |
