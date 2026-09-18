/**
 * §7's projection commands driven through the real panel.
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
  useStore.setState({ wsStatus: 'connected', feedStale: false, riskSnapshot: null, positions: [] } as never);
  const { PresencePanel } = await import('../components/ai/PresencePanel');
  return render(<PresencePanel ready providersReachable={1} />);
}

function say(phrase: string) {
  const input = screen.getByLabelText(/^ask$/i);
  fireEvent.change(input, { target: { value: phrase } });
  fireEvent.submit(input.closest('form')!);
}

function coreSize(): number {
  const canvas = document.querySelector('canvas');
  return canvas ? Number.parseFloat(canvas.style.width || '0') : 0;
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('minimising the presence', () => {
  it('makes it smaller', async () => {
    await renderPresence();
    const before = coreSize();
    expect(before).toBeGreaterThan(0);

    say('get out of the way');
    await waitFor(() => expect(coreSize()).toBeLessThan(before));
  });

  it('never removes it entirely', async () => {
    // The presence is where the alert state lives. One that can be dismissed
    // is one an operator can lose, along with the only thing on screen that
    // says the kill switch tripped.
    await renderPresence();
    say('minimise');
    await waitFor(() => expect(coreSize()).toBeGreaterThan(0));
    expect(screen.getByRole('region', { name: 'Presence core' })).toBeTruthy();
  });

  it('comes back', async () => {
    await renderPresence();
    const before = coreSize();
    say('minimise');
    await waitFor(() => expect(coreSize()).toBeLessThan(before));
    say('come back to full size');
    await waitFor(() => expect(coreSize()).toBe(before));
  });
});

describe('splitting', () => {
  it('says it stayed as one when there is nothing to split across', async () => {
    // Rather than silently doing nothing, which reads as the command failing.
    await renderPresence();
    say('split yourself');
    await waitFor(() => expect(screen.getByText(/stayed as one/i)).toBeTruthy());
  });

  it('splits across the surfaces on the plane', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });
    say('split yourself');
    await waitFor(() => expect(screen.getByText(/split into 3/i)).toBeTruthy());
  });

  it('merges back to one', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });
    say('split yourself');
    await waitFor(() => expect(screen.getByText(/split into 3/i)).toBeTruthy());
    say('just one of you please');
    await waitFor(() => expect(screen.getByText(/one of me again/i)).toBeTruthy());
  });
});

describe('a projection command is not also a surface command', () => {
  it('does not open panels for the words inside it', async () => {
    await renderPresence();
    say('move to the left');
    await waitFor(() => expect(screen.getByText(/moved to the left/i)).toBeTruthy());
    expect(screen.queryByRole('region', { name: /gold price/i })).toBeNull();
  });
});
