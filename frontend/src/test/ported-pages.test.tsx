/**
 * Dedicated unit tests for the five roadmap pages ported from the legacy
 * dashboard into the served frontend/ app:
 *   Observability · Transparency · NewsSentiment · MLDashboard · StrategyBuilder
 *
 * Each page is exercised for its loading, populated, empty, and error states,
 * plus the key user interactions (refresh, retrain/promote, template deploy).
 * The useApi client is fully mocked so no network is touched; extractApiError
 * is the real implementation so error-message rendering is covered honestly.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

// ─── Mocked API surface (only the modules the five pages consume) ───────────────
const mocks = vi.hoisted(() => ({
  observabilityApi: { metrics: vi.fn(), services: vi.fn(), alerts: vi.fn() },
  transparencyApi:  { stats: vi.fn(), decisions: vi.fn(), auditLog: vi.fn() },
  newsApi:          { sentimentLatest: vi.fn(), feed: vi.fn() },
  mlOpsApi:         { health: vi.fn(), shadow: vi.fn(), retrainHistory: vi.fn(), triggerRetrain: vi.fn(), promote: vi.fn() },
  nocodeApi:        { templates: vi.fn(), nodeTypes: vi.fn(), deploy: vi.fn() },
}));

vi.mock('../hooks/useApi', () => ({
  observabilityApi: mocks.observabilityApi,
  transparencyApi:  mocks.transparencyApi,
  newsApi:          mocks.newsApi,
  mlOpsApi:         mocks.mlOpsApi,
  nocodeApi:        mocks.nocodeApi,
}));

import Observability   from '../pages/Observability';
import Transparency    from '../pages/Transparency';
import NewsSentiment   from '../pages/NewsSentiment';
import MLDashboard     from '../pages/MLDashboard';
import StrategyBuilder from '../pages/StrategyBuilder';

const ok = <T,>(data: T) => Promise.resolve({ data });
// A rejection with no message/response so extractApiError yields the page fallback.
const fail = () => Promise.reject({});

beforeEach(() => {
  vi.clearAllMocks();
  // Sensible empty defaults; individual tests override as needed.
  mocks.observabilityApi.metrics.mockReturnValue(ok({}));
  mocks.observabilityApi.services.mockReturnValue(ok({ services: [] }));
  mocks.observabilityApi.alerts.mockReturnValue(ok({ alerts: [] }));

  mocks.transparencyApi.stats.mockReturnValue(ok({}));
  mocks.transparencyApi.decisions.mockReturnValue(ok({ decisions: [] }));
  mocks.transparencyApi.auditLog.mockReturnValue(ok({ entries: [] }));

  mocks.newsApi.sentimentLatest.mockReturnValue(ok({}));
  mocks.newsApi.feed.mockReturnValue(ok({ articles: [] }));

  mocks.mlOpsApi.health.mockReturnValue(ok({}));
  mocks.mlOpsApi.shadow.mockReturnValue(ok({ shadows: {} }));
  mocks.mlOpsApi.retrainHistory.mockReturnValue(ok({ history: [] }));
  mocks.mlOpsApi.triggerRetrain.mockReturnValue(ok({ message: 'Retrain triggered.' }));
  mocks.mlOpsApi.promote.mockReturnValue(ok({ message: 'Model promoted.' }));

  mocks.nocodeApi.templates.mockReturnValue(ok({ templates: [] }));
  mocks.nocodeApi.nodeTypes.mockReturnValue(ok({ node_types: {} }));
  mocks.nocodeApi.deploy.mockReturnValue(ok({ message: 'Deployed.' }));
});

// ─── Observability ──────────────────────────────────────────────────────────────
describe('Observability page', () => {
  it('shows a loading state before data resolves', () => {
    render(<Observability />);
    expect(screen.getByText('Loading telemetry…')).toBeInTheDocument();
  });

  it('renders metrics, services and alerts from the API', async () => {
    mocks.observabilityApi.metrics.mockReturnValue(ok({ cpu_percent: 12.5, memory_percent: 40, error_rate: 0.01, active_connections: 7 }));
    mocks.observabilityApi.services.mockReturnValue(ok({ services: [{ name: 'api-gateway', status: 'healthy', uptime_seconds: 3600, version: '1.2.3' }] }));
    mocks.observabilityApi.alerts.mockReturnValue(ok({ alerts: [{ id: 'a1', severity: 'warning', message: 'High latency', service: 'oms' }] }));
    render(<Observability />);
    expect(await screen.findByText('12.5%')).toBeInTheDocument();
    expect(screen.getByText('api-gateway')).toBeInTheDocument();
    expect(screen.getByText('High latency')).toBeInTheDocument();
  });

  it('renders empty states when nothing is returned', async () => {
    render(<Observability />);
    expect(await screen.findByText('No service data.')).toBeInTheDocument();
    expect(screen.getByText('No active alerts. 🎉')).toBeInTheDocument();
  });

  it('shows an error banner when every request fails', async () => {
    mocks.observabilityApi.metrics.mockReturnValue(fail());
    mocks.observabilityApi.services.mockReturnValue(fail());
    mocks.observabilityApi.alerts.mockReturnValue(fail());
    render(<Observability />);
    expect(await screen.findByText('Failed to load observability data.')).toBeInTheDocument();
  });

  it('re-fetches when Refresh is clicked', async () => {
    render(<Observability />);
    await screen.findByText('No service data.');
    const calls = mocks.observabilityApi.metrics.mock.calls.length;
    fireEvent.click(screen.getByText('↻ Refresh'));
    await waitFor(() => expect(mocks.observabilityApi.metrics.mock.calls.length).toBeGreaterThan(calls));
  });
});

// ─── Transparency ─────────────────────────────────────────────────────────────
describe('Transparency page', () => {
  it('shows a loading state first', () => {
    render(<Transparency />);
    expect(screen.getByText('Loading decisions…')).toBeInTheDocument();
  });

  it('renders stats, decisions and audit entries', async () => {
    mocks.transparencyApi.stats.mockReturnValue(ok({ total_decisions: 42, win_rate: 61.5 }));
    mocks.transparencyApi.decisions.mockReturnValue(ok({ decisions: [{ trade_id: 't1', symbol: 'XAUUSD', direction: 'long', confidence: 0.8, outcome: 'win', reasoning: 'momentum' }] }));
    mocks.transparencyApi.auditLog.mockReturnValue(ok({ entries: [{ action_type: 'kill_switch_armed', timestamp: '2026-01-01' }] }));
    render(<Transparency />);
    expect(await screen.findByText('42')).toBeInTheDocument();
    expect(screen.getByText('XAUUSD')).toBeInTheDocument();
    expect(screen.getByText('momentum')).toBeInTheDocument();
    expect(screen.getByText('kill_switch_armed')).toBeInTheDocument();
  });

  it('renders empty states', async () => {
    render(<Transparency />);
    expect(await screen.findByText('No decisions recorded yet.')).toBeInTheDocument();
    expect(screen.getByText('No audit entries.')).toBeInTheDocument();
  });

  it('shows an error banner when all requests fail', async () => {
    mocks.transparencyApi.stats.mockReturnValue(fail());
    mocks.transparencyApi.decisions.mockReturnValue(fail());
    mocks.transparencyApi.auditLog.mockReturnValue(fail());
    render(<Transparency />);
    expect(await screen.findByText('Failed to load transparency data.')).toBeInTheDocument();
  });
});

// ─── News & Sentiment ───────────────────────────────────────────────────────────
describe('NewsSentiment page', () => {
  it('shows a loading state first', () => {
    render(<NewsSentiment />);
    expect(screen.getByText('Loading news…')).toBeInTheDocument();
  });

  it('renders sentiment tiles and article feed', async () => {
    mocks.newsApi.sentimentLatest.mockReturnValue(ok({ overall_score: 7.2, bullish_pct: 60, bearish_pct: 25, news_count: 12 }));
    mocks.newsApi.feed.mockReturnValue(ok({ articles: [{ id: 'n1', title: 'Gold rallies on Fed pause', source: 'Reuters', sentiment: 'bullish', impact: 'high' }] }));
    render(<NewsSentiment />);
    expect(await screen.findByText('Gold rallies on Fed pause')).toBeInTheDocument();
    expect(screen.getByText('7.2')).toBeInTheDocument();
  });

  it('surfaces a nuclear sentiment alert when flagged', async () => {
    mocks.newsApi.sentimentLatest.mockReturnValue(ok({ nuclear_alert: true, symbol: 'XAUUSD' }));
    render(<NewsSentiment />);
    expect(await screen.findByText(/Nuclear sentiment alert active/)).toBeInTheDocument();
  });

  it('renders an empty feed message', async () => {
    render(<NewsSentiment />);
    expect(await screen.findByText('No recent news.')).toBeInTheDocument();
  });

  it('shows an error banner when both requests fail', async () => {
    mocks.newsApi.sentimentLatest.mockReturnValue(fail());
    mocks.newsApi.feed.mockReturnValue(fail());
    render(<NewsSentiment />);
    expect(await screen.findByText('Failed to load news & sentiment.')).toBeInTheDocument();
  });
});

// ─── ML-Ops Dashboard ───────────────────────────────────────────────────────────
describe('MLDashboard page', () => {
  it('shows a loading state first', () => {
    render(<MemoryRouter><MLDashboard /></MemoryRouter>);
    expect(screen.getByText('Loading pipeline…')).toBeInTheDocument();
  });

  it('renders pipeline health, shadow models and history', async () => {
    mocks.mlOpsApi.health.mockReturnValue(ok({ running: true, retraining_state: 'idle', drift_history_count: 3, latest_drift: { is_drifted: false } }));
    mocks.mlOpsApi.shadow.mockReturnValue(ok({ shadows: { 'model-2026-01-01': { auc: 0.7 } } }));
    mocks.mlOpsApi.retrainHistory.mockReturnValue(ok({ history: ['retrained 2026-01-01'] }));
    render(<MemoryRouter><MLDashboard /></MemoryRouter>);
    expect(await screen.findByText('Running')).toBeInTheDocument();
    expect(screen.getByText('model-2026-01-01')).toBeInTheDocument();
    expect(screen.getByText('retrained 2026-01-01')).toBeInTheDocument();
  });

  it('triggers a retrain and shows the returned message', async () => {
    render(<MemoryRouter><MLDashboard /></MemoryRouter>);
    await screen.findByText('No shadow deployments.');
    fireEvent.click(screen.getByText('Trigger Retrain'));
    expect(await screen.findByText('Retrain triggered.')).toBeInTheDocument();
    expect(mocks.mlOpsApi.triggerRetrain).toHaveBeenCalledTimes(1);
  });

  it('promotes a shadow model', async () => {
    mocks.mlOpsApi.shadow.mockReturnValue(ok({ shadows: { 'model-x': {} } }));
    render(<MemoryRouter><MLDashboard /></MemoryRouter>);
    fireEvent.click(await screen.findByText('Promote'));
    await waitFor(() => expect(mocks.mlOpsApi.promote).toHaveBeenCalledWith('model-x'));
    expect(await screen.findByText('Model promoted.')).toBeInTheDocument();
  });

  it('shows an error banner when all requests fail', async () => {
    mocks.mlOpsApi.health.mockReturnValue(fail());
    mocks.mlOpsApi.shadow.mockReturnValue(fail());
    mocks.mlOpsApi.retrainHistory.mockReturnValue(fail());
    render(<MemoryRouter><MLDashboard /></MemoryRouter>);
    expect(await screen.findByText('Failed to load ML-Ops data.')).toBeInTheDocument();
  });
});

// ─── Strategy Builder ───────────────────────────────────────────────────────────
describe('StrategyBuilder page', () => {
  it('shows a loading state first', () => {
    render(<StrategyBuilder />);
    expect(screen.getByText('Loading templates…')).toBeInTheDocument();
  });

  it('lists templates and reveals the config panel when one is picked', async () => {
    mocks.nocodeApi.templates.mockReturnValue(ok({ templates: [
      { id: 'tpl-momentum', name: 'Momentum', category: 'trend', complexity: 'beginner', parameters: { lookback: 14 } },
    ] }));
    render(<StrategyBuilder />);
    const card = await screen.findByText('Momentum');
    fireEvent.click(card);
    expect(await screen.findByText(/Configure/)).toBeInTheDocument();
    // Parameter from the template is rendered as an editable field.
    expect(screen.getByText('lookback')).toBeInTheDocument();
  });

  it('deploys the selected template and shows the result message', async () => {
    mocks.nocodeApi.templates.mockReturnValue(ok({ templates: [
      { id: 'tpl-momentum', name: 'Momentum', parameters: {} },
    ] }));
    mocks.nocodeApi.deploy.mockReturnValue(ok({ message: 'Strategy deployed.' }));
    render(<StrategyBuilder />);
    fireEvent.click(await screen.findByText('Momentum'));
    fireEvent.click(await screen.findByText('🚀 Deploy Strategy'));
    await waitFor(() => expect(mocks.nocodeApi.deploy).toHaveBeenCalledTimes(1));
    expect(mocks.nocodeApi.deploy.mock.calls[0]?.[0]).toMatchObject({ template_id: 'tpl-momentum', symbol: 'XAUUSD', timeframe: 'M15' });
    expect(await screen.findByText('Strategy deployed.')).toBeInTheDocument();
  });

  it('renders the empty template state', async () => {
    render(<StrategyBuilder />);
    expect(await screen.findByText('No templates available.')).toBeInTheDocument();
  });

  it('shows an error banner when templates fail to load', async () => {
    mocks.nocodeApi.templates.mockReturnValue(fail());
    render(<StrategyBuilder />);
    expect(await screen.findByText('Failed to load strategy templates.')).toBeInTheDocument();
  });
});
