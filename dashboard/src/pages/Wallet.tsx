import { useState, useEffect } from 'react'
import { Wallet as WalletIcon, ArrowDownLeft, ArrowUpRight, CreditCard, RefreshCw } from 'lucide-react'
import { api } from '../hooks/useApi'

interface Transaction {
  id: number | string
  type: string
  amount: number
  status: string
  date: string
  method: string
}

interface Subscription {
  tier: string
  status: string
  renewal_date: string | null
  price_monthly: number | null
  features: string[]
}

interface PaymentMethod {
  id: string
  brand: string
  last4: string
  exp_month: number
  exp_year: number
  is_default: boolean
}

export function Wallet() {
  const [activeTab, setActiveTab] = useState('overview')
  const [balance, setBalance] = useState(0)
  const [frozen, setFrozen] = useState(0)
  const [pending, setPending] = useState(0)
  const [transactions, setTxs] = useState<Transaction[]>([])
  const [subscription, setSub] = useState<Subscription | null>(null)
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethod[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionMsg, setActionMsg] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [bal, txRes, subRes, pmRes] = await Promise.allSettled([
        api.get('/api/billing/balance'),
        api.get('/api/billing/transactions'),
        api.get('/api/billing/subscription'),
        api.get('/api/billing/payment-methods'),
      ])
      if (bal.status === 'fulfilled') {
        setBalance(bal.value.data?.balance ?? 0)
        setFrozen(bal.value.data?.frozen ?? 0)
        setPending(bal.value.data?.pending ?? 0)
      }
      if (txRes.status === 'fulfilled') setTxs(txRes.value.data?.transactions ?? txRes.value.data ?? [])
      if (subRes.status === 'fulfilled') setSub(subRes.value.data)
      if (pmRes.status === 'fulfilled') setPaymentMethods(pmRes.value.data?.methods ?? pmRes.value.data ?? [])
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to load wallet data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const deposit = async () => {
    setActionMsg(null)
    try {
      const res = await api.post('/api/payments/deposit', { amount: 100, method: 'card' })
      setActionMsg(res.data?.message ?? 'Deposit initiated.')
      load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setActionMsg(detail ?? 'Deposit failed.')
    }
  }

  const withdraw = async () => {
    setActionMsg(null)
    try {
      const res = await api.post('/api/payments/withdraw', { amount: 100, destination: 'bank' })
      setActionMsg(res.data?.message ?? 'Withdrawal initiated.')
      load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setActionMsg(detail ?? 'Withdrawal failed.')
    }
  }

  const totalDeposited = transactions.filter(t => t.type === 'deposit').reduce((s, t) => s + Math.abs(t.amount), 0)
  const totalWithdrawn = transactions.filter(t => t.type === 'withdrawal').reduce((s, t) => s + Math.abs(t.amount), 0)
  const tradingPnl = balance - totalDeposited + totalWithdrawn

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Wallet & Payments</h2>
        <button onClick={load} disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>}
      {actionMsg && <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4 text-blue-400 text-sm">{actionMsg}</div>}

      {/* Balance Card */}
      <div className="bg-gradient-to-r from-amber-500/20 to-amber-600/10 rounded-lg border border-amber-500/30 p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-amber-400 text-sm font-medium mb-1">Available Balance</p>
            <h3 className="text-4xl font-bold">${balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</h3>
            <p className="text-slate-400 text-sm mt-1">
              Frozen: ${frozen.toFixed(2)} • Pending: ${pending.toFixed(2)}
            </p>
          </div>
          <div className="flex gap-3">
            <button onClick={deposit} className="flex items-center gap-2 px-4 py-2 bg-amber-500 text-slate-950 rounded-lg font-medium hover:bg-amber-400">
              <ArrowDownLeft className="w-4 h-4" />
              Deposit
            </button>
            <button onClick={withdraw} className="flex items-center gap-2 px-4 py-2 border border-amber-500/50 text-amber-400 rounded-lg font-medium hover:bg-amber-500/10">
              <ArrowUpRight className="w-4 h-4" />
              Withdraw
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-800">
        {['overview', 'transactions', 'subscriptions', 'payment-methods'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-3 text-sm font-medium capitalize border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-amber-500 text-amber-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.replace('-', ' ')}
          </button>
        ))}
      </div>

      {/* Content */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 bg-green-500/10 rounded">
                <ArrowDownLeft className="w-5 h-5 text-green-400" />
              </div>
              <span className="text-slate-400">Total Deposited</span>
            </div>
            <div className="text-2xl font-bold">${totalDeposited.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
          </div>

          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 bg-red-500/10 rounded">
                <ArrowUpRight className="w-5 h-5 text-red-400" />
              </div>
              <span className="text-slate-400">Total Withdrawn</span>
            </div>
            <div className="text-2xl font-bold">${totalWithdrawn.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
          </div>

          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 bg-amber-500/10 rounded">
                <WalletIcon className="w-5 h-5 text-amber-400" />
              </div>
              <span className="text-slate-400">Trading P&L</span>
            </div>
            <div className={`text-2xl font-bold ${tradingPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {tradingPnl >= 0 ? '+' : ''}${tradingPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'transactions' && (
        <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
          {transactions.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-sm">No transactions yet.</div>
          ) : (
            <table className="w-full">
              <thead className="bg-slate-800/50">
                <tr>
                  <th className="px-6 py-3 text-left text-sm font-medium text-slate-400">Type</th>
                  <th className="px-6 py-3 text-left text-sm font-medium text-slate-400">Method</th>
                  <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Amount</th>
                  <th className="px-6 py-3 text-center text-sm font-medium text-slate-400">Status</th>
                  <th className="px-6 py-3 text-right text-sm font-medium text-slate-400">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {transactions.map((tx) => (
                  <tr key={tx.id}>
                    <td className="px-6 py-4 capitalize">{String(tx.type).replace('_', ' ')}</td>
                    <td className="px-6 py-4 text-slate-400">{tx.method}</td>
                    <td className={`px-6 py-4 text-right font-medium ${tx.amount > 0 ? 'text-green-400' : 'text-slate-200'}`}>
                      {tx.amount > 0 ? '+' : ''}{Number(tx.amount).toFixed(2)}
                    </td>
                    <td className="px-6 py-4 text-center">
                      <span className={`px-2 py-1 rounded text-xs ${
                        tx.status === 'completed' ? 'bg-green-500/10 text-green-400' : 'bg-amber-500/10 text-amber-400'
                      }`}>
                        {tx.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right text-slate-400">{tx.date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {activeTab === 'subscriptions' && (
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-6">
          {!subscription ? (
            <div className="text-center py-8 text-slate-500 text-sm">Loading subscription…</div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h3 className="font-semibold capitalize">Current Plan: {subscription.tier}</h3>
                  <p className="text-slate-400 text-sm">
                    {subscription.renewal_date ? `Renews on ${subscription.renewal_date}` : 'No renewal date'}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`px-2 py-1 rounded text-xs ${
                    subscription.status === 'active' ? 'bg-green-500/10 text-green-400' : 'bg-amber-500/10 text-amber-400'
                  }`}>{subscription.status}</span>
                  {subscription.price_monthly != null && (
                    <span className="px-3 py-1 bg-amber-500/10 text-amber-400 rounded-full text-sm">
                      ${subscription.price_monthly}/month
                    </span>
                  )}
                </div>
              </div>

              {subscription.features.length > 0 && (
                <div className="space-y-3 mb-6">
                  {subscription.features.map(f => (
                    <div key={f} className="flex items-center gap-3">
                      <div className="w-5 h-5 rounded-full bg-green-500/20 flex items-center justify-center">
                        <div className="w-2 h-2 rounded-full bg-green-400" />
                      </div>
                      <span>{f}</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex gap-3">
                <button className="px-4 py-2 bg-slate-800 rounded-lg hover:bg-slate-700">
                  Upgrade Plan
                </button>
                {subscription.status === 'active' && (
                  <button className="px-4 py-2 border border-slate-700 rounded-lg hover:bg-slate-800">
                    Cancel Subscription
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {activeTab === 'payment-methods' && (
        <div className="space-y-4">
          {paymentMethods.length === 0 ? (
            <div className="bg-slate-900 rounded-lg border border-slate-800 p-8 text-center text-slate-500 text-sm">
              No payment methods saved.
            </div>
          ) : (
            paymentMethods.map(pm => (
              <div key={pm.id} className="bg-slate-900 rounded-lg border border-slate-800 p-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-blue-500/10 rounded-lg">
                    <CreditCard className="w-6 h-6 text-blue-400" />
                  </div>
                  <div>
                    <p className="font-medium capitalize">{pm.brand} •••• {pm.last4}</p>
                    <p className="text-sm text-slate-400">Expires {pm.exp_month}/{pm.exp_year}</p>
                  </div>
                </div>
                {pm.is_default && (
                  <span className="px-2 py-1 bg-green-500/10 text-green-400 text-xs rounded">Default</span>
                )}
              </div>
            ))
          )}
          <button className="w-full py-3 border border-dashed border-slate-700 rounded-lg text-slate-400 hover:border-slate-500 hover:text-slate-300">
            + Add Payment Method
          </button>
        </div>
      )}
    </div>
  )
}
