/**
 * F1 — Runtime failure matrix.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md, slice F1. This is the pass Round 3 recorded
 * as NOT performed:
 *
 *   "The 'run it' clause of this slice — pointing the dev server at a stopped
 *    backend and at one returning 500s, and recording what each view actually
 *    does — was not performed. The findings above are from reading the code."
 *                                        — HARDENING_BACKLOG.md, S9-03
 *
 * What this does differently from the existing page tests: those mock
 * `hooks/useApi` wholesale with resolved happy-path values, so the real request
 * layer, its interceptors and every component's failure branch are never
 * exercised. Here the **axios adapter** is stubbed instead, so the genuine
 * `useApi` module runs and each page meets a real failure.
 *
 * Scenarios:
 *   down     — no backend at all (network error)
 *   error500 — backend up, every /api/* returns 500
 *   auth401  — token expired, every call returns 401
 *   wsDead   — HTTP fine, WebSocket never opens
 *   wsSilent — WebSocket opens then delivers nothing
 *
 * The output is a classification per page per scenario. The dangerous class is
 * MEANINGFUL_ZERO: a view that renders a confident "none/zero/empty" when it
 * simply could not reach the backend. That is the shape of the defect already
 * confirmed in PositionsTable (S9-03).
 *
 * KNOWN LIMITS OF THIS HARNESS — read before trusting a result:
 *   - jsdom, not a browser: no layout, no paint, no real network.
 *   - Pages are rendered bare, without the app's theme/auth/layout providers,
 *     so some render empty here and would not in the app.
 *   - The shared `src/test/setup.ts` mocks `lightweight-charts` incompletely
 *     (no `HistogramSeries`), so chart pages throw in this harness for reasons
 *     unrelated to the backend. Those are reported as `crash` and not asserted.
 *   - Only pages that actually issued a request are asserted on; a page with
 *     zero requests has nothing to fail.
 * A real dev-server pass against a stopped backend remains worth doing; this
 * catches the cheap majority of it in CI.
 *
 * Set F1_REPORT=1 to print the full matrix.
 */

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import axios from 'axios';

import { api } from '../hooks/useApi';
import { useStore } from '../store';

// ─── Backend stubs ────────────────────────────────────────────────────────────

type Scenario = 'healthy' | 'down' | 'error500' | 'auth401' | 'wsDead' | 'wsSilent';

let callCount = 0;
const callsPerRender: Record<string, number> = {};

function installAxiosStub(scenario: Scenario) {
  const adapter = async (config: any) => {
    callCount += 1;
    if (scenario === 'down') {
      const err: any = new Error('Network Error');
      err.config = config;
      err.request = {};
      err.isAxiosError = true;
      throw err;
    }
    const status = scenario === 'auth401' ? 401 : 500;
    if (scenario === 'error500' || scenario === 'auth401') {
      const err: any = new Error(`Request failed with status code ${status}`);
      err.config = config;
      err.isAxiosError = true;
      err.response = { status, data: { detail: 'stubbed failure' }, headers: {}, config };
      throw err;
    }
    // healthy / wsDead / wsSilent: HTTP is fine but empty — the interesting axis is the
    // socket, and an empty-but-successful payload is the realistic pairing.
    return { data: [], status: 200, statusText: 'OK', headers: {}, config };
  };
  // Both: `api` is created with axios.create() at import time, which snapshots
  // the defaults — setting only axios.defaults.adapter leaves the real instance
  // untouched and the harness silently measures nothing (it did, at first: zero
  // requests on every page).
  (axios.defaults as any).adapter = adapter;
  (api.defaults as any).adapter = adapter;
  return adapter;
}

class DeadSocket {
  static OPEN = 1;
  readyState = 0; // CONNECTING, forever
  onopen: any = null;
  onclose: any = null;
  onerror: any = null;
  onmessage: any = null;
  constructor(public url: string) {}
  send() {}
  close() {}
  addEventListener() {}
  removeEventListener() {}
}

class SilentSocket extends DeadSocket {
  constructor(url: string) {
    super(url);
    this.readyState = 1; // OPEN, but never delivers a message
    setTimeout(() => this.onopen?.({}), 0);
  }
}

// ─── Page registry ────────────────────────────────────────────────────────────
// The money-relevant and highest-traffic routes. Deliberately not all 86: the
// point is a ranked answer, not a wall of noise.

const PAGES: Array<[name: string, loader: () => Promise<any>]> = [
  ['Dashboard', () => import('../pages/Dashboard')],
  ['Trading', () => import('../pages/Trading')],
  ['Trade', () => import('../pages/Trade')],
  ['TradingDashboard', () => import('../pages/TradingDashboard')],
  ['Portfolio', () => import('../pages/Portfolio')],
  ['Wallet', () => import('../pages/Wallet')],
  ['PnLDashboard', () => import('../pages/PnLDashboard')],
  ['Performance', () => import('../pages/Performance')],
  ['RiskCalculator', () => import('../pages/RiskCalculator')],
  ['Watchlist', () => import('../pages/Watchlist')],
  ['PriceAlerts', () => import('../pages/PriceAlerts')],
  ['TradeJournal', () => import('../pages/TradeJournal')],
];

// ─── The instrument ───────────────────────────────────────────────────────────
//
// A word-list classifier proved unreliable: "ERROR_SHOWN" fired on healthy
// pages because a connection badge renders the word "disconnected". The
// objective question is differential, and needs no vocabulary:
//
//     does this page render DIFFERENTLY when the backend is unreachable?
//
// If a page's output is byte-identical whether the backend is healthy or dead,
// then by construction the user cannot tell the difference. That is the whole
// finding, and it is not a matter of interpretation.

const rendered: Record<string, Record<string, string>> = {};

/** Strip values that legitimately vary between renders (times, ids, prices). */
function normalise(text: string): string {
  return text
    .replace(/\d{1,2}:\d{2}(:\d{2})?/g, '<time>')
    .replace(/[\d,]+\.\d+/g, '<num>')
    .replace(/\b\d+\b/g, '<n>')
    .replace(/\s+/g, ' ')
    .trim();
}

async function renderPage(name: string, loader: () => Promise<any>, scenario: Scenario) {
  let text = '';
  let crashed = false;
  callCount = 0;
  try {
    const mod = await loader();
    const Page = mod.default ?? Object.values(mod)[0];
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
    });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Page />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await new Promise((r) => setTimeout(r, 60));
    text = container.textContent ?? '';
  } catch (e) {
    crashed = true;
    text = `__CRASH__ ${String((e as Error)?.message).slice(0, 120)}`;
  } finally {
    cleanup();
  }
  rendered[name] ??= {};
  rendered[name][scenario] = crashed ? text : normalise(text);
  callsPerRender[`${name}|${scenario}`] = callCount;
  return rendered[name][scenario];
}

// ─── The matrix ───────────────────────────────────────────────────────────────

// 'healthy' is the control. Without it a page that always throws is
// indistinguishable from one that throws *because* the backend broke.
const SCENARIOS: Scenario[] = ['healthy', 'down', 'error500', 'auth401', 'wsDead', 'wsSilent'];

describe('F1 — what every view does when the backend is broken', () => {
  const realAdapter = (axios.defaults as any).adapter;
  const realApiAdapter = (api.defaults as any).adapter;
  const realWS = globalThis.WebSocket;

  beforeEach(() => {
    useStore.setState({
      wsStatus: 'disconnected',
      feedStale: false,
      positions: [],
      account: null,
    } as never);
  });

  afterEach(() => {
    (axios.defaults as any).adapter = realAdapter;
    (api.defaults as any).adapter = realApiAdapter;
    globalThis.WebSocket = realWS;
    vi.restoreAllMocks();
  });

  for (const scenario of SCENARIOS) {
    describe(`backend: ${scenario}`, () => {
      for (const [name, loader] of PAGES) {
        it(`${name} looks different when the backend is ${scenario}`, async () => {
          installAxiosStub(scenario);
          globalThis.WebSocket = (scenario === 'wsSilent' ? SilentSocket : DeadSocket) as never;
          if (scenario === 'wsSilent') {
            useStore.setState({ wsStatus: 'connected' } as never);
          }

          const out = await renderPage(name, loader, scenario);

          if (out.startsWith('__CRASH__')) {
            // Crashes are recorded but not asserted here: the shared test setup
            // mocks `lightweight-charts` incompletely (no HistogramSeries), so a
            // chart page crashes in this harness for reasons unrelated to the
            // backend. Distinguishing those needs the real dev server.
            return;
          }
          if (scenario === 'healthy') {
            // Control only — recorded, never asserted. Some pages render empty
            // in this harness because they need providers/context the real app
            // supplies (theme, auth, layout). That is a limit of the harness,
            // not a claim about the product.
            return;
          }

          const healthy = rendered[name]?.healthy;
          if (!healthy || healthy.startsWith('__CRASH__')) return;

          // A page that issued no requests has nothing to fail, so identical
          // output is expected rather than a defect. Only assert where the page
          // actually tried to reach the backend and every attempt failed.
          // (This check exists because the first version of this harness stubbed
          // only `axios.defaults` — `api` is built with axios.create() at import
          // time and snapshots the defaults, so ZERO requests were intercepted
          // and every page trivially looked "identical". The call count is what
          // makes the finding real.)
          if ((callsPerRender[`${name}|${scenario}`] ?? 0) === 0) return;

          expect(
            out,
            `${name} renders identically whether the backend is healthy or ` +
              `"${scenario}". A user cannot tell the difference, so any zero, ` +
              `empty list or price on this page reads as fact when it is ` +
              `actually "we could not reach the server".`,
          ).not.toBe(healthy);
        });
      }
    });
  }

  it('prints the matrix', () => {
    const pad = (x: string, n: number) => x.padEnd(n).slice(0, n);
    const failing = SCENARIOS.filter((x) => x !== 'healthy');
    console.log('\n' + pad('PAGE', 20) + failing.map((x) => pad(x, 12)).join(''));
    const rows: Array<{ page: string; identical: string[] }> = [];
    for (const [name] of PAGES) {
      const h = rendered[name]?.healthy;
      const cells = failing.map((x) => {
        const v = rendered[name]?.[x];
        if (!v || !h) return '?';
        if (v.startsWith('__CRASH__') || h.startsWith('__CRASH__')) return 'crash';
        return v === h ? 'IDENTICAL' : 'differs';
      });
      console.log(pad(name, 20) + cells.map((c) => pad(c, 12)).join(''));
      rows.push({ page: name, identical: failing.filter((_, i) => cells[i] === 'IDENTICAL') });
    }
    const silent = rows.filter((r) => r.identical.length === failing.length);
    console.log(
      `\n${silent.length}/${PAGES.length} pages render IDENTICALLY in every failure state:`,
      silent.map((r) => r.page).join(', ') || '(none)',
    );
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      require('fs').writeFileSync('/tmp/f1_matrix.json', JSON.stringify(rendered, null, 1));
      require('fs').writeFileSync('/tmp/f1_calls.json', JSON.stringify(callsPerRender, null, 1));
    } catch { /* best effort */ }
    expect(Object.keys(rendered).length).toBeGreaterThan(0);
  });
});
