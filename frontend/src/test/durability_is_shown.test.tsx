/**
 * The AI Core header says whether the AI's state actually survives a restart.
 *
 * The backend now reports it, and a JSON field nobody renders is the same
 * defect as the accessors that reported it to nobody: `store_is_shared()`,
 * `durable_sink_installed()` and the eval store's equivalent were each
 * described as what "the health surface reads back", and no health surface
 * read any of them.
 *
 * The distinction matters because all three fail in the same silent direction.
 * A per-process spend ceiling still refuses calls; it just does it with each
 * worker holding its own full allowance, and resets to zero on every deploy.
 * Nothing about the running system looks wrong.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const BASE = {
  role: 'superadmin', is_superadmin: true,
  reasoning_primary: 'claude-opus-5', reasoning_primary_reachable: true,
  fallback_available: true,
  providers_reachable: ['anthropic'], providers_unreachable: [],
  local_inference_enabled: false,
  calls_recorded: 3, calls_unserved: 0, spent_usd: 0.12, cache_enabled: true,
};

async function renderWith(durability: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(['ai-core', 'summary'], { ...BASE, durability });
  const { AICore } = await import('../pages/AICore');
  return render(
    <QueryClientProvider client={qc}>
      <AICore />
    </QueryClientProvider>,
  );
}

describe('durability is visible', () => {
  it('says so plainly when nothing is shared', async () => {
    await renderWith({
      budget_shared: false, audit_durable: false,
      eval_report_shared: false, eval_schedule_hours: null,
    });
    // The wording has to name the consequence, not the setting: "not shared"
    // tells an operator nothing they can act on.
    expect(await screen.findByText(/resets on restart|per-process|lost on restart/i)).toBeTruthy();
  });

  it('says so when everything is shared', async () => {
    await renderWith({
      budget_shared: true, audit_durable: true,
      eval_report_shared: true, eval_schedule_hours: 12,
    });
    expect(await screen.findByText(/survives a restart|shared across workers/i)).toBeTruthy();
  });

  it('reports the eval schedule being off without calling it a fault', async () => {
    // Off is the default and a legitimate choice — every eval case is a paid
    // model call. Rendering it in red would push an operator to switch on a
    // recurring bill just to clear a warning.
    //
    // Asserted on the rendered text and the colour rather than through
    // `findByText`: the phrase sits in a div beside a <strong> label, and the
    // property under test is "the page says this, and does not style it as a
    // fault" — which is two assertions, not a query.
    const { container } = await renderWith({
      budget_shared: true, audit_durable: true,
      eval_report_shared: true, eval_schedule_hours: null,
    });
    await screen.findByText(/claude-opus-5/);

    const text = container.textContent ?? '';
    expect(text).toMatch(/Eval schedule: off — the suite is run by hand/);

    const warn = [...container.querySelectorAll<HTMLElement>('[style*="color"]')].filter(
      (el) => /run by hand/.test(el.textContent ?? '') && /245, 184, 75|f5b84b/i.test(el.getAttribute('style') ?? ''),
    );
    expect(warn).toHaveLength(0);
  });

  it('renders without a durability block at all', async () => {
    // An older server, or a partial response. The page must not blank out.
    await renderWith(undefined);
    expect(await screen.findByText(/claude-opus-5/)).toBeTruthy();
  });
});
