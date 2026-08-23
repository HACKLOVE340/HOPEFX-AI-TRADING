/**
 * F169 — the order form must tell a trader when a filled order left the
 * position UNPROTECTED because the broker never received the stop.
 *
 * These assert the contract, not the rendering: the API field exists, the
 * component reads it, and a warning result is not auto-dismissed.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(
  resolve(__dirname, '../components/panels/OrderEntryForm.tsx'),
  'utf-8',
);

describe('F169 — unprotected-position warning', () => {
  it('reads stop_loss_placed from the order response', () => {
    expect(SRC).toContain('stop_loss_placed');
  });

  it('treats stop_loss_placed === false as a NON-ok result', () => {
    // must branch on the explicit false, not on falsy — null means "no bracket
    // was requested" and is not a warning condition
    expect(SRC).toMatch(/slPlaced === false/);
    const i = SRC.indexOf('slPlaced === false');
    const branch = SRC.slice(i, i + 400);
    expect(branch).toMatch(/ok:\s*false/);
  });

  it('names the consequence in words a trader can act on', () => {
    expect(SRC).toMatch(/UNPROTECTED/);
  });

  it('does NOT auto-dismiss a non-ok result', () => {
    // the 4s timer must be gated on result.ok
    expect(SRC).toMatch(/if \(!result\.ok\) return;/);
    const timerIdx = SRC.indexOf('setTimeout(() => setResult(null), 4_000)');
    const guardIdx = SRC.indexOf('if (!result.ok) return;');
    expect(guardIdx).toBeGreaterThan(-1);
    expect(guardIdx).toBeLessThan(timerIdx);
  });
});
