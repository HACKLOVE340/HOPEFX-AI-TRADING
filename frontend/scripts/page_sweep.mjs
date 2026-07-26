#!/usr/bin/env node
/**
 * frontend/scripts/page_sweep.mjs
 * ======================
 * Visit every route in the app as a logged-in user and report what is broken.
 *
 * Diagnosing a SPA from screenshots is slow and misses most of it: a page can
 * look merely "empty" while the console holds the actual TypeError, or while a
 * single API call is quietly 500ing behind a spinner that never resolves. This
 * walks all ~80 routes and reports, per page:
 *
 *   - uncaught exceptions and console errors (the real cause, with the message)
 *   - failed network requests (4xx/5xx), with method, path and status
 *   - pages still showing a loading state after the network goes quiet
 *   - pages that rendered essentially nothing
 *
 * Usage — from the frontend/ directory (Playwright resolves from
 * frontend/node_modules, so it must be run from there):
 *
 *   cd frontend && npm ci
 *   HOPEFX_URL=https://hopefx.site \
 *   HOPEFX_USER=you@example.com \
 *   HOPEFX_PASS='...' \
 *   node scripts/page_sweep.mjs
 *
 * Add --headed to watch it, --route=/trade to sweep a single page, and
 * --out=report.json to keep the machine-readable copy.
 *
 * Read-only by design: it navigates and observes. It never submits an order,
 * clicks Close All, or changes a setting. Safe to run against production —
 * though it does log in, so use an account you don't mind appearing in the
 * session/audit log.
 *
 * Credentials come from the environment, never from arguments, so they do not
 * land in your shell history or the process list.
 */

import { chromium } from '@playwright/test';
import { writeFileSync } from 'node:fs';

const BASE = (process.env.HOPEFX_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const USER = process.env.HOPEFX_USER || '';
const PASS = process.env.HOPEFX_PASS || '';
const args = process.argv.slice(2);
const HEADED = args.includes('--headed');
const ONE = args.find((a) => a.startsWith('--route='))?.split('=')[1];
const OUT = args.find((a) => a.startsWith('--out='))?.split('=')[1];

// Every route from frontend/src/App.tsx, minus the ones a sweep must not touch:
// auth flows that mutate state (/register, /reset-password), and /checkout,
// which would start a real payment session.
const ROUTES = ONE ? [ONE] : [
  '/', '/dashboard', '/home', '/trade', '/trading', '/terminal', '/portfolio',
  '/watchlist', '/journal', '/performance', '/pnl', '/calendar', '/alerts',
  '/signals', '/feed', '/social', '/social-feed', '/leaderboard', '/marketplace',
  '/academy', '/news', '/research', '/intelligence', '/geopolitical', '/correlation',
  '/ai-chart', '/ai-chart-dashboard', '/ai-charts', '/ai-assistant', '/ai-strategy',
  '/nuclear', '/indicators', '/pattern-detector', '/strategy-builder', '/replay',
  '/backtest', '/walk-forward', '/ab-testing', '/tca', '/risk-calc', '/risk-calculator',
  '/copy-trading', '/sub-accounts', '/teams', '/wallet', '/affiliate', '/prop-firm',
  '/kyc', '/profile', '/settings', '/security', '/notifications', '/status',
  '/system-status', '/system-reliability', '/reliability', '/observability',
  '/ml-ops', '/auto-heal', '/master-control', '/audit', '/audit-log', '/admin',
  '/superadmin', '/whitelabel', '/elite', '/mobile', '/chat', '/docs',
  '/pricing', '/upgrade', '/transparency', '/privacy', '/terms', '/risk-disclosure',
];

const SETTLE_MS = Number(process.env.SWEEP_SETTLE_MS || 3500);
const c = { red: '\x1b[31m', yellow: '\x1b[33m', green: '\x1b[32m', dim: '\x1b[2m', bold: '\x1b[1m', off: '\x1b[0m' };

async function login(page) {
  if (!USER || !PASS) {
    console.log(`${c.yellow}No HOPEFX_USER/HOPEFX_PASS set — sweeping as an anonymous visitor.${c.off}`);
    console.log(`${c.yellow}Most routes will redirect to /login, which is not a useful report.${c.off}\n`);
    return false;
  }
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  // Match by type rather than a brittle test id, so this keeps working as the
  // login form is restyled.
  await page.locator('input[type="email"], input[name="email"]').first().fill(USER);
  await page.locator('input[type="password"]').first().fill(PASS);
  await page.locator('button[type="submit"]').first().click();
  try {
    await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 20000 });
  } catch {
    console.log(`${c.red}Login did not navigate away from /login — check the credentials.${c.off}`);
    return false;
  }
  console.log(`${c.green}Logged in as ${USER}${c.off}\n`);
  return true;
}

async function sweep(page, route) {
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];

  const onConsole = (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300)); };
  const onPageError = (e) => pageErrors.push(String(e).slice(0, 300));
  const onResponse = (r) => {
    if (r.status() >= 400) {
      const u = new URL(r.url());
      failedRequests.push(`${r.status()} ${r.request().method()} ${u.pathname}${u.search}`);
    }
  };
  page.on('console', onConsole);
  page.on('pageerror', onPageError);
  page.on('response', onResponse);

  let navError = null;
  try {
    await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(SETTLE_MS);
  } catch (e) {
    navError = String(e).split('\n')[0].slice(0, 200);
  }

  let text = '';
  let stuck = false;
  try {
    text = (await page.locator('body').innerText({ timeout: 5000 })).trim();
    // A spinner that never resolves is the single most common symptom here, and
    // it produces no console error at all — so detect it from the rendered text.
    stuck = /loading|fetching|awaiting|please wait/i.test(text) && text.length < 900;
  } catch { /* body unreadable — treated as blank below */ }

  page.off('console', onConsole);
  page.off('pageerror', onPageError);
  page.off('response', onResponse);

  const redirectedTo = new URL(page.url()).pathname;
  return {
    route,
    redirectedTo: redirectedTo === route ? null : redirectedTo,
    navError,
    blank: text.length < 40,
    stuck,
    pageErrors: [...new Set(pageErrors)],
    consoleErrors: [...new Set(consoleErrors)],
    failedRequests: [...new Set(failedRequests)],
  };
}

const results = [];
// Playwright's bundled browser revision often differs from whatever is already
// on a server. Accept an explicit path so this runs without a 400MB download,
// and fail with the actual remedy rather than a stack trace.
const EXEC = process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined;
let browser;
try {
  browser = await chromium.launch({ headless: !HEADED, executablePath: EXEC });
} catch (e) {
  console.error(`${c.red}Could not start Chromium.${c.off} ${String(e).split('\n')[0]}`);
  console.error('Either install it:            npx playwright install chromium');
  console.error('or point at an existing one:  PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome');
  process.exit(2);
}
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();

console.log(`${c.bold}Sweeping ${ROUTES.length} route(s) on ${BASE}${c.off}\n`);
await login(page);

for (const route of ROUTES) {
  const r = await sweep(page, route);
  results.push(r);
  const problems =
    r.pageErrors.length + r.consoleErrors.length + r.failedRequests.length +
    (r.navError ? 1 : 0) + (r.blank ? 1 : 0) + (r.stuck ? 1 : 0);
  const mark = problems === 0 ? `${c.green}ok  ${c.off}` : `${c.red}FAIL${c.off}`;
  const note = r.redirectedTo ? `${c.dim} → ${r.redirectedTo}${c.off}` : '';
  console.log(`${mark} ${route.padEnd(24)}${note}`);
  if (r.navError)          console.log(`       ${c.red}nav:${c.off} ${r.navError}`);
  if (r.blank)             console.log(`       ${c.yellow}rendered nothing${c.off}`);
  if (r.stuck)             console.log(`       ${c.yellow}stuck on a loading state${c.off}`);
  for (const e of r.pageErrors.slice(0, 3))     console.log(`       ${c.red}exception:${c.off} ${e}`);
  for (const e of r.consoleErrors.slice(0, 3))  console.log(`       ${c.red}console:${c.off} ${e}`);
  for (const e of r.failedRequests.slice(0, 6)) console.log(`       ${c.red}request:${c.off} ${e}`);
}

// ── Summary — the point of the whole exercise ────────────────────────────────
const broken = results.filter((r) =>
  r.navError || r.blank || r.stuck || r.pageErrors.length || r.consoleErrors.length || r.failedRequests.length);

console.log(`\n${c.bold}── Summary ──${c.off}`);
console.log(`${results.length - broken.length}/${results.length} pages clean`);

// Group failing endpoints across all pages. One broken API usually explains
// a dozen "broken pages", so fix by endpoint, not by page.
const byEndpoint = new Map();
for (const r of results) {
  for (const f of r.failedRequests) byEndpoint.set(f, (byEndpoint.get(f) || 0) + 1);
}
if (byEndpoint.size) {
  console.log(`\n${c.bold}Failing endpoints, most widespread first${c.off}`);
  console.log(`${c.dim}One bad endpoint usually explains several "broken" pages — start here.${c.off}`);
  for (const [ep, n] of [...byEndpoint.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20)) {
    console.log(`  ${String(n).padStart(3)}×  ${ep}`);
  }
}

if (OUT) {
  writeFileSync(OUT, JSON.stringify({ base: BASE, sweptAt: new Date().toISOString(), results }, null, 2));
  console.log(`\nFull report: ${OUT}`);
}

await browser.close();
process.exit(broken.length ? 1 : 0);
