/**
 * Referral attribution chain.
 *
 * The affiliate program — four commission tiers, a leaderboard, monthly payouts,
 * a withdrawal flow — received zero attributions from any legitimate path,
 * because the chain broke in three places at once:
 *
 *   1. `Affiliate.tsx` handed out `${origin}/?ref=CODE`, which lands on
 *      LandingPage.
 *   2. `LandingPage.tsx` never read query parameters at all, and its CTAs were
 *      hardcoded `href="/register"` — so the code was dropped on the hop.
 *   3. `api/billing.py` generated `${base}/signup?ref=CODE`, and `/signup` is not
 *      a route, so that link hit the catch-all and redirected to /login.
 *
 * `Register.tsx` read `?ref=` correctly the whole time; nothing ever reached it.
 * The bitter detail from the audit: the only way a referral could be created was
 * by calling the unauthenticated activate-free-tier endpoint directly — the
 * fraud path worked and the legitimate one did not.
 *
 * These are source assertions because the failure was structural: three files
 * each individually plausible, agreeing on nothing.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const PAGES = join(__dirname, '..', 'pages');
const read = (f: string) => readFileSync(join(PAGES, f), 'utf8');

/** Source with comments stripped — the docs quote the very strings we assert against. */
const readCode = (f: string) =>
  read(f)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');

describe('referral chain', () => {
  it('LandingPage captures ?ref= on arrival', () => {
    const src = read('LandingPage.tsx');
    expect(src).toMatch(/URLSearchParams\(window\.location\.search\)\.get\('ref'\)/);
    expect(src).toContain('sessionStorage.setItem(REF_STORAGE_KEY');
  });

  it('every LandingPage register CTA carries the code', () => {
    const src = readCode('LandingPage.tsx');
    // No bare href="/register" left — each must go through the helper.
    expect(src).not.toMatch(/href="\/register"/);
    expect(src.match(/href=\{registerHref\(\)\}/g)?.length ?? 0).toBeGreaterThanOrEqual(4);
  });

  it('Affiliate shares a URL that attributes without a hop', () => {
    const src = read('Affiliate.tsx');
    expect(src).toContain('/register?ref=');
    // `/?ref=` relies on LandingPage forwarding it; the direct link does not.
    expect(src).not.toMatch(/origin\}\/\?ref=/);
  });

  it('Register accepts the code from the URL or from storage', () => {
    const src = read('Register.tsx');
    expect(src).toMatch(/params\.get\('ref'\)\s*\?\?\s*readStoredRef\(\)/);
    expect(src).toContain("sessionStorage.getItem('hopefx_ref')");
  });

  it('Register surfaces a failed trial grant instead of only logging it', () => {
    const src = read('Register.tsx');
    expect(src).toContain('setTrialWarning');
    expect(src).not.toContain('Free tier activation failed (non-fatal)');
  });
});
