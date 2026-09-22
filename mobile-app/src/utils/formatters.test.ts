import { confidenceLabel, formatCurrency, formatPct } from './formatters';

describe('formatters', () => {
  it('formats trading values and confidence labels deterministically', () => {
    expect(formatCurrency(1234.5)).toBe('$1,234.50');
    expect(formatPct(-2.5)).toBe('-2.50%');
    expect(confidenceLabel(0.9)).toBe('Very High');
    expect(confidenceLabel(0.6)).toBe('Medium');
  });
});
