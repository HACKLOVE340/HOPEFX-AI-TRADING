/**
 * src/test/mlops_dashboard_honesty.test.tsx
 * =========================================
 * The ML-Ops page showed a red error banner above tiles that looked loaded.
 *
 * Tracing it through the backend first, because two plausible explanations were
 * both wrong:
 *
 *  * "the router is not registered" — it is. `core/router_registry.py` imports
 *    `api.ml_ops` and all seven routes are present.
 *  * "the frontend calls the wrong path" — it does not. A flat scan of
 *    `app.routes` shows only `/api/v1/mlops/*`, but that scan is wrong:
 *    `app.routes` holds opaque `_IncludedRouter` wrappers for anything added
 *    via `include_router`, which is exactly what the registry's own comment
 *    warns about. Walking `iter_api_routes()` shows `/api/mlops/health`,
 *    `/shadow` and `/retrain/history` all present, and a TestClient request
 *    returns 200 for each.
 *
 * So the endpoints work, and the page defects are its own:
 *
 * **1. "Stable" is manufactured from absence.** The live response is
 *
 *     {"running": false, "drift_history_count": 0, "latest_drift": null, ...}
 *
 * and the drift tile reads `health?.latest_drift?.is_drifted ? '⚠️ Drifted' :
 * 'Stable'`. Zero drift checks have ever run and the pipeline is stopped, and
 * the page reports **Stable** — a clean bill of health computed from no data.
 * The same shape reaches the tile when the request *fails*: `health` is null,
 * `?.` short-circuits, and the operator is told drift is Stable by a page that
 * could not reach the pipeline at all. This is the S4-05 pattern the inference
 * engine was just fixed for, on the surface an operator actually reads.
 *
 * **2. A partial failure is silent.** The banner required all three requests to
 * reject. With health down but shadow and history up there was no banner at
 * all, `health` stayed null, and every health-derived tile rendered a dash or
 * "Stable" as though that were the answer.
 *
 * Degrading is fine. Degrading invisibly, while asserting the safe value, is
 * not.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

const healthMock = vi.fn();
const shadowMock = vi.fn();
const historyMock = vi.fn();

vi.mock('../hooks/useApi', () => ({
  mlOpsApi: {
    health: (...a: unknown[]) => healthMock(...a),
    shadow: (...a: unknown[]) => shadowMock(...a),
    retrainHistory: (...a: unknown[]) => historyMock(...a),
    triggerRetrain: vi.fn().mockResolvedValue({ data: {} }),
    promote: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

/** The response the deployed pipeline actually returns today. */
const IDLE_HEALTH = {
  running: false,
  retraining_state: 'idle',
  can_retrain: true,
  drift_history_count: 0,
  latest_drift: null,
  shadow_models: {},
  promotion_history: [],
};

async function renderPage() {
  const Page = (await import('../pages/MLDashboard')).default;
  return render(
    <MemoryRouter>
      <Page />
    </MemoryRouter>,
  );
}

/** Text of the tile whose label matches, so assertions do not match the banner. */
async function tileValue(label: string): Promise<string> {
  const labelEl = await screen.findByText(label);
  const tile = labelEl.parentElement as HTMLElement;
  return (tile.textContent ?? '').replace(label, '').trim();
}

beforeEach(() => {
  healthMock.mockResolvedValue({ data: IDLE_HEALTH });
  shadowMock.mockResolvedValue({ data: { count: 0, shadows: {} } });
  historyMock.mockResolvedValue({ data: { history: [] } });
  vi.clearAllMocks();
  healthMock.mockResolvedValue({ data: IDLE_HEALTH });
  shadowMock.mockResolvedValue({ data: { count: 0, shadows: {} } });
  historyMock.mockResolvedValue({ data: { history: [] } });
});

// ── "Stable" must be earned ──────────────────────────────────────────────────

describe('the drift tile does not report a clean result it cannot support', () => {
  it('says no checks have run rather than "Stable" when the count is zero', async () => {
    await renderPage();
    const value = await tileValue('Drift');
    expect(value).not.toMatch(/stable/i);
    expect(value).toMatch(/no checks|never|—/i);
  });

  it('says unknown rather than "Stable" when the health request failed', async () => {
    healthMock.mockRejectedValue(new Error('boom'));
    await renderPage();
    const value = await tileValue('Drift');
    expect(value).not.toMatch(/stable/i);
  });

  it('still reports Stable when checks have actually run and found nothing', async () => {
    // Control. Without this the tests above pass by never saying Stable at all.
    healthMock.mockResolvedValue({
      data: { ...IDLE_HEALTH, drift_history_count: 12, latest_drift: { is_drifted: false, score: 0.1 } },
    });
    await renderPage();
    expect(await tileValue('Drift')).toMatch(/stable/i);
  });

  it('still reports drift when the pipeline reports drift', async () => {
    healthMock.mockResolvedValue({
      data: { ...IDLE_HEALTH, drift_history_count: 3, latest_drift: { is_drifted: true, score: 0.9 } },
    });
    await renderPage();
    expect(await tileValue('Drift')).toMatch(/drift/i);
  });
});

// ── Partial failures are visible ─────────────────────────────────────────────

describe('a partial failure is reported, not swallowed', () => {
  it('warns when only the health request fails', async () => {
    healthMock.mockRejectedValue(new Error('health exploded'));
    await renderPage();

    await waitFor(() => {
      expect(document.body.textContent).toMatch(/pipeline health/i);
    });
  });

  it('warns when only the shadow request fails', async () => {
    shadowMock.mockRejectedValue(new Error('shadow exploded'));
    await renderPage();

    await waitFor(() => {
      // "shadow deployments" is the failure label. Matching bare /shadow/i
      // would match the always-present "Shadow Models" heading, and this test
      // passed against the unfixed page for exactly that reason.
      expect(document.body.textContent).toMatch(/could not load:.*shadow deployments/i);
    });
    // The health-derived tiles must still show their real values.
    expect(await tileValue('Retrain state')).toBe('idle');
  });

  it('names every failing part when all three fail', async () => {
    healthMock.mockRejectedValue(new Error('a'));
    shadowMock.mockRejectedValue(new Error('b'));
    historyMock.mockRejectedValue(new Error('c'));
    await renderPage();

    await waitFor(() => {
      const text = document.body.textContent ?? '';
      expect(text).toMatch(/pipeline health/i);
      expect(text).toMatch(/shadow/i);
      expect(text).toMatch(/history/i);
    });
  });

  it('shows no error banner when everything loads', async () => {
    await renderPage();
    await waitFor(() => expect(screen.getByText('Retrain state')).toBeInTheDocument());
    expect(document.body.textContent).not.toMatch(/could not load|failed to load/i);
  });
});

// ── Stale data is not presented as current ───────────────────────────────────

describe('a failed refresh does not leave stale values looking live', () => {
  it('clears health-derived tiles when a later load fails', async () => {
    const { rerender } = await renderPage();
    expect(await tileValue('Retrain state')).toBe('idle');

    healthMock.mockRejectedValue(new Error('gone'));
    // Re-mount to drive a second load through the same code path.
    rerender(
      <MemoryRouter>
        <div />
      </MemoryRouter>,
    );
    await renderPage();

    await waitFor(async () => {
      expect(await tileValue('Retrain state')).toBe('—');
    });
  });
});
