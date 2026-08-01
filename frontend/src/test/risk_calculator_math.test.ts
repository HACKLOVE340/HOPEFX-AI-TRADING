/**
 * Position-sizing math.
 *
 * A pip is worth `pipSize * contractSize` in the QUOTE currency. Every pair in
 * the calculator quotes USD except USD/JPY, which quotes yen — so treating that
 * figure as dollars overstated USD/JPY pip value by roughly the USD/JPY rate,
 * about 150×. Lot size is derived by dividing risk by pip value, so the
 * suggested position came out ~150× too small.
 *
 * These assert the invariant rather than fixed numbers: whatever the lot size,
 * being stopped out must lose the amount the trader chose to risk.
 */
import { describe, it, expect } from 'vitest';
import { calculate, type CalcState } from '../pages/RiskCalculator';

const base: CalcState = {
  symbol: 'XAU/USD',
  accountBalance: '10000',
  riskPercent: '1',
  entryPrice: '2000',
  stopLoss: '1990',
  takeProfit: '2020',
  leverage: '100',
};

describe('risk calculator', () => {
  it('sizes gold so a stop-out loses exactly the risk budget', () => {
    const r = calculate(base)!;
    expect(r.riskAmount).toBe(100);        // 1% of 10,000
    expect(r.maxLoss).toBeCloseTo(100, 6);
  });

  it('sizes USD/JPY so a stop-out loses exactly the risk budget', () => {
    // 150.00 → 149.00 is 100 pips at a pipSize of 0.01.
    const r = calculate({
      ...base,
      symbol: 'USD/JPY',
      entryPrice: '150.00',
      stopLoss: '149.00',
      takeProfit: '152.00',
    })!;

    expect(r.stopPips).toBeCloseTo(100, 6);
    expect(r.maxLoss).toBeCloseTo(100, 6);
  });

  it('prices a USD/JPY pip in dollars, not yen', () => {
    const r = calculate({
      ...base,
      symbol: 'USD/JPY',
      entryPrice: '150.00',
      stopLoss: '149.00',
      takeProfit: '152.00',
    })!;

    // One standard lot is ¥1,000/pip → 1000 / 150 ≈ $6.67.
    const perLot = r.pipValue / r.lotSize;
    expect(perLot).toBeCloseTo(1000 / 150, 6);
    // The bug produced $1,000/pip — a 150× overstatement.
    expect(perLot).toBeLessThan(10);
  });

  it('sizes a USD/JPY position larger than the buggy version did', () => {
    const jpy = {
      ...base,
      symbol: 'USD/JPY',
      entryPrice: '150.00',
      stopLoss: '149.00',
      takeProfit: '152.00',
    };
    const r = calculate(jpy)!;
    // Buggy lot size was riskAmount / (stopPips * 1000) = 100 / 100000 = 0.001.
    expect(r.lotSize).toBeCloseTo(0.15, 6);
    expect(r.lotSize / 0.001).toBeCloseTo(150, 0);
  });

  it('leaves USD-quoted pairs unchanged', () => {
    const r = calculate({
      ...base,
      symbol: 'EUR/USD',
      entryPrice: '1.1000',
      stopLoss: '1.0950',
      takeProfit: '1.1100',
    })!;
    // 0.0001 * 100,000 = $10/pip on a standard lot, regardless of price.
    expect(r.pipValue / r.lotSize).toBeCloseTo(10, 6);
    expect(r.maxLoss).toBeCloseTo(100, 6);
  });

  it('rejects inputs that would divide by zero', () => {
    expect(calculate({ ...base, stopLoss: base.entryPrice })).toBeNull();
    expect(calculate({ ...base, entryPrice: '0' })).toBeNull();
    expect(calculate({ ...base, symbol: 'NOT/APAIR' })).toBeNull();
  });
});
