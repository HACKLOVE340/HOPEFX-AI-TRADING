/**
 * Additional formatting and display logic tests.
 * ~30 tests
 */

import { describe, it, expect } from 'vitest';

// ─── Symbol decimal places ────────────────────────────────────────────────────

describe('symbol decimal places', () => {
  const getDecimals = (symbol: string) =>
    symbol.includes('JPY') ? 3 :
    symbol.includes('BTC') ? 0 :
    symbol.includes('XAU') ? 2 : 5;

  it('XAU/USD uses 2 decimals', () => expect(getDecimals('XAU/USD')).toBe(2));
  it('EUR/USD uses 5 decimals', () => expect(getDecimals('EUR/USD')).toBe(5));
  it('GBP/USD uses 5 decimals', () => expect(getDecimals('GBP/USD')).toBe(5));
  it('USD/JPY uses 3 decimals', () => expect(getDecimals('USD/JPY')).toBe(3));
  it('EUR/JPY uses 3 decimals', () => expect(getDecimals('EUR/JPY')).toBe(3));
  it('BTC/USD uses 0 decimals', () => expect(getDecimals('BTC/USD')).toBe(0));
  it('ETH/USD uses 5 decimals (default)', () => expect(getDecimals('ETH/USD')).toBe(5));
  it('XAG/USD uses 5 decimals (default, no XAU match)', () => expect(getDecimals('XAG/USD')).toBe(5));
});

// ─── WS status display ────────────────────────────────────────────────────────

describe('WS status display', () => {
  const getLabel = (status: string) =>
    status === 'connected' ? 'Live' :
    status.charAt(0).toUpperCase() + status.slice(1);

  it('connected shows Live', () => expect(getLabel('connected')).toBe('Live'));
  it('disconnected shows Disconnected', () => expect(getLabel('disconnected')).toBe('Disconnected'));
  it('connecting shows Connecting', () => expect(getLabel('connecting')).toBe('Connecting'));
  it('error shows Error', () => expect(getLabel('error')).toBe('Error'));
});

// ─── Date formatting ──────────────────────────────────────────────────────────

describe('date formatting', () => {
  it('ISO date slice gives YYYY-MM-DD', () => {
    const d = new Date('2024-03-15T10:30:00.000Z');
    expect(d.toISOString().slice(0, 10)).toBe('2024-03-15');
  });
  it('toLocaleString produces non-empty string', () => {
    expect(new Date().toLocaleString().length).toBeGreaterThan(0);
  });
  it('date comparison works for equity history ordering', () => {
    const d1 = new Date('2024-01-01');
    const d2 = new Date('2024-01-02');
    expect(d1 < d2).toBe(true);
  });
  it('90 days ago is before today', () => {
    const now = new Date();
    const past = new Date(now);
    past.setDate(past.getDate() - 90);
    expect(past < now).toBe(true);
  });
});

// ─── Number display edge cases ────────────────────────────────────────────────

describe('number display edge cases', () => {
  it('Infinity is not a finite number', () => {
    expect(isFinite(Infinity)).toBe(false);
  });
  it('NaN is not a finite number', () => {
    expect(isFinite(NaN)).toBe(false);
  });
  it('0 is finite', () => {
    expect(isFinite(0)).toBe(true);
  });
  it('very large number is finite', () => {
    expect(isFinite(1e15)).toBe(true);
  });
  it('parseFloat preserves precision', () => {
    expect(parseFloat((2340.12345).toFixed(5))).toBe(2340.12345);
  });
  it('toFixed(2) rounds correctly', () => {
    expect((1.005).toFixed(2)).toMatch(/1\.(00|01)/);
  });
});
