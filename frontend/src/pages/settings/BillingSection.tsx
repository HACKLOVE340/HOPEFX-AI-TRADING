// settings/BillingSection.tsx — Subscription plan, billing info, transactions
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../hooks/useApi';
import type { BillingInfo } from './types';
import { Card, SectionHeader, Button, StatusBadge, Divider } from './ui';

interface Transaction {
  id: string;
  amount: number;
  currency: string;
  description: string;
  status: string;
  created_at: string;
}

const PLAN_COLORS: Record<string, string> = {
  free:         '#475569',
  starter:      '#3b82f6',
  professional: '#8b5cf6',
  pro:          '#8b5cf6',  // legacy alias
  enterprise:   '#06b6d4',
  elite:        '#f59e0b',
};

const BillingSection: React.FC = () => {
  const navigate = useNavigate();
  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [txLoading, setTxLoading] = useState(true);

  useEffect(() => {
    api.get<BillingInfo>('/billing/subscription')
      .then((r) => setBilling(r.data))
      .catch((err: unknown) => console.warn('[Settings/Billing] subscription:', err))
      .finally(() => setLoading(false));

    api.get<{ transactions: Transaction[] }>('/billing/transactions')
      .then((r) => setTransactions(r.data.transactions ?? []))
      .catch((err: unknown) => console.warn('[Settings/Billing] transactions:', err))
      .finally(() => setTxLoading(false));
  }, []);

  const planColor = billing ? (PLAN_COLORS[billing.plan?.toLowerCase()] ?? '#3b82f6') : '#3b82f6';

  return (
    <div>
      <SectionHeader icon="💳" title="Billing & Subscription" description="Your current plan, usage, and payment history." />

      {/* Current plan */}
      <Card>
        {loading ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>Loading subscription…</div>
        ) : billing ? (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                  <span style={{
                    fontSize: 22, fontWeight: 800, color: planColor,
                    textTransform: 'uppercase', letterSpacing: '0.05em',
                  }}>
                    {billing.plan}
                  </span>
                  <StatusBadge
                    status={billing.status === 'active' ? 'ok' : billing.status === 'trialing' ? 'info' : 'warning'}
                    label={billing.status}
                  />
                </div>
                {billing.renewal_date && (
                  <div style={{ fontSize: 13, color: '#64748b' }}>
                    Renews {new Date(billing.renewal_date).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
                  </div>
                )}
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>Wallet balance</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#22c55e', fontFamily: 'JetBrains Mono, monospace' }}>
                  {billing.currency} {billing.balance?.toLocaleString(undefined, { minimumFractionDigits: 2 }) ?? '0.00'}
                </div>
              </div>
            </div>

            {billing.features?.length > 0 && (
              <>
                <Divider />
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
                  {billing.features.map((f) => (
                    <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#94a3b8' }}>
                      <span style={{ color: '#22c55e', fontSize: 12 }}>✓</span> {f}
                    </div>
                  ))}
                </div>
              </>
            )}

            <Divider />
            <div style={{ display: 'flex', gap: 10 }}>
              <Button onClick={() => navigate('/checkout')} variant="primary">
                {billing.plan?.toLowerCase() === 'free' ? 'Upgrade plan' : 'Change plan'}
              </Button>
              <Button onClick={() => navigate('/wallet')} variant="secondary">
                Manage wallet
              </Button>
            </div>
          </>
        ) : (
          <div style={{ color: '#64748b', fontSize: 13 }}>
            No subscription found.{' '}
            <button
              onClick={() => navigate('/checkout')}
              style={{ background: 'none', border: 'none', color: '#3b82f6', cursor: 'pointer', fontSize: 13, padding: 0 }}
            >
              Choose a plan →
            </button>
          </div>
        )}
      </Card>

      {/* Plan comparison */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>Available plans</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))', gap: 10 }}>
          {[
            { id: 'free',         name: 'Free',         price: '$0',      features: ['Paper trading', '5 signals/day', '3 backtests/mo', '1 strategy'] },
            { id: 'starter',      name: 'Starter',      price: '$1,800',  features: ['Live trading', '20 signals/day', '10 backtests/mo', '3 strategies'] },
            { id: 'professional', name: 'Professional', price: '$4,500',  features: ['AI charting', 'ML signals', 'Pattern recognition', 'Copy trading', 'API access'], highlight: true },
            { id: 'enterprise',   name: 'Enterprise',   price: '$7,500',  features: ['Unlimited strategies', 'News integration', 'Research tools', 'Teams', 'Market replay'] },
            { id: 'elite',        name: 'Elite',        price: '$10,000', features: ['Sub-accounts', 'Dedicated support', 'Custom development', 'White-label', '0.1% commission'] },
          ].map(({ id, name, price, features, highlight }) => (
            <div key={id} style={{
              padding: '14px', borderRadius: 10,
              border: `1px solid ${highlight ? '#3b82f6' : '#334155'}`,
              background: highlight ? '#0c1a2e' : '#0f172a',
              position: 'relative',
            }}>
              {highlight && (
                <div style={{
                  position: 'absolute', top: -10, left: '50%', transform: 'translateX(-50%)',
                  background: '#3b82f6', color: '#fff', fontSize: 10, fontWeight: 700,
                  padding: '2px 8px', borderRadius: 10, whiteSpace: 'nowrap',
                }}>
                  MOST POPULAR
                </div>
              )}
              <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9', marginBottom: 4 }}>{name}</div>
              <div style={{ fontSize: 18, fontWeight: 800, color: PLAN_COLORS[id] ?? '#94a3b8', marginBottom: 10 }}>
                {price}<span style={{ fontSize: 11, fontWeight: 400, color: '#64748b' }}>/mo</span>
              </div>
              {features.map((f) => (
                <div key={f} style={{ fontSize: 11, color: '#94a3b8', marginBottom: 3, display: 'flex', gap: 5 }}>
                  <span style={{ color: '#22c55e' }}>✓</span> {f}
                </div>
              ))}
              <Button
                variant={highlight ? 'primary' : 'secondary'}
                size="sm"
                onClick={() => navigate('/checkout')}
                style={{ marginTop: 10, width: '100%', justifyContent: 'center' }}
              >
                {billing?.plan?.toLowerCase() === id ? 'Current plan' : 'Select'}
              </Button>
            </div>
          ))}
        </div>
      </Card>

      {/* Transaction history */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>
          Transaction history
        </h3>
        {txLoading ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>Loading transactions…</div>
        ) : transactions.length === 0 ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>No transactions yet.</div>
        ) : (
          transactions.map((tx) => (
            <div key={tx.id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '12px 0', borderBottom: '1px solid #1e293b',
            }}>
              <div>
                <div style={{ fontSize: 14, color: '#e2e8f0', fontWeight: 500 }}>{tx.description}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                  {new Date(tx.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: tx.amount >= 0 ? '#22c55e' : '#f87171', fontFamily: 'JetBrains Mono, monospace' }}>
                  {tx.amount >= 0 ? '+' : ''}{tx.currency} {Math.abs(tx.amount).toFixed(2)}
                </div>
                <StatusBadge
                  status={tx.status === 'completed' ? 'ok' : tx.status === 'pending' ? 'warning' : 'error'}
                  label={tx.status}
                />
              </div>
            </div>
          ))
        )}
      </Card>
    </div>
  );
};

export default BillingSection;
