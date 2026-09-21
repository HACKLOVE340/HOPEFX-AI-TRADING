/**
 * The page-migration failure mode, pinned.
 *
 * Moving a page onto PageShell means replacing its wrapper and lifting its
 * header. The way that goes wrong is not a crash: an earlier codemod in this
 * repository took "everything after the header" as the body, and silently
 * dropped the elements that came BEFORE it. The page still rendered. Nothing
 * threw. It just rendered less.
 *
 * AIStrategyGenerator is the sharpest case of that shape, because what sits
 * ahead of its header is the LLM availability banner — the one thing that
 * tells an operator why strategy generation is about to fail. Losing it leaves
 * a page that looks healthy and returns errors.
 *
 * It is also plan-gated, so a signed-in trader and the route sweep both see
 * "Upgrade now" and could not catch any of this.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

const health = vi.fn();

vi.mock('../hooks/useApi', () => ({
  llmApi: { health: (...a: unknown[]) => health(...a) },
  aiStrategyApi: {
    history:        vi.fn().mockResolvedValue({ data: { strategies: [] } }),
    generate:       vi.fn().mockResolvedValue({ data: {} }),
    deploy:         vi.fn().mockResolvedValue({ data: {} }),
    deleteStrategy: vi.fn().mockResolvedValue({ data: {} }),
  },
  extractApiError: (_e: unknown, f: string) => f,
}));

import AIStrategyGenerator from '../pages/AIStrategyGenerator';

const wrap = () => render(
  <MemoryRouter initialEntries={['/ai-strategy']}><AIStrategyGenerator /></MemoryRouter>,
);

describe('AIStrategyGenerator on the standard shell', () => {
  beforeEach(() => vi.clearAllMocks());

  it('still warns when no LLM backend is configured', async () => {
    health.mockRejectedValue(new Error('no backend'));
    wrap();
    // This banner sits BEFORE the header, which is precisely where a migration
    // loses content. Without it the page offers generation and returns errors.
    expect(await screen.findByText(/AI backend not configured/i)).toBeTruthy();
  });

  it('still reports the backend when one is available', async () => {
    health.mockResolvedValue({ data: { status: 'ok', backend: 'anthropic' } });
    wrap();
    await waitFor(() => expect(screen.getByText(/anthropic/i)).toBeTruthy());
  });

  it('states its title and keeps both tabs', async () => {
    health.mockRejectedValue(new Error('x'));
    wrap();
    expect(await screen.findByText('AI Strategy Generator')).toBeTruthy();
    expect(screen.getAllByText('Generate').length).toBeGreaterThan(0);
    expect(screen.getAllByText('History').length).toBeGreaterThan(0);
  });

  it('keeps its two onward actions', async () => {
    health.mockRejectedValue(new Error('x'));
    wrap();
    await screen.findByText('AI Strategy Generator');
    expect(screen.getByText('Patterns')).toBeTruthy();
    expect(screen.getByText('A/B Test')).toBeTruthy();
  });

  it('shows the hand-picked footer exactly once', async () => {
    health.mockRejectedValue(new Error('x'));
    const { container } = wrap();
    await screen.findByText('AI Strategy Generator');
    // The page rendered its own <RelatedPages> before the migration. Left in
    // place beside the shell's derived footer, the reader gets two.
    expect(container.querySelectorAll('nav[aria-label="Where to next"]').length).toBe(1);
    expect(screen.getByText('Walk-forward')).toBeTruthy();
  });
});
