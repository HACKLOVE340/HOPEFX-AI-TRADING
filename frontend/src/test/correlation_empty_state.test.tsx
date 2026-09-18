/**
 * F189 regression — the Correlation page must not discard the server's
 * explanation, and a secondary-data outage must not blank the page.
 *
 * The endpoint returns 200 with an EMPTY matrix plus a plain-English `note`
 * ("Correlation matrix requires OHLCV history for at least 2 symbols. Found
 * data for: ['XAU_USD']…") and the symbols it lacked. The page modelled
 * neither field, so a user waited ~20s and got a blank card while the remedy
 * sat unread in the response.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(__dirname, '../pages/CorrelationDashboard.tsx');
const src = fs.readFileSync(SRC, 'utf-8');

describe('F189 — correlation empty state and partial failure', () => {
  it('models the server fields it is sent', () => {
    // Without these on the interface the values cannot be rendered at all.
    expect(src).toMatch(/note\?:\s*string/);
    expect(src).toMatch(/symbols_missing_data\?:\s*string\[\]/);
  });

  it('renders the server note rather than an empty table', () => {
    expect(src).toMatch(/\{corr\.note\}/);
    expect(src).toMatch(/symbols\s*\?\?\s*\[\]\)\.length === 0/);
  });

  it('tells the user which symbols lacked history', () => {
    expect(src).toMatch(/corr\.symbols_missing_data\s*\?\?\s*\[\]\)\.join/);
  });

  it('does not require BOTH requests to fail before reporting an error', () => {
    // The original guard. If it comes back, a failing correlation request is
    // silent whenever the independent COT request happens to succeed.
    expect(src).not.toMatch(/if\s*\(\s*!corrOk\s*&&\s*!cotOk\s*\)/);
    expect(src).toMatch(/setLoadErr\(corrOk \? null :/);
  });

  it('keeps a COT outage out of the page-level error state', () => {
    // `loadErr` replaces the entire view, so routing the COT failure there
    // would hide a perfectly good correlation matrix.
    expect(src).toMatch(/setCotErr\(cotOk \? null :/);
    expect(src).toMatch(/\{cotErr && !cot &&/);
  });
});
