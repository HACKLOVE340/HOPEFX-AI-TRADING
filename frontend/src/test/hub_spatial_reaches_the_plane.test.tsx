/**
 * §9 driven through the real panel: breadcrumbs that go somewhere, a zoom that
 * changes the drawn series, and a position claim that is only made when it was
 * measured.
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

async function renderPresence() {
  const { useStore } = await import('../store');
  useStore.setState({
    wsStatus: 'connected',
    // A real series, so a zoom has something to slice.
    priceHistory: { 'XAU/USD': Array.from({ length: 100 }, (_, i) => 2000 + i) },
  } as never);
  const { PresencePanel } = await import('../components/ai/PresencePanel');
  return render(<PresencePanel ready providersReachable={1} />);
}

function say(phrase: string) {
  const input = screen.getByLabelText(/^ask$/i);
  fireEvent.change(input, { target: { value: phrase } });
  fireEvent.submit(input.closest('form')!);
}

/** Number of points in the gold chart's rendered polyline. */
function drawnPoints(): number {
  const line = document
    .querySelector('[data-surface-id] polyline')
    ?.getAttribute('points');
  return line ? line.trim().split(/\s+/).length : 0;
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('breadcrumbs go somewhere', () => {
  it('appears only once there is somewhere to go back to', async () => {
    // A trail of one is a label, not a breadcrumb.
    await renderPresence();
    expect(screen.queryByRole('navigation', { name: /breadcrumbs/i })).toBeNull();

    say('show me gold');
    await screen.findByRole('region', { name: /gold price/i });
    say('focus on the gold price');
    await waitFor(() => expect(screen.getByRole('navigation', { name: /breadcrumbs/i })).toBeTruthy());
  });

  it('takes you back to the plane', async () => {
    await renderPresence();
    say('show me gold');
    await screen.findByRole('region', { name: /gold price/i });
    say('focus on the gold price');
    await screen.findByRole('navigation', { name: /breadcrumbs/i });

    fireEvent.click(screen.getByRole('button', { name: 'Plane' }));
    await waitFor(() => expect(screen.queryByRole('navigation', { name: /breadcrumbs/i })).toBeNull());
  });

  it('drops a breadcrumb whose surface was closed', async () => {
    // A breadcrumb that navigates nowhere is worse than no breadcrumb.
    await renderPresence();
    say('show me gold');
    await screen.findByRole('region', { name: /gold price/i });
    say('focus on the gold price');
    await screen.findByRole('navigation', { name: /breadcrumbs/i });

    fireEvent.click(screen.getByRole('button', { name: /close gold price/i }));
    await waitFor(() => expect(screen.queryByRole('navigation', { name: /breadcrumbs/i })).toBeNull());
  });
});

describe('zooming into a region', () => {
  it('draws fewer points after a zoom', async () => {
    await renderPresence();
    say('show me gold');
    await screen.findByRole('region', { name: /gold price/i });
    const before = drawnPoints();
    expect(before).toBeGreaterThan(50);

    say('zoom in on the last 10 of the gold price');
    await waitFor(() => expect(drawnPoints()).toBeLessThan(before));
  });

  it('puts the range back on the way out', async () => {
    // A chart still showing a sliced range after you navigated out of that view
    // is a chart quietly lying about its range.
    await renderPresence();
    say('show me gold');
    await screen.findByRole('region', { name: /gold price/i });
    const full = drawnPoints();

    say('zoom in on the last 10 of the gold price');
    await waitFor(() => expect(drawnPoints()).toBeLessThan(full));

    say('back to the top');
    await waitFor(() => expect(drawnPoints()).toBe(full));
  });

  it('leaves the chart alone for an ordinary question', async () => {
    await renderPresence();
    say('show me gold');
    await screen.findByRole('region', { name: /gold price/i });
    const before = drawnPoints();

    say('what is the gold price');
    await waitFor(() => expect(drawnPoints()).toBe(before));
  });
});

describe('position is claimed only when measured', () => {
  it('says nothing about where panels are when nothing has a rect', async () => {
    // jsdom lays nothing out, so every `getBoundingClientRect` is zero. The AI
    // must describe the plane without inventing corners — pointing an operator
    // at the wrong part of their own screen is worse than not pointing.
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });

    say('what am I looking at');
    await waitFor(() => expect(screen.getByText(/3 surfaces/i)).toBeTruthy());
    expect(screen.queryByText(/top left|bottom right|the centre/i)).toBeNull();
  });
});
