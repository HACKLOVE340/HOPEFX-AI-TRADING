/**
 * §6 driven through the real panel: entering a mode introduces the presence,
 * changes the register, opens its surfaces — and cannot bury an alert.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => ({
    speak: vi.fn(), cancelSpeak: vi.fn(), startListening: vi.fn(), stopListening: vi.fn(),
    speaking: false, listening: false, sttSupported: false, transcript: '', status: null,
    spokenText: '', speechProgress: null,
  }),
}));

async function renderPresence(state: Record<string, unknown> = {}) {
  const { useStore } = await import('../store');
  // Every key this file touches is reset, not merged. The store is a module
  // singleton: a `kill_switch_active` left over from the previous test put a
  // later one into emergency mode and made it fail for a reason that had
  // nothing to do with what it was testing.
  useStore.setState({
    wsStatus: 'connected',
    feedStale: false,
    riskSnapshot: null,
    positions: [],
    ...state,
  } as never);
  const { PresencePanel } = await import('../components/ai/PresencePanel');
  return render(<PresencePanel ready providersReachable={1} />);
}

function say(phrase: string) {
  const input = screen.getByLabelText(/^ask$/i);
  fireEvent.change(input, { target: { value: phrase } });
  fireEvent.submit(input.closest('form')!);
}

/** The whole header rail, as one string — the layout label sits in its own span. */
function railText(): string {
  return document.querySelector('header')?.textContent ?? '';
}

function panels(): string[] {
  return screen
    .getAllByRole('region')
    .map((el) => el.getAttribute('aria-label') ?? '')
    .filter((l) => l !== 'AI presence' && l !== 'Presence core');
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('entering a mode', () => {
  it('introduces itself', async () => {
    // §6 wants the presence to say who it is being now, not to change silently.
    await renderPresence();
    say('switch to mission control');
    await waitFor(() => expect(screen.getByText(/mission control\. everything at once/i)).toBeTruthy());
  });

  it('names the register on screen', async () => {
    // A mode that changes how much scaffolding goes round a number without
    // saying which mode is in force leaves the operator unable to tell whether
    // "you have used most of your room" is the whole story.
    await renderPresence();
    say('analyst mode');
    await waitFor(() => expect(screen.getByText('Market analyst')).toBeTruthy());
  });

  it('opens the surfaces the mode is for', async () => {
    await renderPresence();
    say('engineering mode');
    await waitFor(() => {
      const open = panels().join(' ').toLowerCase();
      expect(open).toMatch(/model calls/);
      expect(open).toMatch(/agents/);
    });
  });

  it('goes back to the professional core on "normal mode"', async () => {
    await renderPresence();
    say('mission control');
    await waitFor(() => expect(screen.getByText('Mission control')).toBeTruthy());
    say('back to normal mode');
    await waitFor(() => expect(screen.getByText('Professional')).toBeTruthy());
  });
});

describe('a mode is a preference; an alert is a fact', () => {
  it('forces emergency when the kill switch is tripped, whatever mode was chosen', async () => {
    // A tripped kill switch does not become less true because somebody selected
    // the briefing register five minutes ago.
    await renderPresence({ riskSnapshot: { kill_switch_active: true } });
    say('give me the executive briefing');
    await waitFor(() => expect(screen.getByText('Emergency')).toBeTruthy());
    expect(screen.queryByText('Executive briefing')).toBeNull();
  });

  it('says why, in words, rather than only turning red', async () => {
    // §27: colour is never the only indicator, and this is the one signal on
    // the screen where that matters most.
    await renderPresence({ riskSnapshot: { kill_switch_active: true } });
    await waitFor(() => expect(screen.getAllByText(/kill switch is tripped/i).length).toBeGreaterThan(0));
  });

  it('reaches the presence at all — the alert input was hard-coded to null', async () => {
    // `alert: null` with a note deferring it to a later phase made `alerting`
    // unreachable in the running app, and with it the emergency promotion, the
    // alert tone and the interrupting reason. A control that cannot fire is not
    // a control (F176), and this one guards the kill switch.
    await renderPresence({ riskSnapshot: { kill_switch_active: true } });
    await waitFor(() => expect(screen.getByText(/^Needs you$/)).toBeTruthy());
  });

  it('puts risk and positions up in an emergency', async () => {
    await renderPresence({ riskSnapshot: { kill_switch_active: true } });
    say('emergency mode');
    await waitFor(() => {
      const open = panels().join(' ').toLowerCase();
      expect(open).toMatch(/risk limits/);
      expect(open).toMatch(/positions/);
    });
  });
});

describe('a mode does not overrule what was asked for out loud', () => {
  it('lets a named layout win over the mode default', async () => {
    // Otherwise "compare these" stops working the moment somebody is in
    // mission control, and the failure is silent.
    await renderPresence();
    say('mission control');
    await waitFor(() => expect(railText()).toMatch(/war room/i));
    say('compare them side by side');
    await waitFor(() => expect(railText()).toMatch(/compare/i));
  });

  it('does not let a mode ask for more surfaces than the device can hold', async () => {
    // Mission control wants twenty. A phone gets four.
    Object.defineProperty(window, 'innerWidth', { value: 375, configurable: true, writable: true });
    await renderPresence();
    say('mission control');
    await waitFor(() => expect(panels().length).toBeGreaterThan(0));
    expect(panels().length).toBeLessThanOrEqual(4);
  });
});
