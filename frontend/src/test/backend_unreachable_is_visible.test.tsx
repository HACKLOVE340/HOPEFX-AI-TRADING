/**
 * F1-01 — a page must not look identical when its data never arrived.
 *
 * docs/HARDENING_BACKLOG.md F1-01, found by the F1 runtime failure matrix.
 *
 * Three pages issued real requests, every request failed, and each rendered
 * byte-identically to the healthy case in all five failure states. The shape is
 * the same in each: a `catch` that swallows the failure and silently
 * substitutes a fallback.
 *
 *   Watchlist:9      catch { /* API unavailable — show empty list * / }
 *                    catch { /* keep existing prices * / }
 *                    ...under the banner "Live prices refresh every 5 seconds."
 *
 *   RiskCalculator:  catch { /* fall back to store prices * / }
 *                    ...while that price is the input to position sizing.
 *
 * The fallback is not the problem — degrading is fine. Doing it *invisibly* is
 * the problem, because the page then states things it cannot know: that prices
 * are live, that a computed size is based on the current market.
 *
 * `useDataFreshness` gives a page one place to record "my last load failed",
 * and `<StaleDataNotice>` renders it. These tests pin that the notice appears
 * on failure, disappears on recovery, and never claims liveness while failing.
 */

import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { renderHook } from '@testing-library/react';

import { StaleDataNotice } from '../components/ui/StaleDataNotice';
import { useDataFreshness } from '../hooks/useDataFreshness';

describe('useDataFreshness — F1-01', () => {
  it('starts out believing the data is fine', () => {
    const { result } = renderHook(() => useDataFreshness());
    expect(result.current.failed).toBe(false);
  });

  it('records a failure', () => {
    const { result } = renderHook(() => useDataFreshness());
    act(() => result.current.markFailed('prices'));
    expect(result.current.failed).toBe(true);
    expect(result.current.what).toBe('prices');
  });

  it('clears once data arrives again', () => {
    const { result } = renderHook(() => useDataFreshness());
    act(() => result.current.markFailed('prices'));
    act(() => result.current.markOk());
    expect(result.current.failed).toBe(false);
  });

  it('does not report live data while a load is failing', () => {
    const { result } = renderHook(() => useDataFreshness());
    expect(result.current.isLive).toBe(true);
    act(() => result.current.markFailed('watchlist'));
    expect(result.current.isLive).toBe(false);
  });
});

describe('StaleDataNotice — F1-01', () => {
  it('renders nothing when the data is fine', () => {
    const { container } = render(<StaleDataNotice failed={false} />);
    expect(container.textContent?.trim()).toBe('');
  });

  it('is unmistakable when a load failed', () => {
    render(<StaleDataNotice failed what="prices" />);
    const text = screen.getByRole('status').textContent ?? '';
    expect(text).toMatch(/could ?n[o']t|could not|unable|failed/i);
    expect(text.toLowerCase()).toContain('prices');
  });

  it('tells the user the figures may be out of date, not just that something broke', () => {
    render(<StaleDataNotice failed what="prices" />);
    const text = screen.getByRole('status').textContent ?? '';
    expect(text).toMatch(/out of date|stale|not live|may be/i);
  });

  it('is announced to assistive tech', () => {
    render(<StaleDataNotice failed what="prices" />);
    const el = screen.getByRole('status');
    // Not aria-live="assertive": this is important, not an emergency.
    expect(el.getAttribute('aria-live')).toBe('polite');
  });
});

describe('useDataFreshness — identity stability (regression)', () => {
  it('returns a stable object across renders so it is safe in a dep array', () => {
    const { result, rerender } = renderHook(() => useDataFreshness());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it('returns a new object only when the state actually changed', () => {
    const { result } = renderHook(() => useDataFreshness());
    const before = result.current;
    act(() => result.current.markFailed('prices'));
    expect(result.current).not.toBe(before);
    const after = result.current;
    act(() => result.current.markFailed('prices'));
    expect(result.current).toBe(after);
  });
});
