/**
 * A panel shows the answer as it arrives.
 *
 * The whole streaming chain — scanner, adapters, gateway, job runner, private
 * channel — is dead weight if the panel still renders nothing until the job
 * reaches `succeeded`. This is the end of that chain, tested at the end.
 *
 * Two things it must not do:
 *
 * - Render the streamed text as part of the STATUS LIST. `progress` is a list
 *   of notes ("contacting the model"); an answer rendered there reads as a
 *   sequence of bullet points.
 * - Keep showing the partial after the job finished. The finished `result` is
 *   the answer of record — it is what a reload shows, and what carries the
 *   vendor, cost and cached flag.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useStore } from '../store';

function snapshot(job: Record<string, unknown>) {
  return {
    jobs: [{
      id: 'j1', prompt: 'what is the gold regime', state: 'running',
      result: null, error: '', progress: [], elapsed_s: 2, rev: 1, partial: '',
      ...job,
    }],
    running: 1, queued: 0, max_concurrent: 4, max_queued: 16,
  };
}

async function renderWith(data: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(['ai-core', 'generate-jobs'], data);
  const { GenerationWorkbench } = await import('../components/ai/GenerationWorkbench');
  render(
    <QueryClientProvider client={qc}>
      <GenerationWorkbench />
    </QueryClientProvider>,
  );
}

describe('a running panel shows the answer so far', () => {
  beforeEach(() => useStore.setState({ aiJobs: {} }));

  it('renders the partial answer while the job is still running', async () => {
    await renderWith(snapshot({ partial: 'Gold is consolidating between 2380 and 2405.' }));
    expect(await screen.findByText(/Gold is consolidating between 2380 and 2405\./)).toBeTruthy();
  });

  it('does not render the partial answer as a status note', async () => {
    await renderWith(snapshot({
      partial: 'Gold is consolidating.',
      progress: ['contacting the model'],
    }));
    const answer = await screen.findByText(/Gold is consolidating\./);
    expect(answer.closest('ol')).toBeNull();
  });

  it('marks the streaming region busy for assistive technology', async () => {
    await renderWith(snapshot({ partial: 'Gold is' }));
    const region = await screen.findByLabelText(/answer so far/i);
    expect(region.getAttribute('aria-busy')).toBe('true');
  });

  it('shows nothing extra before the first token arrives', async () => {
    await renderWith(snapshot({ partial: '' }));
    expect(screen.queryByLabelText(/answer so far/i)).toBeNull();
  });

  it('replaces the partial with the finished result once the job succeeds', async () => {
    await renderWith(snapshot({
      state: 'succeeded',
      partial: 'Gold is consol',
      result: { text: 'Gold is consolidating between 2380 and 2405.', provider: 'anthropic', cost_usd: 0.004 },
      elapsed_s: 4,
    }));
    expect(await screen.findByText('Gold is consolidating between 2380 and 2405.')).toBeTruthy();
    expect(screen.queryByLabelText(/answer so far/i)).toBeNull();
  });

  it('still shows what arrived when a stream fails part-way', async () => {
    // A vendor that dies mid-stream cannot be continued by another — the
    // gateway refuses to splice two opinions — so the half-answer the operator
    // already read is all there is. Hiding it would leave them with an error
    // and no idea what the model had said.
    await renderWith(snapshot({
      state: 'failed',
      partial: 'Gold is consolidating and',
      error: 'ProviderError: connection_error',
    }));
    expect(await screen.findByText(/Gold is consolidating and/)).toBeTruthy();
    expect(await screen.findByText(/connection_error/)).toBeTruthy();
  });
});
