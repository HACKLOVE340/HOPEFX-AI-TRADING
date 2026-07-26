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
import { writeFileSync, existsSync, readFileSync } from 'node:fs';

const BASE = (process.env.HOPEFX_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const USER = process.env.HOPEFX_USER || '';
const PASS = process.env.HOPEFX_PASS || '';
const args = process.argv.slice(2);
const HEADED = args.includes('--headed');
const ONE = args.find((a) => a.startsWith('--route='))?.split('=')[1];
const OUT = args.find((a) => a.startsWith('--out='))?.split('=')[1];

// Session reuse. Log in once, keep the cookies and localStorage in a file, and
// every later run starts already authenticated.
//
// This is deliberately NOT an auth bypass. A flag that lets the server skip
// authentication is a backdoor in a live trading platform: it exists in
// production, it is one config mistake away from being on, and it is the first
// thing an attacker looks for. Reusing a real session is the same convenience
// with none of that — the server's auth is never weakened, and the file can be
// deleted or expire like any other login.
//
//   node scripts/page_sweep.mjs --save-auth        (log in, write .auth.json)
//   node scripts/page_sweep.mjs                    (reuse it — no password needed)
//
// .auth.json holds a live session token. It is gitignored; treat it like a
// password and delete it when you are done.
const AUTH_FILE = args.find((a) => a.startsWith('--auth='))?.split('=')[1] || '.auth.json';
const SAVE_AUTH = args.includes('--save-auth');

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

// Real device widths, not arbitrary breakpoints: an iPhone 14, an iPad in
// portrait, and a laptop. Override with --viewports=mobile,desktop to go faster.
const ALL_VIEWPORTS = [
  { name: 'desktop 1440', size: { width: 1440, height: 900 } },
  { name: 'tablet 834',   size: { width: 834,  height: 1112 } },
  { name: 'mobile 390',   size: { width: 390,  height: 844 } },
];
const vpFilter = args.find((a) => a.startsWith('--viewports='))?.split('=')[1];
const VIEWPORTS = vpFilter
  ? ALL_VIEWPORTS.filter((v) => vpFilter.split(',').some((f) => v.name.startsWith(f.trim())))
  : ALL_VIEWPORTS;

const SETTLE_MS = Number(process.env.SWEEP_SETTLE_MS || 3500);
const c = { red: '\x1b[31m', yellow: '\x1b[33m', green: '\x1b[32m', dim: '\x1b[2m', bold: '\x1b[1m', off: '\x1b[0m' };

async function login(page) {
  if (!USER || !PASS) {
    console.log(`${c.yellow}No HOPEFX_USER/HOPEFX_PASS set — sweeping as an anonymous visitor.${c.off}`);
    console.log(`${c.yellow}Most routes will redirect to /login, which is not a useful report.${c.off}\n`);
    return false;
  }
  // The identifier field accepts EITHER an email or a username (Login.tsx:195 is
  // type="text" with autoComplete="username"), so matching input[type="email"]
  // found nothing and timed out. Match on autocomplete first, then fall back
  // through the plausible alternatives.
  //
  // Login failure must never be fatal either: this used to throw an uncaught
  // TimeoutError that killed the whole sweep, when the correct behaviour is to
  // carry on anonymously and audit whatever is publicly reachable.
  try {
    await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
    const ident = page.locator(
      'input[autocomplete="username"], input[name="username"], input[name="identifier"], ' +
      'input[type="email"], input[name="email"], form input[type="text"]',
    ).first();
    await ident.waitFor({ state: 'visible', timeout: 15000 });
    await ident.fill(USER);
    await page.locator('input[type="password"]').first().fill(PASS);
    await page.locator('button[type="submit"]').first().click();
    await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 20000 });
  } catch (e) {
    console.log(`${c.red}Login failed:${c.off} ${String(e).split('\n')[0].slice(0, 140)}`);
    console.log(`${c.yellow}Continuing anonymously — public pages will still be audited.${c.off}\n`);
    return false;
  }
  console.log(`${c.green}Logged in as ${USER}${c.off}\n`);
  return true;
}

/**
 * Layout audit, run inside the page.
 *
 * Deliberately checks things a screenshot cannot tell you and a unit test will
 * never catch, because they only exist once real content is laid out at a real
 * width: content wider than the screen, controls too small to tap, buttons with
 * no accessible name, text silently truncated, invisible overlays swallowing
 * clicks. Every finding names the element so it is actionable.
 */
const AUDIT_JS = `() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const desc = (el) => {
    const id = el.id ? '#' + el.id : '';
    const cls = (el.className && typeof el.className === 'string')
      ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
    const txt = (el.textContent || '').trim().slice(0, 30);
    return el.tagName.toLowerCase() + id + cls + (txt ? ' "' + txt + '"' : '');
  };
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const out = { overflowX: null, offscreen: [], smallTargets: [], namelessControls: [],
                truncated: [], brokenImages: [], duplicateIds: [], unlabelledInputs: [],
                junkText: [], deadLinks: [], structure: [], seo: [], mixedContent: [],
                blockingOverlay: null };

  // 1. Horizontal overflow — the page scrolls sideways. The single most common
  //    mobile break, and invisible on desktop.
  const docW = document.documentElement.scrollWidth;
  if (docW > vw + 2) {
    const culprits = [];
    for (const el of document.querySelectorAll('body *')) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.right > vw + 2 && r.width <= docW) culprits.push(desc(el) + ' right=' + Math.round(r.right));
      if (culprits.length >= 5) break;
    }
    out.overflowX = { pageWidth: docW, viewport: vw, culprits };
  }

  const interactive = [...document.querySelectorAll('button, a[href], input, select, textarea, [role="button"], [role="tab"]')]
    .filter(visible);

  for (const el of interactive) {
    const r = el.getBoundingClientRect();
    // 2. Off-screen but interactive — clipped out of reach.
    if (r.right < 0 || r.left > vw || r.bottom < 0) {
      if (out.offscreen.length < 8) out.offscreen.push(desc(el));
    }
    // 3. Touch target size. 44px is Apple's HIG minimum, 24px the WCAG 2.2 floor;
    //    flag below 24 so this reports genuine problems, not stylistic ones.
    if (r.width > 0 && (r.width < 24 || r.height < 24)) {
      if (out.smallTargets.length < 8) {
        out.smallTargets.push(desc(el) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
      }
    }
    // 4. Accessible name — icon-only controls a screen reader announces as "button".
    const name = (el.textContent || '').trim() || el.getAttribute('aria-label') ||
                 el.getAttribute('title') || el.getAttribute('alt') ||
                 el.getAttribute('placeholder') || '';
    if (!name && !el.querySelector('img[alt]:not([alt=""])')) {
      if (out.namelessControls.length < 8) out.namelessControls.push(desc(el));
    }
  }

  // 5. Text clipped by its container — a label that reads "Marg..." instead of
  //    "Margin Level", or a number cut in half.
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || el.children.length) continue;
    const s = getComputedStyle(el);
    if (s.overflow === 'visible' && s.textOverflow !== 'ellipsis') continue;
    if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0) {
      if (out.truncated.length < 8) out.truncated.push(desc(el));
    }
  }

  // 6. Broken images — the icon that never loads.
  for (const img of document.querySelectorAll('img')) {
    if (img.complete && img.naturalWidth === 0) {
      if (out.brokenImages.length < 8) out.brokenImages.push((img.getAttribute('src') || '(no src)').slice(0, 90));
    }
  }

  // 7. Duplicate DOM ids — breaks label/aria wiring and querySelector in subtle ways.
  const seen = new Set();
  for (const el of document.querySelectorAll('[id]')) {
    if (seen.has(el.id)) { if (out.duplicateIds.length < 8) out.duplicateIds.push(el.id); }
    seen.add(el.id);
  }

  // 8. Inputs with no label at all.
  for (const el of document.querySelectorAll('input:not([type="hidden"]), select, textarea')) {
    if (!visible(el)) continue;
    const labelled = el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                     (el.id && document.querySelector('label[for="' + CSS.escape(el.id) + '"]')) ||
                     el.closest('label');
    if (!labelled && out.unlabelledInputs.length < 8) out.unlabelledInputs.push(desc(el));
  }

  // 9. Junk text rendered to the user. This is the single highest-signal check
  //    in the file: "NaN", "undefined", "[object Object]" and "Invalid Date"
  //    are always bugs, they are always visible, and they are never caught by
  //    a type checker because they are the STRING form of a broken value.
  // Built with RegExp(...) rather than /literals/: this whole function lives in
  // a template literal, where \\b is the BACKSPACE escape and silently corrupts
  // every word boundary. Strings keep the patterns intact and readable.
  const JUNK = [
    'NaN', 'undefined', 'null', 'Invalid Date', 'Infinity',
    'TODO', 'FIXME',
  ].map((w) => new RegExp('\\\\b' + w + '\\\\b'))
    .concat([
      new RegExp('\\\\[object Object\\\\]'),
      new RegExp('lorem ipsum', 'i'),
      new RegExp('coming soon', 'i'),
      new RegExp('placeholder text', 'i'),
    ]);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const t = (node.textContent || '').trim();
    if (!t || t.length > 400) continue;
    const el = node.parentElement;
    if (!el || !visible(el)) continue;
    for (const re of JUNK) {
      if (re.test(t)) {
        if (out.junkText.length < 10) out.junkText.push(desc(el) + ' → "' + t.slice(0, 60) + '"');
        break;
      }
    }
  }

  // 10. Dead links — rendered as a link, goes nowhere.
  for (const a of document.querySelectorAll('a')) {
    if (!visible(a)) continue;
    const h = (a.getAttribute('href') || '').trim();
    if (h === '' || h === '#' || h.startsWith('javascript:')) {
      if (out.deadLinks.length < 8) out.deadLinks.push(desc(a));
    }
  }

  // 11. Document structure — one h1 per page, headings not skipping levels.
  const heads = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(visible);
  const h1s = heads.filter((h) => h.tagName === 'H1').length;
  if (h1s === 0) out.structure.push('no <h1> on the page');
  if (h1s > 1) out.structure.push(h1s + ' <h1> elements (should be one)');
  let prev = 0;
  for (const h of heads) {
    const lvl = Number(h.tagName[1]);
    if (prev && lvl > prev + 1) {
      out.structure.push('heading jumps h' + prev + ' → h' + lvl + ' at ' + desc(h));
      break;
    }
    prev = lvl;
  }
  if (!document.documentElement.lang) out.structure.push('<html> has no lang attribute');

  // 12. SEO / sharing metadata.
  const title = (document.title || '').trim();
  if (!title) out.seo.push('no <title>');
  else if (title.length < 10) out.seo.push('title suspiciously short: "' + title + '"');
  const md = document.querySelector('meta[name="description"]');
  if (!md || !(md.getAttribute('content') || '').trim()) out.seo.push('no meta description');

  // 13. Mixed content — an http:// asset on an https:// page is blocked by the
  //     browser and shows as a broken element with no obvious cause.
  if (location.protocol === 'https:') {
    for (const el of document.querySelectorAll('img[src],script[src],link[href],iframe[src]')) {
      const u = el.getAttribute('src') || el.getAttribute('href') || '';
      if (u.startsWith('http://')) {
        if (out.mixedContent.length < 6) out.mixedContent.push(u.slice(0, 90));
      }
    }
  }

  // 14. A main region that rendered nothing — the page "works" but is empty.
  const main = document.querySelector('main, [role="main"], #root > div');
  if (main && (main.textContent || '').trim().length < 20) {
    out.structure.push('main content region is empty');
  }

  // 15. A full-viewport element sitting on top of the page. A backdrop that was
  //    never dismissed looks like a working page but eats every click.
  const mid = document.elementFromPoint(Math.floor(vw / 2), Math.floor(vh / 2));
  if (mid) {
    const s = getComputedStyle(mid);
    const r = mid.getBoundingClientRect();
    if ((s.position === 'fixed' || s.position === 'absolute') &&
        r.width >= vw * 0.95 && r.height >= vh * 0.95 && !mid.contains(document.activeElement)) {
      out.blockingOverlay = desc(mid) + ' z=' + s.zIndex;
    }
  }
  return out;
}`;

async function auditLayout(page) {
  try {
    // Invoked, not just evaluated: page.evaluate treats a string as an
    // EXPRESSION, so passing the arrow function alone yields a function object
    // that never runs — and every audit silently comes back empty.
    return await page.evaluate(`(${AUDIT_JS})()`);
  } catch (e) {
    // Never swallow this. A silent audit failure reads as "no problems found",
    // which is the most misleading output this tool could produce.
    console.log(`       ${c.yellow}layout audit failed:${c.off} ${String(e).split('\n')[0].slice(0, 160)}`);
    return null;
  }
}

async function sweep(page, route) {
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];

  const onConsole = (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300)); };
  const onPageError = (e) => pageErrors.push(String(e).slice(0, 300));
  const timings = [];
  const hosts = new Set();
  const seenCalls = new Map();
  let bytes = 0;
  const onRequestFinished = (req) => {
    try {
      const u = new URL(req.url());
      if (u.host !== new URL(BASE).host) hosts.add(u.host);
      const t = req.timing();
      if (t && t.responseEnd > 0) timings.push({ path: u.pathname, ms: Math.round(t.responseEnd) });
      if (u.pathname.startsWith('/api/')) {
        const k = req.method() + ' ' + u.pathname + u.search;
        seenCalls.set(k, (seenCalls.get(k) || 0) + 1);
      }
    } catch { /* opaque URL */ }
  };
  const onResponse = (r) => {
    const len = Number(r.headers()['content-length'] || 0);
    if (len) bytes += len;
    if (r.status() >= 400) {
      const u = new URL(r.url());
      failedRequests.push(`${r.status()} ${r.request().method()} ${u.pathname}${u.search}`);
    }
  };
  page.on('console', onConsole);
  page.on('pageerror', onPageError);
  page.on('response', onResponse);
  page.on('requestfinished', onRequestFinished);

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

  const layout = navError ? null : await auditLayout(page);

  page.off('console', onConsole);
  page.off('pageerror', onPageError);
  page.off('response', onResponse);
  page.off('requestfinished', onRequestFinished);

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
    // A call fired more than once for the same page render is a double-fetch:
    // usually a useEffect missing its dependency array, and it doubles load on
    // the API for no benefit.
    duplicateCalls: [...seenCalls.entries()].filter(([, n]) => n > 1).map(([k, n]) => `${n}× ${k}`),
    slowRequests: timings.filter((t) => t.ms > 2000)
      .sort((a, b) => b.ms - a.ms).slice(0, 5).map((t) => `${t.ms}ms ${t.path}`),
    thirdPartyHosts: [...hosts],
    transferredKB: Math.round(bytes / 1024),
    layout,
  };
}

/** Count only the layout findings that are worth acting on. */
function layoutIssueCount(l) {
  if (!l) return 0;
  return (l.overflowX ? 1 : 0) + (l.blockingOverlay ? 1 : 0) +
    l.offscreen.length + l.smallTargets.length + l.namelessControls.length +
    l.truncated.length + l.brokenImages.length + l.duplicateIds.length +
    l.unlabelledInputs.length + (l.junkText || []).length + (l.deadLinks || []).length +
    (l.structure || []).length + (l.seo || []).length + (l.mixedContent || []).length;
}

function printLayout(l, indent = '       ') {
  if (!l) return;
  if (l.overflowX) {
    console.log(`${indent}${c.red}scrolls sideways:${c.off} page ${l.overflowX.pageWidth}px wide in a ${l.overflowX.viewport}px viewport`);
    for (const x of l.overflowX.culprits) console.log(`${indent}  ↳ ${x}`);
  }
  if (l.blockingOverlay) console.log(`${indent}${c.red}overlay covering the page:${c.off} ${l.blockingOverlay}`);
  const list = (label, arr, colour = c.yellow) => {
    if (arr && arr.length) {
      console.log(`${indent}${colour}${label} (${arr.length}):${c.off} ${arr.slice(0, 4).join(' | ')}`);
    }
  };
  list('off-screen controls', l.offscreen, c.red);
  list('tap targets under 24px', l.smallTargets);
  list('controls with no accessible name', l.namelessControls);
  list('truncated text', l.truncated);
  list('broken images', l.brokenImages, c.red);
  list('duplicate DOM ids', l.duplicateIds);
  list('unlabelled inputs', l.unlabelledInputs);
  list('junk text rendered to the user', l.junkText, c.red);
  list('dead links', l.deadLinks);
  list('document structure', l.structure);
  list('SEO metadata', l.seo, c.dim);
  list('mixed content (blocked on https)', l.mixedContent, c.red);
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
const reuseAuth = !SAVE_AUTH && existsSync(AUTH_FILE);
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  ...(reuseAuth ? { storageState: JSON.parse(readFileSync(AUTH_FILE, 'utf8')) } : {}),
});
if (reuseAuth) console.log(`${c.green}Reusing the saved session from ${AUTH_FILE}${c.off}\n`);
const page = await context.newPage();

console.log(`${c.bold}Sweeping ${ROUTES.length} route(s) on ${BASE}${c.off}\n`);
if (!reuseAuth) {
  const ok = await login(page);
  if (ok && SAVE_AUTH) {
    await context.storageState({ path: AUTH_FILE });
    console.log(`${c.green}Session saved to ${AUTH_FILE} — later runs need no password.${c.off}`);
    console.log(`${c.yellow}It contains a live token. Treat it like a password; delete it when done.${c.off}\n`);
  }
}

for (const route of ROUTES) {
  // Functional pass at desktop width, then the same page re-laid-out at tablet
  // and phone widths. Responsive breakage only exists at a real width — it
  // cannot be found by reading the CSS or by looking at a desktop screenshot.
  await page.setViewportSize(VIEWPORTS[0].size);
  const r = await sweep(page, route);

  r.layouts = { [VIEWPORTS[0].name]: r.layout };
  for (const vp of VIEWPORTS.slice(1)) {
    await page.setViewportSize(vp.size);
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(Math.min(SETTLE_MS, 2500));
      r.layouts[vp.name] = await auditLayout(page);
    } catch {
      r.layouts[vp.name] = null;
    }
  }
  delete r.layout;
  results.push(r);

  const layoutProblems = Object.values(r.layouts).reduce((n, l) => n + layoutIssueCount(l), 0);
  const problems =
    r.pageErrors.length + r.consoleErrors.length + r.failedRequests.length +
    (r.navError ? 1 : 0) + (r.blank ? 1 : 0) + (r.stuck ? 1 : 0) + layoutProblems;
  const mark = problems === 0 ? `${c.green}ok  ${c.off}` : `${c.red}FAIL${c.off}`;
  const note = r.redirectedTo ? `${c.dim} → ${r.redirectedTo}${c.off}` : '';
  console.log(`${mark} ${route.padEnd(24)}${note}`);
  if (r.navError)          console.log(`       ${c.red}nav:${c.off} ${r.navError}`);
  if (r.blank)             console.log(`       ${c.yellow}rendered nothing${c.off}`);
  if (r.stuck)             console.log(`       ${c.yellow}stuck on a loading state${c.off}`);
  for (const e of r.pageErrors.slice(0, 3))     console.log(`       ${c.red}exception:${c.off} ${e}`);
  for (const e of r.consoleErrors.slice(0, 3))  console.log(`       ${c.red}console:${c.off} ${e}`);
  for (const e of r.failedRequests.slice(0, 6)) console.log(`       ${c.red}request:${c.off} ${e}`);
  for (const e of r.duplicateCalls.slice(0, 4)) console.log(`       ${c.yellow}double-fetch:${c.off} ${e}`);
  for (const e of r.slowRequests.slice(0, 3))    console.log(`       ${c.yellow}slow:${c.off} ${e}`);
  if (r.thirdPartyHosts.length)                  console.log(`       ${c.dim}third-party: ${r.thirdPartyHosts.join(', ')}${c.off}`);
  for (const [vpName, l] of Object.entries(r.layouts)) {
    if (layoutIssueCount(l) === 0) continue;
    console.log(`       ${c.bold}[${vpName}]${c.off}`);
    printLayout(l, '         ');
  }
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

const byLayoutIssue = new Map();
for (const r of results) {
  for (const [vp, l] of Object.entries(r.layouts || {})) {
    if (!l) continue;
    const add = (k, n) => { if (n) byLayoutIssue.set(`${k} @ ${vp}`, (byLayoutIssue.get(`${k} @ ${vp}`) || 0) + 1); };
    add('scrolls sideways', l.overflowX ? 1 : 0);
    add('overlay blocking the page', l.blockingOverlay ? 1 : 0);
    add('off-screen controls', l.offscreen.length);
    add('tap targets under 24px', l.smallTargets.length);
    add('controls with no accessible name', l.namelessControls.length);
    add('truncated text', l.truncated.length);
    add('broken images', l.brokenImages.length);
    add('duplicate DOM ids', l.duplicateIds.length);
    add('unlabelled inputs', l.unlabelledInputs.length);
  }
}
if (byLayoutIssue.size) {
  console.log(`\n${c.bold}Layout issues, by how many pages they affect${c.off}`);
  for (const [k, n] of [...byLayoutIssue.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20)) {
    console.log(`  ${String(n).padStart(3)} pages  ${k}`);
  }
}

if (OUT) {
  writeFileSync(OUT, JSON.stringify({ base: BASE, sweptAt: new Date().toISOString(), results }, null, 2));
  console.log(`\nFull report: ${OUT}`);
}

await browser.close();
process.exit(broken.length ? 1 : 0);
