/**
 * Billing — Subscription & Payment Management
 *
 * Exposes:
 * - Current subscription plan and usage
 * - Payment history and invoices
 * - Plan upgrade/downgrade
 * - Payment method management
 * - Usage metrics (API calls, trades, signals)
 * - Referral/affiliate earnings
 *
 * Backend: /api/billing/*, /api/payments/*, monetization/payment_processor.py
 */
import { useEffect, useState, useCallback } from 'react'
import {
  CreditCard, DollarSign, TrendingUp, Calendar, Download,
  CheckCircle, AlertTriangle, Crown, Zap, Shield, Star,
  RefreshCw, ExternalLink, Plus, ArrowUpRight,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────
interface Subscription {
  plan_id: string
  plan_name: string
  status: 'active' | 'trialing' | 'past_due' | 'cancelled'
  current_period_start: string
  current_period_end: string
  amount: number
  currency: string
  interval: 'monthly' | 'yearly'
  features: string[]
}

interface PaymentMethod {
  id: string
  type: 'card' | 'crypto' | 'bank'
  last4: string
  brand?: string
  exp_month?: number
  exp_year?: number
  is_default: boolean
}

interface Invoice {
  id: string
  amount: number
  currency: string
  status: 'paid' | 'pending' | 'failed'
  created_at: string
  pdf_url: string
  description: string
}

interface UsageMetrics {
  api_calls: { used: number; limit: number }
  trades_executed: { used: number; limit: number }
  ml_predictions: { used: number; limit: number }
  strategies_active: { used: number; limit: number }
  storage_mb: { used: number; limit: number }
}

interface Plan {
  id: string
  name: string
  price_monthly: number
  price_yearly: number
  features: string[]
  popular?: boolean
  current?: boolean
}

// ── Component ─────────────────────────────────────────────────────────────────
export function Billing() {
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [methods, setMethods] = useState<PaymentMethod[]>([])
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [usage, setUsage] = useState<UsageMetrics | null>(null)
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)
  const [billingInterval, setBillingInterval] = useState<'monthly' | 'yearly'>('monthly')

  const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [subRes, methodsRes, invoicesRes, usageRes, plansRes] = await Promise.all([
        fetch('/api/billing/subscription', { headers }),
        fetch('/api/billing/payment-methods', { headers }),
        fetch('/api/billing/invoices', { headers }),
        fetch('/api/billing/usage', { headers }),
        fetch('/api/billing/plans', { headers }),
      ])
      if (subRes.ok) setSubscription(await subRes.json())
      if (methodsRes.ok) { const d = await methodsRes.json(); setMethods(d.methods || []) }
      if (invoicesRes.ok) { const d = await invoicesRes.json(); setInvoices(d.invoices || []) }
      if (usageRes.ok) setUsage(await usageRes.json())
      if (plansRes.ok) { const d = await plansRes.json(); setPlans(d.plans || []) }
    } catch (err) {
      console.error('Billing fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const changePlan = async (planId: string) => {
    try {
      await fetch('/api/billing/change-plan', {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: planId, interval: billingInterval }),
      })
      await fetchAll()
    } catch (err) { console.error('Plan change failed:', err) }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <RefreshCw className="w-6 h-6 text-amber-400 animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Billing & Subscription</h1>
          <p className="text-sm text-slate-400 mt-1">Manage your plan, payments, and usage</p>
        </div>
      </div>

      {/* Current Plan */}
      {subscription && (
        <div className="bg-gradient-to-r from-amber-500/10 to-amber-600/5 rounded-xl border border-amber-500/20 p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-amber-500/20 rounded-xl flex items-center justify-center">
                <Crown className="w-6 h-6 text-amber-400" />
              </div>
              <div>
                <div className="text-lg font-bold text-slate-200">{subscription.plan_name}</div>
                <div className="text-sm text-slate-400">
                  ${subscription.amount}/{subscription.interval === 'monthly' ? 'mo' : 'yr'} •
                  Renews {subscription.current_period_end}
                </div>
              </div>
            </div>
            <div className={`px-3 py-1 rounded-full text-sm font-medium ${
              subscription.status === 'active' ? 'bg-green-500/10 text-green-400 border border-green-500/30' :
              subscription.status === 'trialing' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/30' :
              subscription.status === 'past_due' ? 'bg-red-500/10 text-red-400 border border-red-500/30' :
              'bg-slate-500/10 text-slate-400 border border-slate-500/30'
            }`}>
              {subscription.status}
            </div>
          </div>
        </div>
      )}

      {/* Usage Metrics */}
      {usage && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <UsageCard label="API Calls" used={usage.api_calls.used} limit={usage.api_calls.limit} />
          <UsageCard label="Trades" used={usage.trades_executed.used} limit={usage.trades_executed.limit} />
          <UsageCard label="ML Predictions" used={usage.ml_predictions.used} limit={usage.ml_predictions.limit} />
          <UsageCard label="Strategies" used={usage.strategies_active.used} limit={usage.strategies_active.limit} />
          <UsageCard label="Storage (MB)" used={usage.storage_mb.used} limit={usage.storage_mb.limit} />
        </div>
      )}

      {/* Plans */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold text-slate-200">Available Plans</h2>
          <div className="flex items-center gap-2 bg-slate-800 rounded-lg p-1">
            <button
              onClick={() => setBillingInterval('monthly')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                billingInterval === 'monthly' ? 'bg-amber-500/10 text-amber-400' : 'text-slate-400'
              }`}
            >
              Monthly
            </button>
            <button
              onClick={() => setBillingInterval('yearly')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                billingInterval === 'yearly' ? 'bg-amber-500/10 text-amber-400' : 'text-slate-400'
              }`}
            >
              Yearly <span className="text-green-400 ml-1">-20%</span>
            </button>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {plans.map(plan => (
            <div key={plan.id} className={`rounded-xl border p-5 ${
              plan.popular ? 'border-amber-500/30 bg-amber-500/5' :
              plan.current ? 'border-green-500/30 bg-green-500/5' :
              'border-slate-800 bg-slate-800/50'
            }`}>
              {plan.popular && (
                <div className="text-xs font-semibold text-amber-400 mb-2 flex items-center gap-1">
                  <Star className="w-3 h-3" /> Most Popular
                </div>
              )}
              <h3 className="text-lg font-bold text-slate-200">{plan.name}</h3>
              <div className="mt-2 mb-4">
                <span className="text-3xl font-bold text-slate-100">
                  ${billingInterval === 'monthly' ? plan.price_monthly : plan.price_yearly}
                </span>
                <span className="text-slate-500 text-sm">/{billingInterval === 'monthly' ? 'mo' : 'yr'}</span>
              </div>
              <ul className="space-y-2 mb-5">
                {plan.features.map(f => (
                  <li key={f} className="flex items-center gap-2 text-xs text-slate-300">
                    <CheckCircle className="w-3.5 h-3.5 text-green-400 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              {plan.current ? (
                <button disabled className="w-full py-2.5 bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg text-sm font-medium">
                  Current Plan
                </button>
              ) : (
                <button
                  onClick={() => changePlan(plan.id)}
                  className="w-full py-2.5 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg text-sm font-semibold transition-colors"
                >
                  {plan.price_monthly > (subscription?.amount || 0) ? 'Upgrade' : 'Downgrade'}
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Payment Methods */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-slate-200">Payment Methods</h2>
          <button className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs transition-colors">
            <Plus className="w-3.5 h-3.5" /> Add Method
          </button>
        </div>
        <div className="space-y-2">
          {methods.map(method => (
            <div key={method.id} className="flex items-center justify-between p-3 bg-slate-800 rounded-lg">
              <div className="flex items-center gap-3">
                <CreditCard className="w-5 h-5 text-slate-400" />
                <div>
                  <div className="text-sm text-slate-200">
                    {method.brand ? `${method.brand} ` : ''}{method.type === 'crypto' ? 'Crypto Wallet' : `•••• ${method.last4}`}
                  </div>
                  {method.exp_month && (
                    <div className="text-xs text-slate-500">Expires {method.exp_month}/{method.exp_year}</div>
                  )}
                </div>
              </div>
              {method.is_default && (
                <span className="text-xs px-2 py-0.5 bg-green-500/10 text-green-400 border border-green-500/30 rounded">Default</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Invoice History */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800">
          <h2 className="text-lg font-semibold text-slate-200">Invoice History</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-800">
              <th className="px-6 py-3 text-left">Date</th>
              <th className="px-6 py-3 text-left">Description</th>
              <th className="px-6 py-3 text-left">Amount</th>
              <th className="px-6 py-3 text-left">Status</th>
              <th className="px-6 py-3 text-center">Invoice</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {invoices.map(inv => (
              <tr key={inv.id} className="border-b border-slate-800/50">
                <td className="px-6 py-3 text-slate-400">{inv.created_at}</td>
                <td className="px-6 py-3 text-slate-200">{inv.description}</td>
                <td className="px-6 py-3 text-slate-200">${inv.amount.toFixed(2)} {inv.currency.toUpperCase()}</td>
                <td className="px-6 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    inv.status === 'paid' ? 'bg-green-500/10 text-green-400' :
                    inv.status === 'pending' ? 'bg-amber-500/10 text-amber-400' :
                    'bg-red-500/10 text-red-400'
                  }`}>{inv.status}</span>
                </td>
                <td className="px-6 py-3 text-center">
                  <a href={inv.pdf_url} target="_blank" rel="noreferrer" className="text-amber-400 hover:text-amber-300">
                    <Download className="w-4 h-4 inline" />
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function UsageCard({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit > 0 ? (used / limit) * 100 : 0
  const color = pct > 90 ? 'bg-red-400' : pct > 70 ? 'bg-amber-400' : 'bg-green-400'
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className="text-lg font-bold text-slate-200">{used.toLocaleString()}<span className="text-xs text-slate-500 font-normal">/{limit === -1 ? '∞' : limit.toLocaleString()}</span></div>
      <div className="mt-2 w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </div>
  )
}
