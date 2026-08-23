# HOPEFX — What We Have To Do

Durable action list from the 157-finding audit. Committed so it survives a
context reset or container restart. Nothing here has been fixed — the audit was
read-only by instruction.

Detail for every item: `CODE_READING_FINDINGS.md`. System map:
`PLATFORM_ARCHITECTURE.md`.

**Status legend:** ☐ not started · ◐ in progress · ☑ done

---

## PHASE 0 — Restore the safety net (do this first, it is a settings fix)

- [ ] **F95 · CI has not run on `main` for 30+ consecutive pushes.** All 30 most
      recent `ci.yml` runs failed with `runner_id: 0` and no runner assigned —
      no step executed. Signature points to an Actions billing/spending limit.
      **Cannot be fixed from code.** Check GitHub billing → Actions spending.
      Everything below is unverifiable until this is green.
- [ ] **F96 · `deploy.yml` has no `needs:`** and fires on every push to `main`.
      Add a dependency on CI passing, or a `workflow_run` gate.
- [ ] **F97 · `appleboy/ssh-action@v1.2.5` is the only unpinned action** in 18
      workflows, and it holds `VPS_SSH_KEY`. Pin to a 40-char SHA.
- [ ] **F103 · `brain/` and `news/` coverage gates cannot pass** — neither
      package is in `.coveragerc [run] source`. Add them, or drop the gates.
- [ ] **F104 · the job named "Coverage gate (>=70%)" has no failure path.**
      Add `exit 1` / `core.setFailed`, or rename it so it stops implying a gate.

---

## PHASE 1 — The stop-loss chain (one connected defect, traced end to end)

This is the control a retail trader relies on most. It is offered in the UI at
three layers and does not exist at the broker.

- [ ] **F151 · a user-entered stop-loss is accepted, forwarded, and discarded.**
      `PlaceOrderScreen.tsx:77` → `apiClient.ts:246` → `api/trading.py:690-693`
      (forwards faithfully) → `brokers/base.py:549-560` (logs at DEBUG, ignores).
      Order returns **201 Created**. Minimum honest fix: return the order with
      `stop_loss: null` when it was not applied, so the client can show it.
      Real fix: implement bracket orders per connector, or refuse the order.
- [ ] **F45 · the local SL/TP monitor is dead** — `sl_tp_monitor.py:202` reads
      `pos.position_id`; `PositionTracker.Position` has `.id`. One-line fix.
- [ ] **F59 · all three stop-loss mechanisms are non-functional** on the live
      path. Fixing F151 + F45 covers two; verify the third.
- [ ] **F60/F106 · `trade_executor.py:416` crashes on every non-paper broker,
      AFTER the fill.** `order.status.value` — status is a plain `str`. Plus
      `order.id` at :438/:447/:467/:496/:501 — the field is `order_id`.
- [ ] **F61/F107 · `BROKER_TYPE=oanda` cannot place an order.**
      `AsyncOANDAConnector = OANDABroker` is an alias with no
      `place_market_order` (it has `place_order`). Live OANDA is the stated next
      milestone and `k8s/k8s-configmap.yaml:33-34` already sets
      `BROKER_TYPE=oanda`, `OANDA_PRACTICE=false`.

---

## PHASE 2 — Risk gates that are absent or bypassed

- [ ] **F142 · the ACTIVE paper path has no risk layer.** `PaperRunner` →
      `bus.publish(CH_ORDER)` → `FIXRouter._route`, whose only gate is
      `if self._halted`. No RiskManager, no sizing, no SL/TP, fixed
      `PAPER_ORDER_UNITS=1000`. Route it through `ExecutionEngine`, or add the
      gates to `_route`. (Note F152: the *API* order path IS properly gated —
      this is the internal signal loop only.)
- [ ] **F84 · the data-layer safety gate is skipped in the condition it exists
      for.** `execution/engine.py:687` — drop the `orchestrator._started and`
      conjunct so it fails closed like `ml/inference_engine.py:1403` does.
- [ ] **F139 · `deployments/k8s/` disables cross-pod kill-switch propagation.**
      No RBAC file, no `serviceAccountName` → ConfigMap patch denied. Either
      delete that manifest set or copy `k8s/kill-switch-rbac.yaml` into it and
      set the service account. Also point the flag file at the persistent
      `trading_state` volume rather than the image layer.
- [ ] **F98 · two ConfigMaps named `hopefx-config` with contradictory safety
      values.** Last `kubectl apply` wins. Delete one, or rename.
- [ ] **F130 · self-healer patch signing is off and set nowhere.**
      Set `HEAL_PATCH_SIGNING_KEY` in every env template and ConfigMap, or make
      `_patch_entry_is_trusted` fail closed when the key is absent.

---

## PHASE 3 — Money correctness

- [ ] **F135 · wallet ledger rows collide and are silently dropped.**
      `transaction_id = f"TXN-{...%Y%m%d%H%M%S}"` against a globally unique
      column; 5 ids in 0.1ms are identical. Append a `uuid4`. Also stop
      swallowing the IntegrityError while the in-memory balance has moved.
- [ ] **F136 · the wallet balance is an unlocked read-modify-write.** Use
      `SELECT … FOR UPDATE` or an atomic `UPDATE … SET balance = balance + :amt`.
- [ ] **F138 · `invariants/payments.py:84 verify_balance_after` is never
      called.** Wire it into the wallet write path — it catches F135 and F136.
- [ ] **F137 · `amount_crypto` is a `Float`** and cannot represent 18-decimal
      token amounts. Move to `Numeric`. (USD columns measured adequate — see the
      finding before widening scope.)
- [ ] **F31/F32 · affiliate + subscription money state is in-memory only, with
      a payout TOCTOU and no lock on any money path.**

---

## PHASE 4 — ML correctness

- [ ] **F145 · missing features are zero-filled BEFORE scaling.**
      `ml/__init__.py:328` fills raw `0.0`, `:337` then scales, so a missing
      feature arrives as `(0-mean)/std` — measured **−15σ** for price, **−3.3σ**
      for RSI. With 48.2% of the vector missing (F24) the model gets a confident
      description of an impossible market. **Fix the ordering, not the value.**
- [ ] **F146 · drift coverage is measured and gates nothing.**
      `inference_engine.py:231-241` already computes covered/total and names the
      uncovered features. Refuse to predict below a coverage threshold.
- [ ] **F24 · close the train/serve feature gap** so coverage rises.

---

## PHASE 5 — Things that silently do nothing

- [ ] **F94 · regime detection never runs.** `RegimeRouter.route()` has zero
      callers → regime permanently `"unknown"` → **every position is sized at
      0.5×** via `_REGIME_SIZE_MAP`. Either call it or remove the scalar.
- [ ] **F88 · `hopefx_engine.py:398` injects `StrategyManager()` with zero
      strategies.** Pass `preload_defaults=True`, or document that the nuclear
      agent is the only intended signal source.
- [ ] **F147 · the order-flow subsystem is mounted and never fed** — 2,791 LOC,
      five GET endpoints, no ingest path. Feed it or unmount it.
- [ ] **F123 · `/walk-forward/run` performs no walk-forward analysis** — test
      set inside the train set, all 5 folds identical, nothing optimised.
      `backtesting/walk_forward.py` already has a correct implementation with a
      purge gap. Use it.
- [ ] **F129/F94 · eight independent "market regime" vocabularies.** Pick one.

---

## PHASE 6 — Correctness bugs (isolated, low-risk fixes)

- [ ] **F119 · annualised return uses `252/len(equity_values)`** where the array
      is per-bar and bars are hourly → **34× understated**; Calmar inherits it.
- [ ] **F120 · Sortino denominator** is the std of losing observations, not
      downside deviation. Bias flips sign with distribution shape.
- [ ] **F125 · the regime EMA iterates `reversed()`** → oldest bar weighted
      **7.4×** the newest.
- [ ] **F149 · the GodMode watchlist sparkline is fabricated** from
      `Math.random()` and re-randomises every render.
- [ ] **F150 · "Copy API key" builds the key client-side** and it can never
      authenticate.
- [ ] **F144 · login is user-enumerable by timing** — 268.74 ms measured gap.
      Verify against a fixed dummy hash on the not-found path.
- [ ] **F80 · the nuclear wordmap matches by bare substring** — a headline
      containing "coupon" scores severity 7 and triggers hedge mode. Add word
      boundaries.
- [ ] **F81 · the hedge is marked active before the broker call** and booked
      with `order_id=None` even when the order raises.

---

## PHASE 7 — Test integrity (nothing below is trustworthy until fixed)

- [ ] **F99 · the placeholder-secret test skips on the case it exists for** —
      8 secrets exempted including `DB_ENCRYPTION_KEY` and `POSTGRES_PASSWORD`.
- [ ] **F108 · 14 of 37 tests in one file assert nothing** against a class
      (`PerformanceAnalyzer`) that has never existed.
- [ ] **F105 · the 80% gates measure the packages with the risk logic omitted** —
      `.coveragerc` omits 37% of `risk/` including `risk/manager.py`.
- [ ] **F106 · nothing tests the join** between `TradeExecutor` and a real
      connector; a MagicMock makes the broken line pass.

---

## AUDIT COVERAGE — what has not been read

157 findings from ~200 files read deeply of 1,911 total.

**Never opened (~44,000 LOC), in the order I would take them:**

| LOC | Package | Why it matters |
|---:|---|---|
| 3,473 | `cache/` | Redis layer that F84/F87/F139 all depend on |
| 2,732 | `config/` | F98, F101, F130 all trace to config defaults |
| 2,496 | `compliance/` | money-adjacent; every money path audited found something |
| 2,493 | `portfolio/` | position/PMS state |
| 3,867 | `notifications/` | alert delivery — the thing that tells you when it breaks |
| 3,840 | `charting/` | |
| 3,531 | `utils/` | contains `fault_guard.py` (F143) |
| 2,850 | `analytics/` | F108 showed its tests are inert |
| 2,442 | `infrastructure/` | |
| 2,378 | `resilience/` | |
| ~14,000 | `nocode`, `social`, `teams`, `whitelabel`, `chaos`, `monitoring`, `tracing`, `deployment`, `replay`, `transparency`, `rate_limiting`, `shadow`, `explainability`, `events`, `reports`, `visualization`, `forensics`, `examples`, `locust`, `mobile` | lower value |

**Also never audited: `tests/` (221,598 LOC, 588 files).** Only sampled. Given
F99 and F108 — tests that skip the exact case they exist for — this is a real
gap, not a formality.
