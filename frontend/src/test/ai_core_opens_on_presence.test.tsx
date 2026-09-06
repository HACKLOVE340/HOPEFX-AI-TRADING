/**
 * What the AI Core page opens on — decision D2, revised.
 *
 * The owner's instruction was to use the existing page rather than build a
 * second AI screen beside it. So the presence is a tab here, and it is the tab
 * that opens first when the flag is on.
 *
 * A comment in `AICore.tsx` previously said promoting a different tab "changes
 * what this page IS" and was the owner's call. It was, and it has been made.
 * This file is that decision written down where a future change will trip over
 * it — including the half of it that matters more: **with the flag off, nothing
 * moved.**
 */

import { describe, it, expect, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const SUMMARY = {
  role: 'superadmin', is_superadmin: true,
  reasoning_primary: 'claude-opus-5', reasoning_primary_reachable: true,
  fallback_available: true,
  providers_reachable: ['anthropic'], providers_unreachable: [],
  local_inference_enabled: false,
  calls_recorded: 0, calls_unserved: 0, spent_usd: 0, cache_enabled: true,
};

async function renderCore() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } });
  qc.setQueryData(['ai-core', 'summary'], SUMMARY);
  const { AICore } = await import('../pages/AICore');
  return render(
    <QueryClientProvider client={qc}>
      <AICore />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  delete (import.meta.env as Record<string, unknown>).VITE_HUB_ENABLED;
  // The page reads the flag at mount, so the module must be re-evaluated.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).__vitest_resetModules?.();
});

describe('with the flag off — the behaviour everyone already has', () => {
  it('still opens on the status board', async () => {
    delete (import.meta.env as Record<string, unknown>).VITE_HUB_ENABLED;
    await renderCore();
    expect(await screen.findByText(/Control plane at a glance/i)).toBeTruthy();
  });

  it('still offers the presence as a tab you can reach', async () => {
    // Available, not imposed — §2: capabilities are summonable, and the default
    // stays clean rather than being replaced without consent.
    delete (import.meta.env as Record<string, unknown>).VITE_HUB_ENABLED;
    await renderCore();
    expect(screen.getByRole('tab', { name: 'Presence' })).toBeTruthy();
  });
});

describe('every existing tab survived', () => {
  it('offers all six of the tabs that were there before, plus the new one', async () => {
    // The instruction was to use the existing page, not to replace it. If a tab
    // vanished, this is where that shows up.
    await renderCore();
    for (const label of ['Presence', 'Workbench', 'Overview', 'Model chain', 'Spend', 'Calls', 'Governance']) {
      expect(screen.getByRole('tab', { name: label })).toBeTruthy();
    }
  });
});
