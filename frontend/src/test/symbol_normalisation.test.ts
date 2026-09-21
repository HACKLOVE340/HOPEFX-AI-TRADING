/**
 * `toSlashSymbol` — the price feed keys on 'XAU/USD', most pages store 'XAUUSD'.
 *
 * Watchlist offered ten symbols but mapped five of them with a hardcoded chain
 * of .replace() calls, so ETHUSD, USDCAD, AUDUSD, USDCHF and NZDUSD matched no
 * feed key and showed no live price at all. Three other sites wrote the same
 * rule as `slice(0,3) + '/' + slice(3)`.
 */
import { describe, it, expect } from 'vitest';
import { toSlashSymbol } from '../lib/utils';

describe('toSlashSymbol', () => {
  it.each([
    ['XAUUSD', 'XAU/USD'],
    ['EURUSD', 'EUR/USD'],
    ['USDJPY', 'USD/JPY'],
    // The five the hardcoded mapping missed.
    ['ETHUSD', 'ETH/USD'],
    ['USDCAD', 'USD/CAD'],
    ['AUDUSD', 'AUD/USD'],
    ['USDCHF', 'USD/CHF'],
    ['NZDUSD', 'NZD/USD'],
  ])('maps %s to %s', (input, expected) => {
    expect(toSlashSymbol(input)).toBe(expected);
  });

  it('leaves already-slashed symbols alone', () => {
    expect(toSlashSymbol('XAU/USD')).toBe('XAU/USD');
  });

  it('leaves anything that is not a six-character pair alone', () => {
    // The slice() version produced 'BTC/USDT' → 'BTC/USDT'.slice was fine, but
    // 'US500'.slice(0,3) + '/' + 'US500'.slice(3) gave the nonsense 'US5/00'.
    expect(toSlashSymbol('US500')).toBe('US500');
    expect(toSlashSymbol('BTCUSDT')).toBe('BTCUSDT');
    expect(toSlashSymbol('')).toBe('');
  });
});
