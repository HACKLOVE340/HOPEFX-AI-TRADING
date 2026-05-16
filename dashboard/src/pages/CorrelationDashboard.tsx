/**
 * Multi-Symbol Correlation Dashboard — dashboard version (Tailwind)
 * Wires to: GET /api/analysis/correlation  |  GET /api/analysis/cot
 */
import { useState, useEffect } from 'react'
import { Link2, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react'
import { api } from '../hooks/useApi'

const SYMBOLS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD', 'DXY']



function corrColor(v: number): string {
  if (v >= 0.7)  return 'bg-green-500 text-white'
  if (v >= 0.3)  return 'bg-green-500/40 text-green-300'
  if (v >= -0.3) return 'bg-slate-700 text-slate-300'
  if (v >= -0.7) return 'bg-red-500/40 text-red-300'
  return 'bg-red-500 text-white'
}

interface CotData {
  report_date: string
  net_speculator_long: number
  long_positions: number
  short_positions: number
  sentiment: string
  sentiment_strength: string
  weekly_change: number
  note: string
}

export default function CorrelationDashboard() {
  const [matrix, setMatrix] = useState<Record<string, Record<string, number>>>({})
  const [cot, setCot] = useState<CotData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [window, setWindow] = useState(30)

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const [cm, cd] = await Promise.all([
        api.get(`/api/analysis/correlation?window=${window}`),
        api.get('/api/analysis/cot'),
      ])
      setMatrix(cm.data.matrix ?? cm.data ?? {})
      setCot(cd.data ?? null)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to load correlation data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [window])

  const matrixSymbols = Object.keys(matrix)
  const displaySymbols = matrixSymbols.length > 0 ? matrixSymbols : SYMBOLS

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link2 className="w-7 h-7 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Correlation Dashboard</h1>
            <p className="text-sm text-slate-400">Multi-symbol correlation matrix and COT sentiment proxy.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select value={window} onChange={e => setWindow(Number(e.target.value))}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-300 text-sm focus:outline-none">
            {[14, 30, 60, 90].map(w => <option key={w} value={w}>{w}d window</option>)}
          </select>
          <button onClick={refresh} disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>}

      {/* Correlation matrix */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Pearson Correlation Matrix — {window}-day rolling window
        </h2>
        {loading ? (
          <div className="text-center py-8 text-slate-500 text-sm">Loading correlation data…</div>
        ) : matrixSymbols.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-sm">No correlation data available. Click refresh to load.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="text-xs">
              <thead>
                <tr>
                  <th className="w-24 text-left text-slate-500 pb-2" />
                  {displaySymbols.map(s => (
                    <th key={s} className="px-1 pb-2 text-slate-400 font-medium text-center min-w-[72px]">{s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displaySymbols.map(row => (
                  <tr key={row}>
                    <td className="pr-3 py-1 text-slate-400 font-medium whitespace-nowrap">{row}</td>
                    {displaySymbols.map(col => {
                      const v = matrix[row]?.[col] ?? 0
                      const isDiag = row === col
                      return (
                        <td key={col} className="px-1 py-1 text-center">
                          <div className={`rounded px-2 py-1.5 font-mono font-semibold ${isDiag ? 'bg-slate-700 text-slate-300' : corrColor(v)}`}>
                            {v.toFixed(2)}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center gap-4 mt-4 text-xs text-slate-500">
          <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded bg-green-500" />Strong positive (≥0.7)</div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded bg-slate-700" />Weak (−0.3 to 0.3)</div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded bg-red-500" />Strong negative (≤−0.7)</div>
        </div>
      </div>

      {/* COT proxy */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
          COT Proxy — Gold Speculator Sentiment
        </h2>
        {!cot ? (
          <div className="text-center py-6 text-slate-500 text-sm">No COT data available.</div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              {[
                { label: 'Net Long',        value: cot.net_speculator_long.toLocaleString(), good: cot.net_speculator_long > 0 },
                { label: 'Long Positions',  value: cot.long_positions.toLocaleString(),      good: true },
                { label: 'Short Positions', value: cot.short_positions.toLocaleString(),     good: false },
                { label: 'Weekly Change',   value: (cot.weekly_change ?? 0) > 0 ? `+${cot.weekly_change?.toLocaleString()}` : (cot.weekly_change ?? 0).toLocaleString(), good: (cot.weekly_change ?? 0) > 0 },
              ].map(({ label, value, good }) => (
                <div key={label} className="bg-slate-800 rounded-lg p-3">
                  <div className="text-xs text-slate-500 mb-1">{label}</div>
                  <div className={`text-lg font-bold ${good ? 'text-green-400' : 'text-red-400'}`}>{value}</div>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-3">
              <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold ${
                cot.sentiment === 'Bullish' ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 'bg-red-500/20 text-red-400 border border-red-500/30'
              }`}>
                {cot.sentiment === 'Bullish' ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                {cot.sentiment} — {cot.sentiment_strength}
              </div>
              <span className="text-xs text-slate-500">Report date: {cot.report_date}</span>
            </div>
            {cot.note && <p className="text-xs text-slate-600 mt-3 italic">{cot.note}</p>}
          </>
        )}
      </div>
    </div>
  )
}
