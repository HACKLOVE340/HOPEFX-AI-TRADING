/**
 * Walk-Forward Optimisation — dashboard version (Tailwind)
 * Wires to: GET /api/backtesting/walk-forward
 */
import { useState, useEffect } from 'react'
import { BarChart2, Play, RefreshCw, CheckCircle, XCircle, Clock } from 'lucide-react'
import { api } from '../hooks/useApi'

interface WFResult {
  window_id: number
  train_start: string
  train_end: string
  test_start: string
  test_end: string
  in_sample_sharpe: number
  out_sample_sharpe: number
  in_sample_accuracy: number
  out_sample_accuracy: number
  trades: number
  passed: boolean
}

interface WFSummary {
  windows: WFResult[]
  avg_oos_sharpe: number
  avg_oos_accuracy: number
  pass_rate: number
  total_trades: number
  status: 'idle' | 'running' | 'complete' | 'error'
  message?: string
}

export default function WalkForward() {
  const [data, setData] = useState<WFSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)

  useEffect(() => {
    const loadLatest = async () => {
      try {
        const res = await api.get('/api/backtesting/walk-forward/latest')
        if (res.data) setData(res.data)
      } catch {
        try {
          const res = await api.get('/api/backtesting/walk-forward')
          if (res.data) setData(res.data)
        } catch {
          // No existing results — show empty state
        }
      }
    }
    loadLatest()
  }, [])

  const runWalkForward = async () => {
    setLoading(true)
    setRunError(null)
    try {
      const res = await api.post('/api/backtesting/walk-forward', { symbol: 'XAU_USD', timeframe: 'H1' })
      setData(res.data)
    } catch {
      setRunError('Walk-forward analysis failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BarChart2 className="w-7 h-7 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Walk-Forward Optimisation</h1>
            <p className="text-sm text-slate-400">Validates strategy robustness across rolling time windows.</p>
          </div>
        </div>
        <button onClick={runWalkForward} disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-slate-900 font-semibold rounded-lg text-sm transition-colors">
          {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          {loading ? 'Running…' : 'Run Walk-Forward'}
        </button>
      </div>

      {runError && (
        <div style={{ background: '#450a0a', border: '1px solid #dc262633', borderRadius: 8, padding: '12px 16px', color: '#f87171' }}>
          ❌ {runError}
        </div>
      )}

      {data ? (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: 'Avg OOS Sharpe',   value: data.avg_oos_sharpe.toFixed(2),  good: data.avg_oos_sharpe >= 1.0 },
              { label: 'Avg OOS Accuracy', value: `${data.avg_oos_accuracy.toFixed(1)}%`, good: data.avg_oos_accuracy >= 60 },
              { label: 'Pass Rate',        value: `${data.pass_rate.toFixed(0)}%`,  good: data.pass_rate >= 70 },
              { label: 'Total Trades',     value: data.total_trades.toString(),     good: data.total_trades >= 200 },
            ].map(({ label, value, good }) => (
              <div key={label} className="bg-slate-900 rounded-xl border border-slate-800 p-4">
                <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">{label}</div>
                <div className={`text-2xl font-bold ${good ? 'text-green-400' : 'text-amber-400'}`}>{value}</div>
              </div>
            ))}
          </div>

          {/* Window table */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-800">
              <h2 className="text-sm font-semibold text-slate-300">Window Results</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800">
                    {['Window', 'Train Period', 'Test Period', 'IS Sharpe', 'OOS Sharpe', 'IS Acc', 'OOS Acc', 'Trades', 'Pass'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.windows.map(w => (
                    <tr key={w.window_id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                      <td className="px-4 py-3 text-slate-300 font-medium">#{w.window_id}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{w.train_start} → {w.train_end}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{w.test_start} → {w.test_end}</td>
                      <td className="px-4 py-3 text-slate-300">{w.in_sample_sharpe.toFixed(2)}</td>
                      <td className={`px-4 py-3 font-semibold ${w.out_sample_sharpe >= 1.0 ? 'text-green-400' : 'text-amber-400'}`}>{w.out_sample_sharpe.toFixed(2)}</td>
                      <td className="px-4 py-3 text-slate-300">{w.in_sample_accuracy.toFixed(1)}%</td>
                      <td className={`px-4 py-3 font-semibold ${w.out_sample_accuracy >= 65 ? 'text-green-400' : 'text-amber-400'}`}>{w.out_sample_accuracy.toFixed(1)}%</td>
                      <td className="px-4 py-3 text-slate-300">{w.trades}</td>
                      <td className="px-4 py-3">
                        {w.passed
                          ? <CheckCircle className="w-4 h-4 text-green-400" />
                          : <XCircle className="w-4 h-4 text-red-400" />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-12 text-center">
          <p className="text-slate-400">No walk-forward results yet. Click <strong className="text-slate-300">Run Walk-Forward</strong> to start.</p>
        </div>
      )}

      {/* Interpretation */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">Interpretation</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm text-slate-400">
          <div className="flex items-start gap-2"><CheckCircle className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" /><span>OOS Sharpe ≥ 1.0 indicates the strategy generalises beyond the training period.</span></div>
          <div className="flex items-start gap-2"><CheckCircle className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" /><span>OOS Accuracy ≥ 65% with p &lt; 0.05 is the minimum bar for live deployment.</span></div>
          <div className="flex items-start gap-2"><Clock className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" /><span>N=238 total trades approaches the 200-trade minimum for SE ≤ ±0.10 on Sharpe.</span></div>
        </div>
      </div>
    </div>
  )
}
