/**
 * Pushed AI job progress — the private channel, and the merge that consumes it.
 *
 * Two things can silently make this a dead control, and both have a test here:
 *
 * 1. `ai_jobs` is PRIVATE on the server, so a connection that never names it in
 *    a `subscribe` receives nothing. The channel would exist, the server would
 *    publish, and the screen would poll forever.
 * 2. A pushed frame that overwrites a newer polled one reverts a finished job
 *    to `running`. `_reap` promotes a job to `timed_out` on a read path and
 *    pushes nothing at all, so the poll is sometimes the only source of truth.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { useStore } from '../store';

describe('the private channel is actually subscribed to', () => {
  it('names ai_jobs in every subscribe the client sends', () => {
    // Asserted against the real source rather than a re-implementation: the
    // failure this guards against is a channel missing from a literal list.
    const src = readFileSync(resolve(__dirname, '../hooks/useWebSocket.ts'), 'utf-8');
    const subscribes = src.match(/type: 'subscribe',[\s\S]*?\]/g) ?? [];
    expect(subscribes.length).toBeGreaterThan(0);
    for (const block of subscribes) {
      expect(block).toContain("'ai_jobs'");
    }
  });

  it('routes ai_job_update somewhere', () => {
    const src = readFileSync(resolve(__dirname, '../hooks/useWebSocket.ts'), 'utf-8');
    expect(src).toContain("case 'ai_job_update'");
    expect(src).toContain('upsertAiJob');
  });
});

describe('upsertAiJob orders frames', () => {
  beforeEach(() => {
    useStore.setState({ aiJobs: {} });
  });

  it('keeps the newer revision when a stale frame arrives late', () => {
    const { upsertAiJob } = useStore.getState();
    upsertAiJob({ id: 'j1', state: 'succeeded', rev: 5 });
    upsertAiJob({ id: 'j1', state: 'running', rev: 3 });
    expect(useStore.getState().aiJobs['j1']?.state).toBe('succeeded');
  });

  it('applies a newer frame', () => {
    const { upsertAiJob } = useStore.getState();
    upsertAiJob({ id: 'j1', state: 'running', rev: 3 });
    upsertAiJob({ id: 'j1', state: 'succeeded', rev: 4 });
    expect(useStore.getState().aiJobs['j1']?.state).toBe('succeeded');
  });
});

describe('the workbench prefers whichever of push and poll is newer', () => {
  beforeEach(() => {
    useStore.setState({ aiJobs: {} });
  });

  const polled = (state: string, rev: number) => ({
    jobs: [{
      id: 'j1', prompt: 'what is the gold regime', state,
      result: null, error: '', progress: [], elapsed_s: 1, rev,
    }],
    running: state === 'running' ? 1 : 0,
    queued: 0,
    max_concurrent: 4,
    max_queued: 16,
  });

  async function renderWith(snapshot: unknown) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['ai-core', 'generate-jobs'], snapshot);
    const { GenerationWorkbench } = await import('../components/ai/GenerationWorkbench');
    render(
      <QueryClientProvider client={qc}>
        <GenerationWorkbench />
      </QueryClientProvider>,
    );
  }

  it('shows the pushed state when the push is ahead of the poll', async () => {
    useStore.getState().upsertAiJob({ id: 'j1', state: 'succeeded', rev: 9 });
    await renderWith(polled('running', 4));
    expect(await screen.findByText('Done')).toBeTruthy();
  });

  it('shows the polled state when the poll is ahead — a reaped timeout pushes nothing', async () => {
    useStore.getState().upsertAiJob({ id: 'j1', state: 'running', rev: 4 });
    await renderWith(polled('timed_out', 9));
    expect(await screen.findByText('Passed its deadline')).toBeTruthy();
  });
});
