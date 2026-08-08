/**
 * S9-02 + S10-05 — show the age of what you are looking at.
 *
 * docs/HARDENING_BACKLOG.md S9-02, S10-05.
 *
 * S10-05: there was no latency or data-age indicator anywhere in the app.
 * S9-02:  the one freshness cue that *was* on screen — `LivePriceTicker`'s
 *         "94%" quality/confidence — is assigned when the tick is ingested and
 *         stored on a frozen dataclass. It never re-evaluates as the tick ages,
 *         so a tick graded GOOD at 14:00 still reports 94% at 15:00.
 *
 * The two compound. A stalled feed showed a frozen price *and* a reassuring
 * green percentage, so the one visible cue actively reinforced the illusion
 * S9-01 created rather than correcting it.
 *
 * Age is computed from client arrival time, not the server's `timestamp`:
 * server clock skew cannot then corrupt it, and "how long since we last heard"
 * is the question a trader is actually asking.
 */

import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { formatAge } from '../lib/utils';
import { DataAge } from '../components/ui/DataAge';

describe('formatAge — S10-05', () => {
  it('reads as "just now" for a fresh tick', () => {
    expect(formatAge(0)).toMatch(/just now/i);
    expect(formatAge(900)).toMatch(/just now/i);
  });

  it('counts seconds', () => {
    expect(formatAge(5_000)).toBe('5s ago');
    expect(formatAge(45_000)).toBe('45s ago');
  });

  it('switches to minutes rather than printing 240s', () => {
    expect(formatAge(240_000)).toBe('4m ago');
  });

  it('switches to hours rather than printing 180m', () => {
    expect(formatAge(3 * 3_600_000)).toBe('3h ago');
  });

  it('says unknown rather than guessing when there is no timestamp', () => {
    expect(formatAge(null)).toMatch(/unknown|—/i);
    expect(formatAge(undefined)).toMatch(/unknown|—/i);
  });

  it('does not render a negative age from clock skew', () => {
    expect(formatAge(-5_000)).toMatch(/just now/i);
  });
});

describe('DataAge — S10-05', () => {
  const now = Date.now();

  it('shows the age of the data', () => {
    render(<DataAge at={now - 12_000} />);
    expect(screen.getByText(/12s ago/)).toBeTruthy();
  });

  it('marks the data stale past the threshold', () => {
    render(<DataAge at={now - 120_000} staleAfterMs={30_000} />);
    const el = screen.getByRole('status');
    expect(el.getAttribute('data-stale')).toBe('true');
  });

  it('does not mark fresh data stale', () => {
    render(<DataAge at={now - 2_000} staleAfterMs={30_000} />);
    expect(screen.getByRole('status').getAttribute('data-stale')).toBe('false');
  });

  it('says so when it has never received anything', () => {
    render(<DataAge at={null} />);
    expect(screen.getByRole('status').textContent).toMatch(/no data|unknown|—/i);
  });

  it('is announced politely, not assertively', () => {
    render(<DataAge at={now} />);
    expect(screen.getByRole('status').getAttribute('aria-live')).toBe('polite');
  });
});

// ── S9-02: the quality number must not outlive its data ──────────────────────

describe('qualityIsMeaningful — S9-02', () => {
  it('a fresh reading is meaningful', async () => {
    const { qualityIsMeaningful } = await import('../lib/utils');
    expect(qualityIsMeaningful(Date.now() - 1_000, 30_000)).toBe(true);
  });

  it('a reading older than the stale threshold is not', async () => {
    const { qualityIsMeaningful } = await import('../lib/utils');
    expect(qualityIsMeaningful(Date.now() - 120_000, 30_000)).toBe(false);
  });

  it('no timestamp means not meaningful — never assume fresh', async () => {
    const { qualityIsMeaningful } = await import('../lib/utils');
    expect(qualityIsMeaningful(null, 30_000)).toBe(false);
  });
});

// ── The ticker itself: the surface S9-02 named ───────────────────────────────

describe('LivePriceTicker — S9-02 end to end', () => {
  const renderTicker = async () => {
    const { LivePriceTicker } = await import('../components/panels/LivePriceTicker');
    return render(<LivePriceTicker />);
  };

  it('paints the quality score green when the feed is live', async () => {
    const { useStore } = await import('../store');
    useStore.setState({
      orchestratorHealth: { quality_score: 0.94 } as never,
      lastDataAt: Date.now(),
      feedStale: false,
      wsStatus: 'connected',
    } as never);

    const { container } = await renderTicker();
    const el = Array.from(container.querySelectorAll('span')).find((n) =>
      n.textContent?.trim().startsWith('94%'),
    );
    expect(el, 'quality score not rendered').toBeTruthy();
    expect(el!.getAttribute('style')).toContain('rgb(0, 230, 118)'); // #00e676
  });

  it('does NOT paint it green once the data has gone stale', async () => {
    const { useStore } = await import('../store');
    useStore.setState({
      orchestratorHealth: { quality_score: 0.94 } as never,
      lastDataAt: Date.now() - 5 * 60_000, // five minutes ago
      feedStale: true,
      wsStatus: 'connected',
    } as never);

    const { container } = await renderTicker();
    const el = Array.from(container.querySelectorAll('span')).find((n) =>
      n.textContent?.trim().startsWith('94%'),
    );
    expect(el, 'quality score not rendered').toBeTruthy();
    expect(
      el!.getAttribute('style'),
      'a five-minute-old quality score is still painted "healthy" green — the ' +
        'S9-02 defect: the one visible freshness cue reinforcing the frozen-price illusion',
    ).not.toContain('rgb(0, 230, 118)');
    expect(el!.textContent).toMatch(/as of last tick/i);
  });

  it('shows how old the data is', async () => {
    const { useStore } = await import('../store');
    useStore.setState({
      orchestratorHealth: { quality_score: 0.9 } as never,
      lastDataAt: Date.now() - 42_000,
      feedStale: false,
      wsStatus: 'connected',
    } as never);

    const { container } = await renderTicker();
    expect(container.textContent).toMatch(/42s ago/);
  });
});
