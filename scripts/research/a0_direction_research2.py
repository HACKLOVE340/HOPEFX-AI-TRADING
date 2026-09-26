# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/research/a0_direction_research2.py
==========================================
Research spike 2 (A0): a wider search for directional skill on daily XAUUSD,
in families the first spike (``a0_target_research.py``, 52 tests) did not run.
Writes nothing outside ``--out``; never touches ``ml/saved_models/``,
``ml/rl_models/`` or any registry.

Report: ``docs/audit/2026-09-25-direction-research-2.md``.

Families (numbered after the first spike's 1-5; every variant is counted):

6. Conditional / regime-gated direction: reversal after k-sigma days, momentum
   gated by volatility regime, variance-ratio (trend vs range) gating, and a
   regime-split logit. Plus four rules traded from them.
7. Meta-labelling: the eight ``strategies/`` classes are the primary model;
   a secondary model predicts which of their long entries win under a
   triple-barrier label, and filters them.
8. Calendar: day-of-week, turn-of-month, month-of-year, US-holiday proximity,
   each as a walk-forward mean forecast and as a long/flat rule.
9. Cross-asset lead-lag from ``data/macro`` (DXY, US10Y, US2Y, VIX, GLD),
   2021-03-29 onward only: no earlier data exists offline, so no replication.
10. Asymmetric / tail: the sign of a large move given one occurs, and a
    tradable up-tail minus down-tail score.
11. Ensemble of every weak signal above in one regularised logit.

The data loader, features, walk-forward, block bootstrap, strategy accounting
and deflated Sharpe are imported from ``a0_target_research`` unchanged, so the
two spikes share one protocol. Bonferroni runs over ``PRIOR_TESTS`` (52) plus
every test counted here.

Usage::

    python scripts/research/a0_direction_research2.py --out /tmp/a0-research2
    python scripts/research/a0_direction_research2.py --out /tmp/a0-research2 --truncate-at 2018-03-26
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, skew

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import a0_target_research as base

logger = logging.getLogger("a0_direction_research2")

PRIOR_TESTS = 52  # docs/audit/2026-09-25-a0-target-research.md, main run
MACRO_START = pd.Timestamp("2021-03-29")
MACRO_OOS_YEARS = 3
TB_HORIZON = 10
TB_WIDTH = 1.0  # barrier = TB_WIDTH * sigma20 * sqrt(TB_HORIZON), close-to-close


# ── shared helpers ────────────────────────────────────────────────────────────


def sigmoid(x: pd.Series) -> pd.Series:
    return 1.0 / (1.0 + np.exp(-x.clip(-50, 50)))


def direction_label(close: pd.Series, h: int) -> pd.Series:
    fr = base.fwd_log_return(close, h)
    return (fr > 0).astype(float).where(fr.notna())


def rule_test(
    name: str, family: str, score: pd.Series, y: pd.Series, rows: pd.Series, h: int, note: str = ""
) -> dict | None:
    """AUC of an a-priori-signed score for direction on the selected rows.

    No fitting: the score's sign was fixed before the data was seen, so the
    test is one-sided (H1: AUC > 0.5). Accuracy uses score > 0 as "up" and is
    held to the repo rule (accuracy above always-majority, AUC bound > 0.5).
    """
    ok = rows & score.notna() & y.notna()
    if ok.sum() < 30:
        logger.warning("skip %s: %d rows", name, int(ok.sum()))
        return None
    r = base.eval_binary(name, family, y[ok], sigmoid(score[ok]), max(h, base.MIN_BLOCK))
    r["rows_selected"] = int(ok.sum())
    if note:
        r["note"] = note
    return r


def eval_strategy_vs_zero(name: str, family: str, sret: pd.Series, bh: pd.Series, pos: pd.Series) -> dict:
    """Sharpe of a long/short rule against zero (flat). B&H reported for context."""
    s = sret.to_numpy()
    idx = base.mbb_index(len(s), base.STRATEGY_BLOCK)
    sr = float(base.sharpe(s))
    eq = np.cumprod(1 + s)
    years = len(s) / base.TRADING_DAYS
    p = pos.loc[sret.index]
    return {
        "name": name,
        "family": family,
        "metric": "Sharpe(strategy), net of costs, vs 0",
        "baseline": "zero (flat)",
        "n": len(s),
        "block": base.STRATEGY_BLOCK,
        **base.summarise(sr, base.sharpe(s[idx]), 0.0),
        "sharpe": round(sr, 4),
        "sharpe_bh": round(float(base.sharpe(bh.to_numpy())), 4),
        "cagr": round(float(eq[-1] ** (1 / years) - 1), 4),
        "max_dd": round(float((eq / np.maximum.accumulate(eq) - 1).min()), 4),
        "exposure": round(float(p.abs().mean()), 4),
        "turnover_per_year": round(float(p.diff().abs().sum() / years), 2),
        "daily_sr": float(s.mean() / s.std(ddof=1)),
        "skew": float(skew(s)),
        "kurt": float(kurtosis(s, fisher=False)),
        "window": f"{sret.index[0].date()}..{sret.index[-1].date()}",
        "repo_rule_pass": None,
        "counted": True,
    }


def strat_vs_bh(name: str, family: str, pos: pd.Series, close: pd.Series, win: pd.Series, cost: float) -> dict:
    bh = close.pct_change().fillna(0.0)
    sret = base.strategy_returns(pos.fillna(0.0), close, cost)
    return base.eval_strategy(name, family, sret[win], bh[win], pos.fillna(0.0), {})


def same_close_returns(pos: pd.Series, close: pd.Series, cost_bps: float) -> pd.Series:
    """UPPER BOUND, breaks the protocol: a position decided at close t also fills at close t.

    Only achievable if the signal is computed from a price just before the
    close and filled at it. Reported to size what a same-close execution path
    would be worth, never as a pass.
    """
    r = close.pct_change()
    held = pos.fillna(0.0)
    cost = held.diff().abs().fillna(held.abs()) * cost_bps / 1e4
    return (held.shift(1).fillna(0.0) * r - cost).fillna(0.0)


def strat_vs_zero(name: str, family: str, pos: pd.Series, close: pd.Series, win: pd.Series, cost: float) -> dict:
    bh = close.pct_change().fillna(0.0)
    sret = base.strategy_returns(pos.fillna(0.0), close, cost)
    return eval_strategy_vs_zero(name, family, sret[win], bh[win], pos.fillna(0.0))


def r2_vs(name: str, family: str, y: pd.Series, pm: pd.Series, pb: pd.Series, block: int, baseline: str) -> dict:
    yv, a, b = y.to_numpy(), pm.to_numpy(), pb.to_numpy()
    em, eb = (yv - a) ** 2, (yv - b) ** 2
    idx = base.mbb_index(len(yv), block)
    return {
        "name": name,
        "family": family,
        "metric": "OOS R2 relative to baseline (1 - SSE/SSE_base)",
        "baseline": baseline,
        "n": len(yv),
        "block": block,
        **base.summarise(1 - em.sum() / eb.sum(), 1 - em[idx].sum(axis=1) / eb[idx].sum(axis=1), 0.0),
        "repo_rule_pass": None,
        "counted": True,
    }


# ── extra features (all use data <= t) ────────────────────────────────────────


def regime_features(close: pd.Series) -> pd.DataFrame:
    lc = np.log(close)
    r = lc.diff()
    f = pd.DataFrame(index=close.index)
    sig20 = r.rolling(20).std()
    f["z1"] = r / sig20.shift(1)  # today's move in units of yesterday's sigma
    ewvol = np.sqrt((r**2).ewm(alpha=1 - base.EWMA_LAMBDA, adjust=False).mean())
    f["high_vol"] = (ewvol > ewvol.rolling(252).median()).astype(float).where(ewvol.rolling(252).median().notna())
    # Lo-MacKinlay variance ratio VR(5) over a trailing 120-day window.
    f["vr5"] = r.rolling(5).sum().rolling(120).var() / (5 * r.rolling(120).var())
    f["skew_60"] = r.rolling(60).skew()
    f["skew_250"] = r.rolling(250).skew()
    dn = (r.clip(upper=0) ** 2).rolling(60).sum()
    up = (r.clip(lower=0) ** 2).rolling(60).sum()
    f["semivar_ratio_60"] = np.log((dn + 1e-12) / (up + 1e-12))
    big = np.sign(r).where(f["z1"].abs() > 2)
    f["last_large_sign_20"] = big.ffill(limit=19).fillna(0.0).where(sig20.notna())
    return f


def calendar_categories(index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Calendar category of each bar. All are knowable before the bar."""
    s = pd.Series(index, index=index)
    month = index.to_period("M")
    pos_in_month = s.groupby(month).cumcount()
    from_end = s.groupby(month).cumcount(ascending=False)
    tom = ((from_end == 0) | (pos_in_month <= 2)).astype(int)
    d = index.values.astype("M8[D]")
    gap = np.busday_count(d[:-1], d[1:])  # 1 for consecutive business days
    bdays_next = np.append(gap, 1)
    bdays_prev = np.insert(gap, 0, 1)
    # 0 normal, 1 pre-holiday (next bar skips a weekday), 2 post-holiday
    hol = np.select([bdays_next > 1, bdays_prev > 1], [1, 2], 0)
    hol[0] = 0
    hol[-1] = 0
    return {
        "day-of-week": pd.Series(index.dayofweek, index=index),
        "turn-of-month": pd.Series(tom.to_numpy(), index=index),
        "month-of-year": pd.Series(index.month, index=index),
        "US-holiday proximity": pd.Series(hol, index=index),
    }


def calendar_expanding_feature(r: pd.Series, cat: pd.Series) -> pd.Series:
    """At t: the mean daily return, over days <= t, of the category of day t+1."""
    dummies = pd.get_dummies(cat).astype(float)
    num = dummies.mul(r.fillna(0.0), axis=0).cumsum()
    den = dummies.mul(r.notna().astype(float), axis=0).cumsum()
    means = (num / den.where(den >= 20)).sub((r.fillna(0.0).cumsum() / r.notna().cumsum()), axis=0)
    nxt = cat.shift(-1)
    out = pd.Series(np.nan, index=r.index)
    for c in means.columns:
        m = nxt == c
        out[m] = means.loc[m, c]
    return out


# ── family 6: regime-gated direction ──────────────────────────────────────────


def run_regime(df: pd.DataFrame, feats: pd.DataFrame, rf: pd.DataFrame, oos: pd.Series, cost: float) -> list[dict]:
    close = df["close"]
    fam = "6 regime-gated direction"
    out: list[dict | None] = []
    z1 = rf["z1"]
    y = {h: direction_label(close, h) for h in (1, 5, 20)}
    low = rf["high_vol"] == 0
    high = rf["high_vol"] == 1
    for k in (2, 3):
        for h in (1, 5):
            out.append(rule_test(f"reversal after {k}-sigma day, h={h}", fam, -z1, y[h], oos & (z1.abs() > k), h))
    for side, cond, desc in (("down", z1 < -2, "buy the dip"), ("up", z1 > 2, "fade the rally")):
        out.append(rule_test(f"reversal after 2-sigma {side} day ({desc}), h=5", fam, -z1, y[5], oos & cond, 5))
    for reg_name, reg in (("low-vol", low), ("high-vol", high)):
        out.append(rule_test(f"momentum ret_20 in {reg_name}, h=5", fam, feats["ret_20"], y[5], oos & reg, 5))
        out.append(rule_test(f"momentum ret_20 in {reg_name}, h=20", fam, feats["ret_20"], y[20], oos & reg, 20))
        out.append(rule_test(f"momentum 12-1 in {reg_name}, h=20", fam, feats["mom_12_1"], y[20], oos & reg, 20))
    trend, rng = rf["vr5"] > 1, rf["vr5"] < 1
    out.append(rule_test("momentum ret_20 when VR(5)>1 (trending), h=5", fam, feats["ret_20"], y[5], oos & trend, 5))
    out.append(rule_test("momentum ret_20 when VR(5)>1 (trending), h=20", fam, feats["ret_20"], y[20], oos & trend, 20))
    out.append(rule_test("reversal ret_5 when VR(5)<1 (ranging), h=5", fam, -feats["ret_5"], y[5], oos & rng, 5))
    # Regime-split logit: trained only on its own regime's rows.
    oos_start = oos.idxmax()
    for reg_name, reg in (("low-vol", low), ("high-vol", high)):
        yy = y[5].where(reg)
        p, yo = base.walk_forward(feats, yy, 5, oos_start, base.logit_clf, "proba")
        out.append(base.eval_binary(f"regime-split logit, {reg_name} rows, h=5", fam, yo, p, base.MIN_BLOCK))
    # POST-HOC (added after family 11 showed h=1 skill coming from ret_1; see
    # the report): plain 1-day reversal on every day, at h=1 and against the
    # return the protocol can actually trade, r(t+2).
    y_t2 = (base.fwd_log_return(close, 2) - base.fwd_log_return(close, 1)).pipe(
        lambda s: (s > 0).astype(float).where(s.notna())
    )
    out.append(rule_test("POST-HOC 1-day reversal -ret_1, all days, h=1", fam, -feats["ret_1"], y[1], oos, 1))
    out.append(
        rule_test("POST-HOC 1-day reversal -ret_1 vs sign r(t+2) (tradable)", fam, -feats["ret_1"], y_t2, oos, 1)
    )
    # Rules traded (decided at close t, executed t+1, 5bp).
    ev = np.sign(-z1).where(z1.abs() > 2)
    pos_rev = ev.ffill(limit=4).fillna(0.0)
    out.append(strat_vs_zero("2-sigma reversal, hold 5d, long/short", "6 regime (strategy)", pos_rev, close, oos, cost))
    out.append(
        strat_vs_bh(
            "B&H with 2x after 2-sigma down / flat after 2-sigma up (5d)",
            "6 regime (strategy)",
            1.0 + pos_rev,
            close,
            oos,
            cost,
        )
    )
    pos_lv = pd.Series(np.where(low, np.sign(feats["ret_20"]), 1.0), index=close.index).where(rf["high_vol"].notna())
    out.append(strat_vs_bh("B&H, momentum sign(ret_20) in low-vol", "6 regime (strategy)", pos_lv, close, oos, cost))
    pos_r1 = np.sign(-feats["ret_1"]).fillna(0.0)
    out.append(
        strat_vs_zero(
            "POST-HOC 1-day reversal long/short (protocol lag)", "6 regime (strategy)", pos_r1, close, oos, cost
        )
    )
    sc = same_close_returns(pos_r1, close, cost)
    r_sc = eval_strategy_vs_zero(
        "POST-HOC 1-day reversal long/short, SAME-CLOSE fill (upper bound)",
        "6 regime (strategy)",
        sc[oos],
        close.pct_change().fillna(0.0)[oos],
        pos_r1,
    )
    r_sc["repo_rule_pass"] = False  # breaks the 1-bar-lag protocol: never a pass
    out.append(r_sc)
    sc0 = same_close_returns(pos_r1, close, 0.0)
    r_sc0 = eval_strategy_vs_zero(
        "POST-HOC 1-day reversal long/short, SAME-CLOSE fill, 0bp",
        "6 regime (strategy)",
        sc0[oos],
        close.pct_change().fillna(0.0)[oos],
        pos_r1,
    )
    r_sc0["repo_rule_pass"] = False
    out.append(r_sc0)
    pos_vr = pd.Series(np.where(trend, np.sign(feats["ret_20"]), -np.sign(feats["ret_5"])), index=close.index)
    pos_vr = pos_vr.where(rf["vr5"].notna())
    out.append(strat_vs_zero("VR-gated momentum/reversal long/short", "6 regime (strategy)", pos_vr, close, oos, cost))
    return [r for r in out if r is not None]


# ── family 7: meta-labelling ──────────────────────────────────────────────────


def repo_positions(df_full: pd.DataFrame, cache: Path, window: int = 500) -> pd.DataFrame:
    """Long/flat position of each repo strategy on every bar (causal; cached)."""
    if cache.exists():
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    from backtesting.strategy_adapter import BacktestStrategyAdapter
    from strategies.registry import available_strategies, build

    close = df_full["close"]
    frame = df_full.copy()
    frame["timestamp"] = frame.index
    out = pd.DataFrame(index=close.index)
    for key in available_strategies():
        t0 = time.time()
        adapter = BacktestStrategyAdapter(build(key, "XAUUSD", timeframe="1d"), "XAUUSD")
        pos = np.full(len(frame), np.nan)
        for i in range(window, len(frame)):
            win = frame.iloc[i - window + 1 : i + 1]
            adapter.generate_signals(frame.index[i], {"XAUUSD": float(close.iloc[i])}, {"XAUUSD": win})
            pos[i] = 1.0 if adapter.position == "long" else 0.0
        out[key] = pos
        logger.info("repo %s positions in %.0fs (errors=%d)", key, time.time() - t0, len(adapter.errors))
    out.to_csv(cache)
    return out


def triple_barrier_events(close: pd.Series, positions: pd.DataFrame) -> pd.DataFrame:
    """Non-overlapping long entries per strategy, labelled by a triple barrier.

    Signal at close t (flat -> long). Entry at close t+1 (one bar of lag).
    Barriers at +/- TB_WIDTH * sigma20_t * sqrt(TB_HORIZON) in log terms, on
    closes t+2 .. t+1+TB_HORIZON. Label 1 if the upper barrier is hit first,
    else 0 if the lower is; at the time barrier, 1 if the return is positive.
    ``obs`` is the bar whose close reveals the outcome; the exit trades at
    close obs+1, so the position is decided long on bars t .. obs-1... and the
    exit is decided at obs.
    """
    lc = np.log(close).to_numpy()
    sig = np.log(close).diff().rolling(20).std().to_numpy()
    n = len(close)
    rows = []
    for key in positions.columns:
        p = positions[key].to_numpy()
        busy_until = -1
        for t in range(1, n):
            if not (p[t] == 1 and p[t - 1] == 0) or t <= busy_until or not np.isfinite(sig[t]):
                continue
            e0 = t + 1
            last = e0 + TB_HORIZON
            if last >= n:
                break
            barrier = TB_WIDTH * sig[t] * math.sqrt(TB_HORIZON)
            path = lc[e0 + 1 : last + 1] - lc[e0]
            hit_up = np.flatnonzero(path >= barrier)
            hit_dn = np.flatnonzero(path <= -barrier)
            first_up = hit_up[0] if len(hit_up) else TB_HORIZON
            first_dn = hit_dn[0] if len(hit_dn) else TB_HORIZON
            if first_up < first_dn:
                label, k = 1, first_up
            elif first_dn < first_up:
                label, k = 0, first_dn
            else:
                label, k = int(path[-1] > 0), TB_HORIZON - 1
            obs = e0 + 1 + k
            rows.append({"strategy": key, "t": t, "obs": obs, "label": label})
            busy_until = obs  # one open trade per strategy
    ev = pd.DataFrame(rows)
    ev["date"] = close.index[ev["t"].to_numpy()]
    ev["obs_date"] = close.index[ev["obs"].to_numpy()]
    return ev.sort_values(["t", "strategy"]).reset_index(drop=True)


def event_walk_forward(
    x: pd.DataFrame, ev: pd.DataFrame, oos_start: pd.Timestamp, make_model: Any
) -> tuple[pd.Series, pd.Series]:
    """Yearly refit; a training event is purged unless its outcome is known before the fold.

    Returns (P(win) for OOS events, that fold's training win rate as the filter threshold).
    """
    preds = pd.Series(np.nan, index=ev.index)
    thr = pd.Series(np.nan, index=ev.index)
    starts = base.fold_starts(oos_start, ev["date"].max())
    for k, fs in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else ev["date"].max() + pd.Timedelta(days=1)
        test = (ev["date"] >= fs) & (ev["date"] < end)
        train = ev["obs_date"] < fs
        if not test.any():
            continue
        model = make_model()
        model.fit(x[train].to_numpy(), ev.loc[train, "label"].to_numpy())
        preds[test] = model.predict_proba(x[test].to_numpy())[:, 1]
        thr[test] = float(ev.loc[train, "label"].mean())
    return preds, thr


def events_to_position(ev: pd.DataFrame, keep: pd.Series, index: pd.DatetimeIndex, n_strats: int) -> pd.Series:
    """Equal-weight portfolio: each strategy's kept trades held t .. obs-1 (decision bars)."""
    pos = np.zeros(len(index))
    for t, obs, k in zip(ev["t"], ev["obs"], keep, strict=True):
        if k:
            pos[t:obs] += 1.0 / n_strats
    return pd.Series(pos, index=index)


def run_meta(
    df: pd.DataFrame, feats: pd.DataFrame, positions: pd.DataFrame, oos: pd.Series, cost: float
) -> tuple[list[dict], dict]:
    close = df["close"]
    fam = "7 meta-labelling"
    pos = positions.reindex(close.index)
    ev = triple_barrier_events(close, pos)
    x = feats.iloc[ev["t"].to_numpy()].reset_index(drop=True)
    x = pd.concat([x, pd.get_dummies(ev["strategy"]).astype(float)], axis=1)
    ok = x.notna().all(axis=1)
    ev, x = ev[ok].reset_index(drop=True), x[ok].reset_index(drop=True)
    oos_start = oos.idxmax()
    in_oos = ev["date"] >= oos_start
    info = {
        "events_total": len(ev),
        "events_oos": int(in_oos.sum()),
        "win_rate_train": round(float(ev.loc[~in_oos, "label"].mean()), 4),
        "win_rate_oos": round(float(ev.loc[in_oos, "label"].mean()), 4),
        "per_strategy_oos": ev[in_oos].groupby("strategy")["label"].agg(["count", "mean"]).round(3).to_dict("index"),
    }
    out: list[dict] = []
    n_strats = positions.shape[1]
    primary = events_to_position(ev, pd.Series(True, index=ev.index), close.index, n_strats)
    bh = close.pct_change().fillna(0.0)
    prim_ret = base.strategy_returns(primary, close, cost)
    for mname, mk in (("logit", base.logit_clf), ("gbm", base.gbm_clf)):
        p, thr = event_walk_forward(x, ev, oos_start, mk)
        po = p[in_oos]
        yo = ev.loc[in_oos, "label"].astype(float)
        r = base.eval_binary(f"meta-label P(win) pooled {mname}", fam, yo, po, base.MIN_BLOCK)
        r["note"] = "rows are the primary strategies' OOS long entries, in time order"
        out.append(r)
        # Filter: take a trade when P(win) exceeds that fold's training win rate.
        keep = (p > thr) | ~in_oos
        filt = events_to_position(ev, keep, close.index, n_strats)
        filt_ret = base.strategy_returns(filt, close, cost)
        r = base.eval_strategy(
            f"meta-filtered ({mname}) vs primary",
            fam + " (strategy)",
            filt_ret[oos],
            prim_ret[oos],
            filt,
            {"kept_share_oos": round(float(keep[in_oos].mean()), 4)},
        )
        r["baseline"] = f"primary (all entries, same exits) Sharpe {r['sharpe_bh']:.3f}"
        out.append(r)
        out.append(
            base.eval_strategy(
                f"meta-filtered ({mname}) vs buy-and-hold", fam + " (strategy)", filt_ret[oos], bh[oos], filt, {}
            )
        )
    out.append(
        base.eval_strategy(
            "primary 8-strategy triple-barrier portfolio vs buy-and-hold",
            fam + " (strategy)",
            prim_ret[oos],
            bh[oos],
            primary,
            {},
        )
    )
    return out, info


# ── family 8: calendar ────────────────────────────────────────────────────────


def run_calendar(df: pd.DataFrame, oos: pd.Series, cost: float) -> list[dict]:
    close = df["close"]
    r = np.log(close).diff()
    oos_start = oos.idxmax()
    out: list[dict] = []
    for cname, cat in calendar_categories(close.index).items():
        pred = pd.Series(np.nan, index=close.index)
        mean_fc = pd.Series(np.nan, index=close.index)
        for fs in base.fold_starts(oos_start, close.index[-1]):
            fe = fs + pd.DateOffset(years=1)
            test = (close.index >= fs) & (close.index < fe)
            # decisions for day d are taken at close d-2: drop the last 2 rows
            train = r[close.index < fs].iloc[:-2]
            ctr = cat.loc[train.index]
            means = train.groupby(ctr).mean()
            pred[test] = cat[test].map(means).fillna(train.mean()).to_numpy()
            mean_fc[test] = train.mean()
        rows = oos & r.notna()
        out.append(
            r2_vs(
                f"calendar {cname}: mean forecast vs train mean",
                "8 calendar",
                r[rows],
                pred[rows],
                mean_fc[rows],
                base.MIN_BLOCK,
                "training-mean daily return",
            )
        )
        # Long on bar d when its forecast >= the training mean, flat otherwise.
        # The flag for bar d is known at close d-2 (the calendar is), so the
        # decision series is the flag shifted back two bars.
        flag = (pred >= mean_fc).astype(float).where(pred.notna())
        pos = flag.shift(-2)
        out.append(strat_vs_bh(f"calendar {cname}: long/flat", "8 calendar (strategy)", pos, close, oos, cost))
    return out


# ── family 9: cross-asset lead-lag ────────────────────────────────────────────

MACRO_PRIOR_SIGN = {  # a-priori direction of the gold response to a rise
    "dxy_daily": -1.0,  # dollar up -> gold down
    "us10y_daily": -1.0,  # yields up -> gold down (opportunity cost)
    "us2y_daily": -1.0,
    "vix_daily": +1.0,  # risk-off -> haven bid
    "gold_etf_flow": +1.0,  # GLD price: later close than the gold bar
}


def macro_frame(index: pd.DatetimeIndex, extra_lag: int) -> pd.DataFrame:
    """Macro changes aligned to gold bars. ``extra_lag=1``: bar t sees values dated <= t-1."""
    f = pd.DataFrame(index=index)
    for s in MACRO_PRIOR_SIGN:
        m = base.load_macro(s)
        x = np.log(m) if s in ("dxy_daily", "vix_daily", "gold_etf_flow") else m
        x = x.reindex(index, method="ffill").where(index >= MACRO_START)
        for n in (1, 5):
            f[f"{s}_chg{n}"] = (x - x.shift(n)).shift(extra_lag)
    f["slope_chg5"] = f["us10y_daily_chg5"] - f["us2y_daily_chg5"]
    return f


def run_cross_asset(df: pd.DataFrame, cost: float) -> list[dict]:
    close = df["close"]
    fam = "9 cross-asset"
    out: list[dict | None] = []
    y1 = direction_label(close, 1)
    mf = macro_frame(close.index, extra_lag=1)
    rows = close.index >= MACRO_START + pd.Timedelta(days=10)
    rows = pd.Series(rows, index=close.index)
    for s, sign in MACRO_PRIOR_SIGN.items():
        out.append(
            rule_test(
                f"{s} 1d change (lagged 1 extra bar), prior sign {sign:+.0f}, h=1",
                fam,
                sign * mf[f"{s}_chg1"],
                y1,
                rows,
                1,
                note="2021-04..2026-03, no fitting",
            )
        )
    mf0 = macro_frame(close.index, extra_lag=0)
    out.append(
        rule_test(
            "DIAGNOSTIC gold_etf_flow (GLD) 1d change dated t, h=1",
            fam,
            mf0["gold_etf_flow_chg1"],
            y1,
            rows,
            1,
            note="no extra lag: measures close-time mismatch, not tradable",
        )
    )
    oos_start = close.index[-1] - pd.DateOffset(years=MACRO_OOS_YEARS) + pd.Timedelta(days=1)
    for h in (1, 5):
        p, yy = base.walk_forward(mf, direction_label(close, h), h, oos_start, base.logit_clf, "proba")
        out.append(base.eval_binary(f"macro logit (11 features), h={h}", fam, yy, p, max(h, base.MIN_BLOCK)))
        if h == 1:
            thr = float(direction_label(close, 1)[(close.index < oos_start) & rows].mean())
            pos = (p > thr).astype(float).reindex(close.index)
            win = pd.Series(close.index >= oos_start, index=close.index)
            out.append(strat_vs_bh("macro logit h=1 long/flat", fam + " (strategy)", pos, close, win, cost))
    return [r for r in out if r is not None]


# ── family 10: asymmetric / tail ──────────────────────────────────────────────

ASYM_COLS = ["skew_60", "skew_250", "semivar_ratio_60", "last_large_sign_20", "z1"]
BASE_ASYM_COLS = ["dist_hi250", "dist_lo250", "ret_20", "logvol_20", "logvol_ewma", "vol_ratio_20_60"]


def run_tails(df: pd.DataFrame, feats: pd.DataFrame, rf: pd.DataFrame, oos: pd.Series, cost: float) -> list[dict]:
    close = df["close"]
    fam = "10 tails"
    x = pd.concat([rf[ASYM_COLS], feats[BASE_ASYM_COLS]], axis=1)
    sig = np.log(close).diff().rolling(20).std()
    oos_start = oos.idxmax()
    out: list[dict | None] = []
    diag = "rows selected on the realised future move: not tradable"
    for h, k in ((1, 2.0), (5, 1.5)):
        fr = base.fwd_log_return(close, h)
        ev = fr.abs() > k * sig * math.sqrt(h)
        y = (fr > 0).astype(float).where(fr.notna() & ev & sig.notna())
        p, yy = base.walk_forward(x, y, h, oos_start, base.logit_clf, "proba")
        r = base.eval_binary(
            f"sign | large move (|r|>{k} sigma), h={h}, asym logit (DIAGNOSTIC)", fam, yy, p, base.MIN_BLOCK
        )
        r["note"] = diag
        out.append(r)
    fr5 = base.fwd_log_return(close, 5)
    ev5 = fr5.abs() > 1.5 * sig * math.sqrt(5)
    out.append(
        rule_test(
            "skew_60 sign -> sign | large move, h=5 (DIAGNOSTIC)",
            fam,
            rf["skew_60"],
            direction_label(close, 5),
            oos & ev5,
            5,
            note=diag,
        )
    )
    # Tradable: P(up tail tomorrow) - P(down tail tomorrow), two walk-forward logits.
    fr1 = base.fwd_log_return(close, 1)
    thr = 2.0 * sig
    ok = fr1.notna() & thr.notna()
    p_up, _ = base.walk_forward(x, (fr1 > thr).astype(float).where(ok), 1, oos_start, base.logit_clf, "proba")
    p_dn, _ = base.walk_forward(x, (fr1 < -thr).astype(float).where(ok), 1, oos_start, base.logit_clf, "proba")
    score = (p_up - p_dn).reindex(close.index)
    # Logit of a centred difference keeps AUC; accuracy uses score > 0 as "up".
    y1 = direction_label(close, 1)
    out.append(rule_test("tail score P(up-tail)-P(down-tail), all days, h=1", fam, score * 50, y1, oos, 1))
    out.append(
        rule_test(
            "tail score, realised large-move days only, h=1 (DIAGNOSTIC)",
            fam,
            score * 50,
            y1,
            oos & (fr1.abs() > thr),
            1,
            note=diag,
        )
    )
    pos = (score > 0).astype(float).where(score.notna())
    out.append(strat_vs_bh("tail score long/flat", fam + " (strategy)", pos, close, oos, cost))
    return [r for r in out if r is not None]


# ── family 11: ensemble ───────────────────────────────────────────────────────


def ensemble_features(close: pd.Series, feats: pd.DataFrame, rf: pd.DataFrame) -> pd.DataFrame:
    r = np.log(close).diff()
    x = pd.concat([feats, rf], axis=1)
    x["mom20_x_lowvol"] = feats["ret_20"] * (1 - rf["high_vol"])
    x["mom20_x_trend"] = feats["ret_20"] * (rf["vr5"] > 1)
    x["rev5_x_range"] = -feats["ret_5"] * (rf["vr5"] < 1)
    x["z1_x_large"] = -rf["z1"] * (rf["z1"].abs() > 2)
    for cname, cat in calendar_categories(close.index).items():
        x[f"cal_{cname}"] = calendar_expanding_feature(r, cat)
    return x


def l1_logit() -> Any:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), LogisticRegression(C=0.05, l1_ratio=1.0, solver="saga", max_iter=5000))


def l2_logit() -> Any:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=2000))


def run_ensemble(
    df: pd.DataFrame, feats: pd.DataFrame, rf: pd.DataFrame, oos: pd.Series, cost: float, with_macro: bool
) -> list[dict]:
    close = df["close"]
    fam = "11 ensemble"
    x = ensemble_features(close, feats, rf)
    oos_start = oos.idxmax()
    out: list[dict] = []
    for h, mname, mk in ((1, "L2", l2_logit), (5, "L2", l2_logit), (5, "L1", l1_logit)):
        y = direction_label(close, h)
        p, yy = base.walk_forward(x, y, h, oos_start, mk, "proba")
        out.append(
            base.eval_binary(
                f"ensemble {mname} logit ({x.shape[1]} signals), h={h}", fam, yy, p, max(h, base.MIN_BLOCK)
            )
        )
        if h == 1:
            # The protocol trades r(t+2): does the h=1 score still rank it?
            r2 = base.fwd_log_return(close, 2) - base.fwd_log_return(close, 1)
            y2 = (r2 > 0).astype(float).where(r2.notna())
            ok = y2.loc[p.index].notna()
            out.append(
                base.eval_binary(
                    "ensemble L2 h=1 score vs sign r(t+2) (tradable)", fam, y2.loc[p.index][ok], p[ok], base.MIN_BLOCK
                )
            )
        if mname == "L2":
            thr = float(y[(close.index < oos_start)].mean())
            pos = (p > thr).astype(float).reindex(close.index)
            out.append(strat_vs_bh(f"ensemble L2 h={h} long/flat", fam + " (strategy)", pos, close, oos, cost))
    if with_macro:
        xm = pd.concat([x, macro_frame(close.index, extra_lag=1)], axis=1)
        mo = close.index[-1] - pd.DateOffset(years=MACRO_OOS_YEARS) + pd.Timedelta(days=1)
        p, yy = base.walk_forward(xm, direction_label(close, 1), 1, mo, l2_logit, "proba")
        out.append(
            base.eval_binary(f"ensemble + macro L2 logit ({xm.shape[1]}), h=1, 2023-26", fam, yy, p, base.MIN_BLOCK)
        )
        # Does macro add anything? Same rows, same 2021+ training rows, macro columns removed.
        keep_rows = xm.notna().all(axis=1)
        p0, _ = base.walk_forward(x.where(keep_rows), direction_label(close, 1), 1, mo, l2_logit, "proba")
        d = base.paired_auc(
            "ensemble + macro minus ensemble-only (same rows), h=1, 2023-26", yy, p, p0.loc[yy.index], base.MIN_BLOCK
        )
        d["family"] = fam
        d["baseline"] = f"ensemble-only AUC {d['auc_baseline']:.4f}"
        out.append(d)
    return out


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--families", default="6,7,8,9,10,11")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--truncate-at", default=None, help="replication: drop bars on/after this date first")
    ap.add_argument("--prior-strategies", action="store_true", help="re-run spike-1 strategy rows for the DSR pool")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for noisy in ("ml", "strategies", "backtesting", "data_layer", "a0_target_research"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    df_full = base.load_gold()
    df = df_full[df_full.index < pd.Timestamp(args.truncate_at)] if args.truncate_at else df_full
    oos_start = df.index[-1] - pd.DateOffset(years=base.OOS_YEARS) + pd.Timedelta(days=1)
    oos = pd.Series(df.index >= oos_start, index=df.index)
    close = df["close"]
    feats = base.build_features(close)
    rf = regime_features(close)
    fam = set(args.families.split(","))
    cost = args.cost_bps
    meta: dict[str, Any] = {
        "rows": len(df),
        "first": str(df.index[0].date()),
        "last": str(df.index[-1].date()),
        "oos_start": str(oos_start.date()),
        "cost_bps": cost,
        "n_boot": base.N_BOOT,
        "seed": base.SEED,
    }
    results: list[dict] = []
    t0 = time.time()
    if "6" in fam:
        results += run_regime(df, feats, rf, oos, cost)
        logger.info("family 6 done (%.0fs)", time.time() - t0)
    if "7" in fam:
        positions = repo_positions(df_full, out_dir / "repo_positions_full.csv")
        rows, info = run_meta(df, feats, positions, oos, cost)
        results += rows
        meta["meta_labelling"] = info
        logger.info("family 7 done (%.0fs)", time.time() - t0)
    if "8" in fam:
        results += run_calendar(df, oos, cost)
        logger.info("family 8 done (%.0fs)", time.time() - t0)
    if "9" in fam and not args.truncate_at:
        results += run_cross_asset(df, cost)
        logger.info("family 9 done (%.0fs)", time.time() - t0)
    if "10" in fam:
        results += run_tails(df, feats, rf, oos, cost)
        logger.info("family 10 done (%.0fs)", time.time() - t0)
    if "11" in fam:
        results += run_ensemble(df, feats, rf, oos, cost, with_macro=not args.truncate_at)
        logger.info("family 11 done (%.0fs)", time.time() - t0)

    m_new = sum(1 for r in results if r.get("counted"))
    m = PRIOR_TESTS + m_new
    strat = [r for r in results if "daily_sr" in r]
    prior_strat: list[dict] = []
    if args.prior_strategies and strat:
        prior_strat = base.run_rules(df, oos_start, cost) + base.run_repo_strategies(df, oos_start, cost)
    if strat:
        pool = strat + prior_strat
        base.deflated_sharpe(pool)
    for r in results:
        r["p_bonferroni"] = min(1.0, r["p_one_sided"] * m)
        r["pass_uncorrected"] = bool(r["ci_low"] is not None and r["ci_low"] > r["null"])
        rule_ok = r["repo_rule_pass"] is not False
        r["pass_corrected"] = bool(r["p_bonferroni"] < args.alpha and r["pass_uncorrected"] and rule_ok)
    meta.update(
        {"tests_new": m_new, "tests_prior": PRIOR_TESTS, "tests_total": m, "dsr_trials": len(strat) + len(prior_strat)}
    )
    suffix = f"_until_{args.truncate_at}" if args.truncate_at else ""
    path = out_dir / f"results_{'_'.join(sorted(fam, key=int))}{suffix}.json"
    path.write_text(json.dumps({"meta": meta, "results": results}, indent=2, default=str))
    print(f"\n{m_new} new tests + {PRIOR_TESTS} prior = {m}; Bonferroni alpha = {args.alpha / m:.6f}\n")
    for r in sorted(results, key=lambda r: r["p_one_sided"]):
        print(
            f"{r['name'][:62]:62s} {r['stat']:+.4f} [{r['ci_low']:+.4f},{r['ci_high']:+.4f}] n={r['n']:5d} "
            f"p={r['p_one_sided']:.2e} pB={r['p_bonferroni']:.3f} pass={r['pass_corrected']} "
            f"rule={r['repo_rule_pass']} dsr={r.get('dsr', '')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
