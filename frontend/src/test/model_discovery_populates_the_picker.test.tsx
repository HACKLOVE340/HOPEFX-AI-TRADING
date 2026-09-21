/**
 * The model picker offers what the vendors actually serve.
 *
 * Owner requirement, 2026-09-06: "make sure this app can accept external API
 * ... and it pops up all the model."
 *
 * Two things were hard-coded here. `PROVIDERS` listed five vendors, so Moonshot
 * (Kimi), Qwen, DeepSeek, Groq, xAI, OpenRouter and Together could not be
 * SELECTED at all even once the gateway could call them. And the model field
 * was a free-text input, so choosing a model meant knowing its exact identifier
 * and typing it — a vendor shipping a model was invisible here until somebody
 * edited this file.
 *
 * `GET /api/ai-core/models` asks each vendor. This wires that answer into the
 * editor: every known provider in the dropdown, and the vendor's live model
 * list offered on the model field.
 *
 * The field stays free text with a datalist rather than becoming a closed
 * select, deliberately. A vendor's listing is not always complete — preview
 * models, fine-tunes and regional identifiers are routinely absent from it —
 * and an operator who cannot type a model the listing omits is worse off than
 * one who had no listing at all.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const platformConfigMock = vi.fn();
const chainMock = vi.fn();
const modelsMock = vi.fn();

vi.mock('../hooks/useApi', () => ({
  superadminApi: {
    platformConfig: () => platformConfigMock(),
    savePlatformConfigFull: vi.fn().mockResolvedValue({ data: {} }),
    validatePlatformConfig: vi.fn().mockResolvedValue({ data: { ok: true, errors: [] } }),
    autoHealConfig: vi.fn().mockResolvedValue({ data: {} }),
    autoHealSaveConfig: vi.fn().mockResolvedValue({ data: {} }),
    autoHealStatus: vi.fn().mockResolvedValue({ data: {} }),
    autoHealTestIndex: vi.fn().mockResolvedValue({ data: {} }),
  },
  aiCoreApi: {
    chain: () => chainMock(),
    models: () => modelsMock(),
  },
}));

import PlatformConfiguration from '../pages/settings/PlatformConfiguration';

const CHAIN_RESPONSE = {
  data: {
    roles: [
      {
        role: 'reasoning',
        legs: [{ position: 0, provider: 'anthropic', model: 'claude-opus-5', reachable: true, local: false }],
        usable_legs: 1, fallback_available: false, primary_reachable: true,
      },
    ],
    providers: { anthropic: true, openai: false, google: false, ollama: false },
    embedding: { provider: 'openai', model: 'text-embedding-3-large' },
    local_provider: 'ollama', local_inference_enabled: false, local_in_chain: false, local_only: false,
  },
};

const MODELS_RESPONSE = {
  data: {
    providers: [
      { provider: 'anthropic', label: 'Anthropic', configured: true, models: ['claude-opus-5'], error: null },
      { provider: 'moonshot', label: 'Moonshot (Kimi)', configured: true, models: ['kimi-k2-0905-preview'], error: null },
      { provider: 'qwen', label: 'Alibaba Qwen (DashScope)', configured: false, models: [], error: null },
      { provider: 'ollama', label: 'Local (Ollama)', configured: true, models: ['qwen2.5:32b'], error: null },
    ],
    configured_count: 3,
    total_models: 3,
  },
};

beforeEach(() => {
  platformConfigMock.mockResolvedValue({ data: { config: { llm_chain: {} } } });
  chainMock.mockResolvedValue(CHAIN_RESPONSE);
  modelsMock.mockResolvedValue(MODELS_RESPONSE);
});

afterEach(() => { cleanup(); vi.clearAllMocks(); });

/** The chain editor lives behind the LLM / AI tab; it does not mount until opened. */
async function openLlmTab() {
  const user = userEvent.setup();
  const view = render(<PlatformConfiguration />);
  await user.click(await screen.findByRole('button', { name: /LLM \/ AI/i }));
  await screen.findByText('Model chain (ordered, per role)');
  return view;
}

describe('the model picker is populated from the vendors', () => {
  it('asks the server which models exist', async () => {
    await openLlmTab();
    await waitFor(() => expect(modelsMock).toHaveBeenCalled());
  });

  it('offers a vendor the hard-coded list never had', async () => {
    await openLlmTab();
    await waitFor(() => expect(modelsMock).toHaveBeenCalled());
    const options = await screen.findAllByRole('option', { name: /Moonshot \(Kimi\)/i });
    expect(options.length).toBeGreaterThan(0);
  });

  it('offers the selected provider\'s models, not every vendor\'s at once', async () => {
    /* The chain's one leg is anthropic, so anthropic's models are what it
       suggests. Pooling every vendor's list would offer a Kimi identifier on an
       Anthropic leg — a suggestion that can only fail at call time. */
    const { container } = await openLlmTab();
    await waitFor(() => expect(modelsMock).toHaveBeenCalled());
    await waitFor(() => {
      const values = Array.from(container.querySelectorAll('datalist option'))
        .map((o) => (o as HTMLOptionElement).value);
      expect(values).toContain('claude-opus-5');
      expect(values).not.toContain('kimi-k2-0905-preview');
    });
  });

  it('offers the new vendor\'s models once its leg selects it', async () => {
    const user = userEvent.setup();
    const { container } = await openLlmTab();
    await waitFor(() => expect(modelsMock).toHaveBeenCalled());

    await user.selectOptions(
      await screen.findByLabelText(/Reasoning leg 1 provider/i),
      'moonshot',
    );

    await waitFor(() => {
      const values = Array.from(container.querySelectorAll('datalist option'))
        .map((o) => (o as HTMLOptionElement).value);
      expect(values).toContain('kimi-k2-0905-preview');
    });
  });

  it('still lets an operator type a model the listing omits', async () => {
    const { container } = await openLlmTab();
    await waitFor(() => expect(modelsMock).toHaveBeenCalled());
    const modelInputs = Array.from(container.querySelectorAll('input[list]'));
    expect(modelInputs.length).toBeGreaterThan(0);
    modelInputs.forEach((el) => {
      expect((el as HTMLInputElement).readOnly).toBe(false);
    });
  });

  it('stays usable when discovery fails', async () => {
    modelsMock.mockRejectedValue(new Error('vendor listing unreachable'));
    await openLlmTab();
    await waitFor(() => expect(modelsMock).toHaveBeenCalled());
    // The editor still renders and the chain is still editable.
    expect(await screen.findByText(/Model chain \(ordered, per role\)/i)).toBeTruthy();
  });
});
