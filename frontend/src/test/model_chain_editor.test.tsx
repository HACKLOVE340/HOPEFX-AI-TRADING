/**
 * The chain editor must send what the server reads — D8 inverted (plan Task 14).
 *
 * The two flat LLM fields were declared in this form, carried in
 * PlatformConfigBody, defaulted in api/superadmin/platform.py, round-tripped
 * through the config store — and read by no runtime code at all. A superadmin
 * could set the primary and fallback model, save, and change nothing.
 *
 * The backend half of the fix is proven in
 * tests/unit/test_ai_model_chain_editor.py, which asserts that what
 * /platform/config holds is what the gateway calls. This is the other half:
 * that the editor actually PUTS a chain in the shape resolve_chain reads, in
 * the order the operator arranged, and that it cannot save a role with no legs.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const platformConfigMock = vi.fn();
const updatePlatformConfigMock = vi.fn();
const chainMock = vi.fn();

vi.mock('../hooks/useApi', () => ({
  superadminApi: {
    platformConfig: () => platformConfigMock(),
    savePlatformConfigFull: (p: object) => updatePlatformConfigMock(p),
    validatePlatformConfig: vi.fn().mockResolvedValue({ data: { ok: true, errors: [] } }),
    autoHealConfig: vi.fn().mockResolvedValue({ data: {} }),
    autoHealSaveConfig: vi.fn().mockResolvedValue({ data: {} }),
    autoHealStatus: vi.fn().mockResolvedValue({ data: {} }),
    autoHealTestIndex: vi.fn().mockResolvedValue({ data: {} }),
  },
  aiCoreApi: {
    chain: () => chainMock(),
    // The editor now also asks which models each vendor serves. Stubbed empty
    // here: these tests are about the chain's SHAPE and order, and the
    // suggestions are covered in model_discovery_populates_the_picker.test.tsx.
    models: () => Promise.resolve({ data: { providers: [], configured_count: 0, total_models: 0 } }),
  },
}));

import PlatformConfiguration from '../pages/settings/PlatformConfiguration';

const CHAIN_RESPONSE = {
  data: {
    roles: [
      {
        role: 'reasoning',
        legs: [
          { position: 0, provider: 'anthropic', model: 'claude-opus-5', reachable: true, local: false },
          { position: 1, provider: 'openai', model: 'gpt-5.5', reachable: false, local: false },
        ],
        usable_legs: 1, fallback_available: false, primary_reachable: true,
      },
      { role: 'fast', legs: [{ position: 0, provider: 'anthropic', model: 'claude-sonnet-5', reachable: true, local: false }], usable_legs: 1, fallback_available: false, primary_reachable: true },
      { role: 'vision', legs: [{ position: 0, provider: 'google', model: 'gemini-3.5-flash', reachable: false, local: false }], usable_legs: 0, fallback_available: false, primary_reachable: false },
      { role: 'embedding', legs: [{ position: 0, provider: 'openai', model: 'text-embedding-3-large', reachable: false, local: false }], usable_legs: 0, fallback_available: false, primary_reachable: false },
    ],
    providers: { anthropic: true, openai: false, google: false, ollama: false },
    embedding: { provider: 'openai', model: 'text-embedding-3-large' },
    local_provider: 'ollama', local_inference_enabled: false, local_in_chain: false, local_only: false,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  platformConfigMock.mockResolvedValue({ data: {} });
  updatePlatformConfigMock.mockResolvedValue({ data: { ok: true } });
  chainMock.mockResolvedValue(CHAIN_RESPONSE);
});

afterEach(cleanup);

/** Open the LLM tab and return the reasoning role's block. */
async function openLlmTab(user: ReturnType<typeof userEvent.setup>) {
  render(<PlatformConfiguration />);
  await user.click(await screen.findByRole('button', { name: /LLM \/ AI/i }));
  return await screen.findByText('Model chain (ordered, per role)');
}

describe('the chain editor', () => {
  it('shows the resolved chain, in order, with each leg credential state', async () => {
    const user = userEvent.setup();
    await openLlmTab(user);

    expect(await screen.findByDisplayValue('claude-opus-5')).toBeTruthy();
    expect(screen.getByDisplayValue('gpt-5.5')).toBeTruthy();
    expect(screen.getAllByText('Primary').length).toBe(4);
    // openai has no credential in the probe; the row must say so, not stay blank.
    expect(screen.getAllByText('no credential').length).toBeGreaterThan(0);
    expect(screen.getAllByText('credential present').length).toBeGreaterThan(0);
  });

  it('sends the chain in the shape resolve_chain reads, in the order arranged', async () => {
    const user = userEvent.setup();
    await openLlmTab(user);

    // Promote the second reasoning leg to primary.
    await user.click(screen.getByRole('button', { name: 'Move Reasoning leg 2 up' }));
    await user.click(screen.getAllByRole('button', { name: /^Save/i })[0]!);

    expect(updatePlatformConfigMock).toHaveBeenCalled();
    const calls = updatePlatformConfigMock.mock.calls;
    const sent = calls[calls.length - 1]![0] as {
      llm_chain: Record<string, { provider: string; model: string }[]>;
    };
    expect(sent.llm_chain.reasoning).toEqual([
      { provider: 'openai', model: 'gpt-5.5' },
      { provider: 'anthropic', model: 'claude-opus-5' },
    ]);
  });

  it('cannot remove the last leg — an empty chain is no model at all', async () => {
    const user = userEvent.setup();
    await openLlmTab(user);

    await user.click(screen.getByRole('button', { name: 'Remove Reasoning leg 2' }));
    const remaining = screen.getByRole('button', { name: 'Remove Reasoning leg 1' });
    expect(remaining).toHaveProperty('disabled', true);
  });

  it('offers "Use platform default" only once a role has been overridden', async () => {
    const user = userEvent.setup();
    await openLlmTab(user);

    const resets = screen.getAllByRole('button', { name: /Use the platform default chain for/ });
    expect(resets[0]).toHaveProperty('disabled', true);

    await user.click(screen.getByRole('button', { name: 'Move Reasoning leg 2 up' }));
    expect(screen.getAllByRole('button', { name: /Use the platform default chain for/ })[0]).toHaveProperty('disabled', false);
  });

  it('still saves when the reachability probe fails, and says the column is unknown', async () => {
    chainMock.mockRejectedValue(new Error('probe down'));
    const user = userEvent.setup();
    await openLlmTab(user);

    expect(await screen.findByText(/only the credential column is unknown/i)).toBeTruthy();
    await user.click(screen.getAllByRole('button', { name: /^Save/i })[0]!);
    expect(updatePlatformConfigMock).toHaveBeenCalled();
  });
});

describe('local inference', () => {
  it('is off by default and says why it is never the primary', async () => {
    const user = userEvent.setup();
    await openLlmTab(user);

    // Queried by ROLE and NAME: the switch is a div, so it only has an
    // accessible name at all because `aria-labelledby` supplies one. A
    // `<label for>` on a non-labellable element is silently dropped.
    const toggle = screen.getByRole('switch', { name: /Enable local inference as a last resort/i });
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(screen.getByText(/joins last and never answers first/i)).toBeTruthy();
  });

  it('states that local-only is a ceiling over the chain, not a preference', async () => {
    const user = userEvent.setup();
    await openLlmTab(user);

    await user.click(screen.getByRole('switch', { name: /Local only — never send a prompt to a hosted model/i }));
    expect(await screen.findByText(/not even as a fallback/i)).toBeTruthy();
    expect(screen.getAllByText(/overrides the chain above/i).length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole('button', { name: /^Save/i })[0]!);
    const calls = updatePlatformConfigMock.mock.calls;
    const sent = calls[calls.length - 1]![0] as { llm_local_only: boolean };
    expect(sent.llm_local_only).toBe(true);
  });
});
