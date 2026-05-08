/**
 * Wallet & Payments — balance overview, transaction history, subscriptions,
 * and saved payment methods.
 *
 * Mobile-first: balance card stacks on xs, tabs scroll horizontally,
 * transaction rows wrap gracefully on small screens.
 *
 * Wires to: GET  /api/billing/balance
 *           GET  /api/billing/transactions
 *           GET  /api/billing/subscription
 *           GET  /api/billing/payment-methods
 *           POST /api/payments/deposit
 *           POST /api/payments/withdraw
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { PageHeader } from '../components/PageHeader';
import { MetricCard } from '../components/MetricCard';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { Spinner } from '../components/Spinner';
import { extractApiError } from '../lib/utils';



// ── Types ─────────────────────────────────────────────────────────────────────

interface Transaction {
  id: number;
  type: 'deposit' | 'withdrawal' | 'subscription' | 'copy_fee' | 'refund';
  amount: number;
  status: 'completed' | 'pending' | 'failed';
  date: string;
  method: string;
}

interface Subscription {
  tier: string;
  status: string;
  renewal_date: string | null;
  price_monthly: number | null;
  features: string[];
}

interface PaymentMethod {
  id: string;
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  is_default: boolean;
}

const TYPE_ICON: Record<string, string> = {
  deposit: '↓', withdrawal: '↑', subscription: '🔄', copy_fee: '📊', refund: '↩',
};
const TYPE_COLOR: Record<string, string> = {
  deposit: '#4ade80', withdrawal: '#f87171', subscription: '#94a3b8',
  copy_fee: '#fbbf24', refund: '#60a5fa',
};
const STATUS_COLOR: Record<string, string> = {
  completed: '#4ade80', pending: '#fbbf24', failed: '#f87171',
};

type WalletTab = 'overview' | 'transactions' | 'subscriptions' | 'payment-methods';

// ── Sub-components ────────────────────────────────────────────────────────────

const AmountForm: React.FC<{
  mode: 'deposit' | 'withdraw';
  onConfirm: (amount: string) => Promise<void>;
  onCancel: () => void;
}> = ({ mode, onConfirm, onCancel }) => {
  const [amount, setAmount] = useState('');
  const [busy, setBusy]     = useState(false);
  const [msg, setMsg]       = useState('');

  const handle = async () => {
    if (!amount || isNaN(Number(amount)) || Number(amount) <= 0) {
      setMsg('Enter a valid amount.'); return;
    }
    setBusy(true); setMsg('');
    try { await onConfirm(amount); }
    catch (e) { setMsg(extractApiError(e, `${mode === 'deposit' ? 'Deposit' : 'Withdrawal'} failed.`)); }
    finally { setBusy(false); }
  };

  return (
    <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-6 mb-4">
      <h3 className="text-slate-100 text-base font-semibold mb-4 mt-0">
        {mode === 'deposit' ? 'Deposit Funds' : 'Withdraw Funds'}
      </h3>
      <label className="block text-slate-400 text-xs font-semibold uppercase tracking-wider mb-1.5">
        Amount (USD)
      </label>
      <input
        type="number"
        min="1"
        value={amount}
        onChange={e => setAmount(e.target.value)}
        placeholder="e.g. 1000"
        className="w-full bg-terminal-raised border border-terminal-border rounded-lg px-3 py-2.5 text-slate-200 text-sm outline-none focus:border-blue-500 transition-colors mb-3"
      />
      {/* Quick-amount chips */}
      <div className="flex gap-2 flex-wrap mb-4">
        {['100', '500', '1000', '5000'].map(v => (
          <button key={v} onClick={() => setAmount(v)}
            className={`px-3 py-1 rounded-lg text-xs font-semibold border cursor-pointer transition-colors ${
              amount === v
                ? 'bg-blue-500/20 border-blue-500 text-blue-400'
                : 'bg-terminal-raised border-terminal-border text-slate-500 hover:text-slate-300'
            }`}>
            ${v}
          </button>
        ))}
      </div>
      {msg && (
        <div className={`text-xs rounded px-3 py-2 mb-3 ${
          msg.includes('failed') || msg.includes('valid')
            ? 'bg-red-950/40 border border-red-900 text-red-400'
            : 'bg-green-950/40 border border-green-900 text-green-400'
        }`}>{msg}</div>
      )}
      <div className="flex gap-2">
        <button
          onClick={handle}
          disabled={busy || !amount}
          className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold cursor-pointer transition-colors disabled:opacity-50 border-0"
        >
          {busy ? 'Processing…' : 'Confirm'}
        </button>
        <button
          onClick={onCancel}
          className="px-5 py-2.5 bg-terminal-raised border border-terminal-border text-slate-400 rounded-lg text-sm font-semibold cursor-pointer hover:border-slate-500 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const Wallet: React.FC = () => {
  const [tab, setTab]                   = useState<WalletTab>('overview');
  const [balance, setBalance]           = useState(0);
  const [frozen, setFrozen]             = useState(0);
  const [pendingBal, setPendingBal]     = useState(0);
  const [balanceLoading, setBalanceLoading] = useState(true);
  const [balanceErr, setBalanceErr]     = useState('');
  const [transactions, setTxs]          = useState<Transaction[]>([]);
  const [txLoading, setTxLoading]       = useState(true);
  const [txErr, setTxErr]               = useState('');
  const [subscription, setSub]          = useState<Subscription | null>(null);
  const [subLoading, setSubLoading]     = useState(true);
  const [subErr, setSubErr]             = useState('');
  const [paymentMethods, setPMs]        = useState<PaymentMethod[]>([]);
  const [pmLoading, setPmLoading]       = useState(true);
  const [pmErr, setPmErr]               = useState('');
  const [actionMode, setActionMode]     = useState<'deposit' | 'withdraw' | null>(null);
  const [actionMsg, setActionMsg]       = useState('');
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();

    api.get<{ balance: number; frozen: number; pending: number }>(
      '/billing/balance', { signal: ctrl.signal })
      .then(r => { setBalance(r.data?.balance ?? 0); setFrozen(r.data?.frozen ?? 0); setPendingBal(r.data?.pending ?? 0); })
      .catch(e => { if ((e as {name?:string}).name !== 'CanceledError') setBalanceErr(extractApiError(e, 'Failed to load balance.')); })
      .finally(() => { if (mountedRef.current) setBalanceLoading(false); });

    api.get<{ transactions: Transaction[] } | Transaction[]>(
      '/billing/transactions', { signal: ctrl.signal })
      .then(r => { const d = Array.isArray(r.data) ? r.data : (r.data as {transactions:Transaction[]}).transactions ?? []; setTxs(d); })
      .catch(e => { if ((e as {name?:string}).name !== 'CanceledError') setTxErr(extractApiError(e, 'Failed to load transactions.')); })
      .finally(() => { if (mountedRef.current) setTxLoading(false); });

    api.get<Subscription>('/billing/subscription', { signal: ctrl.signal })
      .then(r => setSub(r.data ?? null))
      .catch(e => { if ((e as {name?:string}).name !== 'CanceledError') setSubErr(extractApiError(e, 'Failed to load subscription.')); })
      .finally(() => { if (mountedRef.current) setSubLoading(false); });

    api.get<{ methods: PaymentMethod[] } | PaymentMethod[]>(
      '/billing/payment-methods', { signal: ctrl.signal })
      .then(r => { const d = Array.isArray(r.data) ? r.data : (r.data as {methods:PaymentMethod[]}).methods ?? []; setPMs(d); })
      .catch(e => { if ((e as {name?:string}).name !== 'CanceledError') setPmErr(extractApiError(e, 'Failed to load payment methods.')); })
      .finally(() => { if (mountedRef.current) setPmLoading(false); });

    return () => ctrl.abort();
  }, []);

  const handleDeposit = useCallback(async (amount: string) => {
    await api.post('/payments/deposit', { amount: parseFloat(amount) });
    setActionMsg(`Deposit of $${amount} initiated.`);
    setActionMode(null);
    // Refresh balance
    const r = await api.get<{ balance: number; frozen: number; pending: number }>('/billing/balance');
    setBalance(r.data?.balance ?? balance);
    setFrozen(r.data?.frozen ?? frozen);
    setPendingBal(r.data?.pending ?? pendingBal);
  }, [balance, frozen, pendingBal]);

  const handleWithdraw = useCallback(async (amount: string) => {
    await api.post('/payments/withdraw', { amount: parseFloat(amount) });
    setActionMsg(`Withdrawal of $${amount} submitted.`);
    setActionMode(null);
    const r = await api.get<{ balance: number; frozen: number; pending: number }>('/billing/balance');
    setBalance(r.data?.balance ?? balance);
    setFrozen(r.data?.frozen ?? frozen);
    setPendingBal(r.data?.pending ?? pendingBal);
  }, [balance, frozen, pendingBal]);

  const totalDeposited = transactions.filter(t => t.type === 'deposit').reduce((s, t) => s + t.amount, 0);
  const totalWithdrawn = Math.abs(transactions.filter(t => t.type === 'withdrawal').reduce((s, t) => s + t.amount, 0));
  const totalFees      = Math.abs(transactions.filter(t => ['subscription','copy_fee'].includes(t.type)).reduce((s, t) => s + t.amount, 0));

  const TABS: { id: WalletTab; label: string; icon: string }[] = [
    { id: 'overview',         label: 'Overview',         icon: '📊' },
    { id: 'transactions',     label: 'Transactions',     icon: '📋' },
    { id: 'subscriptions',    label: 'Subscription',     icon: '⭐' },
    { id: 'payment-methods',  label: 'Payment Methods',  icon: '💳' },
  ];

  return (
    <div className="max-w-4xl mx-auto px-3 sm:px-6 py-4 sm:py-8">
      <PageHeader
        title="Wallet & Payments"
        icon="💰"
        subtitle="Manage your balance, transactions, subscriptions, and payment methods"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Account',   href: '/settings' },
          { label: 'Wallet' },
        ]}
        actions={
          <div className="flex gap-2 flex-wrap">
            <Link to="/trade"
              className="px-3 py-1.5 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-xs font-bold no-underline hover:bg-green-500/20 transition-colors">
              ⚡ Trade
            </Link>
            <Link to="/pricing"
              className="px-3 py-1.5 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-xs font-bold no-underline hover:bg-amber-500/20 transition-colors">
              ⭐ Upgrade
            </Link>
          </div>
        }
      />

      <CrossLinkBar links={[
        { label: '🤝 Affiliate', href: '/affiliate', color: '#4ade80' },
        { label: '🪪 KYC',       href: '/kyc',        color: '#60a5fa' },
        { label: '⚙️ Settings', href: '/settings',   color: '#a78bfa' },
        { label: '📋 Pricing',   href: '/pricing',    color: '#fbbf24' },
        { label: '💼 Portfolio', href: '/portfolio',  color: '#34d399' },
      ]} className="mb-5" />

      {balanceErr && <ErrorBanner message={balanceErr} onDismiss={() => setBalanceErr('')} />}

      {/* Balance hero card */}
      <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-6 mb-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="text-slate-500 text-xs font-semibold uppercase tracking-wider mb-1">
              Available Balance
            </div>
            {balanceLoading ? (
              <div className="flex items-center gap-3">
                <Spinner size="sm" />
                <span className="text-slate-500 text-sm">Loading wallet…</span>
              </div>
            ) : (
              <>
                <div className="text-3xl sm:text-4xl font-black text-amber-400 tabular-nums tracking-tight">
                  ${balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </div>
                <div className="text-slate-500 text-xs mt-1.5 flex gap-3 flex-wrap">
                  <span>Frozen: <span className="text-slate-400">${frozen.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span></span>
                  <span>Pending: <span className="text-slate-400">${pendingBal.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span></span>
                </div>
              </>
            )}
          </div>
          <div className="flex gap-2 sm:flex-shrink-0">
            <button
              onClick={() => { setActionMode('deposit'); setActionMsg(''); }}
              className="flex-1 sm:flex-none px-5 py-2.5 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm font-bold cursor-pointer transition-colors border-0"
            >
              ↓ Deposit
            </button>
            <button
              onClick={() => { setActionMode('withdraw'); setActionMsg(''); }}
              className="flex-1 sm:flex-none px-5 py-2.5 bg-terminal-raised border border-terminal-border text-slate-300 rounded-lg text-sm font-bold cursor-pointer hover:border-slate-500 transition-colors"
            >
              ↑ Withdraw
            </button>
          </div>
        </div>
      </div>

      {/* Action success message */}
      {actionMsg && (
        <div className="bg-green-950/40 border border-green-900 rounded-lg px-4 py-3 text-green-400 text-sm mb-4">
          {actionMsg}
          <button onClick={() => setActionMsg('')} className="ml-3 text-green-600 hover:text-green-400 bg-transparent border-0 cursor-pointer text-base leading-none">×</button>
        </div>
      )}

      {/* Deposit / Withdraw form */}
      {actionMode && (
        <AmountForm
          mode={actionMode}
          onConfirm={actionMode === 'deposit' ? handleDeposit : handleWithdraw}
          onCancel={() => setActionMode(null)}
        />
      )}

      {/* Tabs — horizontal scroll on mobile */}
      <div className="flex overflow-x-auto border-b border-terminal-border mb-5 gap-0"
        style={{ scrollbarWidth: 'none', WebkitOverflowScrolling: 'touch' } as React.CSSProperties}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-3 sm:px-4 py-2.5 text-xs sm:text-sm font-medium whitespace-nowrap cursor-pointer transition-colors bg-transparent border-0 border-b-2 ${
              tab === t.id
                ? 'text-blue-400 border-b-blue-500'
                : 'text-slate-500 border-b-transparent hover:text-slate-300'
            }`}
            style={{ borderBottom: tab === t.id ? '2px solid #3b82f6' : '2px solid transparent' }}
          >
            <span className="text-xs">{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </div>

      {/* ── Overview ── */}
      {tab === 'overview' && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <MetricCard icon="↓" label="Total Deposited"
            value={`$${totalDeposited.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
            accent="green" />
          <MetricCard icon="↑" label="Total Withdrawn"
            value={`$${totalWithdrawn.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
            accent="red" />
          <MetricCard icon="💸" label="Total Fees Paid"
            value={`$${totalFees.toFixed(2)}`}
            accent="amber" />
        </div>
      )}

      {/* ── Transactions ── */}
      {tab === 'transactions' && (
        <div>
          {txLoading && (
            <div className="flex justify-center py-12"><Spinner size="lg" /></div>
          )}
          {!txLoading && txErr && <ErrorBanner message={txErr} onDismiss={() => setTxErr('')} />}
          {!txLoading && !txErr && transactions.length === 0 && (
            <EmptyState icon="📋" title="No transactions yet"
              description="Your deposits, withdrawals, and subscription payments will appear here." />
          )}
          {!txLoading && transactions.map(tx => (
            <div key={tx.id}
              className="flex items-center gap-3 sm:gap-4 bg-terminal-surface border border-terminal-border rounded-xl px-3 sm:px-4 py-3 mb-2 hover:border-slate-600 transition-colors">
              {/* Icon */}
              <div className="w-9 h-9 rounded-full flex items-center justify-center text-base flex-shrink-0"
                style={{ background: `${TYPE_COLOR[tx.type]}22`, color: TYPE_COLOR[tx.type] }}>
                {TYPE_ICON[tx.type]}
              </div>
              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="text-slate-200 text-sm font-semibold capitalize">
                  {tx.type.replace('_', ' ')}
                </div>
                <div className="text-slate-500 text-xs mt-0.5 truncate">
                  {tx.method} · {tx.date}
                </div>
              </div>
              {/* Amount + status */}
              <div className="text-right flex-shrink-0">
                <div className={`text-sm font-bold tabular-nums ${tx.amount >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {tx.amount >= 0 ? '+' : ''}${Math.abs(tx.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </div>
                <div className="text-2xs font-semibold capitalize mt-0.5"
                  style={{ color: STATUS_COLOR[tx.status] }}>
                  {tx.status}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Subscription ── */}
      {tab === 'subscriptions' && (
        <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-6">
          {subLoading && <div className="flex justify-center py-8"><Spinner size="md" /></div>}
          {!subLoading && subErr && <ErrorBanner message={subErr} onDismiss={() => setSubErr('')} />}
          {!subLoading && !subErr && !subscription && (
            <EmptyState icon="⭐" title="No active subscription"
              description="Subscribe to unlock AI signals, copy trading, and advanced analytics."
              action={
                <Link to="/pricing"
                  className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold no-underline transition-colors">
                  View Plans
                </Link>
              }
            />
          )}
          {!subLoading && !subErr && subscription && (
            <>
              <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
                <div>
                  <div className="text-slate-100 text-lg font-bold capitalize">{subscription.tier} Plan</div>
                  <div className="text-slate-500 text-sm mt-0.5">
                    {subscription.renewal_date
                      ? `Renews monthly · Next: ${subscription.renewal_date}`
                      : 'No renewal date'}
                  </div>
                </div>
                <div className="text-right sm:flex-shrink-0">
                  {subscription.price_monthly != null && (
                    <div className="text-amber-400 text-xl font-black tabular-nums">
                      ${subscription.price_monthly}/mo
                    </div>
                  )}
                  <div className={`text-xs font-semibold capitalize mt-0.5 ${
                    subscription.status === 'active' ? 'text-green-400' : 'text-amber-400'
                  }`}>
                    {subscription.status}
                  </div>
                </div>
              </div>
              {subscription.features.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
                  {subscription.features.map(f => (
                    <div key={f} className="flex items-center gap-2 text-slate-400 text-sm">
                      <span className="text-green-400 flex-shrink-0">✓</span> {f}
                    </div>
                  ))}
                </div>
              )}
              <div className="border-t border-terminal-border pt-4 flex gap-2 flex-wrap">
                <Link to="/pricing"
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold no-underline transition-colors">
                  Upgrade Plan
                </Link>
                {subscription.status === 'active' && (
                  <button className="px-4 py-2 bg-transparent border border-red-900 text-red-400 rounded-lg text-sm font-semibold cursor-pointer hover:bg-red-950/40 transition-colors">
                    Cancel Subscription
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Payment Methods ── */}
      {tab === 'payment-methods' && (
        <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-6">
          {pmLoading && <div className="flex justify-center py-8"><Spinner size="md" /></div>}
          {!pmLoading && pmErr && <ErrorBanner message={pmErr} onDismiss={() => setPmErr('')} />}
          {!pmLoading && !pmErr && paymentMethods.length === 0 && (
            <EmptyState icon="💳" title="No payment methods saved"
              description="Add a card or crypto wallet to enable deposits and withdrawals." />
          )}
          {!pmLoading && !pmErr && paymentMethods.length > 0 && (
            <div className="flex flex-col gap-2 mb-4">
              {paymentMethods.map(pm => (
                <div key={pm.id}
                  className="flex items-center justify-between gap-3 bg-terminal-raised border border-terminal-border rounded-xl px-4 py-3">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg bg-blue-950 flex items-center justify-center text-lg flex-shrink-0">
                      💳
                    </div>
                    <div>
                      <div className="text-slate-200 text-sm font-semibold capitalize">
                        {pm.brand} •••• {pm.last4}
                      </div>
                      <div className="text-slate-500 text-xs">
                        Expires {pm.exp_month}/{pm.exp_year}
                      </div>
                    </div>
                  </div>
                  {pm.is_default && (
                    <span className="text-2xs font-bold px-2 py-0.5 rounded bg-green-500/10 border border-green-500/30 text-green-400 flex-shrink-0">
                      Default
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          {!pmLoading && (
            <button className="px-4 py-2.5 bg-blue-950 border border-blue-500/40 text-blue-400 rounded-lg text-sm font-semibold cursor-pointer hover:bg-blue-900/40 transition-colors">
              + Add Payment Method
            </button>
          )}
        </div>
      )}

      <CrossLinkBar title="Related" className="mt-8" links={[
        { label: '🤝 Affiliate', href: '/affiliate', color: '#4ade80' },
        { label: '🪪 KYC',       href: '/kyc',        color: '#60a5fa' },
        { label: '⭐ Upgrade',   href: '/pricing',    color: '#fbbf24' },
        { label: '💼 Portfolio', href: '/portfolio',  color: '#34d399' },
        { label: '⚙️ Settings', href: '/settings',   color: '#94a3b8' },
      ]} />
    </div>
  );
};

export default Wallet;
