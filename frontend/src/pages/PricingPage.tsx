/**
 * Pricing page — full plan comparison with live prices from /api/billing/plans.
 *
 * Wires to:
 *   GET /api/billing/plans       — canonical 5-tier plan catalogue
 *   GET /api/billing/subscription — current user plan (to highlight active)
 */

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { useStore, selectIsAuth } from '../store';
import { PLAN_COLORS, PLAN_LABELS, normalisePlan } from '../lib/subscription';
import type { Plan } from '../lib/subscription';

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlanData {
  id: string;
  name: string;
  price_usd_monthly: number;
  price_usd_annual: number;
  commission_rate: number;
  features: string[];
  limits: {
    signals_per_day: number;
    backtests_per_month: number;
    live_accounts: number;
    max_strategies: number;
    max_brokers: number;
  };
}

// ── Feature display map ───────────────────────────────────────────────────────

const FEATURE_LABELS: Record<string, string> = {
  paper_trading:       'Paper trading',
  live_trading:        'Live trading',
  ai_signals:          'AI signals',
  backtesting:         'Backtesting',
  pattern_recognition: 'Pattern recognition',
  api_access:          'API access',
  priority_support:    'Priority support',
  news_integration:    'News integration',
  white_label:         'White-label branding',
  dedicated_support:   'Dedicated support',
  custom_development:  'Custom development',
};

const ALL_FEATURES = Object.keys(FEATURE_LABELS);

// ── Plan accent colours ───────────────────────────────────────────────────────

const PLAN_ACCENTS: Record<string, string> = {
  free:         '#475569',
  starter:      '#3b82f6',
  professional: '#8b5cf6',
  enterprise:   '#06b6d4',
  elite:        '#f59e0b',
};

const PLAN_BADGES: Record<string, string | null> = {
  free:         null,
  starter:      null,
  professional: 'Most Popular',
  enterprise:   null,
  elite:        'Best Value',
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtLimit(v: number): string {
  return v === -1 ? 'Unlimited' : v.toString();
}

function fmtPrice(cents: number, annual: boolean): string {
  if (cents === 0) return 'Free';
  const monthly = annual ? Math.round((cents * 10) / 12) : cents;
  return `$${monthly.toLocaleString()}`;
}

// ── Plan card ─────────────────────────────────────────────────────────────────

interface PlanCardProps {
  plan: PlanData;
  annual: boolean;
  isActive: boolean;
  onSelect: () => void;
}

function PlanCard({ plan, annual, isActive, onSelect }: PlanCardProps) {
  const accent  = PLAN_ACCENTS[plan.id] ?? '#475569';
  const badge   = PLAN_BADGES[plan.id];
  const isFree  = plan.price_usd_monthly === 0;

  return (
    <div style={{
      background: '#1e293b',
      border: `2px solid ${isActive ? accent : '#334155'}`,
      borderRadius: 16,
      padding: '28px 24px',
      display: 'flex',
      flexDirection: 'column',
      position: 'relative',
      transition: 'border-color 0.2s, transform 0.2s',
      transform: badge ? 'scale(1.03)' : 'scale(1)',
    }}>
      {/* Badge */}
      {badge && (
        <div style={{
          position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)',
          background: accent, color: '#fff', fontSize: 11, fontWeight: 700,
          padding: '3px 12px', borderRadius: 20, whiteSpace: 'nowrap',
        }}>
          {badge}
        </div>
      )}

      {/* Active indicator */}
      {isActive && (
        <div style={{
          position: 'absolute', top: 12, right: 12,
          background: `${accent}22`, color: accent, fontSize: 10, fontWeight: 700,
          padding: '2px 8px', borderRadius: 10, border: `1px solid ${accent}44`,
        }}>
          CURRENT
        </div>
      )}

      {/* Plan name */}
      <div style={{ fontSize: 11, fontWeight: 700, color: accent, textTransform: 'uppercase',
        letterSpacing: '0.08em', marginBottom: 8 }}>
        {plan.name}
      </div>

      {/* Price */}
      <div style={{ marginBottom: 4 }}>
        <span style={{ fontSize: 36, fontWeight: 800, color: '#f1f5f9' }}>
          {fmtPrice(plan.price_usd_monthly, annual)}
        </span>
        {!isFree && (
          <span style={{ fontSize: 13, color: '#64748b', marginLeft: 4 }}>/mo</span>
        )}
      </div>
      {!isFree && annual && (
        <div style={{ fontSize: 11, color: '#22c55e', marginBottom: 4 }}>
          Billed annually — 2 months free
        </div>
      )}
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 20 }}>
        {(plan.commission_rate * 100).toFixed(1)}% commission per trade
      </div>

      {/* CTA */}
      <button onClick={onSelect}
        style={{
          width: '100%', padding: '11px 0', borderRadius: 8, fontSize: 14, fontWeight: 700,
          cursor: 'pointer', border: 'none', marginBottom: 24,
          background: isActive ? `${accent}22` : accent,
          color: isActive ? accent : '#fff',
          transition: 'opacity 0.15s',
        }}>
        {isActive ? 'Current Plan' : isFree ? 'Get Started' : 'Upgrade'}
      </button>

      {/* Limits */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 20 }}>
        {[
          ['Signals / day',       fmtLimit(plan.limits.signals_per_day)],
          ['Backtests / month',   fmtLimit(plan.limits.backtests_per_month)],
          ['Live accounts',       fmtLimit(plan.limits.live_accounts)],
          ['Strategies',          fmtLimit(plan.limits.max_strategies)],
          ['Brokers',             fmtLimit(plan.limits.max_brokers)],
        ].map(([label, val]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
            <span style={{ color: '#64748b' }}>{label}</span>
            <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{val}</span>
          </div>
        ))}
      </div>

      {/* Feature list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {ALL_FEATURES.map(f => {
          const included = plan.features.includes(f);
          return (
            <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
              <span style={{ color: included ? '#22c55e' : '#334155', fontSize: 14, flexShrink: 0 }}>
                {included ? '✓' : '✕'}
              </span>
              <span style={{ color: included ? '#cbd5e1' : '#475569' }}>
                {FEATURE_LABELS[f] ?? f}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── FAQ ───────────────────────────────────────────────────────────────────────

const FAQ = [
  {
    q: 'Can I change plans at any time?',
    a: 'Yes. Upgrades take effect immediately. Downgrades apply at the end of your billing period.',
  },
  {
    q: 'What payment methods are accepted?',
    a: 'We accept all major credit cards via Stripe, plus crypto payments (USDT, BTC, ETH) and Flutterwave for African markets.',
  },
  {
    q: 'Is there a free trial?',
    a: 'The Free tier is permanently free with no credit card required. Paid plans include a 14-day money-back guarantee.',
  },
  {
    q: 'What is the commission rate?',
    a: 'Commission is charged per executed trade as a percentage of notional value. Higher tiers have lower rates — Elite pays just 0.1%.',
  },
  {
    q: 'What does "Unlimited" mean?',
    a: 'Enterprise and Elite plans have no hard caps on strategies, brokers, or API calls. Fair-use policy applies.',
  },
];

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderBottom: '1px solid #1e293b' }}>
      <button onClick={() => setOpen(o => !o)}
        style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none',
          padding: '16px 0', cursor: 'pointer', display: 'flex', justifyContent: 'space-between',
          alignItems: 'center' }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0' }}>{q}</span>
        <span style={{ color: '#64748b', fontSize: 18, transform: open ? 'rotate(45deg)' : 'none',
          transition: 'transform 0.2s' }}>+</span>
      </button>
      {open && (
        <p style={{ margin: '0 0 16px', fontSize: 13, color: '#94a3b8', lineHeight: 1.6 }}>{a}</p>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const PricingPage: React.FC = () => {
  const navigate  = useNavigate();
  const isAuth    = useStore(selectIsAuth);
  const userPlan  = useStore(s => s.plan);
  const [annual, setAnnual] = useState(false);

  const { data: plansData, isLoading } = useQuery({
    queryKey: ['billing-plans'],
    queryFn: () => api.get<{ plans: PlanData[] }>('/billing/plans').then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const plans = plansData?.plans ?? [];

  const handleSelect = (planId: string) => {
    if (!isAuth) {
      navigate(`/register?plan=${planId}`);
      return;
    }
    if (planId === 'free') return;
    navigate(`/checkout?plan=${planId}&billing=${annual ? 'annual' : 'monthly'}`);
  };

  return (
    <div style={{ padding: '40px 28px', maxWidth: 1300, margin: '0 auto' }}>
      {/* Hero */}
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <h1 style={{ margin: '0 0 12px', fontSize: 36, fontWeight: 800, color: '#f1f5f9' }}>
          Simple, transparent pricing
        </h1>
        <p style={{ margin: '0 0 28px', fontSize: 16, color: '#94a3b8', maxWidth: 520, marginInline: 'auto' }}>
          From paper trading to institutional-grade execution. No hidden fees.
        </p>

        {/* Billing toggle */}
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 12,
          background: '#1e293b', border: '1px solid #334155', borderRadius: 30, padding: '6px 8px' }}>
          <button onClick={() => setAnnual(false)}
            style={{ padding: '6px 18px', borderRadius: 24, border: 'none', cursor: 'pointer', fontSize: 13,
              fontWeight: 600, background: !annual ? '#334155' : 'transparent',
              color: !annual ? '#e2e8f0' : '#64748b' }}>
            Monthly
          </button>
          <button onClick={() => setAnnual(true)}
            style={{ padding: '6px 18px', borderRadius: 24, border: 'none', cursor: 'pointer', fontSize: 13,
              fontWeight: 600, background: annual ? '#334155' : 'transparent',
              color: annual ? '#e2e8f0' : '#64748b' }}>
            Annual
            <span style={{ marginLeft: 6, fontSize: 10, color: '#22c55e', fontWeight: 700 }}>−17%</span>
          </button>
        </div>
      </div>

      {/* Plan grid */}
      {isLoading ? (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 40 }}>Loading plans…</div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 20,
          marginBottom: 64,
          alignItems: 'start',
        }}>
          {plans.map(plan => (
            <PlanCard
              key={plan.id}
              plan={plan}
              annual={annual}
              isActive={normalisePlan(userPlan) === plan.id}
              onSelect={() => handleSelect(plan.id)}
            />
          ))}
        </div>
      )}

      {/* Commission comparison */}
      <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 16,
        padding: '32px 28px', marginBottom: 64 }}>
        <h2 style={{ margin: '0 0 20px', fontSize: 20, fontWeight: 700, color: '#e2e8f0', textAlign: 'center' }}>
          Commission rates by plan
        </h2>
        <div style={{ display: 'flex', gap: 0, borderRadius: 8, overflow: 'hidden', border: '1px solid #334155' }}>
          {plans.map((plan, i) => {
            const accent = PLAN_ACCENTS[plan.id] ?? '#475569';
            return (
              <div key={plan.id} style={{
                flex: 1, padding: '16px 12px', textAlign: 'center',
                background: i % 2 === 0 ? '#0f172a' : '#1e293b',
                borderRight: i < plans.length - 1 ? '1px solid #334155' : 'none',
              }}>
                <div style={{ fontSize: 11, color: accent, fontWeight: 700, marginBottom: 6,
                  textTransform: 'uppercase' }}>{plan.name}</div>
                <div style={{ fontSize: 22, fontWeight: 800, color: '#f1f5f9' }}>
                  {(plan.commission_rate * 100).toFixed(1)}%
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* FAQ */}
      <div style={{ maxWidth: 720, margin: '0 auto 64px' }}>
        <h2 style={{ margin: '0 0 24px', fontSize: 22, fontWeight: 700, color: '#e2e8f0', textAlign: 'center' }}>
          Frequently asked questions
        </h2>
        {FAQ.map(item => <FAQItem key={item.q} q={item.q} a={item.a} />)}
      </div>

      {/* CTA */}
      <div style={{ textAlign: 'center', padding: '40px 0' }}>
        <p style={{ fontSize: 14, color: '#64748b', marginBottom: 16 }}>
          Questions? Contact us at{' '}
          <a href="mailto:support@hopefx.io" style={{ color: '#8b5cf6' }}>support@hopefx.io</a>
        </p>
        {!isAuth && (
          <button onClick={() => navigate('/register')}
            style={{ padding: '12px 32px', background: '#8b5cf6', color: '#fff', border: 'none',
              borderRadius: 8, fontSize: 15, fontWeight: 700, cursor: 'pointer' }}>
            Start for free
          </button>
        )}
      </div>
    </div>
  );
};

export default PricingPage;
