/**
 * Tests for the AI Intelligence surfacing components.
 * Covers the real logic: signal consensus/strength rendering, the analytics
 * distribution breakdown, and the store-driven risk transparency strip.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { useStore } from '../store';
import { SignalIntelligenceCard } from '../components/intelligence/SignalIntelligenceCard';
import { SignalDistribution } from '../components/intelligence/SignalDistribution';
import { RiskTransparencyStrip } from '../components/intelligence/RiskTransparencyStrip';
import type { EngineSignal, SignalAnalyticsReport } from '../types';

const sampleSignal: EngineSignal = {
  id: 'sig-1',
  symbol: 'XAU/USD',
  direction: 'buy',
  strength: 'very_strong',
  confidence: 0.82,
  price: 2340,
  entry_price: 2340,
  stop_loss: 2330,
  take_profit: 2370,
  risk_reward_ratio: 3.0,
  timeframe: '1H',
  strategies_agreeing: ['momentum', 'meanrev'],
  total_strategies: 4,
  regime: 'uptrend',
  session: 'london',
  expiry: new Date(Date.now() + 3_600_000).toISOString(),
  timestamp: new Date().toISOString(),
  metadata: { probability: 0.71, model_version: 'xgb-v7' },
  is_valid: true,
};

describe('SignalIntelligenceCard', () => {
  it('renders symbol, direction and strength tier', () => {
    render(<SignalIntelligenceCard signal={sampleSignal} />);
    expect(screen.getByText('XAU/USD')).toBeTruthy();
    expect(screen.getByText(/BUY/)).toBeTruthy();
    expect(screen.getByText('Very Strong')).toBeTruthy();
  });

  it('shows calibrated confidence and raw probability', () => {
    render(<SignalIntelligenceCard signal={sampleSignal} />);
    expect(screen.getByText(/82%/)).toBeTruthy();
    expect(screen.getByText(/raw 71%/)).toBeTruthy();
  });

  it('renders model consensus as agreeing/total', () => {
    render(<SignalIntelligenceCard signal={sampleSignal} />);
    expect(screen.getByText('2/4 agree')).toBeTruthy();
    expect(screen.getByText('momentum')).toBeTruthy();
    expect(screen.getByText('meanrev')).toBeTruthy();
  });

  it('surfaces regime, session and model version', () => {
    render(<SignalIntelligenceCard signal={sampleSignal} />);
    expect(screen.getByText(/uptrend/)).toBeTruthy();
    expect(screen.getByText(/london/)).toBeTruthy();
    expect(screen.getByText(/xgb-v7/)).toBeTruthy();
  });

  it('marks expired signals', () => {
    render(<SignalIntelligenceCard signal={{ ...sampleSignal, is_valid: false }} />);
    expect(screen.getByText('expired')).toBeTruthy();
  });
});

describe('SignalDistribution', () => {
  const analytics: SignalAnalyticsReport = {
    signals_generated: 30,
    signals_by_direction: { buy: 18, sell: 10, hold: 2 },
    signals_by_strength: { very_strong: 5, strong: 8, moderate: 10, weak: 5, very_weak: 2 },
    signals_by_symbol: { 'XAU/USD': 20, 'EUR/USD': 10 },
    hit_rate: { tp: 6, sl: 3, expired: 1 },
    tp_rate: 0.6,
    sl_rate: 0.3,
    avg_confidence: 0.68,
    avg_rr_ratio: 2.1,
    hourly_distribution: Object.fromEntries(Array.from({ length: 24 }, (_, h) => [String(h), h === 13 ? 9 : 1])),
  };

  it('renders strength, direction and top-symbol panels', () => {
    render(<SignalDistribution analytics={analytics} />);
    expect(screen.getByText('By strength tier')).toBeTruthy();
    expect(screen.getByText('By direction')).toBeTruthy();
    expect(screen.getByText('Top symbols')).toBeTruthy();
    expect(screen.getByText('By hour (UTC)')).toBeTruthy();
  });

  it('shows direction counts', () => {
    render(<SignalDistribution analytics={analytics} />);
    expect(screen.getAllByText('18').length).toBeGreaterThan(0); // buy bar (also hour axis)
    expect(screen.getAllByText('10').length).toBeGreaterThan(0); // sell + EUR/USD
  });
});

describe('RiskTransparencyStrip', () => {
  beforeEach(() => {
    useStore.setState({ riskSnapshot: null, account: null });
  });

  it('shows a connect-feed hint when no data is present', () => {
    render(<RiskTransparencyStrip />);
    expect(screen.getByText(/Risk telemetry will appear/)).toBeTruthy();
  });

  it('flags an active kill switch from the risk snapshot', () => {
    useStore.setState({
      riskSnapshot: { daily_loss_pct: 1.2, max_drawdown_pct: 10, open_risk_pct: 2, kill_switch_active: true },
    });
    render(<RiskTransparencyStrip />);
    expect(screen.getByText(/Kill switch active/)).toBeTruthy();
    expect(screen.getByText('1.2%')).toBeTruthy();
  });

  it('shows trading enabled when no kill switch', () => {
    useStore.setState({
      riskSnapshot: { daily_loss_pct: 0, max_drawdown_pct: 10, open_risk_pct: 1, kill_switch_active: false },
    });
    render(<RiskTransparencyStrip />);
    expect(screen.getByText(/Trading enabled/)).toBeTruthy();
  });
});
