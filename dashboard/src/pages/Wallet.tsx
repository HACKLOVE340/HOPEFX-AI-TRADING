import { useState } from 'react'
import { Wallet as WalletIcon, ArrowDownLeft, ArrowUpRight, History, CreditCard } from 'lucide-react'

const TRANSACTIONS = [
  { id: 1, type: 'deposit', amount: 10000, status: 'completed', date: '2024-01-15', method: 'Bank Transfer' },
  { id: 2, type: 'subscription', amount: -99, status: 'completed', date: '2024-01-14', method: 'Pro Plan' },
  { id: 3, type: 'copy_fee', amount: -234.50, status: 'completed', date: '2024-01-13', method: 'Performance Fee' },
  { id: 4, type: 'withdrawal', amount: -5000, status: 'pending', date: '2024-01-12', method: 'Crypto' },
]

export function Wallet() {
  const [activeTab, setActiveTab] = useState('overview')
  const balance = 24765.50

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Wallet & Payments</h2>

      {/* Balance Card */}
      <div className="bg-gradient-to-r from-amber-500/20 to-amber-600/10 rounded-lg border border-amber-500/30 p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-amber-400 text-sm font-medium mb-1">Available Balance</p>
            <h3 className="text-4xl font-bold">${balance.toLocaleString()}</h3>
            <p className="text-slate-400 text-sm mt-1">
              Frozen: $0.00 • Pending: $500.00
            </p>
          </div>
          <div className="flex gap-3">
            <button className="flex items-center gap-2 px-4 py-2 bg-amber-500 text-slate-950 rounded-lg font-medium hover:bg-amber-400">
              <ArrowDownLeft className="w-4 h-4" />
              Deposit
            </button>
            <button className="flex items-center gap-2 px-4 py-2 border border-amber-500/50 text-amber-400 rounded-lg font-medium hover:bg-amber-500/10">
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
            <div className="text-2xl font-bold">$45,000.00</div>
          </div>
          
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 bg-red-500/10 rounded">
                <ArrowUpRight className="w-5 h-5 text-red-400" />
              </div>
              <span className="text-slate-400">Total Withdrawn</span>
            </div>
            <div className="text-2xl font-bold">$20,234.50</div>
          </div>
          
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 bg-amber-500/10 rounded">
                <WalletIcon className="w-5 h-5 text-amber-400" />
              </div>
              <span className="text-slate-400">Trading P&L</span>
            </div>
            <div className="text-2xl font-bold text-green-400">+$4,000.00</div>
          </div>
        </div>
      )}

      {activeTab === 'transactions' && (
        <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
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
              {TRANSACTIONS.map((tx) => (
                <tr key={tx.id}>
                  <td className="px-6 py-4 capitalize">{tx.type.replace('_', ' ')}</td>
                  <td className="px-6 py-4 text-slate-400">{tx.method}</td>
                  <td className={`px-6 py-4 text-right font-medium ${
                    tx.amount > 0 ? 'text-green-400' : 'text-slate-200'
                  }`}>
                    {tx.amount > 0 ? '+' : ''}{tx.amount.toFixed(2)}
                  </td>
                  <td className="px-6 py-4 text-center">
                    <span className={`px-2 py-1 rounded text-xs ${
                      tx.status === 'completed' 
                        ? 'bg-green-500/10 text-green-400' 
                        : 'bg-amber-500/10 text-amber-400'
                    }`}>
                      {tx.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right text-slate-400">{tx.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'subscriptions' && (
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="font-semibold">Current Plan: Pro</h3>
              <p className="text-slate-400 text-sm">Renews on Feb 14, 2024</p>
            </div>
            <span className="px-3 py-1 bg-amber-500/10 text-amber-400 rounded-full text-sm">
              $99/month
            </span>
          </div>
          
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="w-5 h-5 rounded-full bg-green-500/20 flex items-center justify-center">
                <div className="w-2 h-2 rounded-full bg-green-400" />
              </div>
              <span>Advanced ML Models</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-5 h-5 rounded-full bg-green-500/20 flex items-center justify-center">
                <div className="w-2 h-2 rounded-full bg-green-400" />
              </div>
              <span>Copy Trading (5 leaders)</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-5 h-5 rounded-full bg-green-500/20 flex items-center justify-center">
                <div className="w-2 h-2 rounded-full bg-green-400" />
              </div>
              <span>Priority Support</span>
            </div>
          </div>
          
          <div className="flex gap-3 mt-6">
            <button className="px-4 py-2 bg-slate-800 rounded-lg hover:bg-slate-700">
              Upgrade to Elite
            </button>
            <button className="px-4 py-2 border border-slate-700 rounded-lg hover:bg-slate-800">
              Cancel Subscription
            </button>
          </div>
        </div>
      )}

      {activeTab === 'payment-methods' && (
        <div className="space-y-4">
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-blue-500/10 rounded-lg">
                <CreditCard className="w-6 h-6 text-blue-400" />
              </div>
              <div>
                <p className="font-medium">•••• 4242</p>
                <p className="text-sm text-slate-400">Expires 12/25</p>
              </div>
            </div>
            <span className="px-2 py-1 bg-green-500/10 text-green-400 text-xs rounded">
              Default
            </span>
          </div>
          
          <button className="w-full py-3 border border-dashed border-slate-700 rounded-lg text-slate-400 hover:border-slate-500 hover:text-slate-300">
            + Add Payment Method
          </button>
        </div>
      )}
    </div>
  )
}
