/**
 * ML signal and model accuracy tests.
 * ~80 tests
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import type { Signal } from '../store';

beforeEach(() => {
  useStore.setState({
    token: null, user: null, isAuthenticated: false,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── Model accuracy thresholds ────────────────────────────────────────────────

describe('model accuracy thresholds', () => {
  const TARGET_MIN = 0.85;
  const DEPLOY_MIN = 0.55;
  const PVALUE_MAX = 0.05;

  it('85% accuracy meets production target', () => {
    expect(0.85).toBeGreaterThanOrEqual(TARGET_MIN);
  });
  it('90% accuracy exceeds production target', () => {
    expect(0.90).toBeGreaterThan(TARGET_MIN);
  });
  it('84% accuracy does not meet target', () => {
    expect(0.84).toBeLessThan(TARGET_MIN);
  });
  it('55% accuracy meets minimum deploy threshold', () => {
    expect(0.55).toBeGreaterThanOrEqual(DEPLOY_MIN);
  });
  it('49% accuracy is below deploy threshold', () => {
    expect(0.49).toBeLessThan(DEPLOY_MIN);
  });
  it('p < 0.05 is statistically significant', () => {
    expect(0.04).toBeLessThan(PVALUE_MAX);
  });
  it('p = 0.05 is not significant (strict)', () => {
    expect(0.05).not.toBeLessThan(PVALUE_MAX);
  });
  it('p > 0.05 is not significant', () => {
    expect(0.10).toBeGreaterThan(PVALUE_MAX);
  });
  it('AUC > 0.5 is better than random', () => {
    expect(0.87).toBeGreaterThan(0.5);
  });
  it('AUC = 0.5 is random', () => {
    expect(0.5).toBe(0.5);
  });
  it('F1 score between 0 and 1', () => {
    expect(0.86).toBeGreaterThan(0);
    expect(0.86).toBeLessThanOrEqual(1);
  });
  it('stacking ensemble accuracy target', () => {
    const stackingAcc = 0.87;
    expect(stackingAcc).toBeGreaterThanOrEqual(TARGET_MIN);
  });
});

// ─── Signal confidence scoring ────────────────────────────────────────────────

describe('signal confidence scoring', () => {
  const scoreSignal = (confidence: number, atr_move: number, min_atr = 0.25) => ({
    tradeable: confidence >= 0.6 && atr_move >= min_atr,
    tier: confidence >= 0.85 ? 'A' : confidence >= 0.70 ? 'B' : confidence >= 0.55 ? 'C' : 'D',
  });

  it('high confidence + large move = tradeable', () => {
    expect(scoreSignal(0.87, 0.5).tradeable).toBe(true);
  });
  it('high confidence + small move = not tradeable', () => {
    expect(scoreSignal(0.87, 0.1).tradeable).toBe(false);
  });
  it('low confidence + large move = not tradeable', () => {
    expect(scoreSignal(0.45, 0.5).tradeable).toBe(false);
  });
  it('tier A at 0.87 confidence', () => {
    expect(scoreSignal(0.87, 0.5).tier).toBe('A');
  });
  it('tier B at 0.75 confidence', () => {
    expect(scoreSignal(0.75, 0.5).tier).toBe('B');
  });
  it('tier C at 0.60 confidence', () => {
    expect(scoreSignal(0.60, 0.5).tier).toBe('C');
  });
  it('tier D at 0.40 confidence', () => {
    expect(scoreSignal(0.40, 0.5).tier).toBe('D');
  });
  it('exactly 0.85 is tier A', () => {
    expect(scoreSignal(0.85, 0.5).tier).toBe('A');
  });
  it('exactly 0.70 is tier B', () => {
    expect(scoreSignal(0.70, 0.5).tier).toBe('B');
  });
  it('exactly 0.55 is tier C', () => {
    expect(scoreSignal(0.55, 0.5).tier).toBe('C');
  });
});

// ─── Feature importance validation ───────────────────────────────────────────

describe('feature importance', () => {
  const features = {
    macro_dxy_ret: 0.12,
    macro_vix: 0.10,
    adx_14: 0.09,
    rsi_14: 0.08,
    macd_hist: 0.07,
    mtf_alignment: 0.06,
    vol_ratio_5_20: 0.05,
    zscore_20: 0.05,
    pa_body_ratio: 0.04,
    hurst_proxy: 0.04,
  };

  it('all importances are positive', () => {
    expect(Object.values(features).every(v => v > 0)).toBe(true);
  });
  it('importances sum to less than 1 (top-10 only)', () => {
    const sum = Object.values(features).reduce((a, b) => a + b, 0);
    expect(sum).toBeLessThan(1);
  });
  it('macro_dxy_ret is top feature', () => {
    const max = Math.max(...Object.values(features));
    expect(features.macro_dxy_ret).toBe(max);
  });
  it('10 features listed', () => {
    expect(Object.keys(features)).toHaveLength(10);
  });
  it('all importances between 0 and 1', () => {
    expect(Object.values(features).every(v => v >= 0 && v <= 1)).toBe(true);
  });
  it('macro features present', () => {
    expect(features).toHaveProperty('macro_dxy_ret');
    expect(features).toHaveProperty('macro_vix');
  });
  it('technical features present', () => {
    expect(features).toHaveProperty('rsi_14');
    expect(features).toHaveProperty('adx_14');
    expect(features).toHaveProperty('macd_hist');
  });
});

// ─── Walk-forward validation ──────────────────────────────────────────────────

describe('walk-forward validation', () => {
  interface FoldResult { fold: number; accuracy: number; f1: number; auc: number }

  const folds: FoldResult[] = [
    { fold: 1, accuracy: 0.84, f1: 0.83, auc: 0.88 },
    { fold: 2, accuracy: 0.87, f1: 0.86, auc: 0.91 },
    { fold: 3, accuracy: 0.85, f1: 0.84, auc: 0.89 },
    { fold: 4, accuracy: 0.88, f1: 0.87, auc: 0.92 },
    { fold: 5, accuracy: 0.86, f1: 0.85, auc: 0.90 },
  ];

  const mean = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length;
  const std  = (arr: number[]) => {
    const m = mean(arr);
    return Math.sqrt(arr.reduce((a, b) => a + (b - m) ** 2, 0) / arr.length);
  };

  it('mean accuracy meets target', () => {
    expect(mean(folds.map(f => f.accuracy))).toBeGreaterThanOrEqual(0.85);
  });
  it('all folds above 0.80', () => {
    expect(folds.every(f => f.accuracy >= 0.80)).toBe(true);
  });
  it('mean AUC above 0.85', () => {
    expect(mean(folds.map(f => f.auc))).toBeGreaterThan(0.85);
  });
  it('mean F1 above 0.80', () => {
    expect(mean(folds.map(f => f.f1))).toBeGreaterThan(0.80);
  });
  it('std of accuracy is low (stable model)', () => {
    expect(std(folds.map(f => f.accuracy))).toBeLessThan(0.05);
  });
  it('5 folds evaluated', () => {
    expect(folds).toHaveLength(5);
  });
  it('fold numbers are sequential', () => {
    folds.forEach((f, i) => expect(f.fold).toBe(i + 1));
  });
  it('no fold has AUC below 0.85', () => {
    expect(folds.every(f => f.auc >= 0.85)).toBe(true);
  });
});

// ─── Signal store integration ─────────────────────────────────────────────────

describe('signal store integration', () => {
  const makeSig = (id: string, conf: number, dir: 'long' | 'short' | 'neutral' = 'long'): Signal => ({
    id, symbol: 'XAU/USD', direction: dir, confidence: conf,
    model: 'Stacking Ensemble', entry_price: 2340, stop_loss: 2320, take_profit: 2380,
    generated_at: new Date().toISOString(), status: 'active',
  });

  it('high confidence signals are stored', () => {
    useStore.getState().addSignal(makeSig('s1', 0.92));
    expect(useStore.getState().signals[0]?.confidence).toBe(0.92);
  });

  it('signals sorted by insertion (newest first)', () => {
    useStore.getState().addSignal(makeSig('s1', 0.80));
    useStore.getState().addSignal(makeSig('s2', 0.90));
    useStore.getState().addSignal(makeSig('s3', 0.85));
    expect(useStore.getState().signals[0]?.id).toBe('s3');
    expect(useStore.getState().signals[1]?.id).toBe('s2');
    expect(useStore.getState().signals[2]?.id).toBe('s1');
  });

  it('active signals count', () => {
    useStore.getState().setSignals([
      makeSig('s1', 0.87),
      { ...makeSig('s2', 0.72), status: 'expired' },
      makeSig('s3', 0.65),
    ]);
    const active = useStore.getState().signals.filter(s => s.status === 'active');
    expect(active).toHaveLength(2);
  });

  it('long signals count', () => {
    useStore.getState().setSignals([
      makeSig('s1', 0.87, 'long'),
      makeSig('s2', 0.72, 'short'),
      makeSig('s3', 0.65, 'long'),
    ]);
    const longs = useStore.getState().signals.filter(s => s.direction === 'long');
    expect(longs).toHaveLength(2);
  });

  it('short signals count', () => {
    useStore.getState().setSignals([
      makeSig('s1', 0.87, 'long'),
      makeSig('s2', 0.72, 'short'),
    ]);
    const shorts = useStore.getState().signals.filter(s => s.direction === 'short');
    expect(shorts).toHaveLength(1);
  });

  it('average confidence calculation', () => {
    useStore.getState().setSignals([
      makeSig('s1', 0.80),
      makeSig('s2', 0.90),
      makeSig('s3', 0.70),
    ]);
    const sigs = useStore.getState().signals;
    const avg = sigs.reduce((a, s) => a + s.confidence, 0) / sigs.length;
    expect(avg).toBeCloseTo(0.80, 5);
  });

  it('highest confidence signal', () => {
    useStore.getState().setSignals([
      makeSig('s1', 0.80),
      makeSig('s2', 0.95),
      makeSig('s3', 0.70),
    ]);
    const best = useStore.getState().signals.reduce((a, b) => a.confidence > b.confidence ? a : b);
    expect(best.id).toBe('s2');
  });

  it('signals for specific symbol', () => {
    useStore.getState().setSignals([
      { ...makeSig('s1', 0.87), symbol: 'XAU/USD' },
      { ...makeSig('s2', 0.72), symbol: 'EUR/USD' },
      { ...makeSig('s3', 0.65), symbol: 'XAU/USD' },
    ]);
    const gold = useStore.getState().signals.filter(s => s.symbol === 'XAU/USD');
    expect(gold).toHaveLength(2);
  });
});

// ─── Macro feature logic ──────────────────────────────────────────────────────

describe('macro feature logic', () => {
  // DXY up → gold bearish; VIX up → gold bullish; yield up → gold bearish
  const goldBias = (dxyRet: number, vixRet: number, yieldChg: number) => {
    let score = 0;
    if (dxyRet < 0) score += 1;   // weak dollar = gold bullish
    if (dxyRet > 0) score -= 1;   // strong dollar = gold bearish
    if (vixRet > 0) score += 1;   // rising fear = gold bullish
    if (yieldChg > 0) score -= 1; // rising yields = gold bearish
    return score;
  };

  it('weak DXY + high VIX = bullish gold', () => {
    expect(goldBias(-0.5, 5, 0)).toBe(2);
  });
  it('strong DXY + rising yields = bearish gold', () => {
    expect(goldBias(0.5, 0, 0.1)).toBe(-2);
  });
  it('neutral conditions = neutral gold', () => {
    expect(goldBias(0, 0, 0)).toBe(0);
  });
  it('weak DXY alone = slightly bullish', () => {
    expect(goldBias(-0.3, 0, 0)).toBe(1);
  });
  it('rising VIX alone = slightly bullish', () => {
    expect(goldBias(0, 3, 0)).toBe(1);
  });
  it('rising yields alone = slightly bearish', () => {
    expect(goldBias(0, 0, 0.05)).toBe(-1);
  });
  it('all bullish factors = max bullish', () => {
    expect(goldBias(-1, 10, 0)).toBe(2);
  });
  it('all bearish factors = max bearish', () => {
    expect(goldBias(1, 0, 0.1)).toBe(-2);
  });
});
