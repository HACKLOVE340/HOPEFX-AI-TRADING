/**
 * S10-02 — every kill-switch indicator must read the same truth.
 *
 * docs/HARDENING_BACKLOG.md S10-02 (paired with the backend S2-01 split-brain).
 *
 * Three surfaces displayed the kill switch, from **two** different fields, with
 * three different precedences:
 *
 *   AccountBar.tsx:157            account.kill_switch
 *   RiskTransparencyStrip.tsx:42  risk.kill_switch_active ?? account.kill_switch
 *   RiskDashboard.tsx:74          account.kill_switch
 *
 * So a backend that populated `risk.kill_switch_active` but not
 * `account.kill_switch` produced one badge reading HALTED and two reading
 * nothing — on the same screen, about the same switch.
 *
 * This is the S13-01 duplication pattern on the frontend: every duplicated pair
 * in this codebase had already produced a defect, and the backend half of this
 * one (S2-01) was a CRITICAL where activating the switch through one endpoint
 * stopped trading and through the other did not.
 *
 * The rule for a safety indicator is asymmetric: it may over-report, never
 * under-report. If **any** source says halted, the UI says halted.
 */

import { describe, it, expect } from 'vitest';
import { selectKillSwitch } from '../store';

const store = (account: unknown, riskSnapshot: unknown) =>
  ({ account, riskSnapshot }) as never;

describe('selectKillSwitch — S10-02', () => {
  it('is false when nothing reports a halt', () => {
    expect(selectKillSwitch(store({ kill_switch: false }, { kill_switch_active: false }))).toBe(false);
  });

  it('is true when the account reports a halt', () => {
    expect(selectKillSwitch(store({ kill_switch: true }, { kill_switch_active: false }))).toBe(true);
  });

  it('is true when the risk snapshot reports a halt', () => {
    expect(selectKillSwitch(store({ kill_switch: false }, { kill_switch_active: true }))).toBe(true);
  });

  it('is true when only ONE source reports a halt and the other is absent', () => {
    // The exact disagreement: risk says halted, account never mentions it.
    // Two of the three surfaces used to show nothing here.
    expect(selectKillSwitch(store({}, { kill_switch_active: true }))).toBe(true);
    expect(selectKillSwitch(store({ kill_switch: true }, undefined))).toBe(true);
  });

  it('never under-reports when the sources disagree', () => {
    expect(selectKillSwitch(store({ kill_switch: true }, { kill_switch_active: false }))).toBe(true);
    expect(selectKillSwitch(store({ kill_switch: false }, { kill_switch_active: true }))).toBe(true);
  });

  it('is false — not undefined — when there is no data at all', () => {
    expect(selectKillSwitch(store(null, null))).toBe(false);
    expect(selectKillSwitch(store(undefined, undefined))).toBe(false);
  });
});

// ── The call sites must actually use it ──────────────────────────────────────

describe('every kill-switch surface reads the shared selector — S10-02', () => {
  const SURFACES = [
    'src/components/terminal/AccountBar.tsx',
    'src/components/intelligence/RiskTransparencyStrip.tsx',
    'src/components/panels/RiskDashboard.tsx',
  ];

  it.each(SURFACES)('%s does not re-derive the kill switch itself', async (rel) => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const file = path.resolve(process.cwd(), rel);
    if (!fs.existsSync(file)) return;
    const src = fs.readFileSync(file, 'utf8');

    if (!/kill.?switch/i.test(src)) return;

    expect(
      src.includes('selectKillSwitch'),
      `${rel} reads the kill switch without the shared selector. Three surfaces ` +
        `each derived it differently from two different fields, so they could ` +
        `disagree about whether trading was halted (S10-02).`,
    ).toBe(true);
  });
});
