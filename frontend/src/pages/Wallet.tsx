/**
 * Wallet & Payments — balance overview, transaction history, subscriptions.
 *
 * Wires to: GET /api/payments/balance
 *           GET /api/payments/transactions
 *           POST /api/payments/deposit
 *           POST /api/payments/withdraw
 */

import React, { useState, useEffect } from 'react';
import { useStore } from '../store';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Transaction {
  id: number;
  type: 'deposit' | 'withdrawal' | 'subscription' | 'copy_fee' | 'refund';
  amount: number;
  status: 'completed' | 'pending' | 'failed';
  date: string;
  method: string;
}

// ── Fallback data ─────────────────────────────────────────────────────────────

const FALLBACK_TXS: Transaction[] = [
  { id: 1, type: 'deposit',      amount:  10000,   status: 'completed', date: '2024-01-15', method: 'Bank Transfer'    },
  { id: 2, type: 'subscription', amount:    -99,   status: 'completed', date: '2024-01-14', method: 'Pro Plan'         },
  { id: 3, type: 'copy_fee',     amount:  -234.50, status: 'completed', date: '2024-01-13', method: 'Performance Fee'  },
  { id: 4, type: 'withdrawal',   amount:  -5000,   status: 'pending',   date: '2024-01-12', method: 'Crypto'           },
];

const TYPE_ICON: Record<string, string> = {
  deposit:      '↓',
  withdrawal:   '↑',
  subscription: '🔄',
  copy_fee:     '📊',
  refund:       '↩',
};

const TYPE_COLOR: Record<string, string> = {
  deposit:      '#4ade80',
  withdrawal:   '#f87171',
  subscription: '#94a3b8',
  copy_fee:     '#fbbf24',
  refund:       '#60a5fa',
};

const STATUS_COLOR: Record<string, string> = {
  completed: '#4ade80',
  pending:   '#fbbf24',
  failed:    '#f87171',
};

// ── Main component ────────────────────────────────────────────────────────────

const Wallet: React.FC = () => {
  const token = useStore((s) => s.token);

  const [tab, setTab]               = useState<'overview' | 'transactions' | 'subscriptions' | 'payment-methods'>('overview');
  const [transactions, setTxs]      = useState<Transaction[]>(FALLBACK_TXS);
  const [balance, setBalance]       = useState(24765.50);
  const [showDeposit, setShowDeposit] = useState(false);
  const [showWithdraw, setShowWithdraw] = useState(false);
  const [amount, setAmount]         = useState('');
  const [processing, setProcessing] = useState(false);
  const [msg, setMsg]               = useState('');

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  useEffect(() => {
    fetch('/api/payments/balance', { headers })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.balance) setBalance(d.balance); })
      .catch(() => {});

    fetch('/api/payments/transactions', { headers })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.length) setTxs(d); })
      .catch(() => {});
  }, []);

  const handleDeposit = async () => {
    if (!amount) return;
    setProcessing(true);
    setMsg('');
    try {
      const res = await fetch('/api/payments/deposit', {
        method: 'POST', headers,
        body: JSON.stringify({ amount: parseFloat(amount) }),
      });
      if (res.ok) {
        setMsg(`Deposit of $${amount} initiated.`);
        setShowDeposit(false);
        setAmount('');
      } else {
        setMsg('Deposit failed.');
      }
    } catch { setMsg('Network error.'); }
    setProcessing(false);
  };

  const handleWithdraw = async () => {
    if (!amount) return;
    setProcessing(true);
    setMsg('');
    try {
      const res = await fetch('/api/payments/withdraw', {
        method: 'POST', headers,
        body: JSON.stringify({ amount: parseFloat(amount) }),
      });
      if (res.ok) {
        setMsg(`Withdrawal of $${amount} submitted.`);
        setShowWithdraw(false);
        setAmount('');
      } else {
        setMsg('Withdrawal failed.');
      }
    } catch { setMsg('Network error.'); }
    setProcessing(false);
  };

  const totalDeposited  = transactions.filter((t) => t.type === 'deposit').reduce((s, t) => s + t.amount, 0);
  const totalWithdrawn  = Math.abs(transactions.filter((t) => t.type === 'withdrawal').reduce((s, t) => s + t.amount, 0));
  const totalFees       = Math.abs(transactions.filter((t) => ['subscription', 'copy_fee'].includes(t.type)).reduce((s, t) => s + t.amount, 0));

  return (
    <div style={s.page}>
      <h1 style={s.title}>Wallet & Payments</h1>

      {/* Balance card */}
      <div style={s.balanceCard}>
        <div>
          <div style={s.balanceLabel}>Available Balance</div>
          <div style={s.balanceValue}>${balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
          <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            Frozen: $0.00 · Pending: $500.00
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={() => { setShowDeposit(true); setShowWithdraw(false); setMsg(''); }} style={s.depositBtn}>
            ↓ Deposit
          </button>
          <button onClick={() => { setShowWithdraw(true); setShowDeposit(false); setMsg(''); }} style={s.withdrawBtn}>
            ↑ Withdraw
          </button>
        </div>
      </div>

      {/* Deposit / Withdraw form */}
      {(showDeposit || showWithdraw) && (
        <div style={s.actionCard}>
          <h3 style={s.cardTitle}>{showDeposit ? 'Deposit Funds' : 'Withdraw Funds'}</h3>
          <label style={s.label}>Amount (USD)</label>
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="e.g. 1000"
            style={s.input}
          />
          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <button
              onClick={showDeposit ? handleDeposit : handleWithdraw}
              disabled={processing || !amount}
              style={{ ...s.confirmBtn, opacity: processing || !amount ? 0.6 : 1 }}
            >
              {processing ? 'Processing…' : 'Confirm'}
            </button>
            <button onClick={() => { setShowDeposit(false); setShowWithdraw(false); }} style={s.cancelBtn}>
              Cancel
            </button>
          </div>
          {msg && <div style={{ marginTop: 10, fontSize: 13, color: msg.includes('failed') || msg.includes('error') ? '#f87171' : '#4ade80' }}>{msg}</div>}
        </div>
      )}

      {/* Tabs */}
      <div style={s.tabs}>
        {(['overview', 'transactions', 'subscriptions', 'payment-methods'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            style={{ ...s.tab, ...(tab === t ? s.tabActive : {}) }}>
            {t.replace('-', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
          </button>
        ))}
      </div>

      {/* Overview */}
      {tab === 'overview' && (
        <div style={s.statsGrid}>
          <StatCard icon="↓" label="Total Deposited"  value={`$${totalDeposited.toLocaleString()}`}  color="#4ade80" />
          <StatCard icon="↑" label="Total Withdrawn"  value={`$${totalWithdrawn.toLocaleString()}`}  color="#f87171" />
          <StatCard icon="💸" label="Total Fees Paid" value={`$${totalFees.toFixed(2)}`}             color="#fbbf24" />
        </div>
      )}

      {/* Transactions */}
      {tab === 'transactions' && (
        <div style={s.txList}>
          {transactions.map((tx) => (
            <div key={tx.id} style={s.txRow}>
              <div style={{
                width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
                background: `${TYPE_COLOR[tx.type]}22`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 16, color: TYPE_COLOR[tx.type],
              }}>
                {TYPE_ICON[tx.type]}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>
                  {tx.type.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                </div>
                <div style={{ fontSize: 12, color: '#64748b' }}>{tx.method} · {tx.date}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: tx.amount >= 0 ? '#4ade80' : '#f87171' }}>
                  {tx.amount >= 0 ? '+' : ''}${Math.abs(tx.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </div>
                <div style={{ fontSize: 11, color: STATUS_COLOR[tx.status] }}>{tx.status}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Subscriptions */}
      {tab === 'subscriptions' && (
        <div style={s.subCard}>
          <div style={s.subRow}>
            <div>
              <div style={{ fontWeight: 700, color: '#f1f5f9' }}>Pro Plan</div>
              <div style={{ fontSize: 13, color: '#64748b' }}>Renews monthly · Next: Feb 14, 2024</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: '#fbbf24' }}>$99/mo</div>
              <div style={{ fontSize: 11, color: '#4ade80' }}>Active</div>
            </div>
          </div>
          <div style={{ borderTop: '1px solid #334155', paddingTop: 12, marginTop: 12 }}>
            <button style={s.cancelSubBtn}>Cancel Subscription</button>
          </div>
        </div>
      )}

      {/* Payment methods */}
      {tab === 'payment-methods' && (
        <div style={s.subCard}>
          <div style={{ color: '#64748b', fontSize: 14, marginBottom: 16 }}>No payment methods saved.</div>
          <button style={s.addMethodBtn}>+ Add Payment Method</button>
        </div>
      )}
    </div>
  );
};

// ── Sub-components ────────────────────────────────────────────────────────────

const StatCard: React.FC<{ icon: string; label: string; value: string; color: string }> = ({ icon, label, value, color }) => (
  <div style={s.statCard}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
      <div style={{ width: 32, height: 32, borderRadius: 8, background: `${color}22`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, color }}>
        {icon}
      </div>
      <span style={{ fontSize: 13, color: '#64748b' }}>{label}</span>
    </div>
    <div style={{ fontSize: 22, fontWeight: 700, color: '#f1f5f9' }}>{value}</div>
  </div>
);

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:          { padding: 24, maxWidth: 900, margin: '0 auto' },
  title:         { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 20px' },
  balanceCard:   { background: 'linear-gradient(135deg, #1c1a0a 0%, #0f172a 100%)', border: '1px solid #f59e0b55', borderRadius: 12, padding: '24px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 16 },
  balanceLabel:  { fontSize: 13, color: '#fbbf24', fontWeight: 600, marginBottom: 4 },
  balanceValue:  { fontSize: 36, fontWeight: 800, color: '#f1f5f9' },
  depositBtn:    { background: '#f59e0b', border: 'none', borderRadius: 8, color: '#0f172a', fontSize: 14, fontWeight: 700, cursor: 'pointer', padding: '10px 18px', display: 'flex', alignItems: 'center', gap: 6 },
  withdrawBtn:   { background: 'transparent', border: '1px solid #f59e0b55', borderRadius: 8, color: '#fbbf24', fontSize: 14, fontWeight: 600, cursor: 'pointer', padding: '10px 18px', display: 'flex', alignItems: 'center', gap: 6 },
  actionCard:    { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 20, marginBottom: 20 },
  cardTitle:     { fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: '0 0 14px' },
  label:         { display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 },
  input:         { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '9px 12px', fontSize: 14, boxSizing: 'border-box' },
  confirmBtn:    { background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer', padding: '9px 20px' },
  cancelBtn:     { background: 'transparent', border: '1px solid #334155', borderRadius: 8, color: '#64748b', fontSize: 14, cursor: 'pointer', padding: '9px 16px' },
  tabs:          { display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid #1e293b', paddingBottom: 0 },
  tab:           { background: 'transparent', border: 'none', borderBottom: '2px solid transparent', color: '#64748b', cursor: 'pointer', fontSize: 14, fontWeight: 500, padding: '10px 16px', textTransform: 'capitalize' },
  tabActive:     { borderBottomColor: '#f59e0b', color: '#fbbf24' },
  statsGrid:     { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 },
  statCard:      { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' },
  txList:        { display: 'flex', flexDirection: 'column', gap: 2 },
  txRow:         { display: 'flex', alignItems: 'center', gap: 14, background: '#1e293b', borderRadius: 8, padding: '12px 16px' },
  subCard:       { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: 20 },
  subRow:        { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  cancelSubBtn:  { background: 'transparent', border: '1px solid #7f1d1d', borderRadius: 6, color: '#f87171', cursor: 'pointer', fontSize: 13, padding: '7px 14px' },
  addMethodBtn:  { background: '#1e3a5f', border: '1px solid #3b82f6', borderRadius: 8, color: '#60a5fa', cursor: 'pointer', fontSize: 14, fontWeight: 600, padding: '10px 18px' },
};

export default Wallet;
