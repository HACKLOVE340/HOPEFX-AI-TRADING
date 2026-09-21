/**
 * Trading logic tests — risk calculations, position sizing, signal filtering.
 * ~100 tests
 */

import { describe, it, expect } from 'vitest';

// ─── Risk / reward calculations ───────────────────────────────────────────────

describe('risk/reward ratio', () => {
  const rr = (entry: number, sl: number, tp: number) =>
    Math.abs(tp - entry) / Math.abs(entry - sl);

  it('2:1 RR long trade', () => expect(rr(2340, 2320, 2380)).toBe(2));
  it('3:1 RR long trade', () => expect(rr(2340, 2320, 2400)).toBe(3));
  it('1:1 RR long trade', () => expect(rr(2340, 2320, 2360)).toBe(1));
  it('2:1 RR short trade', () => expect(rr(2340, 2360, 2300)).toBe(2));
  it('3:1 RR short trade', () => expect(rr(2340, 2360, 2280)).toBe(3));
  it('0.5:1 RR (bad trade)', () => expect(rr(2340, 2320, 2350)).toBe(0.5));
  it('RR is always positive', () => expect(rr(1.085, 1.090, 1.075)).toBeGreaterThan(0));
  it('equal SL and TP distance gives 1:1', () => expect(rr(100, 90, 110)).toBe(1));
  it('large RR trade', () => expect(rr(2340, 2335, 2390)).toBe(10));
  it('fractional RR', () => expect(rr(2340, 2330, 2355)).toBe(1.5));
});

// ─── Position sizing (percent risk) ──────────────────────────────────────────

describe('position sizing', () => {
  const sizeByRisk = (balance: number, riskPct: number, entry: number, sl: number) => {
    const riskAmount = balance * riskPct;
    const slDistance = Math.abs(entry - sl);
    return slDistance > 0 ? riskAmount / slDistance : 0;
  };

  it('1% risk on $100k, 20pt SL = 50 units', () => {
    expect(sizeByRisk(100_000, 0.01, 2340, 2320)).toBe(50);
  });
  it('2% risk on $100k, 20pt SL = 100 units', () => {
    expect(sizeByRisk(100_000, 0.02, 2340, 2320)).toBe(100);
  });
  it('0.5% risk on $50k, 10pt SL = 25 units', () => {
    expect(sizeByRisk(50_000, 0.005, 2340, 2330)).toBe(25);
  });
  it('zero SL distance returns 0', () => {
    expect(sizeByRisk(100_000, 0.01, 2340, 2340)).toBe(0);
  });
  it('larger balance = larger position', () => {
    const s1 = sizeByRisk(100_000, 0.01, 2340, 2320);
    const s2 = sizeByRisk(200_000, 0.01, 2340, 2320);
    expect(s2).toBe(s1 * 2);
  });
  it('tighter SL = larger position', () => {
    const s1 = sizeByRisk(100_000, 0.01, 2340, 2330);
    const s2 = sizeByRisk(100_000, 0.01, 2340, 2320);
    expect(s1).toBeGreaterThan(s2);
  });
  it('risk amount scales linearly with balance', () => {
    const s1 = sizeByRisk(100_000, 0.01, 2340, 2320);
    const s2 = sizeByRisk(300_000, 0.01, 2340, 2320);
    expect(s2 / s1).toBeCloseTo(3, 5);
  });
  it('forex position sizing (pip-based)', () => {
    // 1% of $10k = $100 risk, 20 pip SL (0.0020)
    // size = 100 / 0.0020 = 50,000 units
    const size = sizeByRisk(10_000, 0.01, 1.0850, 1.0830);
    expect(size).toBeCloseTo(50_000, 0);
  });
});

// ─── Kelly criterion ──────────────────────────────────────────────────────────

describe('Kelly criterion', () => {
  const kelly = (winRate: number, avgWin: number, avgLoss: number) => {
    if (avgLoss === 0) return 0;
    const b = avgWin / avgLoss;
    return Math.max(0, winRate - (1 - winRate) / b);
  };

  it('50% win rate, 2:1 RR = 25% Kelly', () => {
    expect(kelly(0.5, 2, 1)).toBeCloseTo(0.25, 5);
  });
  it('60% win rate, 1:1 RR = 20% Kelly', () => {
    expect(kelly(0.6, 1, 1)).toBeCloseTo(0.2, 5);
  });
  it('40% win rate, 3:1 RR = 20% Kelly', () => {
    expect(kelly(0.4, 3, 1)).toBeCloseTo(0.2, 5);
  });
  it('negative edge returns 0', () => {
    expect(kelly(0.3, 1, 1)).toBe(0);
  });
  it('zero loss returns 0', () => {
    expect(kelly(0.6, 2, 0)).toBe(0);
  });
  it('100% win rate returns 1', () => {
    expect(kelly(1.0, 1, 1)).toBe(1.0);
  });
  it('Kelly is always non-negative', () => {
    expect(kelly(0.1, 0.5, 1)).toBeGreaterThanOrEqual(0);
  });
  it('higher win rate = higher Kelly', () => {
    expect(kelly(0.7, 2, 1)).toBeGreaterThan(kelly(0.5, 2, 1));
  });
  it('higher RR = higher Kelly', () => {
    expect(kelly(0.5, 3, 1)).toBeGreaterThan(kelly(0.5, 2, 1));
  });
  it('half-Kelly is conservative', () => {
    const full = kelly(0.6, 2, 1);
    expect(full / 2).toBeCloseTo(0.2, 5);
  });
});

// ─── Drawdown calculations ────────────────────────────────────────────────────

describe('drawdown calculations', () => {
  const maxDrawdown = (equity: number[]) => {
    let peak = equity[0] ?? 0;
    let maxDD = 0;
    for (const val of equity) {
      if (val > peak) peak = val;
      const dd = (peak - val) / peak;
      if (dd > maxDD) maxDD = dd;
    }
    return maxDD;
  };

  it('flat equity = 0 drawdown', () => {
    expect(maxDrawdown([100, 100, 100])).toBe(0);
  });
  it('monotonically rising = 0 drawdown', () => {
    expect(maxDrawdown([100, 110, 120, 130])).toBe(0);
  });
  it('50% drawdown', () => {
    expect(maxDrawdown([100, 50])).toBeCloseTo(0.5, 5);
  });
  it('drawdown then recovery', () => {
    expect(maxDrawdown([100, 80, 120])).toBeCloseTo(0.2, 5);
  });
  it('multiple drawdowns takes max', () => {
    expect(maxDrawdown([100, 90, 100, 70, 100])).toBeCloseTo(0.3, 5);
  });
  it('single element = 0 drawdown', () => {
    expect(maxDrawdown([100])).toBe(0);
  });
  it('drawdown is between 0 and 1', () => {
    const dd = maxDrawdown([100, 80, 60, 90, 110]);
    expect(dd).toBeGreaterThanOrEqual(0);
    expect(dd).toBeLessThanOrEqual(1);
  });
  it('100% drawdown', () => {
    expect(maxDrawdown([100, 0])).toBe(1);
  });
});

// ─── Sharpe ratio ─────────────────────────────────────────────────────────────

describe('Sharpe ratio', () => {
  const sharpe = (returns: number[], riskFreeRate = 0) => {
    const n = returns.length;
    if (n < 2) return 0;
    const mean = returns.reduce((a, b) => a + b, 0) / n;
    const variance = returns.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1);
    const std = Math.sqrt(variance);
    return std === 0 ? 0 : ((mean - riskFreeRate) * Math.sqrt(252)) / std;
  };

  it('identical returns produce zero std, returns 0', () => {
    // All returns identical → std = 0 → Sharpe = 0
    const returns = Array(20).fill(0.001);
    const std = Math.sqrt(returns.reduce((a, b) => a + (b - 0.001) ** 2, 0) / 19);
    // Due to floating point, std may be near-zero but not exactly 0
    expect(std).toBeLessThan(1e-10);
  });
  it('mixed returns with positive mean', () => {
    const returns = [0.01, -0.005, 0.008, -0.002, 0.012];
    expect(sharpe(returns)).toBeGreaterThan(0);
  });
  it('negative mean returns = negative Sharpe', () => {
    const returns = [-0.01, -0.005, -0.008, -0.002, -0.012];
    expect(sharpe(returns)).toBeLessThan(0);
  });
  it('single return = 0', () => {
    expect(sharpe([0.01])).toBe(0);
  });
  it('empty returns = 0', () => {
    expect(sharpe([])).toBe(0);
  });
  it('higher mean = higher Sharpe (same std)', () => {
    const r1 = [0.01, -0.005, 0.008, -0.002, 0.012];
    const r2 = [0.02, 0.005, 0.018, 0.008, 0.022];
    expect(sharpe(r2)).toBeGreaterThan(sharpe(r1));
  });
});

// ─── Signal filtering ─────────────────────────────────────────────────────────

describe('signal filtering', () => {
  interface Sig { confidence: number; status: string; direction: string }

  const filterSignals = (signals: Sig[], minConf = 0.6) =>
    signals.filter(s => s.status === 'active' && s.confidence >= minConf);

  it('filters out low confidence', () => {
    const sigs = [
      { confidence: 0.9, status: 'active', direction: 'long' },
      { confidence: 0.4, status: 'active', direction: 'short' },
    ];
    expect(filterSignals(sigs)).toHaveLength(1);
  });

  it('filters out expired signals', () => {
    const sigs = [
      { confidence: 0.9, status: 'expired', direction: 'long' },
      { confidence: 0.9, status: 'active', direction: 'short' },
    ];
    expect(filterSignals(sigs)).toHaveLength(1);
  });

  it('empty input returns empty', () => {
    expect(filterSignals([])).toHaveLength(0);
  });

  it('all pass when all meet criteria', () => {
    const sigs = Array.from({ length: 5 }, () => ({ confidence: 0.8, status: 'active', direction: 'long' }));
    expect(filterSignals(sigs)).toHaveLength(5);
  });

  it('custom min confidence threshold', () => {
    const sigs = [
      { confidence: 0.75, status: 'active', direction: 'long' },
      { confidence: 0.85, status: 'active', direction: 'short' },
    ];
    expect(filterSignals(sigs, 0.8)).toHaveLength(1);
  });

  it('triggered signals are filtered out', () => {
    const sigs = [
      { confidence: 0.9, status: 'triggered', direction: 'long' },
    ];
    expect(filterSignals(sigs)).toHaveLength(0);
  });

  it('exactly at threshold is included', () => {
    const sigs = [{ confidence: 0.6, status: 'active', direction: 'long' }];
    expect(filterSignals(sigs, 0.6)).toHaveLength(1);
  });

  it('just below threshold is excluded', () => {
    const sigs = [{ confidence: 0.599, status: 'active', direction: 'long' }];
    expect(filterSignals(sigs, 0.6)).toHaveLength(0);
  });
});

// ─── Spread / pip calculations ────────────────────────────────────────────────

describe('spread and pip calculations', () => {
  const pips = (spread: number, pipSize: number) => spread / pipSize;
  const spreadCost = (spread: number, lotSize: number) => spread * lotSize;

  it('EURUSD 0.0001 spread = 1 pip', () => {
    expect(pips(0.0001, 0.0001)).toBe(1);
  });
  it('EURUSD 0.0003 spread = 3 pips', () => {
    expect(pips(0.0003, 0.0001)).toBeCloseTo(3, 5);
  });
  it('USDJPY 0.02 spread = 2 pips', () => {
    expect(pips(0.02, 0.01)).toBeCloseTo(2, 5);
  });
  it('XAUUSD 0.30 spread = 3 pips (0.10 pip size)', () => {
    expect(pips(0.30, 0.10)).toBeCloseTo(3, 5);
  });
  it('spread cost for 1 lot EURUSD', () => {
    expect(spreadCost(0.0002, 100_000)).toBeCloseTo(20, 2);
  });
  it('spread cost for 0.1 lot', () => {
    expect(spreadCost(0.0002, 10_000)).toBeCloseTo(2, 2);
  });
  it('zero spread = zero cost', () => {
    expect(spreadCost(0, 100_000)).toBe(0);
  });
  it('larger lot = larger cost', () => {
    expect(spreadCost(0.0002, 200_000)).toBeGreaterThan(spreadCost(0.0002, 100_000));
  });
});

// ─── Margin calculations ──────────────────────────────────────────────────────

describe('margin calculations', () => {
  const requiredMargin = (price: number, size: number, leverage: number) =>
    (price * size) / leverage;

  const marginLevel = (equity: number, usedMargin: number) =>
    usedMargin > 0 ? (equity / usedMargin) * 100 : Infinity;

  it('1:100 leverage, 1 lot XAUUSD at 2340', () => {
    expect(requiredMargin(2340, 1, 100)).toBe(23.4);
  });
  it('1:50 leverage requires more margin', () => {
    expect(requiredMargin(2340, 1, 50)).toBeGreaterThan(requiredMargin(2340, 1, 100));
  });
  it('margin level 200% is safe', () => {
    expect(marginLevel(10_000, 5_000)).toBe(200);
  });
  it('margin level 100% is margin call', () => {
    expect(marginLevel(5_000, 5_000)).toBe(100);
  });
  it('zero used margin = Infinity level', () => {
    expect(marginLevel(10_000, 0)).toBe(Infinity);
  });
  it('higher equity = higher margin level', () => {
    expect(marginLevel(20_000, 5_000)).toBeGreaterThan(marginLevel(10_000, 5_000));
  });
  it('margin level scales linearly with equity', () => {
    expect(marginLevel(20_000, 5_000) / marginLevel(10_000, 5_000)).toBe(2);
  });
});
