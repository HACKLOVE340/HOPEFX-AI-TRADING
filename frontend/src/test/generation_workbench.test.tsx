/**
 * The workbench must show several generations at once, and be honest about each.
 *
 * Owner requirement, 2026-09-06: the AI screen generates multiple things
 * simultaneously, stays interactive, and communicates well. The backend runs
 * them concurrently; these cover the half an operator actually looks at.
 *
 * The rules being asserted are the page's own, applied to a live surface:
 *
 *  * Absence is a state, not a blank — a queued job explains it is waiting.
 *  * A failure never renders as a healthy value — a failed panel says so where
 *    it sits, while its succeeding neighbour still shows its answer.
 *  * Colour is never the only signal — every state carries a word.
 *  * Backpressure is not an outage — a full queue reads as "try again", not
 *    "the server broke".
 */
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { GenerationWorkbench } from '../components/ai/GenerationWorkbench';
import { aiCoreApi } from '../hooks/useApi';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderWorkbench() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GenerationWorkbench />
    </QueryClientProvider>,
  );
}

const job = (over: Record<string, unknown> = {}) => ({
  id: 'j1',
  prompt: 'what is the drawdown?',
  state: 'running',
  result: null,
  error: '',
  progress: [],
  elapsed_s: 0,
  ...over,
});

function snapshot(jobs: unknown[], over: Record<string, unknown> = {}) {
  return {
    data: { jobs, running: 0, queued: 0, max_concurrent: 4, max_queued: 16, ...over },
  } as never;
}

describe('GenerationWorkbench', () => {
  it('renders several jobs at the same time, each with its own state', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot(
        [
          job({ id: 'a', prompt: 'first question', state: 'running' }),
          job({ id: 'b', prompt: 'second question', state: 'queued' }),
          job({
            id: 'c',
            prompt: 'third question',
            state: 'succeeded',
            result: { text: 'the answer', provider: 'anthropic', cost_usd: 0.004 },
          }),
        ],
        { running: 1, queued: 1 },
      ),
    );

    renderWorkbench();

    await waitFor(() => expect(screen.getByText('first question')).toBeTruthy());
    expect(screen.getByText('second question')).toBeTruthy();
    expect(screen.getByText('third question')).toBeTruthy();
    // Three panels, three different states, all visible together. Matched by
    // exact text: /generating/i alone also hits the "Start generating" button.
    expect(screen.getByText('Generating')).toBeTruthy();
    expect(screen.getByText('Waiting for a slot')).toBeTruthy();
    expect(screen.getByText('Done')).toBeTruthy();
  });

  it('shows how many are running against the ceiling', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot([job({ state: 'running' })], { running: 2, queued: 3, max_concurrent: 4 }),
    );

    renderWorkbench();
    // Six submitted against a ceiling of four should look deliberate, not broken.
    await waitFor(() => expect(screen.getByText(/2 of 4 running/i)).toBeTruthy());
    expect(screen.getByText(/3 waiting/i)).toBeTruthy();
  });

  it('states why a job is queued rather than leaving the panel blank', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot([job({ state: 'queued' })], { queued: 1 }),
    );

    renderWorkbench();
    await waitFor(() => expect(screen.getByText(/starts as soon as one frees up/i)).toBeTruthy());
  });

  it('shows progress while a job runs, not just a spinner', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot([job({ state: 'running', progress: ['resolving the model chain', 'contacting the model'] })], {
        running: 1,
      }),
    );

    renderWorkbench();
    await waitFor(() => expect(screen.getByText('contacting the model')).toBeTruthy());
    expect(screen.getByText('resolving the model chain')).toBeTruthy();
  });

  it('a failed panel says so without its neighbour implying it worked', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot([
        job({ id: 'bad', prompt: 'the failed one', state: 'failed', error: 'RuntimeError: connection reset' }),
        job({
          id: 'good',
          prompt: 'the good one',
          state: 'succeeded',
          result: { text: 'a real answer', provider: 'anthropic', cost_usd: 0.01 },
        }),
      ]),
    );

    renderWorkbench();

    await waitFor(() => expect(screen.getByText(/connection reset/i)).toBeTruthy());
    expect(screen.getByText('a real answer')).toBeTruthy();
    // The failure is announced, not merely coloured.
    expect(screen.getAllByRole('alert').length).toBeGreaterThan(0);
  });

  it('distinguishes a deadline from a failure', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot([job({ state: 'timed_out', error: 'exceeded its 120s deadline' })]),
    );

    renderWorkbench();
    // The operator's next move differs: retry a failure, simplify a timeout.
    await waitFor(() => expect(screen.getByText(/passed its deadline/i)).toBeTruthy());
  });

  it('shows what each answer cost, per panel', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot([
        job({ state: 'succeeded', result: { text: 'answer', provider: 'anthropic', cost_usd: 0.0123 } }),
      ]),
    );

    renderWorkbench();
    // Four panels is four times the spend; that should be visible while
    // deciding whether to start a fifth.
    await waitFor(() => expect(screen.getByText(/\$0\.0123/)).toBeTruthy());
  });

  it('submits a generation and clears the box for the next one', async () => {
    const user = userEvent.setup();
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(snapshot([]));
    const post = vi.spyOn(aiCoreApi, 'generate').mockResolvedValue({
      data: { job_id: 'new', state: 'queued' },
    } as never);

    renderWorkbench();

    const box = await screen.findByLabelText(/what should it work on/i);
    await user.type(box, 'analyse the regime');
    await user.click(screen.getByRole('button', { name: /start generating/i }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    // Cleared, so a second generation can be started immediately alongside it.
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe(''));
  });

  it('will not submit an empty prompt', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(snapshot([]));
    const post = vi.spyOn(aiCoreApi, 'generate');

    renderWorkbench();
    const button = await screen.findByRole('button', { name: /start generating/i });

    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(post).not.toHaveBeenCalled();
  });

  it('reads a full queue as backpressure, not as an outage', async () => {
    const user = userEvent.setup();
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(snapshot([]));
    vi.spyOn(aiCoreApi, 'generate').mockRejectedValue({ response: { status: 429 } });

    renderWorkbench();

    await user.type(await screen.findByLabelText(/what should it work on/i), 'one too many');
    await user.click(screen.getByRole('button', { name: /start generating/i }));

    await waitFor(() => {
      const alert = screen.getByRole('alert');
      expect(alert.textContent ?? '').toMatch(/let some finish/i);
      expect(alert.textContent ?? '').not.toMatch(/error|failed/i);
    });
  });

  it('offers a stop control only on live jobs', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot([
        job({ id: 'live', prompt: 'live one', state: 'running' }),
        job({ id: 'done', prompt: 'done one', state: 'succeeded', result: { text: 'x' } }),
      ]),
    );

    renderWorkbench();

    await waitFor(() => expect(screen.getByText('live one')).toBeTruthy());
    // A control that would do nothing is worse than no control.
    expect(screen.getAllByRole('button', { name: /stop this one/i })).toHaveLength(1);
  });

  it('cancels one panel without touching the others', async () => {
    const user = userEvent.setup();
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(
      snapshot([
        job({ id: 'a', prompt: 'first', state: 'running' }),
        job({ id: 'b', prompt: 'second', state: 'running' }),
      ]),
    );
    const cancel = vi.spyOn(aiCoreApi, 'cancelGenerate').mockResolvedValue({ data: {} } as never);

    renderWorkbench();

    await waitFor(() => expect(screen.getByText('first')).toBeTruthy());
    const firstPanel = screen.getByText('first').closest('article') as HTMLElement;
    await user.click(within(firstPanel).getByRole('button', { name: /stop this one/i }));

    await waitFor(() => expect(cancel).toHaveBeenCalledWith('a'));
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it('says plainly when nothing is running', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockResolvedValue(snapshot([]));

    renderWorkbench();
    await waitFor(() => expect(screen.getByText(/nothing running yet/i)).toBeTruthy());
  });

  it('does not present stale panels as current when the list fails to load', async () => {
    vi.spyOn(aiCoreApi, 'generateJobs').mockRejectedValue(new Error('network is gone'));

    renderWorkbench();
    await waitFor(() => expect(screen.getByText(/may be out of date/i)).toBeTruthy());
  });
});
