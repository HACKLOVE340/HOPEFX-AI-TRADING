/**
 * Phase P2 — the presence, rendered on every screen.
 *
 * Owner approved building this on 2026-09-07, after P1 shipped the architecture
 * and left `presence.overlay` planned pending that approval.
 *
 * ## Design brief, held steady across every state below
 *
 *   Goal      ask the AI about, and act on, whatever screen you are on,
 *             without leaving it
 *   Human     a trader mid-decision; available, never in the way
 *   Entry     mounted app-wide under the router; the exit is dismiss, and
 *             dismiss persists
 *   System    existing dark tokens, the existing PresenceCore canvas, lucide
 *             icons — no new visual language is introduced by this phase
 *   Signature it docks to whichever corner is free, and steps aside when the
 *             order ticket opens
 *   Feedback  transform and opacity only, 220ms; the readout is a polite live
 *             region; no haptics, because a browser cannot honestly claim them
 *   Rejecting a chat bubble that covers content; a presence that returns after
 *             being dismissed
 *   Variants  narrow viewport docks to an edge bar; reduced motion removes
 *             travel; the AI Core page has no overlay because the presence
 *             already owns that plane
 *
 * ## The state coverage map is this file
 *
 * `flow-prototype` asks for a review surface where every state is reachable
 * without timing luck. A throwaway route would have to be deleted afterwards
 * and would prove nothing durable, so the coverage map lives here instead:
 * every state below is reached deterministically and asserted, and it stays
 * asserted after the review is over.
 *
 * States: idle · with page problems · expanded · alerting · dismissed ·
 * narrow-viewport bar · reduced motion · unknown page · no-capability page ·
 * absent on the page that already has a presence.
 *
 * N/A: offline — the presence's own offline tone is `hub/presence.ts`'s job and
 * is asserted there; this overlay renders whatever tone it is handed.
 * N/A: haptics — a browser vibration API is a simulation, and the repository's
 * rule is never to claim native behaviour from one.
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';

import { PresenceAnywhere, DISMISS_KEY } from '../hub/PresenceAnywhere';

const NAV = [
  { path: '/trade', label: 'Trade', group: 'core', plan: 'free', featureKey: 'trade' },
  { path: '/ai-core', label: 'AI Core', group: 'admin', plan: 'pro', featureKey: 'ai_core' },
];

const SURFACE = [
  { method: 'GET', path: '/api/trading/positions', mode: 'read', area: 'core', summary: 'Open positions', invokable: false },
  { method: 'POST', path: '/api/trading/close', mode: 'write', area: 'core', summary: 'Close a position', invokable: true, tool: 'markets_execution.close' },
];

const PRESENCE = {
  state: 'idle' as const,
  reason: 'Standing by',
  tone: 'info' as const,
  intensity: 0.2,
  headroomKnown: true,
};

function mount(props: Partial<React.ComponentProps<typeof PresenceAnywhere>> = {}) {
  return render(
    <PresenceAnywhere
      pathname="/trade"
      nav={NAV}
      surface={SURFACE}
      presence={PRESENCE}
      viewport={{ x: 0, y: 0, width: 1440, height: 900 }}
      {...props}
    />,
  );
}

beforeEach(() => {
  cleanup();
  try {
    localStorage.clear();
  } catch {
    /* storage blocked; the component must cope, which other tests assert */
  }
});

// ── it is there, on an ordinary page ─────────────────────────────────────────

describe('presence overlay — idle', () => {
  it('renders on a page that is not the AI Core', () => {
    mount();
    expect(screen.getByRole('complementary', { name: /assistant/i })).toBeTruthy();
  });

  it('is absent on the page that already has a presence', () => {
    // Two presences on one screen is not twice the presence, it is a bug that
    // looks like a design.
    mount({ pathname: '/ai-core' });
    expect(screen.queryByRole('complementary', { name: /assistant/i })).toBeNull();
  });

  it('says what page it is on, so "what am I looking at" is already answered', () => {
    mount();
    expect(screen.getByRole('complementary')).toHaveTextContent(/Trade/);
  });

  it('has exactly one live region, not two competing ones', () => {
    // PresenceCore already owns a polite live region for the presence's own
    // reason. A second one here announced on every navigation and spoke over
    // it — a screen reader saying two things at once is one nobody leaves on.
    mount();
    const live = screen.getAllByRole('status');
    expect(live).toHaveLength(1);
    const only = live[0];
    if (!only) throw new Error('unreachable: length was just asserted');
    expect(only.getAttribute('aria-live')).toBe('polite');
  });

  it('hides the decorative canvas from assistive technology', () => {
    const { container } = mount();
    const canvas = container.querySelector('canvas');
    if (canvas) expect(canvas.getAttribute('aria-hidden')).toBe('true');
  });
});

// ── what is wrong with the page ──────────────────────────────────────────────

describe('presence overlay — page problems', () => {
  it('reports how many things on the page are wrong', () => {
    mount({
      landmarks: [
        { id: 'chart', role: 'img', label: 'XAUUSD chart', stale: true },
        { id: 'positions', role: 'table', label: 'Open positions', error: 'feed disconnected' },
      ],
    });
    expect(screen.getByRole('complementary')).toHaveTextContent(/2 problems|2 issues/i);
  });

  it('does not claim a page is healthy when nothing inspected it', () => {
    // "No landmarks reported" and "nothing wrong" look identical, and only one
    // of them is something the AI should say out loud.
    mount();
    expect(screen.getByRole('complementary')).not.toHaveTextContent(/no problems|all clear|healthy/i);
  });

  it('says the page is clear only when it was actually inspected', () => {
    mount({ landmarks: [{ id: 'ticket', role: 'form', label: 'Order ticket' }] });
    expect(screen.getByRole('complementary')).toHaveTextContent(/nothing wrong|no problems/i);
  });
});

// ── opening it ───────────────────────────────────────────────────────────────

describe('presence overlay — expanded', () => {
  it('opens on click and lists what it can read here', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    const panel = screen.getByRole('complementary');
    expect(within(panel).getByText(/Open positions/)).toBeTruthy();
  });

  it('separates what it can do from what it can only read', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    const panel = screen.getByRole('complementary');
    expect(within(panel).getByText(/Close a position/)).toBeTruthy();
    // The two lists are headed differently, because a single list would read as
    // "the AI can do all of this".
    expect(panel.textContent).toMatch(/can read/i);
    expect(panel.textContent).toMatch(/can do|can request/i);
  });

  it('offers no action on a page where nothing is invokable', () => {
    const readOnly = SURFACE.filter((entry) => entry.mode === 'read');
    mount({ surface: readOnly });
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    expect(screen.getByRole('complementary').textContent).toMatch(/nothing it can do here|read only|cannot act/i);
  });

  it('closes on Escape, and Escape does not dismiss it for good', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getByRole('complementary')).toBeTruthy();
    expect(screen.getByRole('button', { name: /open|ask/i })).toBeTruthy();
  });

  it('never traps the keyboard', () => {
    // A floating panel that captures Tab makes every page behind it unusable
    // for anyone navigating by keyboard.
    const { container } = mount();
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    const panel = container.querySelector('[role="complementary"]');
    expect(panel?.getAttribute('aria-modal')).not.toBe('true');
  });
});

// ── dismissal ────────────────────────────────────────────────────────────────

describe('presence overlay — dismissed', () => {
  it('goes away when dismissed', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /dismiss|close assistant/i }));
    expect(screen.queryByRole('complementary', { name: /assistant/i })).toBeNull();
  });

  it('stays away on the next page, because a dismissal that expires is a delay', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /dismiss|close assistant/i }));
    cleanup();
    mount({ pathname: '/trade/XAUUSD' });
    expect(screen.queryByRole('complementary', { name: /assistant/i })).toBeNull();
  });

  it('can be brought back, so dismissal is not a one-way door', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /dismiss|close assistant/i }));
    expect(screen.getByRole('button', { name: /bring back|show assistant/i })).toBeTruthy();
  });

  it('still renders when storage is unreadable rather than crashing the page', () => {
    // localStorage throws outright in Safari's private mode. A presence overlay
    // must never be the reason a trading page fails to render.
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('site data blocked');
    });
    try {
      expect(() => mount()).not.toThrow();
      expect(screen.getByRole('complementary')).toBeTruthy();
    } finally {
      spy.mockRestore();
    }
  });

  it('uses one storage key, so the dismissal can be found and cleared', () => {
    expect(DISMISS_KEY).toMatch(/hopefx/);
  });
});

// ── staying out of the way ───────────────────────────────────────────────────

describe('presence overlay — placement', () => {
  it('moves off the order ticket rather than sitting on it', () => {
    const { container } = mount({ avoid: [{ x: 1100, y: 620, width: 320, height: 260 }] });
    const panel = container.querySelector('[role="complementary"]') as HTMLElement;
    // bottom-right is where the ticket is, so the dock must have chosen elsewhere.
    expect(panel.getAttribute('data-corner')).not.toBe('bottom-right');
  });

  it('docks to an edge bar on a narrow viewport', () => {
    const { container } = mount({ viewport: { x: 0, y: 0, width: 380, height: 720 } });
    const panel = container.querySelector('[role="complementary"]') as HTMLElement;
    expect(panel.getAttribute('data-mode')).toBe('bar');
  });

  it('does not animate its travel under reduced motion', () => {
    const { container } = mount({ reducedMotion: true });
    const panel = container.querySelector('[role="complementary"]') as HTMLElement;
    expect(panel.style.transition).toBe('none');
  });

  it('animates with transform and opacity only, never layout properties', () => {
    const { container } = mount();
    const panel = container.querySelector('[role="complementary"]') as HTMLElement;
    expect(panel.style.transition).toMatch(/transform|opacity/);
    expect(panel.style.transition).not.toMatch(/\b(width|height|top|left)\b/);
  });
});

// ── alerting ─────────────────────────────────────────────────────────────────

describe('presence overlay — alerting', () => {
  it('says what is wrong in words, not only in colour', () => {
    mount({
      presence: { state: 'alerting' as const, reason: 'Risk headroom below 10%', tone: 'bad' as const, intensity: 1, headroomKnown: true },
    });
    expect(screen.getByRole('complementary')).toHaveTextContent(/Risk headroom below 10%/);
  });

  it('an alert is announced assertively, unlike everything else', () => {
    mount({
      presence: { state: 'alerting' as const, reason: 'Risk headroom below 10%', tone: 'bad' as const, intensity: 1, headroomKnown: true },
    });
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('an alert still shows on a dismissed presence, because dismissal is not consent to be uninformed', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /dismiss|close assistant/i }));
    cleanup();
    mount({
      presence: { state: 'alerting' as const, reason: 'Kill switch engaged', tone: 'bad' as const, intensity: 1, headroomKnown: false },
    });
    expect(screen.getByRole('alert')).toHaveTextContent(/Kill switch engaged/);
  });
});

// ── an unknown page ──────────────────────────────────────────────────────────

describe('presence overlay — unknown page', () => {
  it('says it does not recognise the page rather than describing the wrong one', () => {
    mount({ pathname: '/some-new-screen' });
    expect(screen.getByRole('complementary')).toHaveTextContent(/don't recognise|not recognise|unknown/i);
  });

  it('is still present and usable there', () => {
    mount({ pathname: '/some-new-screen' });
    expect(screen.getByRole('button', { name: /open|ask/i })).toBeTruthy();
  });
});

// ── it is actually mounted ───────────────────────────────────────────────────

describe('presence overlay — wiring', () => {
  it('is rendered app-wide, not merely defined', async () => {
    // A component nobody renders is the defect this codebase keeps finding.
    // `hopefx-dead-controls`, applied to a piece of UI.
    const fs = await import('node:fs');
    const path = await import('node:path');
    const app = fs.readFileSync(path.resolve(__dirname, '../App.tsx'), 'utf8');

    expect(app).toContain('PresenceAnywhereMount');
    expect(app).toMatch(/isAuth && <PresenceAnywhereMount \/>/);
  });

  it('is behind authentication, like every other AI surface', () => {
    const fs = require('node:fs') as typeof import('node:fs');
    const path = require('node:path') as typeof import('node:path');
    const app = fs.readFileSync(path.resolve(__dirname, '../App.tsx'), 'utf8');
    const line = app.split('\n').find((l) => l.includes('<PresenceAnywhereMount'));
    expect(line).toBeDefined();
    expect(line).toContain('isAuth');
  });
});

// ── the pre-delivery checklist, asserted ─────────────────────────────────────

describe('presence overlay — accessibility floor', () => {
  it('gives every control a visible focus ring', () => {
    // The browser default is close to invisible on a near-black panel, and this
    // session already hit the opposite defect once — `outline: none` removing
    // the ring outright.
    const { container } = mount();
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    const buttons = [...container.querySelectorAll('button')];
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) {
      expect(button.className).toMatch(/focus-visible:ring/);
    }
  });

  it('gives every control a 44px hit area', () => {
    // The dismiss control was a 14px icon in p-1 — about 22px square, half the
    // minimum, on the button an operator reaches for when the assistant is in
    // their way.
    const { container } = mount();
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    for (const button of container.querySelectorAll('button')) {
      expect(button.className).toMatch(/min-h-11/);
      expect(button.className).toMatch(/min-w-11/);
    }
  });

  it('uses no text colour that fails contrast on this panel', () => {
    // slate-500 measures 4.21:1 against the panel background and slate-400
    // measures 7.81:1. Measured, not eyeballed.
    const { container } = mount({ surface: [] });
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    expect(container.innerHTML).not.toMatch(/text-slate-500/);
    expect(container.innerHTML).not.toMatch(/text-slate-6\d\d/);
  });

  it('labels every icon-only control', () => {
    const { container } = mount();
    for (const button of container.querySelectorAll('button')) {
      const named = button.getAttribute('aria-label') || button.textContent?.trim();
      expect(named).toBeTruthy();
    }
  });

  it('hides decorative icons from assistive technology', () => {
    const { container } = mount();
    for (const svg of container.querySelectorAll('svg')) {
      expect(svg.getAttribute('aria-hidden')).toBe('true');
    }
  });

  it('says it could not load its capabilities rather than reporting none', () => {
    // "Nothing here is exposed to me" and "I could not find out" are different
    // sentences, and only one of them is true when the request failed.
    mount({ surface: [], surfaceReason: 'I could not load what I am allowed to do here (HTTP 503).' });
    fireEvent.click(screen.getByRole('button', { name: /open|ask/i }));
    expect(screen.getByRole('complementary')).toHaveTextContent(/could not load/i);
    expect(screen.getByRole('complementary')).not.toHaveTextContent(/Nothing on this page is exposed/i);
  });
});
