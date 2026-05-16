/**
 * A/B Strategy Testing — dashboard version (Tailwind)
 * Wires to: GET /api/advanced/ab-tests  |  POST /api/advanced/ab-test
 */
import { useState, useEffect } from 'react'
import { FlaskConical, Play, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { api } from '../hooks/useApi'

interface StrategyResult {
  name: string
  sharpe: number
  win_rate: number
  total_trades: number
  max_drawdown: number
  avg_return_pct: number
  p_value: number
  winner: boolean
}

const STRATEGIES = [
  'MovingAverageCrossover', 'RSIStrategy', 'MACDStrategy',
  'BollingerBands', 'SMCICTStrategy', 'EMAcrossover',
  'MeanReversion', 'Breakout', 'Stochastic',
]

const Delta = ({ a, b, fmt = (v: number) => v.toFixed(2) }: { a: number; b: number; fmt?: (v: number) => string }) => {
  const d = a - b
  if (Math.abs(d) < 0.001) return <Minus className="w-3 h-3 text-slate-500 inline" />
  return <span className={d > 0 ? 'text-green-400' : 'text-red-400'}>{d > 0 ? '+' : ''}{fmt(d)}</span>
}

export default function ABTesting() {
  const [results, setResults] = useState<StrategyResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([STRATEGIES[0], STRATEGIES[1]])

  // Load existing test results on mount
  useEffect(() => {
    api.get('/api/advanced/ab-tests')
      .then(r => {
        const data = r.data.tests ?? r.data ?? []
        if (Array.isArray(data) && data.length > 0) {
          const flat: StrategyResult[] = []
          for (const test of data) {
            if (test.strategy_a) flat.push({ ...test.strategy_a, p_value: test.p_value ?? 1, winner: test.winner === test.strategy_a?.strategy })
            if (test.strategy_b) flat.push({ ...test.strategy_b, p_value: test.p_value ?? 1, winner: test.winner === test.strategy_b?.strategy })
          }
          if (flat.length > 0) setResults(flat)
        }
      })
      .catch(() => { /* No prior results — start empty */ })
  }, [])

  const run = async () => {
    if (selected.length < 2) { setError('Select at least 2 strategies to compare.'); return }
    setLoading(true)
    setError(null)
    try {
      const res = await api.post('/api/advanced/ab-test', {
        strategy_a: selected[0],
        strategy_b: selected[1],
        symbol: 'XAU/USD',
        days: 30,
      })
      const test = res.data
      const flat: StrategyResult[] = []
      if (test.strategy_a) flat.push({ ...test.strategy_a, p_value: test.p_value ?? 1, winner: test.winner === test.strategy_a?.strategy })
      if (test.strategy_b) flat.push({ ...test.strategy_b, p_value: test.p_value ?? 1, winner: test.winner === test.strategy_b?.strategy })
      if (flat.length > 0) setResults(flat)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'A/B test failed — check server logs.')
    } finally {
      setLoading(false)
    }
  }

  const winner = results.find(r => r.winner)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FlaskConical className="w-7 h-7 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">A/B Strategy Testing</h1>
            <p className="text-sm text-slate-400">Compare strategies on the same historical data with statistical significance.</p>
          </div>
        </div>
        <button onClick={run} disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-slate-900 font-semibold rounded-lg text-sm transition-colors">
          {loading ? <><span className="w-4 h-4 border-2 border-slate-900/30 border-t-slate-900 rounded-full animate-spin" />Running…</> : <><Play className="w-4 h-4" />Run Test</>}
        </button>
      </div>

      {/* Strategy selector */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 flex flex-wrap gap-3 items-center">
        <span className="text-sm text-slate-400 font-medium">Compare:</span>
        {STRATEGIES.map(s => (
          <button key={s} onClick={() => setSelected(prev =>
            prev.includes(s) ? prev.filter(x => x !== s) : [...prev.slice(-1), s]
          )}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              selected.includes(s)
                ? 'bg-amber-500/20 border-amber-500/50 text-amber-300'
                : 'bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-500'
            }`}>
            {s}
          </button>
        ))}
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>
      )}

      {results.length === 0 && !loading && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-12 text-center text-slate-500">
          Select strategies above and click <span className="text-amber-400 font-medium">Run Test</span> to compare.
        </div>
      )}

      {/* Winner banner */}
      {winner && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4 flex items-center gap-3">
          <TrendingUp className="w-5 h-5 text-green-400 flex-shrink-0" />
          <div>
            <span className="font-semibold text-green-400">Winner: {winner.name}</span>
            <span className="text-sm text-slate-400 ml-2">Sharpe {winner.sharpe.toFixed(2)} · p={winner.p_value.toFixed(4)} · {winner.total_trades} trades</span>
          </div>
        </div>
      )}

      {/* Comparison table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-slate-300">Strategy Comparison</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                {['Strategy', 'Sharpe', 'Win Rate', 'Trades', 'Max DD', 'Avg Return', 'p-value', 'Sig.'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map(r => (
                <tr key={r.name} className={`border-b border-slate-800/50 transition-colors ${r.winner ? 'bg-green-500/5' : 'hover:bg-slate-800/30'}`}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {r.winner && <span className="w-2 h-2 rounded-full bg-green-400 flex-shrink-0" />}
                      <span className={`font-medium ${r.winner ? 'text-green-400' : 'text-slate-300'}`}>{r.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={r.sharpe >= 1.5 ? 'text-green-400 font-semibold' : r.sharpe >= 1.0 ? 'text-amber-400' : 'text-red-400'}>
                      {r.sharpe.toFixed(2)}
                    </span>
                    {!r.winner && winner && <span className="text-xs text-slate-600 ml-1">(<Delta a={r.sharpe} b={winner.sharpe} />)</span>}
                  </td>
                  <td className="px-4 py-3 text-slate-300">{r.win_rate.toFixed(1)}%</td>
                  <td className="px-4 py-3 text-slate-300">{r.total_trades}</td>
                  <td className={`px-4 py-3 ${r.max_drawdown < 5 ? 'text-green-400' : 'text-amber-400'}`}>{r.max_drawdown.toFixed(1)}%</td>
                  <td className="px-4 py-3 text-slate-300">{r.avg_return_pct.toFixed(2)}%</td>
                  <td className="px-4 py-3 text-slate-400 font-mono text-xs">{r.p_value.toFixed(4)}</td>
                  <td className="px-4 py-3">
                    {r.p_value < 0.05
                      ? <span className="text-xs bg-green-500/20 text-green-400 border border-green-500/30 px-2 py-0.5 rounded-full">p&lt;0.05</span>
                      : <span className="text-xs bg-slate-700 text-slate-500 px-2 py-0.5 rounded-full">n.s.</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Notes */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">Statistical Notes</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm text-slate-400">
          <div className="flex items-start gap-2"><TrendingUp className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" /><span>p&lt;0.05 means the result is unlikely due to chance (one-sided binomial test on OOS accuracy).</span></div>
          <div className="flex items-start gap-2"><TrendingDown className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" /><span>Sharpe SE = 1/√(2(N−1)). At N=48, SE=±0.21 — treat Sharpe as indicative, not definitive.</span></div>
          <div className="flex items-start gap-2"><Minus className="w-4 h-4 text-slate-500 mt-0.5 flex-shrink-0" /><span>All strategies tested on the same OOS period to prevent data snooping bias.</span></div>
          <div className="flex items-start gap-2"><Minus className="w-4 h-4 text-slate-500 mt-0.5 flex-shrink-0" /><span>Target N≥600 trades for SE≤±0.029 (statistically trustworthy Sharpe).</span></div>
        </div>
      </div>
    </div>
  )
}
