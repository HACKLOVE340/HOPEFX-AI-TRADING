/**
 * Phase P1 — what the presence knows and may do, on any page in the app.
 *
 * Owner request, 2026-09-07: the AI should be available on every screen, able
 * to diagnose the page around it, move around it, and act on it.
 *
 * ## Nothing here renders
 *
 * These are pure functions, like the rest of `hub/`. The overlay itself is a
 * major UI change on a money-moving platform — it would sit above the order
 * ticket — and `flow-by-flow` requires a `flow-prototype` approval surface and
 * explicit approval before that ships. This layer is what the overlay will ask;
 * it changes nothing on screen and needs no gate.
 *
 * ## Observing a page is not acting on it
 *
 * The presence may read any page it is on. Anything that CHANGES the page goes
 * through `ai/tools/bus.py` and its two gates, with an operator identity and a
 * risk tier. So `pageCapabilities` returns two lists that are never merged —
 * what can be read here, and what can be requested here — mirroring the
 * `permitted` / `platform_context` split `ai/agent/loop.py` already holds for
 * the same reason. There is no version of this where a presence overlay becomes
 * a second way to place a trade.
 *
 * ## It derives from the app, not from a list of pages
 *
 * `NAV_ITEMS` is the single source of truth for routes, and
 * `ai/hub/app_surface.py` for what each area can do. A hand-written per-page
 * table would be correct on the day it was written and wrong by the next
 * release, which is the failure mode the app-surface module exists to avoid.
 */

import { describe, it, expect } from 'vitest';

import { describePage } from '../hub/pageContext';
import { dockFor, DISMISSED } from '../hub/presenceDock';
import { pageCapabilities } from '../hub/pageCapabilities';

const NAV = [
  { path: '/dashboard', label: 'Dashboard', group: 'core', plan: 'free', featureKey: 'dashboard' },
  { path: '/trade', label: 'Trade', group: 'core', plan: 'free', featureKey: 'trade' },
  { path: '/ai-core', label: 'AI Core', group: 'admin', plan: 'pro', featureKey: 'ai_core' },
];

// ── the page describer ────────────────────────────────────────────────────────

describe('page context', () => {
  it('names the page the operator is on', () => {
    const page = describePage({ pathname: '/trade', nav: NAV });
    expect(page.known).toBe(true);
    expect(page.label).toBe('Trade');
    expect(page.area).toBe('core');
  });

  it('resolves a nested route to its parent page', () => {
    const page = describePage({ pathname: '/trade/XAUUSD/edit', nav: NAV });
    expect(page.known).toBe(true);
    expect(page.path).toBe('/trade');
  });

  it('prefers the longest matching prefix, not the first', () => {
    const nav = [...NAV, { path: '/trade/history', label: 'Trade History', group: 'core', plan: 'free', featureKey: 'trade' }];
    expect(describePage({ pathname: '/trade/history/2026', nav }).label).toBe('Trade History');
  });

  it('reports an unknown route as unknown, with the path, rather than guessing', () => {
    // Guessing the nearest page would have the AI confidently describing a
    // screen the operator is not looking at.
    const page = describePage({ pathname: '/somewhere-new', nav: NAV });
    expect(page.known).toBe(false);
    expect(page.label).toBe('');
    expect(page.reason).toContain('/somewhere-new');
  });

  it('does not match a prefix that is not a path boundary', () => {
    expect(describePage({ pathname: '/trademark', nav: NAV }).known).toBe(false);
  });

  it('reports what is wrong on the page separately from what is on it', () => {
    const page = describePage({
      pathname: '/trade',
      nav: NAV,
      landmarks: [
        { id: 'ticket', role: 'form', label: 'Order ticket' },
        { id: 'chart', role: 'img', label: 'XAUUSD chart', stale: true },
        { id: 'positions', role: 'table', label: 'Open positions', error: 'feed disconnected' },
      ],
    });

    expect(page.landmarks.map((l) => l.id)).toEqual(['ticket', 'chart', 'positions']);
    expect(page.problems).toEqual([
      { id: 'chart', problem: 'stale' },
      { id: 'positions', problem: 'feed disconnected' },
    ]);
  });

  it('says the page was not inspected rather than reporting it healthy', () => {
    // No landmarks and a healthy page look identical, and only one of them is
    // something the AI should say out loud.
    const page = describePage({ pathname: '/trade', nav: NAV });
    expect(page.inspected).toBe(false);
    expect(page.problems).toEqual([]);
    expect(page.reason).toMatch(/not inspected|no landmarks/i);
  });

  it('reports an inspected page with nothing wrong as healthy', () => {
    const page = describePage({
      pathname: '/trade',
      nav: NAV,
      landmarks: [{ id: 'ticket', role: 'form', label: 'Order ticket' }],
    });
    expect(page.inspected).toBe(true);
    expect(page.problems).toEqual([]);
    expect(page.reason).toBe('');
  });
});

// ── where the presence sits ───────────────────────────────────────────────────

const VIEWPORT = { x: 0, y: 0, width: 1440, height: 900 };

describe('presence dock', () => {
  it('sits in a corner by default and stays inside the viewport', () => {
    const dock = dockFor({ viewport: VIEWPORT });
    expect(dock.rect.x).toBeGreaterThanOrEqual(VIEWPORT.x);
    expect(dock.rect.y).toBeGreaterThanOrEqual(VIEWPORT.y);
    expect(dock.rect.x + dock.rect.width).toBeLessThanOrEqual(VIEWPORT.width);
    expect(dock.rect.y + dock.rect.height).toBeLessThanOrEqual(VIEWPORT.height);
  });

  it('moves out of the way of what the operator is using', () => {
    // The order ticket is the thing this must never cover.
    const ticket = { x: 1100, y: 620, width: 320, height: 260 };
    const dock = dockFor({ viewport: VIEWPORT, avoid: [ticket] });
    expect(dock.overlapping).toEqual([]);
    expect(dock.corner).not.toBe('bottom-right');
  });

  it('says so when every corner is taken rather than silently covering one', () => {
    const everywhere = [{ x: 0, y: 0, width: 1440, height: 900 }];
    const dock = dockFor({ viewport: VIEWPORT, avoid: everywhere });
    expect(dock.overlapping.length).toBeGreaterThan(0);
    expect(dock.reason).toMatch(/no corner|every corner/i);
  });

  it('docks to an edge bar on a narrow viewport, where a floating orb would cover content', () => {
    const dock = dockFor({ viewport: { x: 0, y: 0, width: 380, height: 720 } });
    expect(dock.mode).toBe('bar');
    expect(dock.rect.width).toBe(380);
  });

  it('floats on a wide viewport', () => {
    expect(dockFor({ viewport: VIEWPORT }).mode).toBe('float');
  });

  it('stays dismissed once dismissed, on every page', () => {
    // Dismissing a presence that returns on the next navigation is not a
    // dismissal, it is a delay.
    const dock = dockFor({ viewport: VIEWPORT, state: DISMISSED });
    expect(dock.visible).toBe(false);
    expect(dock.reason).toMatch(/dismissed/i);
  });

  it('never traps keyboard focus', () => {
    const dock = dockFor({ viewport: VIEWPORT });
    expect(dock.a11y.role).toBe('complementary');
    expect(dock.a11y['aria-label'].length).toBeGreaterThan(0);
    expect(dock.trapsFocus).toBe(false);
  });

  it('does not animate its travel under reduced motion', () => {
    const dock = dockFor({ viewport: VIEWPORT, reducedMotion: true });
    expect(dock.transition).toBe('none');
  });

  it('animates with transform and opacity only, never layout properties', () => {
    const dock = dockFor({ viewport: VIEWPORT });
    expect(dock.transition).toMatch(/transform|opacity/);
    expect(dock.transition).not.toMatch(/width|height|top|left/);
  });

  it('refuses a viewport it cannot use rather than docking off-screen', () => {
    const dock = dockFor({ viewport: { x: 0, y: 0, width: 0, height: 0 } });
    expect(dock.visible).toBe(false);
    expect(dock.reason).toMatch(/viewport/i);
  });
});

// ── what it may do here ───────────────────────────────────────────────────────

const SURFACE = [
  { method: 'GET', path: '/api/trading/positions', mode: 'read', area: 'trading', summary: 'Open positions', invokable: false, tool: '' },
  { method: 'POST', path: '/api/trading/orders', mode: 'write', area: 'trading', summary: 'Place an order', invokable: false, tool: '' },
  { method: 'POST', path: '/api/trading/close', mode: 'write', area: 'trading', summary: 'Close a position', invokable: true, tool: 'markets_execution.close' },
  { method: 'GET', path: '/api/risk/limits', mode: 'read', area: 'risk', summary: 'Risk limits', invokable: false, tool: '' },
];

describe('page capabilities', () => {
  it('never merges what can be read with what can be requested', () => {
    const caps = pageCapabilities({ area: 'trading', surface: SURFACE });
    expect(caps.readable.map((c) => c.path)).toEqual(['/api/trading/positions']);
    expect(caps.requestable.map((c) => c.path)).toEqual(['/api/trading/close']);
    expect(Object.keys(caps)).not.toContain('all');
  });

  it('lists a write with no registered tool as unavailable, with the reason', () => {
    // Not requestable, and not silently absent either: "the AI cannot do this"
    // and "this does not exist" are different answers to the operator.
    const caps = pageCapabilities({ area: 'trading', surface: SURFACE });
    expect(caps.unavailable).toEqual([
      { path: '/api/trading/orders', reason: 'no tool is registered for it, so the AI cannot invoke it' },
    ]);
  });

  it('does not offer another area capabilities', () => {
    const caps = pageCapabilities({ area: 'trading', surface: SURFACE });
    expect([...caps.readable, ...caps.requestable].some((c) => c.area === 'risk')).toBe(false);
  });

  it('reports an area with nothing in it as empty rather than falling back to everything', () => {
    const caps = pageCapabilities({ area: 'academy', surface: SURFACE });
    expect(caps.readable).toEqual([]);
    expect(caps.requestable).toEqual([]);
    expect(caps.reason).toMatch(/academy/);
  });

  it('counts the two kinds separately, like the app surface does', () => {
    const caps = pageCapabilities({ area: 'trading', surface: SURFACE });
    expect(caps.counts).toEqual({ readable: 1, requestable: 1, unavailable: 1 });
  });
});
