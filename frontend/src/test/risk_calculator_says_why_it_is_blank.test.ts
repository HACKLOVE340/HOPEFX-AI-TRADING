/**
 * src/test/risk_calculator_says_why_it_is_blank.test.ts
 * =====================================================
 * Reported from the deployment: the Risk Calculator "results not computing".
 *
 * `calculate()` has six independent `return null` branches and the Results panel
 * rendered one sentence for all of them — "Fill in all fields to see results."
 * For four of those branches that sentence is factually wrong, because the
 * fields are filled:
 *
 *   - the selected symbol has no contract specification
 *   - entry price is zero or negative
 *   - stop loss equals entry
 *   - take profit equals entry
 *
 * So the page told the user to do the thing they had already done, and the real
 * reason was unreachable. Same shape as the drift banner reading "Stable" with
 * no statistics behind it: absence rendered as a tidy answer.
 *
 * The invariant these tests pin is the one that can rot: `explainMissingResult`
 * must return a reason exactly when `calculate` returns null, and must return
 * `null` exactly when it does not. A message that disagrees with the panel it
 * explains is worse than no message.
 */

import { describe, it, expect } from 'vitest';
import { calculate, explainMissingResult, type CalcState } from '../pages/RiskCalculator';
import { BUILTIN_SPECS } from '../hooks/useInstrumentSpecs';

const base: CalcState = {
  symbol:         'XAU/USD',
  accountBalance: '10000',
  riskPercent:    '1',
  entryPrice:     '4390.00',
  stopLoss:       '4380.00',
  takeProfit:     '4410.00',
  leverage:       '100',
};

describe('explainMissingResult agrees with calculate', () => {
  const cases: CalcState[] = [
    base,
    { ...base, takeProfit: '' },
    { ...base, stopLoss: '' },
    { ...base, entryPrice: '' },
    { ...base, accountBalance: '' },
    { ...base, entryPrice: '0' },
    { ...base, entryPrice: '-1' },
    { ...base, stopLoss: base.entryPrice },
    { ...base, takeProfit: base.entryPrice },
    { ...base, symbol: 'DOGE/USD' },
    { ...base, accountBalance: 'abc' },
    { ...base, riskPercent: '' },
    { ...base, leverage: '' },
  ];

  it.each(cases)('reason is present iff the result is absent (%j)', (state) => {
    const result = calculate(state, BUILTIN_SPECS);
    const reason = explainMissingResult(state, BUILTIN_SPECS);
    expect(reason === null).toBe(result !== null);
  });
});

describe('the reason names the actual problem', () => {
  it('does not say "fill in all fields" when they are all filled', () => {
    // The deployed message, on a fully-populated form.
    const reason = explainMissingResult({ ...base, stopLoss: base.entryPrice }, BUILTIN_SPECS);
    expect(reason).toBeTruthy();
    expect(reason!.toLowerCase()).not.toContain('fill in all fields');
    expect(reason!.toLowerCase()).toContain('stop loss');
  });

  it('names take profit when take profit is the culprit', () => {
    const reason = explainMissingResult({ ...base, takeProfit: base.entryPrice }, BUILTIN_SPECS);
    expect(reason!.toLowerCase()).toContain('take profit');
    expect(reason!.toLowerCase()).not.toContain('stop loss');
  });

  it('names the unpriceable instrument rather than blaming the inputs', () => {
    const reason = explainMissingResult({ ...base, symbol: 'DOGE/USD' }, BUILTIN_SPECS);
    expect(reason).toContain('DOGE/USD');
    expect(reason!.toLowerCase()).toContain('specification');
  });

  it('lists exactly the empty fields, not all of them', () => {
    const reason = explainMissingResult(
      { ...base, stopLoss: '', takeProfit: '' },
      BUILTIN_SPECS,
    )!;
    expect(reason).toContain('stop loss');
    expect(reason).toContain('take profit');
    expect(reason).not.toContain('entry price');
    expect(reason).not.toContain('account balance');
  });

  it('rejects a non-numeric balance instead of sizing against NaN', () => {
    expect(calculate({ ...base, accountBalance: 'abc' }, BUILTIN_SPECS)).toBeNull();
    expect(explainMissingResult({ ...base, accountBalance: 'abc' }, BUILTIN_SPECS))
      .toContain('account balance');
  });

  it('says nothing at all when the form is valid', () => {
    expect(explainMissingResult(base, BUILTIN_SPECS)).toBeNull();
    expect(calculate(base, BUILTIN_SPECS)).not.toBeNull();
  });
});

describe('every instrument the calculator offers can actually be sized', () => {
  it.each(Object.keys(BUILTIN_SPECS))('%s produces a result', (symbol) => {
    const entry = parseFloat(base.entryPrice);
    const state = { ...base, symbol, entryPrice: String(entry), stopLoss: String(entry * 0.99), takeProfit: String(entry * 1.02) };
    expect(explainMissingResult(state, BUILTIN_SPECS)).toBeNull();
    expect(calculate(state, BUILTIN_SPECS)).not.toBeNull();
  });
});
