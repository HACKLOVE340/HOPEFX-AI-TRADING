/**
 * "Trained: 26/06/2026" next to a stale badge that means 167 days is a lie by
 * arithmetic, whichever date is right.
 *
 * `MlSafetyStrip` rendered `last_trained_at`, which comes from
 * `advanced_oos_meta.json`. The freshness gate blocks on a different timestamp:
 * the sha256-bound one in `registry.json`. On the committed artifact those are
 * 2026-06-26 and 2026-04-01 — the same bytes, nearly three months apart — so the
 * strip showed a model trained twelve weeks ago flagged stale at twenty-four,
 * with nothing on screen to reconcile them.
 *
 * Which record is correct is an ML decision (see MODEL-PROVENANCE-DISAGREES);
 * what this screen owes an operator is the date the platform ACTED on. So when
 * health reports `model_provenance_at`, that is what "Trained" shows.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const healthMock = vi.fn();
vi.mock('../hooks/useApi', () => ({
  mlApi: { health: () => healthMock() },
}));

import { MlSafetyStrip } from '../components/intelligence/MlSafetyStrip';

const BASE = {
  status: 'degraded',
  model_available: true,
  model_version: 'v3',
  stale_model: true,
  model_age_days: 166.75,
  model_max_age_days: 30,
  stale_model_block: true,
  feature_drift_detected: false,
  feature_drift_z_max: 0,
  feature_drift_threshold: 3,
  feature_drift_blocking: false,
  last_latency_ms: 12,
  online_learning_enabled: false,
  mtf_fusion_enabled: false,
  threshold_long: 0.58,
  threshold_short: 0.42,
  checked_at: new Date().toISOString(),
  // Fields the strip reads directly and would throw on if absent.
  predict_count: 0,
  fallback_rate: 0,
  non_neutral_rate: 0,
  oos_accuracy: 0.57,
  model_id: 'advanced_oos',
  model_loaded: true,
  calibrator_available: false,
};

const show = async (extra: Record<string, unknown>) => {
  healthMock.mockResolvedValue({ data: { ...BASE, ...extra } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MlSafetyStrip />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.queryByText(/Loading model health/)).toBeNull());
};

const asDate = (iso: string) => new Date(iso).toLocaleDateString();

/** "Trained:" and its date are separate elements, so match on the whole line. */
const trainedLine = () =>
  screen.getByText((_t, el) => (el?.textContent ?? '').startsWith('Trained:')).textContent ?? '';
const GATE = '2026-04-01T05:24:23Z';
const META = '2026-06-26T22:30:44Z';

beforeEach(() => healthMock.mockReset());

describe('the trained date is the one the freshness gate acted on', () => {
  it('shows the provenance the gate used, not the meta file, when they differ', async () => {
    await show({ last_trained_at: META, model_provenance_at: GATE });
    const shown = trainedLine();
    expect(shown).toContain(asDate(GATE));
    expect(shown).not.toContain(asDate(META));
  });

  it('still shows the meta date when the gate reports no provenance', async () => {
    await show({ last_trained_at: META, model_provenance_at: null });
    expect(trainedLine()).toContain(asDate(META));
  });

  it('shows nothing rather than a wrong date when neither is known', async () => {
    await show({ last_trained_at: null, model_provenance_at: null });
    expect(document.body.textContent ?? '').not.toContain('Trained:');
  });
});
