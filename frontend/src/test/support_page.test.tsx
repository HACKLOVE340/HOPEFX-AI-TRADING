/**
 * The customer's support page — what it must never let a customer believe.
 *
 * The mirror of the operator console, and the differences are the point.
 *
 *  1. **A customer must be able to tell who answered.** An AI reply is
 *     labelled as one. On a trading platform, letting a machine's answer pass
 *     as a person's is an honesty problem before it is a regulatory one.
 *  2. **An escalated ticket says a person is coming.** Not silence, and not a
 *     fake "the assistant is typing" — the floor removed the AI from this
 *     conversation on purpose.
 *  3. **The triage internals never appear.** The customer surface omits
 *     `matched_on`, `escalation_reason` and `assigned_operator_id` server-side;
 *     the page must not reintroduce them from anywhere else.
 *  4. **Absence is a state.** No tickets, loading, and a failed request are
 *     three different renders — an error must never read as "you have no
 *     tickets", which would send a customer away believing they never wrote in.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

/** What the SERVER sends a customer — no matched_on, no escalation_reason. */
const escalated = {
  id: 't-1', user_id: 'me', subject: 'Withdrawal has not arrived',
  status: 'awaiting_operator', category: 'account_or_money', department: null,
  needs_human: true, created_at: '2026-09-10T04:00:00Z',
  updated_at: '2026-09-10T04:00:00Z', first_response_at: null, resolved_at: null,
};
const answered = {
  ...escalated, id: 't-2', subject: 'What does the drift chip mean?',
  status: 'open', category: 'account_settings', department: 'platform_engineering',
  needs_human: false, first_response_at: '2026-09-10T04:01:00Z',
};

// Hoisted for the same reason as the console suite: a `vi.mock` factory is
// lifted above the imports and can only reach hoisted values.
const supportApi = vi.hoisted(() => ({
  myTickets: vi.fn(), myThread: vi.fn(), open: vi.fn(), say: vi.fn(),
}));
vi.mock('../hooks/useApi', () => ({ supportApi }));

async function mount() {
  const { default: Support } = await import('../pages/Support');
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Support /></MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  supportApi.myTickets.mockResolvedValue({ data: { tickets: [escalated, answered] } });
  supportApi.myThread.mockResolvedValue({
    data: {
      ticket: answered,
      messages: [
        { author_kind: 'customer', author_id: 'me', body: 'What is the amber chip?', created_at: '2026-09-10T04:00:00Z' },
        { author_kind: 'ai', author_id: 'platform_engineering', body: 'It means the live feature distribution has moved.', created_at: '2026-09-10T04:01:00Z' },
      ],
    },
  });
});

describe('a customer can tell who answered', () => {
  it('labels an AI reply as the AI', async () => {
    await mount();
    fireEvent.click(await screen.findByTestId('mine-t-2'));
    const ai = await screen.findByTestId('msg-1');
    expect(ai.textContent).toMatch(/\bAI\b|assistant/i);
  });

  it('does not label a human reply as the AI', async () => {
    supportApi.myThread.mockResolvedValue({
      data: { ticket: escalated, messages: [
        { author_kind: 'operator', author_id: 'ops-1', body: 'Looking into it now.', created_at: '2026-09-10T04:05:00Z' },
      ] },
    });
    await mount();
    fireEvent.click(await screen.findByTestId('mine-t-1'));
    const msg = await screen.findByTestId('msg-0');
    expect(msg.textContent).not.toMatch(/\bAI\b/);
  });

  it('a system note is not presented as a person either', async () => {
    supportApi.myThread.mockResolvedValue({
      data: { ticket: escalated, messages: [
        { author_kind: 'system', author_id: null, body: 'Passed to the support team.', created_at: '2026-09-10T04:00:00Z' },
      ] },
    });
    await mount();
    fireEvent.click(await screen.findByTestId('mine-t-1'));
    expect((await screen.findByTestId('msg-0')).textContent).toMatch(/automatic|system/i);
  });
});

describe('an escalated ticket says a person is coming', () => {
  it('says so on the thread', async () => {
    supportApi.myThread.mockResolvedValue({ data: { ticket: escalated, messages: [] } });
    await mount();
    fireEvent.click(await screen.findByTestId('mine-t-1'));
    expect(await screen.findByTestId('human-coming')).toBeTruthy();
  });

  it('does not say it on a ticket the AI is handling', async () => {
    await mount();
    fireEvent.click(await screen.findByTestId('mine-t-2'));
    await waitFor(() => expect(screen.getByTestId('thread-subject')).toBeTruthy());
    expect(screen.queryByTestId('human-coming')).toBeNull();
  });
});

describe('the triage internals never reach the page', () => {
  it('renders nothing from a leaked field if the server ever sends one', async () => {
    supportApi.myThread.mockResolvedValue({
      data: {
        ticket: {
          ...escalated,
          matched_on: 'withdraw',
          escalation_reason: 'This platform is not licensed to give financial advice.',
          assigned_operator_id: 'ops-ren',
        },
        messages: [],
      },
    });
    const { container } = await mount();
    fireEvent.click(await screen.findByTestId('mine-t-1'));
    await waitFor(() => expect(screen.getByTestId('thread-subject')).toBeTruthy());
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/withdraw'|not licensed|ops-ren/);
  });
});

describe('absence is a state', () => {
  it('no tickets reads as a starting point, not a void', async () => {
    supportApi.myTickets.mockResolvedValue({ data: { tickets: [] } });
    await mount();
    expect(await screen.findByTestId('no-tickets')).toBeTruthy();
  });

  it('a failed list says so and never reads as "you have no tickets"', async () => {
    supportApi.myTickets.mockRejectedValue(new Error('offline'));
    await mount();
    expect(await screen.findByTestId('list-error')).toBeTruthy();
    expect(screen.queryByTestId('no-tickets')).toBeNull();
  });
});

describe('raising a ticket', () => {
  it('refuses an empty body before it reaches the server', async () => {
    /**
     * Asserted through a POSITIVE observation first.
     *
     * The original was `await waitFor(() => expect(open).not.toHaveBeenCalled())`,
     * which resolves on its first tick — before React Query has invoked the
     * mutation at all — so it passed against a build with the guard deleted.
     * A "nothing happened" assertion with no barrier in front of it proves
     * only that nothing had happened *yet*.
     *
     * Waiting for the refusal message gives the render loop time to have made
     * the call, so the absence that follows is a measured absence.
     */
    await mount();
    fireEvent.click(await screen.findByTestId('new-ticket'));
    fireEvent.click(await screen.findByTestId('submit-ticket'));

    expect((await screen.findByTestId('compose-error')).textContent).toMatch(/subject/i);
    expect(supportApi.open).not.toHaveBeenCalled();
  });

  it('refuses a subject with no body', async () => {
    await mount();
    fireEvent.click(await screen.findByTestId('new-ticket'));
    fireEvent.change(await screen.findByTestId('subject-input'), { target: { value: 'Login help' } });
    fireEvent.click(await screen.findByTestId('submit-ticket'));

    expect(await screen.findByTestId('compose-error')).toBeTruthy();
    expect(supportApi.open).not.toHaveBeenCalled();
  });

  it('refuses whitespace that looks like content', async () => {
    await mount();
    fireEvent.click(await screen.findByTestId('new-ticket'));
    fireEvent.change(await screen.findByTestId('subject-input'), { target: { value: '   ' } });
    fireEvent.change(await screen.findByTestId('body-input'), { target: { value: '  \n ' } });
    fireEvent.click(await screen.findByTestId('submit-ticket'));

    expect(await screen.findByTestId('compose-error')).toBeTruthy();
    expect(supportApi.open).not.toHaveBeenCalled();
  });

  it('sends subject and body when both are given', async () => {
    supportApi.open.mockResolvedValue({ data: { id: 't-3', needs_human: false, ai_reply: 'Here you go.' } });
    await mount();
    fireEvent.click(await screen.findByTestId('new-ticket'));
    fireEvent.change(await screen.findByTestId('subject-input'), { target: { value: 'Login help' } });
    fireEvent.change(await screen.findByTestId('body-input'), { target: { value: 'I cannot sign in.' } });
    fireEvent.click(await screen.findByTestId('submit-ticket'));
    await waitFor(() => expect(supportApi.open).toHaveBeenCalledWith('Login help', 'I cannot sign in.'));
  });

  it('a refused submission reports the server’s reason', async () => {
    supportApi.open.mockRejectedValue({ response: { data: { detail: 'Message body cannot be empty.' } } });
    await mount();
    fireEvent.click(await screen.findByTestId('new-ticket'));
    fireEvent.change(await screen.findByTestId('subject-input'), { target: { value: 'x' } });
    fireEvent.change(await screen.findByTestId('body-input'), { target: { value: 'y' } });
    fireEvent.click(await screen.findByTestId('submit-ticket'));
    expect((await screen.findByTestId('compose-error')).textContent).toMatch(/cannot be empty/);
  });
});
