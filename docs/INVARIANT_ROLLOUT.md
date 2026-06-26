# Invariant Enforcement — Operator Rollout Runbook

How to take the constitutional invariant layer from **observe-only** to
**blocking** safely, and how to roll back instantly if anything misbehaves.

This is a money-moving system. The layer ships **fail-safe and off-by-default
for blocking** so turning it on is a deliberate, staged, reversible decision —
never a surprise.

---

## The one control: `HOPEFX_INVARIANT_MODE`

| Value | Behaviour | Use when |
|-------|-----------|----------|
| `off` | Checks do not run at all. | You need to fully disable the layer. |
| `monitor` *(default)* | Checks run and **log** violations; **never block**. Zero change to trading behaviour. | Always — this is the safe default and the soak-test mode. |
| `enforce` | A CONSTITUTIONAL/CRITICAL violation **blocks the trade / halts** (pre-trade returns zero size; OMS/router refuse the order; reconciliation trips the kill switch). WARNINGs only log. | Only after a clean soak in `monitor`. |

Secondary control:

| Var | Default | Meaning |
|-----|---------|---------|
| `HOPEFX_INVARIANT_FAIL_CLOSED` | `0` (fail-open) | If a bug *inside the checker* raises, do we block (`1`) or allow (`0`)? Keep `0` during rollout so a checker bug can't halt the desk; consider `1` only once the layer is trusted. |

The mode is re-read on every check, so you can change it via env/Config without
a code deploy (process restart picks it up; some orchestrators hot-reload env).

Tunable thresholds (all have safe defaults): `RISK_MAX_TICK_STALENESS_S` (5s),
`RISK_MAX_SYMBOL_EXPOSURE_USD` (1e6), `RECONCILER_DRIFT_QTY`,
`RECONCILER_DRIFT_VALUE`.

---

## What each mode gates (the wiring)

| Surface | File | monitor | enforce |
|---------|------|---------|---------|
| Pre-trade (size/finiteness/tick/spread/confidence/**freshness**) | `risk/manager.py` `size_order()` | logs | returns zero size (order refused) |
| Order authorization (token + decision id) | `execution/oms.py`, `smart_router.py`, `trade_executor.py` | logs | refuses the order at the broker call |
| Reconciliation (book value, PnL identity) | `core/position_reconciler.py` | logs | **trips the kill switch** |
| Per-symbol exposure | `core/position_reconciler.py` | logs | logs (informational) |
| Audit hash-chain | CI: `scripts/runtime_invariant_check.py` | n/a | fails the build on tamper |

---

## Observability — watch this before flipping anything

`GET /health/invariants` returns live status:

```json
{
  "mode": "monitor",
  "blocking_enabled": false,
  "engine_healthy": true,
  "counters": {"checks": N, "violations": N, "blocked": N, "halts_signalled": N, "checker_errors": N},
  "recent": [ ... last 50 violations with rule/severity/reason ... ],
  "ok": true
}
```

Watch for: `checker_errors == 0` (the layer itself is healthy), and the
`recent` list / `violations` counter. **Every entry in `recent` during the soak
is a would-be block** — investigate each before enforcing.

### Tooling for the soak

- **Live CLI watch:** `python scripts/invariant_soak.py --url http://<host>:8000 --interval 30`
  prints mode, engine health, and counter deltas each cycle and surfaces every
  new violation. `--once` for a single snapshot. Exits non-zero if the engine
  goes unhealthy or any checker error is seen.
- **Prometheus metrics** (synced every scrape by `prometheus_monitoring.py`):
  `hopefx_invariant_mode` (0/1/2), `hopefx_invariant_engine_healthy`,
  `hopefx_invariant_checks_total`, `hopefx_invariant_violations_total`,
  `hopefx_invariant_blocked_total`, `hopefx_invariant_halts_signalled_total`,
  `hopefx_invariant_checker_errors_total`.
- **Alerts** (`monitoring/rules/alerts.yml`, group `hopefx-invariants`):
  engine-unhealthy (critical), checker-errors (warning), violations-during-soak
  (warning), block-spike in enforce (critical), kill-switch-trip (critical).

### Config wiring

`HOPEFX_INVARIANT_MODE` (+ `HOPEFX_INVARIANT_FAIL_CLOSED` and the tunable
thresholds) are declared in `.env.example`, `docker-compose.yml`
(`${HOPEFX_INVARIANT_MODE:-monitor}`), and `deployments/k8s/configmap.yaml`
(`hopefx-config`). To change mode in k8s, edit the ConfigMap and restart the
deployment; in compose, set the var in `.env` and `docker compose up -d`.

---

## Rollout sequence (do NOT skip steps)

### Step 0 — Soak in `monitor` (already the default)
- Deploy with `HOPEFX_INVARIANT_MODE=monitor` (or unset).
- Run for at least one full trading session (ideally several).
- **Exit criteria:** `violations` counter reflects only *true* problems (zero
  false positives), `checker_errors == 0`. If you see violations on healthy
  trades, fix the threshold/predicate first — do not proceed.

### Step 1 — Enforce the pre-trade gate (lowest blast radius)
- The pre-trade gate refuses **one order** at a time; it cannot halt the desk.
- Set `HOPEFX_INVARIANT_MODE=enforce`.
- Watch `counters.blocked`. Each block = an order that failed a constitutional
  check (non-finite price, crossed book, stale tick, low confidence). Confirm
  each blocked order *should* have been blocked.

### Step 2 — Confirm order-authorization gates
- Same flag already enables the OMS/router/executor gates. Confirm normal orders
  carry a `risk_approval_token` + `decision_id` and are **not** being refused
  (`counters.blocked` should not spike on healthy flow). If healthy orders are
  refused, the token is not being threaded on some path — return to `monitor`
  and fix the threading before continuing.

### Step 3 — Reconciliation → kill switch (highest blast radius, last)
- This is the only gate that can **halt all trading** (it trips the kill switch
  on a book-value/PnL reconciliation breach).
- Keep `RECONCILER_DRIFT_VALUE` at a sane tolerance so normal broker rounding
  does not trip it.
- Watch `counters.halts_signalled`. The first real trip should correspond to a
  genuine DB-vs-broker divergence; verify against the broker before resuming.

### Step 4 — (optional) Fail-closed
- Once the layer has run clean in `enforce` for a sustained period, you may set
  `HOPEFX_INVARIANT_FAIL_CLOSED=1` so a checker-internal error also blocks.
  Until then, keep it `0`.

---

## Rollback (instant, at any step)

1. Set `HOPEFX_INVARIANT_MODE=monitor` (or `off`) — blocking stops immediately
   on the next check; no code deploy required.
2. If the kill switch was tripped by Step 3, clear it per the kill-switch runbook
   (`kill_switch.py` `deactivate(token)` + remove the flag file) **only after**
   you have reconciled positions against the broker.
3. File the offending `recent` entry as a bug; fix the predicate/threshold; retry
   the soak.

**Golden rule:** if you are unsure, go back to `monitor`. It is always safe and
loses no protection except blocking.

---

## CI gate (independent of runtime mode)

`scripts/runtime_invariant_check.py` runs in CI regardless of mode: it boots the
app, probes endpoints, verifies the audit hash-chain, checks tenant isolation and
recovery-module presence, and scans the event log. Exit 1 (findings) fails the
build; exit 2 (could-not-boot in that environment) is surfaced as a warning.

---

## What this layer does **not** do (still operational programs)

- **Live two-pod isolation** — the mechanism + in-process check exist; a true
  cross-pod probe needs a multi-pod deployment.
- **Live restore/failover drills** — readiness is import-verified in CI; actually
  exercising a restore is an ops runbook against real infra.
- **Rules #2/#5/#7/#11/#15/#18** — partial; each needs the platform to expose new
  state/endpoints. Tracked in `docs/CONSTITUTION_COVERAGE.md`.
