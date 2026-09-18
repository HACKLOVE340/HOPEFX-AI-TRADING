/**
 * The AI Core page must report live state, and must not manufacture a
 * reassuring one.
 *
 * The page it replaces rendered its status from constants: "AI confidence
 * 82.4%", "Risk gate CLEAR", "Drift monitor 0.18σ" are literals in
 * AIIntelligence.tsx, so a control plane that had lost every provider
 * credential rendered identically to a healthy one. That is the D6 defect —
 * a control or a readout that is decorative — applied to a whole page.
 *
 * The properties asserted here are the ones that stop it recurring:
 *
 *  * a value the server did not send is never drawn as a healthy default;
 *  * a failed request shows an error where the panel sits, with a retry, and
 *    a sibling panel's success does not paper over it;
 *  * absence ("no cache", "no eval report", "no calls") reads as a finding,
 *    not as a blank;
 *  * an admin does not see the superadmin-only per-operator spend, and the
 *    page decides that from the server's `scope`, not from the role name;
 *  * a prompt is never rendered — only the digest.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const summaryMock = vi.fn();
const chainMock = vi.fn();
const budgetMock = vi.fn();
const callsMock = vi.fn();
const cacheMock = vi.fn();
const evalsMock = vi.fn();
const capabilitiesMock = vi.fn();

vi.mock('../hooks/useApi', () => ({
  aiCoreApi: {
    summary: () => summaryMock(),
    chain: () => chainMock(),
    budget: () => budgetMock(),
    calls: (...a: unknown[]) => callsMock(...a),
    cache: () => cacheMock(),
    evals: () => evalsMock(),
    capabilities: () => capabilitiesMock(),
  },
}));

import AICore from '../pages/AICore';

const ok = (data: unknown) => Promise.resolve({ data });

const SUMMARY = {
  role: 'admin', is_superadmin: false,
  reasoning_primary: 'claude-opus-5', reasoning_primary_reachable: false,
  fallback_available: false,
  providers_reachable: [], providers_unreachable: ['anthropic', 'openai', 'google', 'ollama'],
  local_inference_enabled: false,
  calls_recorded: 3, calls_unserved: 2, spent_usd: 1.25, cache_enabled: false,
};

const CHAIN = {
  roles: [{
    role: 'reasoning',
    legs: [
      { position: 0, provider: 'anthropic', model: 'claude-opus-5', reachable: false, local: false },
      { position: 1, provider: 'openai', model: 'gpt-5.5', reachable: false, local: false },
    ],
    usable_legs: 0, fallback_available: false, primary_reachable: false,
  }],
  providers: { anthropic: false, openai: false },
  embedding: { provider: 'openai', model: 'text-embedding-3-large' },
  local_provider: 'ollama', local_inference_enabled: false,
};

const CAPABILITIES = {
  role: 'admin', is_superadmin: false,
  capabilities: [
    { name: 'create_proposal', tier: 'propose', min_role: 'admin', requires_2fa: false, quorum_needs_superadmin: false, permitted: true },
    { name: 'execute_proposal', tier: 'execute', min_role: 'superadmin', requires_2fa: true, quorum_needs_superadmin: false, permitted: false },
  ],
  tiers: { view: ['admin', 'superadmin'], execute: ['superadmin'] },
  quorum_needs_superadmin_kinds: ['repair', 'upgrade'],
};

function setDefaults() {
  summaryMock.mockReturnValue(ok(SUMMARY));
  chainMock.mockReturnValue(ok(CHAIN));
  budgetMock.mockReturnValue(ok({
    scope: 'self', operator: 'op-admin', spent_usd: 1.25,
    per_operator_ceiling_usd: 25, headroom_usd: 23.75,
  }));
  callsMock.mockReturnValue(ok({ scope: 'self', calls: [], returned: 0, total_visible: 0, retention: 'in-memory ring, newest 500 calls' }));
  cacheMock.mockReturnValue(ok({ enabled: false, entries: 0, hits: 0, misses: 0, hit_rate: 0, detail: 'no shared response cache is installed; every call reaches a provider' }));
  evalsMock.mockReturnValue(ok({ report: null, promotion_allowed: false, promotion_detail: 'no_eval_report', gate_target: 'canary' }));
  capabilitiesMock.mockReturnValue(ok(CAPABILITIES));
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AICore />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  setDefaults();
});

afterEach(cleanup);

describe('AI Core reports what the server said', () => {
  it('names the primary model and says it cannot answer when it has no credential', async () => {
    renderPage();
    expect(await screen.findByText('claude-opus-5')).toBeTruthy();
    expect(screen.getByText(/no credential — this leg cannot answer/i)).toBeTruthy();
  });

  it('calls a fallback that exists on paper only what it is', async () => {
    renderPage();
    expect(await screen.findByText('Not available')).toBeTruthy();
    expect(screen.getByText(/a fallback on paper only/i)).toBeTruthy();
  });

  it('shows unserved calls rather than burying them', async () => {
    renderPage();
    expect(await screen.findByText(/every leg failed on these/i)).toBeTruthy();
  });

  it('says no provider is reachable instead of leaving the row empty', async () => {
    renderPage();
    expect(await screen.findByText(/none — no model call can succeed/i)).toBeTruthy();
  });
});

describe('a failed request is visible where the panel sits', () => {
  it('shows an error and a retry for the panel that failed, not for the page', async () => {
    chainMock.mockReturnValue(Promise.reject(new Error('boom')));
    const user = userEvent.setup();
    renderPage();

    // The summary panel still renders — a sibling's failure must not blank it.
    expect(await screen.findByText('claude-opus-5')).toBeTruthy();

    await user.click(screen.getByRole('tab', { name: 'Model chain' }));
    const banner = await screen.findByRole('alert');
    expect(banner.textContent).toMatch(/could not load the model chain/i);
    expect(banner.textContent).toMatch(/showing nothing rather than a stale or assumed value/i);

    chainMock.mockReturnValue(ok(CHAIN));
    await user.click(screen.getByRole('button', { name: /retry/i }));
    await waitFor(() => expect(screen.getByText('gpt-5.5')).toBeTruthy());
  });
});

describe('absence reads as a finding', () => {
  it('states that no response cache is installed', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('tab', { name: 'Governance' }));
    expect(await screen.findByText(/no response cache installed/i)).toBeTruthy();
  });

  it('states that no eval report exists and that the gate refuses on absent evidence', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('tab', { name: 'Governance' }));
    expect(await screen.findByText(/no eval report/i)).toBeTruthy();
    expect(screen.getByText(/refuses on absent evidence/i)).toBeTruthy();
    expect(screen.getByText('Refused')).toBeTruthy();
  });

  it('distinguishes an empty call record from a failed one', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('tab', { name: 'Calls' }));
    expect(await screen.findByText(/no model calls recorded/i)).toBeTruthy();
    expect(screen.getByText(/an empty record, not a failed one/i)).toBeTruthy();
  });
});

describe('the page shows what the server scoped, not what the role implies', () => {
  it('an admin gets no per-operator breakdown', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('tab', { name: 'Spend' }));
    expect(await screen.findByText(/you are seeing your own spend/i)).toBeTruthy();
    expect(screen.queryByText('Platform spend')).toBeNull();
  });

  it('a superadmin gets the per-operator table', async () => {
    budgetMock.mockReturnValue(ok({
      scope: 'platform', operator: 'op-super', spent_usd: 1.0,
      per_operator_ceiling_usd: 25, headroom_usd: 24,
      operators: { 'op-super': 1.0, 'someone-else': 7.0 },
      global_spent_usd: 8.0, global_ceiling_usd: 250, global_headroom_usd: 242,
    }));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('tab', { name: 'Spend' }));
    expect(await screen.findByText('someone-else')).toBeTruthy();
    expect(screen.getByText('Platform spend')).toBeTruthy();
  });

  it('marks a capability this role does not hold as not permitted, with no control offered', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('tab', { name: 'Governance' }));

    const row = (await screen.findByText('execute proposal')).closest('tr');
    expect(row).not.toBeNull();
    expect(row!.textContent).toMatch(/not permitted/i);
    // A button the server would refuse is worse than no button.
    expect(row!.querySelector('button')).toBeNull();
  });
});

describe('a prompt never reaches the page', () => {
  it('renders the digest, never the text', async () => {
    callsMock.mockReturnValue(ok({
      scope: 'self',
      calls: [{
        at: '2026-09-05T10:00:00+00:00', operator: 'op-admin', role: 'reasoning',
        prompt_sha256: 'a'.repeat(64), attempts: [],
        served_by: null, model: null, latency_ms: 12.5, cost_usd: 0, tokens_in: 0, tokens_out: 0,
      }],
      returned: 1, total_visible: 1, retention: 'in-memory ring, newest 500 calls',
    }));
    const user = userEvent.setup();
    const { container } = renderPage();
    await user.click(screen.getByRole('tab', { name: 'Calls' }));

    expect(await screen.findByText('aaaaaaaaaaaa…')).toBeTruthy();
    // A call no leg served is named, not shown as a blank cell.
    expect(screen.getByText('no leg served')).toBeTruthy();
    expect(container.textContent).not.toMatch(/prompt"?\s*:/i);
  });
});
