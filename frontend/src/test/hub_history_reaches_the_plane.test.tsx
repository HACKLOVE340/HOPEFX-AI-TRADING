/**
 * §8's own example, driven through the real command box.
 *
 * `hub/history.ts` has twenty-eight unit tests and would pass all of them while
 * "bring back yesterday's workspace" still fell through to the model fallback
 * and got a refusal. The module is not the feature; the wiring is.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => ({
    speak: vi.fn(), cancelSpeak: vi.fn(), startListening: vi.fn(), stopListening: vi.fn(),
    speaking: false, listening: false, sttSupported: false, transcript: '', status: null,
  }),
}));

const KEY = 'hopefx.hub.workspaces.v1';
const DAY = 86_400_000;

async function renderPresence() {
  const { useStore } = await import('../store');
  useStore.setState({ wsStatus: 'connected' });
  const { PresencePanel } = await import('../components/ai/PresencePanel');
  return render(<PresencePanel ready providersReachable={1} />);
}

function say(phrase: string) {
  const input = screen.getByLabelText(/^ask$/i);
  fireEvent.change(input, { target: { value: phrase } });
  fireEvent.submit(input.closest('form')!);
}

/** Put a snapshot in storage as if it had been taken N days ago. */
function seed(daysAgo: number, name: string) {
  const noon = new Date();
  noon.setHours(12, 0, 0, 0);
  localStorage.setItem(
    KEY,
    JSON.stringify([
      {
        id: 'seeded',
        name,
        at: noon.getTime() - daysAgo * DAY,
        layout: 'compare',
        auto: false,
        surfaces: [
          { kind: 'chart', intent: 'Gold price', priority: 'primary', key: 'gold-chart' },
          { kind: 'table', intent: 'Risk limits and headroom', priority: 'critical', key: 'risk' },
        ],
      },
    ]),
  );
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe("bring back yesterday's workspace", () => {
  it('rebuilds the plane from a snapshot taken yesterday', async () => {
    seed(1, 'monday');
    await renderPresence();
    say("bring back yesterday's workspace");

    await screen.findByRole('region', { name: /gold price/i });
    expect(screen.getByRole('region', { name: /risk limits/i })).toBeTruthy();
  });

  it('says there is nothing rather than restoring something else', async () => {
    // The defect: restoring the newest snapshot is one line shorter and
    // silently answers a different question. The operator cannot tell.
    seed(9, 'last week');
    await renderPresence();
    say("bring back yesterday's workspace");

    await waitFor(() => expect(screen.getByText(/no workspace saved from yesterday/i)).toBeTruthy());
    expect(screen.queryByRole('region', { name: /gold price/i })).toBeNull();
  });

  it('restores the arrangement that was saved with it, not the current one', async () => {
    seed(1, 'monday');
    await renderPresence();
    say("bring back yesterday's workspace");
    await screen.findByRole('region', { name: /gold price/i });
    // Seeded as `compare`, so both surfaces get equal width even though one is
    // critical and one is primary.
    await waitFor(() => expect(screen.getByText(/compare · 2 on the plane/i)).toBeTruthy());
  });
});

describe('naming and reopening an arrangement', () => {
  it('saves what is on the plane and brings it back', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });

    say('save this as risk review');
    await waitFor(() => expect(screen.getByText(/saved as/i)).toBeTruthy());

    say('simplify this');
    await waitFor(() => expect(screen.queryByRole('region', { name: /gold price/i })).toBeNull());

    say('bring back risk review');
    await screen.findByRole('region', { name: /gold price/i });
  });

  it('says so when the name is not one it has', async () => {
    await renderPresence();
    say('bring back the tuesday review');
    await waitFor(() => expect(screen.getByText(/no workspace called/i)).toBeTruthy());
  });

  it('will not save an empty plane', async () => {
    await renderPresence();
    say('save this as nothing at all');
    await waitFor(() => expect(screen.getByText(/nothing on the plane to save/i)).toBeTruthy());
  });
});

describe('a history phrase does not also run as a surface command', () => {
  it('does not open panels for the words inside it', async () => {
    // "restore the risk review" contains "risk". Running both readers would
    // open the risk table AND fail the restore, which reads as a bug in both.
    await renderPresence();
    say('bring back the risk review');
    await waitFor(() => expect(screen.getByText(/no workspace called/i)).toBeTruthy());
    expect(screen.queryByRole('region', { name: /risk limits/i })).toBeNull();
  });
});

describe('degrading on a small device', () => {
  it('holds fewer surfaces on a phone than on a desktop', async () => {
    Object.defineProperty(window, 'innerWidth', { value: 375, configurable: true, writable: true });
    await renderPresence();
    say('show me everything affecting gold');
    say('show me risk');
    say('show me the news');
    say('show me positions');
    say('show me spend');
    await screen.findByRole('region', { name: /gold price/i });

    // capacityFor(375) is 4. Every surface is full width at this size, so a
    // twelve-deep plane would be a twelve-screen scroll.
    await waitFor(() => {
      const panels = screen
        .getAllByRole('region')
        .filter((el) => !['AI presence', 'Presence core'].includes(el.getAttribute('aria-label') ?? ''));
      expect(panels.length).toBeLessThanOrEqual(4);
      expect(panels.length).toBeGreaterThan(0);
    });
  });
});
