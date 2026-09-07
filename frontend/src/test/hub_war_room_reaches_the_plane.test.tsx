/**
 * §20 driven through the real panel.
 *
 * `hub_war_room.test.ts` proves the assembly decides correctly. It does not
 * prove anybody asks — and "war room" has been a recognised phrase since Phase
 * 2.1 while doing nothing but rearranging the plane it was already on.
 *
 * The assertion that distinguishes the two is how many panels exist after the
 * command on a plane that started empty.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => ({
    speak: vi.fn(),
    cancelSpeak: vi.fn(),
    startListening: vi.fn(),
    stopListening: vi.fn(),
    speaking: false,
    listening: false,
    sttSupported: false,
    transcript: '',
    status: null,
    spokenText: '',
    speechProgress: null,
  }),
}));

async function renderPresence() {
  const { PresencePanel } = await import('../components/ai/PresencePanel');
  return render(<PresencePanel ready providersReachable={1} />);
}

function say(phrase: string) {
  const input = screen.getByLabelText(/^ask$/i);
  fireEvent.change(input, { target: { value: phrase } });
  fireEvent.submit(input.closest('form')!);
}

function panelKeys(): string[] {
  return Array.from(document.querySelectorAll('[data-surface-id]'))
    .map((el) => el.querySelector('h3')?.textContent ?? '')
    .filter(Boolean);
}

/** Everything a war room can draw from, all reporting. */
async function seedEveryFeed() {
  const { useStore } = await import('../store');
  useStore.setState({
    wsStatus: 'connected',
    priceHistory: { 'XAU/USD': Array.from({ length: 60 }, (_, i) => 2000 + i) },
    positions: [{ symbol: 'XAUUSD', side: 'buy', size: 0.1, unrealized_pnl: 12.5 }],
    riskSnapshot: { daily_loss_limit: 1000, current_drawdown: 120 },
    newsItems: [
      { title: 'Gold steadies', published_at: '2026-09-07T09:00:00Z' },
      { title: 'Dollar softer', published_at: '2026-09-07T10:00:00Z' },
    ],
  } as never);
}

/** A deployment where nothing is connected. */
async function seedNothing() {
  const { useStore } = await import('../store');
  useStore.setState({
    wsStatus: 'connected',
    priceHistory: {},
    positions: [],
    riskSnapshot: null,
    newsItems: [],
  } as never);
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('§20 the war room opens panels', () => {
  it('assembles a plane that started empty', async () => {
    await seedEveryFeed();
    await renderPresence();
    expect(panelKeys()).toHaveLength(0);

    say('war room');
    // The assertion that fails on the pre-fix tree: `readLayout` returned
    // `war_room` and the plane stayed empty, because arranging nothing into a
    // war room arranges nothing.
    await waitFor(() => expect(panelKeys().length).toBeGreaterThan(2));
  });

  it('opens risk, which is the panel a war room exists for', async () => {
    await seedEveryFeed();
    await renderPresence();
    say('war room');
    await waitFor(() => expect(panelKeys().some((k) => /risk/i.test(k))).toBe(true));
  });

  it('says which panels it left out and why', async () => {
    // Only the risk feed reports. The rest must be named rather than quietly
    // absent — an operator who expected a news panel cannot otherwise tell
    // whether the feed is silent or the war room forgot.
    const { useStore } = await import('../store');
    await seedNothing();
    useStore.setState({ riskSnapshot: { daily_loss_limit: 1000, current_drawdown: 0 } } as never);
    await renderPresence();

    say('war room');
    await waitFor(() =>
      expect(screen.getByLabelText(/recent conversation/i).textContent).toMatch(/left out/i),
    );
  });

  it('refuses plainly when every feed is silent', async () => {
    await seedNothing();
    await renderPresence();

    say('war room');
    await waitFor(() =>
      expect(screen.getByLabelText(/recent conversation/i).textContent).toMatch(
        /no war room to open|nothing has any data/i,
      ),
    );
    // And it did not open a wall of empty panels to prove it tried.
    expect(panelKeys()).toHaveLength(0);
  });
});
