/**
 * §10 driven through the real panel: the summary is spoken, and the background
 * really folds into a stack on screen.
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
  useStore.setState({ wsStatus: 'connected' });
  const { PresencePanel } = await import('../components/ai/PresencePanel');
  return render(<PresencePanel ready providersReachable={1} />);
}

function say(phrase: string) {
  const input = screen.getByLabelText(/^ask$/i);
  fireEvent.change(input, { target: { value: phrase } });
  fireEvent.submit(input.closest('form')!);
}

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, 'innerWidth', { value: 1600, configurable: true, writable: true });
});

describe('summarising what is on the plane', () => {
  it('names the relationship between two connected panels', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    await screen.findByRole('region', { name: /gold price/i });

    say('how do these relate');
    await waitFor(() => expect(screen.getByText(/are connected/i)).toBeTruthy());
  });

  it('says the plane is empty rather than summarising nothing', async () => {
    await renderPresence();
    say('what am I looking at');
    await waitFor(() => expect(screen.getByText(/plane is empty/i)).toBeTruthy());
  });

  it('does not also run the phrase as a surface command', async () => {
    // "Explain this" contains no subject, but a reader that ran both would
    // still be free to open something. Nothing should appear.
    await renderPresence();
    say('summarise this');
    await waitFor(() => expect(screen.getByText(/plane is empty/i)).toBeTruthy());
    expect(screen.queryByRole('region', { name: /gold price/i })).toBeNull();
  });
});

describe('the background stack', () => {
  it('folds quiet surfaces into a stack once the plane is crowded', async () => {
    await renderPresence();
    say('show me everything affecting gold');
    say('show me risk');
    say('show me positions');
    say('show me the log');
    await screen.findByRole('region', { name: /gold price/i });

    // Six surfaces, one of them background-tier (`calls`). Five is not
    // crowded — §10 is about cognitive load, not a hard limit.
    await waitFor(() => expect(screen.getByLabelText(/collapsed background surfaces/i)).toBeTruthy());
    const stack = screen.getByLabelText(/collapsed background surfaces/i);
    expect(stack.textContent).toMatch(/recent model calls/i);
  });

  it('names each collapsed surface so it can be brought back', async () => {
    // A collapsed panel the operator cannot see the name of is one they cannot
    // get back — which is the difference between collapsed and hidden.
    await renderPresence();
    say('show me everything affecting gold');
    say('show me risk');
    say('show me positions');
    say('show me the log');
    await screen.findByLabelText(/collapsed background surfaces/i);

    const chip = screen.getByRole('button', { name: /recent model calls/i });
    fireEvent.click(chip);
    // Pinning takes it out of the stack and back onto the plane.
    await waitFor(() => expect(screen.getByRole('region', { name: /recent model calls/i })).toBeTruthy());
  });
});
