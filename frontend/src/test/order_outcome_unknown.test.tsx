/**
 * F2-01 — "Order failed" is a claim, and on a timeout it is a false one.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F2 asks: *"What happens if the request
 * times out — does the user learn whether the order went through?"*
 *
 * `OrderEntryForm.tsx:340`
 *
 *     } catch (e: unknown) {
 *       const httpStatus = e?.response?.status;
 *       if (httpStatus === 503)      detail = 'Broker not ready…'
 *       else if (httpStatus === 403) detail = 'Order rejected…'
 *       else                         detail = extractApiError(e, 'Order failed');
 *
 * The axios instance carries `timeout: 30_000` (useApi.ts:15). A broker that
 * takes 31 seconds produces an error with **no `response` at all**, so it falls
 * through to the final branch and the trader is told the order *failed*.
 *
 * It may not have. A timeout says the answer never came back, not that the
 * order was refused — the order may be live at the broker right now. And the
 * natural response to "Order failed" is to place it again, at which point the
 * trader holds double the position they intended, with one stop covering half
 * of it.
 *
 * The distinction is already drawn, carefully and in exactly these terms, one
 * module away:
 *
 *     /** True only for a DEFINITIVE auth rejection … as opposed to a
 *      *  timeout/network/5xx, which says nothing about whether the session is
 *      *  actually valid. *\/
 *     export function _isDefiniteAuthRejection(err: unknown): boolean
 *                                                        — useApi.ts:198
 *
 * So the reasoning exists in the login path and not in the path that commits
 * capital. That is the S13-01 duplication pattern in its most expensive form:
 * the rule was written once, correctly, and the money path never got it.
 *
 * The same applies to closing: "Close failed" after a timeout invites a second
 * close, and "Close all failed" can follow a call that closed some of them.
 */

import { describe, it, expect } from 'vitest';
import { describeSubmitFailure } from '../lib/utils';

/** An axios error for a server that answered. */
const answered = (status: number, detail = 'nope') => ({
  isAxiosError: true,
  message: `Request failed with status code ${status}`,
  config: {},
  request: {},
  response: { status, data: { detail }, headers: {}, config: {} },
});

/** An axios error for a request that went out and never came back. */
const timedOut = () => ({
  isAxiosError: true,
  code: 'ECONNABORTED',
  message: 'timeout of 30000ms exceeded',
  config: {},
  request: {},
});

const networkDown = () => ({
  isAxiosError: true,
  message: 'Network Error',
  config: {},
  request: {},
});

describe('describeSubmitFailure — F2-01', () => {
  it('a server rejection is definitive: the order did not go through', () => {
    const r = describeSubmitFailure(answered(400, 'quantity too large'), 'order');
    expect(r.outcomeKnown).toBe(true);
    expect(r.message.toLowerCase()).toContain('quantity too large');
  });

  it('a 403 is definitive', () => {
    expect(describeSubmitFailure(answered(403), 'order').outcomeKnown).toBe(true);
  });

  it('a 503 is definitive — the broker refused to accept it', () => {
    expect(describeSubmitFailure(answered(503), 'order').outcomeKnown).toBe(true);
  });

  it('a timeout is NOT definitive', () => {
    // The one that matters. 30s elapsed; the broker may have filled it.
    expect(describeSubmitFailure(timedOut(), 'order').outcomeKnown).toBe(false);
  });

  it('a network error is NOT definitive', () => {
    expect(describeSubmitFailure(networkDown(), 'order').outcomeKnown).toBe(false);
  });

  it('never says "failed" when it does not know that', () => {
    const r = describeSubmitFailure(timedOut(), 'order');
    expect(r.message.toLowerCase()).not.toMatch(/\bfailed\b|\brejected\b|\bdid not\b/);
  });

  it('says the outcome is unknown, in words', () => {
    const r = describeSubmitFailure(timedOut(), 'order');
    expect(r.message.toLowerCase()).toMatch(/may have|might have|unknown|not know/);
  });

  it('tells the trader to check before retrying, rather than to retry', () => {
    const r = describeSubmitFailure(timedOut(), 'order');
    expect(r.message.toLowerCase()).toMatch(/check|verify/);
    expect(r.message.toLowerCase()).not.toMatch(/try again|retry|resubmit/);
  });

  it('names the thing whose outcome is unknown', () => {
    expect(describeSubmitFailure(timedOut(), 'order').message.toLowerCase()).toContain('order');
    expect(describeSubmitFailure(timedOut(), 'close').message.toLowerCase()).toContain('close');
  });

  it('a definite rejection may safely say to try again', () => {
    const r = describeSubmitFailure(answered(503), 'order');
    expect(r.outcomeKnown).toBe(true);
  });

  it('an error that never became a request is definitive — nothing was sent', () => {
    expect(describeSubmitFailure(new Error('bad config'), 'order').outcomeKnown).toBe(true);
  });

  it('never renders "undefined" or "[object Object]"', () => {
    for (const e of [answered(400), timedOut(), networkDown(), new Error('x'), null, undefined]) {
      const m = describeSubmitFailure(e, 'order').message;
      expect(m).toBeTruthy();
      expect(m).not.toMatch(/undefined|\[object Object\]/);
    }
  });
});

// ── The call sites must use it ───────────────────────────────────────────────

describe('every money-committing catch reports outcome honestly — F2-01', () => {
  const SURFACES = [
    'src/components/panels/OrderEntryForm.tsx',
    'src/components/panels/PositionsTable.tsx',
    'src/components/voice/VoiceTradingPanel.tsx',
  ];

  it.each(SURFACES)('%s does not assert failure it cannot know', async (rel) => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const file = path.resolve(process.cwd(), rel);
    if (!fs.existsSync(file)) return;
    const src = fs.readFileSync(file, 'utf8');

    expect(
      src.includes('describeSubmitFailure'),
      `${rel} reports a timeout as a definite failure. A trader told "failed" ` +
        `about an order that may be live will place it again (F2-01).`,
    ).toBe(true);
  });
});
