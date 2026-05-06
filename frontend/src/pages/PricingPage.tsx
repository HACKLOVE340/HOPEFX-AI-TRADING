/**
 * PricingPage — full plan comparison with live prices from /api/pricing/plans.
 *
 * Wires to:
 *   GET /api/pricing/plans        — canonical 5-tier plan catalogue
 *   GET /api/pricing/faq          — FAQ entries
 *   GET /api/billing/subscription — current user plan (to highlight active)
 *
 * Falls back to /api/billing/plans if /api/pricing/plans is unavailable.
 */

import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, pricingApi } from '../hooks/useApi';
import { useStore, selectIsAuth } from '../store';
import { normalisePlan } from '../lib/subscription';
import { PageHeader } from '../components/PageHeader';

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlanLimits {
  signals_per_day: number;
  backtests_per_month: number;
  live_accounts: number;
  max_strategies: number;
  max_brokers: number;
}

interface PlanData {
  id: string;
  name: string;
  tagline?: string;
  price_usd_monthly: number;
  price_usd_annual: number;
  annual_savings_pct?: number;
  commission_rate: number;
  commission_label?: string;
  badge?: string | null;
  cta?: string;
  cta_href?: string;
  features: Record<string, boolean> | string[];
  limits: PlanLimits;
  highlights?: string[];
}

function hasFeature(plan: PlanData, key: string): boolean {
  if (Array.isArray(plan.features)) return plan.features.includes(key);
  return Boolean((plan.features as Record<string, boolean>)[key]);
}

// ── Constants ─────────────────────────────────────────────────────────────────

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

function fmtLimit(v: number): string {
  return v === -1 ? 'Unlimited' : v.toString();
}

function fmtPrice(plan: PlanData, annual: boolean): string {
  if (plan.price_usd_monthly === 0) return 'Free';
  const monthly = annual && plan.price_usd_annual > 0
    ? Math.round(plan.price_usd_annual / 12)
    : plan.price_usd_monthly;
  return '$' + monthly.toLocaleString();
}

// ── Plan card ─────────────────────────────────────────────────────────────────

interface PlanCardProps {
  plan: PlanData;
  annual: boolean;
  isActive: boolean;
  onSelect: () => void;
}

function PlanCard({ plan, annual, isActive, onSelect }: PlanCardProps) {
  const accent = PLAN_ACCENTS[plan.id] ?? '#475569';
  const badge  = plan.badge ?? PLAN_BADGES[plan.id] ?? null;
  const isFree = plan.price_usd_monthly === 0;

  return (
    <div style={{
      background: '#1e293b', border: '2px solid ' + (isActive ? accent : '#334155'),
      borderRadius: 16, padding: '28px 24px', display: 'flex', flexDirection: 'column',
      position: 'relative', transition: 'border-color 0.2s, transform 0.2s',
      transform: badge ? 'scale(1.03)' : 'scale(1)',
    }}>
      {badge && (
        <div style={{
          position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)',
          background: accent, color: '#fff', fontSize: 11, fontWeight: 700,
          padding: '3px 12px', borderRadius: 20, whiteSpace: 'nowrap',
        }}>{badge}</div>
      )}
      {isActive && (
        <div style={{
          position: 'absolute', top: 12, right: 12,
          background: accent + '22', color: accent, fontSize: 10, fontWeight: 700,
          padding: '2px 8px', borderRadius: 10, border: '1px solid ' + accent + '44',
        }}>CURRENT</div>
      )}
      <div style={{ fontSize: 11, fontWeight: 700, color: accent,
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>
        {plan.name}
      </div>
      {plan.tagline && (
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8, lineHeight: 1.4 }}>
          {plan.tagline}
        </div>
      )}
      <div style={{ marginBottom: 4 }}>
        <span style={{ fontSize: 36, fontWeight: 800, color: '#f1f5f9' }}>
          {fmtPrice(plan, annual)}
        </span>
        {!isFree && <span style={{ fontSize: 13, color: '#64748b', marginLeft: 4 }}>/mo</span>}
      </div>
      {!isFree && annual && plan.price_usd_annual > 0 && (
        <div style={{ fontSize: 11, color: '#22c55e', marginBottom: 4 }}>
          Billed ${plan.price_usd_annual.toLocaleString()}/yr — 2 months free
        </div>
      )}
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 20 }}>
        {(plan.commission_rate * 100).toFixed(1)}% commission per trade
      </div>
      <button onClick={onSelect} style={{
        width: '100%', padding: '11px 0', borderRadius: 8, fontSize: 14, fontWeight: 700,
        cursor: 'pointer', border: 'none', marginBottom: 24,
        background: isActive ? accent + '22' : accent,
        color: isActive ? accent : '#fff', transition: 'opacity 0.15s',
      }}>
        {isActive ? 'Current Plan' : isFree ? 'Get Started' : 'Upgrade'}
      </button>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 20 }}>
        {([
          ['Signals / day',     fmtLimit(plan.limits.signals_per_day)],
          ['Backtests / month', fmtLimit(plan.limits.backtests_per_month)],
          ['Live accounts',     fmtLimit(plan.limits.live_accounts)],
          ['Strategies',        fmtLimit(plan.limits.max_strategies)],
          ['Brokers',           fmtLimit(plan.limits.max_brokers)],
        ] as [string, string][]).map(([label, val]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
            <span style={{ color: '#64748b' }}>{label}</span>
            <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{val}</span>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {plan.highlights && plan.highlights.length > 0
          ? plan.highlights.map(h => (
              <div key={h} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                <span style={{ color: '#22c55e', fontSize: 14, flexShrink: 0 }}>✓</span>
                <span style={{ color: '#cbd5e1' }}>{h}</span>
              </div>
            ))
          : ALL_FEATURES.map(f => {
              const included = hasFeature(plan, f);
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
            })
        }
      </div>
    </div>
  );
}

// ── Full feature comparison table ─────────────────────────────────────────────

function ComparisonTable({ plans }: { plans: PlanData[] }) {
  const LIMIT_ROWS: Array<{ label: string; key: keyof PlanLimits }> = [
    { label: 'Signals / day',     key: 'signals_per_day' },
    { label: 'Backtests / month', key: 'backtests_per_month' },
    { label: 'Live accounts',     key: 'live_accounts' },
    { label: 'Strategies',        key: 'max_strategies' },
    { label: 'Brokers',           key: 'max_brokers' },
  ];

  return (
    <div style={{ overflowX: 'auto', marginBottom: 48 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={{ width: '20%', textAlign: 'left', padding: '12px 16px',
              color: '#64748b', fontWeight: 600, borderBottom: '1px solid #334155' }}>
              Feature
            </th>
            {plans.map(p => {
              const accent = PLAN_ACCENTS[p.id] ?? '#475569';
              return (
                <th key={p.id} style={{ textAlign: 'center', padding: '12px 8px',
                  color: accent, fontWeight: 700, borderBottom: '1px solid #334155',
                  textTransform: 'uppercase', fontSize: 11, letterSpacing: '0.06em' }}>
                  {p.name}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colSpan={plans.length + 1} style={{ padding: '10px 16px 4px',
              fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase',
              letterSpacing: '0.08em', background: '#0f172a' }}>
              Limits
            </td>
          </tr>
          {LIMIT_ROWS.map(({ label, key }, ri) => (
            <tr key={key} style={{ background: ri % 2 === 0 ? '#1e293b' : '#0f172a' }}>
              <td style={{ padding: '10px 16px', color: '#94a3b8', borderBottom: '1px solid #1e293b' }}>
                {label}
              </td>
              {plans.map(p => (
                <td key={p.id} style={{ textAlign: 'center', padding: '10px 8px',
                  color: '#e2e8f0', fontWeight: 600, borderBottom: '1px solid #1e293b' }}>
                  {fmtLimit(p.limits[key])}
                </td>
              ))}
            </tr>
          ))}
          <tr>
            <td colSpan={plans.length + 1} style={{ padding: '10px 16px 4px',
              fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase',
              letterSpacing: '0.08em', background: '#0f172a' }}>
              Features
            </td>
          </tr>
          {ALL_FEATURES.map((f, fi) => (
            <tr key={f} style={{ background: fi % 2 === 0 ? '#1e293b' : '#0f172a' }}>
              <td style={{ padding: '10px 16px', color: '#94a3b8', borderBottom: '1px solid #1e293b' }}>
                {FEATURE_LABELS[f] ?? f}
              </td>
              {plans.map(p => {
                const included = hasFeature(p, f);
                return (
                  <td key={p.id} style={{ textAlign: 'center', padding: '10px 8px',
                    borderBottom: '1px solid #1e293b' }}>
                    <span style={{ color: included ? '#22c55e' : '#334155', fontSize: 16 }}>
                      {included ? '✓' : '✕'}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
          <tr>
            <td colSpan={plans.length + 1} style={{ padding: '10px 16px 4px',
              fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase',
              letterSpacing: '0.08em', background: '#0f172a' }}>
              Pricing
            </td>
          </tr>
          <tr style={{ background: '#1e293b' }}>
            <td style={{ padding: '10px 16px', color: '#94a3b8', borderBottom: '1px solid #1e293b' }}>
              Commission rate
            </td>
            {plans.map(p => (
              <td key={p.id} style={{ textAlign: 'center', padding: '10px 8px',
                color: '#e2e8f0', fontWeight: 700, borderBottom: '1px solid #1e293b' }}>
                {(p.commission_rate * 100).toFixed(1)}%
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ── FAQ ───────────────────────────────────────────────────────────────────────

const FAQ_FALLBACK = [
  { question: 'Can I change plans at any time?',
    answer: 'Yes. Upgrades take effect immediately. Downgrades apply at the end of your billing period.' },
  { question: 'What payment methods are accepted?',
    answer: 'We accept all major credit cards via Stripe, plus crypto payments (USDT, BTC, ETH) and Flutterwave for African markets.' },
  { question: 'Is there a free trial?',
    answer: 'The Free tier is permanently free with no credit card required. Paid plans include a 14-day money-back guarantee.' },
  { question: 'What is the commission rate?',
    answer: 'Commission is charged per executed trade as a percentage of notional value. Higher tiers have lower rates — Elite pays just 0.1%.' },
  { question: 'What does "Unlimited" mean?',
    answer: 'Enterprise and Elite plans have no hard caps on strategies, brokers, or API calls. Fair-use policy applies.' },
];

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderBottom: '1px solid #1e293b' }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', textAlign: 'left', background: 'none', border: 'none',
        padding: '16px 0', cursor: 'pointer', display: 'flex',
        justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0' }}>{q}</span>
        <span style={{ color: '#64748b', fontSize: 18,
          transform: open ? 'rotate(45deg)' : 'none', transition: 'transform 0.2s' }}>+</span>
      </button>
      {open && (
        <p style={{ margin: '0 0 16px', fontSize: 13, color: '#94a3b8', lineHeight: 1.6 }}>{a}</p>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const PricingPage: React.FC = () => {
  const navigate = useNavigate();
  const isAuth   = useStore(selectIsAuth);
  const userPlan = useStore(s => s.plan);
  const [annual, setAnnual]       = useState(false);
  const [showTable, setShowTable] = useState(false);

  const { data: plansData, isLoading } = useQuery({
    queryKey: ['pricing-plans', annual ? 'annual' : 'monthly'],
    queryFn: () =>
      pricingApi.getPlans(annual ? 'annual' : 'monthly')
        .then(r => r.data as { plans: PlanData[] })
        .catch(() =>
          api.get<{ plans: PlanData[] }>('/billing/plans').then(r => r.data)
        ),
    staleTime: 5 * 60_000,
  });

  const { data: faqData } = useQuery({
    queryKey: ['pricing-faq'],
    queryFn: () =>
      pricingApi.getFaq()
        .then(r => (r.data as { faq: Array<{ question: string; answer: string }> }).faq)
        .catch(() => null),
    staleTime: 30 * 60_000,
  });

  const plans    = plansData?.plans ?? [];
  const faqItems = faqData ?? FAQ_FALLBACK;

  const handleSelect = (planId: string) => {
    if (!isAuth) { navigate('/register?plan=' + planId); return; }
    if (planId === 'free') return;
    navigate('/checkout?plan=' + planId + '&billing=' + (annual ? 'annual' : 'monthly'));
  };

  const breadcrumbs = isAuth
    ? [{ label: 'Dashboard', href: '/dashboard' }, { label: 'Upgrade' }]
    : [{ label: 'Home', href: '/' }, { label: 'Pricing' }];

  return (
    <div style={{ padding: '40px 28px', maxWidth: 1300, margin: '0 auto' }}>
      <PageHeader
        title="Pricing"
        subtitle="Simple, transparent pricing. No hidden fees."
        breadcrumbs={breadcrumbs}
        actions={
          isAuth ? (
            <Link to="/settings" style={{
              fontSize: 13, color: '#64748b', textDecoration: 'none',
              padding: '6px 14px', border: '1px solid #334155', borderRadius: 6,
            }}>
              Account Settings
            </Link>
          ) : (
            <Link to="/login" style={{
              fontSize: 13, color: '#94a3b8', textDecoration: 'none',
              padding: '6px 14px', border: '1px solid #334155', borderRadius: 6,
            }}>
              Sign in
            </Link>
          )
        }
      />

      {/* Hero */}
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <h1 style={{ margin: '0 0 12px', fontSize: 36, fontWeight: 800, color: '#f1f5f9' }}>
          Simple, transparent pricing
        </h1>
        <p style={{ margin: '0 0 28px', fontSize: 16, color: '#94a3b8',
          maxWidth: 520, marginInline: 'auto' }}>
          From paper trading to institutional-grade execution.
        </p>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 12,
          background: '#1e293b', border: '1px solid #334155', borderRadius: 30, padding: '6px 8px' }}>
          <button onClick={() => setAnnual(false)} style={{
            padding: '6px 18px', borderRadius: 24, border: 'none', cursor: 'pointer', fontSize: 13,
            fontWeight: 600, background: !annual ? '#334155' : 'transparent',
            color: !annual ? '#e2e8f0' : '#64748b',
          }}>Monthly</button>
          <button onClick={() => setAnnual(true)} style={{
            padding: '6px 18px', borderRadius: 24, border: 'none', cursor: 'pointer', fontSize: 13,
            fontWeight: 600, background: annual ? '#334155' : 'transparent',
            color: annual ? '#e2e8f0' : '#64748b',
          }}>
            Annual
            <span style={{ marginLeft: 6, fontSize: 10, color: '#22c55e', fontWeight: 700 }}>−17%</span>
          </button>
        </div>
      </div>

      {/* Plan grid */}
      {isLoading ? (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 40 }}>Loading plans…</div>
      ) : plans.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📋</div>
          <div style={{ color: '#64748b', fontSize: 15 }}>Plans unavailable — please try again shortly.</div>
        </div>
      ) : (
        <>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: 20, marginBottom: 48, alignItems: 'start',
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

          {/* Toggle comparison table */}
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <button onClick={() => setShowTable(t => !t)} style={{
              background: 'none', border: '1px solid #334155', borderRadius: 8,
              color: '#94a3b8', fontSize: 13, padding: '8px 20px', cursor: 'pointer',
            }}>
              {showTable ? 'Hide' : 'Show'} full feature comparison ↕
            </button>
          </div>

          {showTable && <ComparisonTable plans={plans} />}

          {/* Commission bar */}
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 16,
            padding: '32px 28px', marginBottom: 64 }}>
            <h2 style={{ margin: '0 0 20px', fontSize: 20, fontWeight: 700,
              color: '#e2e8f0', textAlign: 'center' }}>
              Commission rates by plan
            </h2>
            <div style={{ display: 'flex', gap: 0, borderRadius: 8, overflow: 'hidden',
              border: '1px solid #334155' }}>
              {plans.map((plan, i) => {
                const accent = PLAN_ACCENTS[plan.id] ?? '#475569';
                return (
                  <div key={plan.id} onClick={() => handleSelect(plan.id)} style={{
                    flex: 1, padding: '16px 12px', textAlign: 'center', cursor: 'pointer',
                    background: i % 2 === 0 ? '#0f172a' : '#1e293b',
                    borderRight: i < plans.length - 1 ? '1px solid #334155' : 'none',
                  }}>
                    <div style={{ fontSize: 11, color: accent, fontWeight: 700,
                      marginBottom: 6, textTransform: 'uppercase' }}>{plan.name}</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: '#f1f5f9' }}>
                      {(plan.commission_rate * 100).toFixed(1)}%
                    </div>
                    <div style={{ fontSize: 11, color: '#475569', marginTop: 4 }}>per trade</div>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      {/* FAQ */}
      <div style={{ maxWidth: 720, margin: '0 auto 64px' }}>
        <h2 style={{ margin: '0 0 24px', fontSize: 22, fontWeight: 700,
          color: '#e2e8f0', textAlign: 'center' }}>
          Frequently asked questions
        </h2>
        {faqItems.map(item => (
          <FAQItem key={item.question} q={item.question} a={item.answer} />
        ))}
      </div>

      {/* CTA footer */}
      <div style={{ textAlign: 'center', padding: '40px 0', borderTop: '1px solid #1e293b' }}>
        <p style={{ fontSize: 14, color: '#64748b', marginBottom: 16 }}>
          Questions? Contact us at{' '}
          <a href="mailto:support@hopefx.io" style={{ color: '#8b5cf6', textDecoration: 'none' }}>
            support@hopefx.io
          </a>
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
          {!isAuth && (
            <button onClick={() => navigate('/register')} style={{
              padding: '12px 32px', background: '#8b5cf6', color: '#fff', border: 'none',
              borderRadius: 8, fontSize: 15, fontWeight: 700, cursor: 'pointer',
            }}>
              Start for free
            </button>
          )}
          <Link to={isAuth ? '/dashboard' : '/login'} style={{
            padding: '12px 32px', background: 'transparent', color: '#94a3b8',
            border: '1px solid #334155', borderRadius: 8, fontSize: 15,
            fontWeight: 600, textDecoration: 'none', display: 'inline-block',
          }}>
            {isAuth ? 'Go to Dashboard' : 'Sign in'}
          </Link>
        </div>
      </div>
    </div>
  );
};

export default PricingPage;
