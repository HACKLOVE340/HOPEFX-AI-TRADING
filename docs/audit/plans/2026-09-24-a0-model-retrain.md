# A0 — Retrain and Register a Current Model: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 176-day-old active model (`xgb_horizon5_v3`, sha256 `dc7454d8…`, provenance 2026-04-01) with a model trained on data that reaches to within `MODEL_MAX_AGE_DAYS=30` of deployment. Register it with a sha256-bound `trained_at`, pass every validation gate, and keep a one-command rollback. The limit and `STALE_MODEL_BLOCK` stay unchanged.

**Architecture:** Train in an isolated git worktree, never in the main checkout, so no step can write the 11 manifest artifacts in `ml/saved_models/`. Evaluate the candidate against the incumbent on the same held-out window. Only then, and only with the owner's approval, copy the artifact in, register it through `ml/model_registry.py::ModelRegistry.register` / `promote`, and update `model_checksums.json`, all in one reviewed commit.

**Tech Stack:** Python **3.12** (`/usr/bin/python3.12`; the repo `.venv` is **3.11.15** and must NOT produce artifacts), XGBoost/sklearn, `scripts/retrain_horizon5.py`, `scripts/retrain_model.py`, `ml/model_registry.py`, `ml/verify_model.py`, `ml/cached_series.py`.

**Spec:** `docs/ai/MASTER_OUTSTANDING.md` §A0; `python scripts/correction_register.py --id MODEL-166-DAYS-OLD` and `--id MODEL-AGE-IS-MTIME`.

## Global Constraints

- Do NOT raise `MODEL_MAX_AGE_DAYS` (30), set it to 0 in any trading deployment, or disable `STALE_MODEL_BLOCK`. The owner decided this on 2026-09-24.
- Pickle artifacts only under Python 3.12, which is what the Dockerfile's `python:3.12-slim` runs. An artifact made with the 3.11 `.venv` is invalid for production.
- Run no training command with the main checkout as its CWD. Both retrain scripts hard-code or default to `ml/saved_models/` (`retrain_horizon5.py:92` `_MODEL_DIR = _ROOT / "ml" / "saved_models"`, which ignores `ML_MODEL_DIR`).
- Do not hand-edit `registry.json` or `model_checksums.json`. Registry entries come from `ModelRegistry.register`, and the manifest from the sha256 of the bytes.
- Never use a yfinance `GC=F` fetch as XAUUSD training data. It is COMEX futures, not spot: `retrain_horizon5.py --symbol` defaults to `GC=F`, and `retrain_model.py` falls back to yfinance. See CLAUDE.md on the delisted ticker.
- Registration, promotion and deployment are owner actions (§(b) below).
- Documentation ships in the same commit: MASTER_OUTSTANDING §A0, CLAUDE.md gotcha, `python scripts/doc_metrics.py --check`.

---

## Measured facts (2026-09-24, this session)

| Fact | Value | How measured |
|---|---|---|
| Active version | `xgb_horizon5_v3`, same sha256 as `advanced_oos_v1/v2`, `xgb_horizon5_v1` | `registry.json` |
| Measured age | **176 days** vs a 30-day limit | `correction_register.py --id MODEL-166-DAYS-OLD` |
| `data/XAUUSD_40Y.csv` | 2000-08-30 .. **2026-03-25**, 6,415 bars (441 bad, all pre-2020) | head/tail |
| `data/XAUUSD_5Y.csv` | 2021-03-26 .. **2026-03-24** | head/tail |
| `data/XAUUSD_50Y.csv` | 1968-01-01 .. **2026-04-01**, deliberately excluded by `ml/cached_series.py` | head/tail |
| `data/XAUUSD_2Y.csv` | 2022-01-03 .. 2024-10-18 | head/tail |
| `data/macro/{dxy,vix,us10y,us2y,gold_etf_flow}_daily.csv` | 2021-03-29 .. **2026-03-25** | head/tail |
| Intraday XAUUSD offline | none (daily/weekly only) | CLAUDE.md, `data/` |
| Retrain workflows | `.github/workflows/retrain.yml` (runs `retrain_model.py --advanced --years 50 --oos-years 8` then `retrain_horizon5.py --verify-only`, Py 3.12), `quarterly_retrain.yml` | workflow files |
| CI runners | none assigned for weeks (F95), so the workflow cannot be relied on | CLAUDE.md |

**The central finding: the newest offline bar is 2026-03-25, which is 183 days before today.** A model trained today on bundled data would get a fresh `trained_at`, and the gate would pass it. But it would have learned from exactly the same market window as the model it replaces. That satisfies the check without satisfying what the check is for: this is the MODEL-AGE-IS-MTIME defect in a new form. **A retrain is only current if the training data is extended to within about 30 days of today, and that needs a data source only the owner can supply.** Task 1 adds a guard so this cannot happen by accident.

---

## (a) Steps an agent can run in a session

### Task 1: A data-recency guard on registration (test-first)

A registry entry's `trained_at` must not be trusted unless the data behind it is recent. Record `data_end` on the entry, and refuse to promote when `data_end` is older than `MODEL_MAX_AGE_DAYS`.

**Files:**
- Modify: `ml/model_registry.py` (`register`: new kwarg `data_end: str | None`; `promote`: refuse if missing or stale)
- Test: tests/unit/test_registry_refuses_stale_training_data.py — to be created

**Interfaces:**
- Produces: `ModelRegistry.register(..., data_end: str | None = None)` stores `"data_end"` (ISO date). `ModelRegistry.promote(name)` raises `ValueError("training data ends <date>, <n> days old > MODEL_MAX_AGE_DAYS")`. `rollback()` is deliberately left unchanged: an emergency restore of a previously validated model must stay possible.

- [ ] **Step 1: Write the failing test.** It uses a `tmp_path` registry only; it must never point at `ml/saved_models`.

```python
import datetime as dt, pytest
from ml.model_registry import ModelRegistry

def _reg(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_MAX_AGE_DAYS", "30")
    art = tmp_path / "m.pkl"; art.write_bytes(b"x")
    r = ModelRegistry(tmp_path / "registry.json")
    return r, art

def test_promote_refuses_model_trained_on_old_data(tmp_path, monkeypatch):
    r, art = _reg(tmp_path, monkeypatch)
    old = (dt.date.today() - dt.timedelta(days=183)).isoformat()
    r.register("cand", art, data_end=old, sharpe_gate_passed=True)
    with pytest.raises(ValueError, match="training data ends"):
        r.promote("cand")

def test_promote_refuses_when_data_end_unknown(tmp_path, monkeypatch):
    r, art = _reg(tmp_path, monkeypatch)
    r.register("cand", art, sharpe_gate_passed=True)
    with pytest.raises(ValueError, match="training data ends"):
        r.promote("cand")
```

Before writing it, check `ModelRegistry.__init__`'s real signature (`sed -n 1,180p ml/model_registry.py`) and adapt the constructor call. Check which other gates `promote` applies (Sharpe/PnL) so the fixture reaches the new check. **Assert that the new check is the one that refused, and not an earlier gate.** An earlier gate refusing would make the test pass for the wrong reason.

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/unit/test_registry_refuses_stale_training_data.py -q` → expected FAIL (`register() got an unexpected keyword 'data_end'`).
- [ ] **Step 3:** Implement. Store `data_end` in `register`. In `promote`, compute `(today - date.fromisoformat(data_end)).days` against `int(os.getenv("MODEL_MAX_AGE_DAYS", "30"))`. A missing value refuses.
- [ ] **Step 4:** Re-run → PASS. Then run `.venv/bin/python -m pytest tests/unit -q -k "registry or model_age or promote"`. Read any newly red test before changing it: it may be asserting the defect (see the hopefx-dead-controls skill).
- [ ] **Step 5:** `git stash push -- ml/model_registry.py`, run the test and watch it fail, then `git stash pop`. Commit the test and the change together.

### Task 2: Isolated 3.12 training workspace

- [ ] **Step 1:**
```bash
git worktree add --detach /tmp/a0-retrain HEAD
/usr/bin/python3.12 -m venv /tmp/a0-venv312
/tmp/a0-venv312/bin/pip install -r /home/user/HOPEFX-AI-TRADING/requirements.txt
/tmp/a0-venv312/bin/python -c "import sys,xgboost,sklearn;print(sys.version,xgboost.__version__,sklearn.__version__)"
```
Expected: `3.12.x`, with library versions matching the Dockerfile and requirements pins. **Record them in the report.** A pickle made under a different sklearn/xgboost version is not loadable either.
- [ ] **Step 2: Snapshot the manifest.** `sha256sum ml/saved_models/*.pkl > /tmp/a0-before.sha` (run in the MAIN checkout). Task 6 diffs against this snapshot.

### Task 3: Dry run on bundled data, to prove the pipeline only

This proves the pipeline end to end. **It does not produce a model to register.** The data ends 2026-03-25, so Task 1's guard must refuse it, and that refusal is part of the check.

- [ ] **Step 1:**
```bash
cd /tmp/a0-retrain && PYTHONPATH=. /tmp/a0-venv312/bin/python scripts/retrain_horizon5.py \
  --use-cached --splits 8 --oos-years 2 2>&1 | tee /tmp/a0-dryrun.log
```
Expected: walk-forward folds are logged, an OOS accuracy/AUC/N is printed, and artifacts are written under `/tmp/a0-retrain/ml/saved_models/`, not under the main checkout.
- [ ] **Step 2:** Confirm the training frame starts at or after `CLEAN_SINCE["XAUUSD"]` (2020), or goes through `data/XAUUSD_40Y_clamped.csv`. `grep -n "load_cached_daily\|XAUUSD_40Y" scripts/retrain_horizon5.py`. If the script reads the raw 40Y file with its 441 bad pre-2020 bars, record that as a finding. Do not silently patch it.
- [ ] **Step 3:** Register the candidate in a **throwaway** `ModelRegistry(/tmp/a0-retrain/ml/saved_models/registry.json)` with `data_end="2026-03-25"`, then call `promote`. Expected: `ValueError: training data ends 2026-03-25…`. The guard is shown able to fail.

### Task 4: Validation gates for any candidate

Run these in the worktree on the candidate. Owner-supplied data goes through the same gates in Task 7.

- [ ] Leakage: `/tmp/a0-venv312/bin/python -m pytest tests/unit/test_mtf_ensemble_leakage.py -q` → PASS. The file asserts it observed a fit before asserting anything else (LEAKAGE-GUARD-CHECKED-NOTHING).
- [ ] Walk-forward OOS: from the training report (`horizon5_training_report.json`), require OOS N ≥ 600, Sharpe SE ≤ 0.10 and `sharpe_gate_passed=true`. These are the gates the incumbent's notes cite.
- [ ] Head-to-head on the same held-out window. Evaluate the incumbent (`git show HEAD:ml/saved_models/advanced_oos.pkl > /tmp/a0-incumbent.pkl`) and the candidate on identical post-cutoff bars. Write `/tmp/a0-compare.json` with accuracy, AUC, N, and net P&L after costs via `backtesting/`. Promote only if the candidate is not worse beyond one standard error. **Held-out bars must post-date every training bar of BOTH models:** the incumbent saw data to about 2026-03, so the comparison window is only the owner-supplied new data.
- [ ] Drift: `/tmp/a0-venv312/bin/python scripts/drift_guard_report.py`. Record the zero-filled-feature fraction (ADR 0019). A candidate trained with `--no-macro` changes the feature set, and the report must show this.
- [ ] Provenance ratchet: `.venv/bin/python scripts/model_provenance_report.py --check` → no growth.
- [ ] Run the fast suite on **both** interpreters in the worktree (SUITE-REWRITES-MODEL is invisible on 3.11): `pytest -m "not slow and not e2e" -q`. `tests/conftest.py::_refuse_to_rewrite_committed_models` must stay in place.

### Task 5: Rollback drill (throwaway registry)

- [ ] In the worktree registry: `register` the candidate, `promote` it, then `ModelRegistry.rollback("xgb_horizon5_v3")`. Assert that `active_version == "xgb_horizon5_v3"` and that `ml.verify_model` passes. The runtime path is `ml/inference_engine.py:2210 rollback_model()`. The git path is `git revert <registration commit>`, which restores the pkl, registry and manifest atomically. **Note:** after a rollback the incumbent is 176 days old again, so inference is refused again. Rollback means "stop trading", not "trade on the old model". Say so in the runbook line in §A0.

### Task 6: Prove the main checkout was untouched

- [ ] `sha256sum ml/saved_models/*.pkl | diff /tmp/a0-before.sha -` → no output. `git -C /home/user/HOPEFX-AI-TRADING status --short ml/` → empty.

---

## (b) Steps that need the owner

### Task 7: Current training data (BLOCKER)

The owner supplies XAUUSD **spot** daily bars (and, ideally, H1) from 2026-03-26 up to within a few days of the training date. The five macro series (DXY, VIX, US10Y, US2Y, gold ETF flow) are needed over the same range, or the owner accepts a `--no-macro` model. Viable sources: an OANDA practice/live account (`OANDA_API_KEY`, `OANDA_ACCOUNT_ID`), MT5 terminal credentials, or a licensed CSV export. Not viable: yfinance `GC=F` (futures).

- [ ] The agent validates the delivered file: monotone timestamps, no duplicate dates, `high ≥ max(open, close)`, `low ≤ min(open, close)`, and the seam with `XAUUSD_40Y.csv` at 2026-03-24/25 within 0.5%. Run `scripts/clamp_ohlc.py --check` style integrity, and check `CachedSeries.integrity`.
- [ ] Rerun Tasks 3–5 on the extended series, with `data_end` = last bar date. The candidate must now pass Task 1's guard.

### Task 8: Approval to register and promote

- [ ] The owner reviews `/tmp/a0-compare.json` and the drift report, and approves.
- [ ] Only then, in the main checkout on a branch, do the following in ONE commit:
  1. Copy the 3.12 artifact(s) in.
  2. Call `ModelRegistry.register(name="xgb_horizon5_v4", file_path=…, data_end=…, trained_at=…)` and `promote`.
  3. Regenerate the `model_checksums.json` entries from `sha256sum`.
  4. Run `.venv/bin/python -m ml.verify_model` → exit 0, and `APP_ENV=production … _verify_checksum` with 11/11 entries verifying.
  5. Run `python scripts/correction_register.py --id MODEL-166-DAYS-OLD` → no longer OWNER, and `--id A8` still green.
  6. Update the docs (MASTER_OUTSTANDING §A0, CLAUDE.md gotcha, `doc_metrics.py --sync`).

### Task 9: Deploy and keep it current

- [ ] The owner deploys. `GET /health` shows the engine healthy and inference is no longer refused.
- [ ] Schedule the next retrain before day 30. That needs either a working Actions runner (F95) or a scheduled session with a data feed. Otherwise A0 recurs in a month.

---

## Effort estimate

- (a), Tasks 1–6: about 1 session (3–5 h). Task 1 ≈ 1 h; the 3.12 env and dry run ≈ 1–2 h (training time depends on `--stacking` and splits); gates and drill ≈ 1–2 h.
- (b), after data arrives: about 0.5–1 session for validation, re-training, comparison and the registration commit.

## Decisions for the owner

1. **Data source.** Choose OANDA, MT5 or a licensed CSV for XAUUSD spot from 2026-03-26 onward. Without it, a retrain is fresh in name only.
2. **Macro features.** Supply the five macro series to the same date, or accept a `--no-macro` model (a different feature set, re-baselining drift).
3. **Promotion bar.** Is "not worse than the incumbent within one SE on the post-March window, plus the N≥600 Sharpe gate" the acceptance criterion?
4. **Training environment.** Run locally in a 3.12 venv as in this plan, or fix the Actions runner (F95) so `retrain.yml` does it.
5. **Cadence.** Set a retrain schedule shorter than 30 days, or record a different limit through an ADR. The limit is not changed by this plan.
6. **Task 1 guard.** Approve adding the `data_end` promotion guard, which makes "fresh on stale data" unregistrable.
