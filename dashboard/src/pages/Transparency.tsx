/**
 * Transparency — Trade Explainability & Decision Audit
 *
 * Exposes the transparency engine:
 * - Full decision tree for every trade (why it was taken)
 * - Factor contribution breakdown (technical, fundamental, ML, sentiment)
 * - Risk assessment reasoning
 * - Confidence decomposition
 * - Historical decision audit trail
 * - Regulatory-grade explainability reports
 *
 * Backend: /api/explain/*, transparency/engine.py
 */
import { useEffect, useState, useCallback } from 'react'
import {
  Eye, Brain, Target, Shield, Activity, Clock,
  ChevronDown, ChevronRight, FileText, Download,
  BarChart2, Layers, Zap, AlertTriangle, CheckCircle,
  RefreshCw, Search,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────
interface TradeDecision {
  id: string
  trade_id: string
  symbol: string
  direction: 'long' | 'short'
  timestamp: string
  overall_confidence: number
  outcome?: 'win' | 'loss' | 'open'
  pnl?: number
  factors: DecisionFactor[]
  risk_assessment: RiskAssessment
  ml_contribution: MLContribution
  final_verdict: string
}

interface DecisionFactor {
  category: 'technical' | 'fundamental' | 'sentiment' | 'ml_model' | 'risk' | 'regime'
  name: string
  signal: 'bullish' | 'bearish' | 'neutral'
  weight: number
  confidence: number
  reasoning: string
  data_points: Record<string, string | number>
}

interface RiskAssessment {
  position_size_reason: string
  sl_placement_reason: string
  tp_placement_reason: string
  risk_reward_ratio: number
  max_risk_pct: number
  correlation_check: string
  prop_firm_compliance: boolean
}

interface MLContribution {
  model_name: string
  prediction_confidence: number
  feature_importances: { feature: string; importance: number }[]
  regime_detected: string
  anomaly_score: number
}

// ── Component ─────────────────────────────────────────────────────────────────
export function Transparency() {
  const [decisions, setDecisions] = useState<TradeDecision[]>([])
  const [selectedDecision, setSelectedDecision] = useState<TradeDecision | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedFactors, setExpandedFactors] = useState<Set<string>>(new Set())

  const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }

  const fetchDecisions = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/explain/decisions?limit=50', { headers })
      if (res.ok) {
        const data = await res.json()
        setDecisions(data.decisions || [])
      }
    } catch (err) {
      console.error('Transparency fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDecisions() }, [fetchDecisions])

  const toggleFactor = (factorId: string) => {
    setExpandedFactors(prev => {
      const next = new Set(prev)
      if (next.has(factorId)) next.delete(factorId)
      else next.add(factorId)
      return next
    })
  }

  const filteredDecisions = decisions.filter(d =>
    d.symbol.toLowerCase().includes(searchQuery.toLowerCase()) ||
    d.trade_id.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const exportReport = async (decisionId: string) => {
    try {
      const res = await fetch(`/api/explain/decisions/${decisionId}/report`, { headers })
      if (res.ok) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `decision_report_${decisionId}.pdf`
        a.click()
      }
    } catch (err) {
      console.error('Export failed:', err)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Trade Transparency</h1>
          <p className="text-sm text-slate-400 mt-1">
            Full explainability for every trading decision — audit-grade reasoning
          </p>
        </div>
        <button onClick={fetchDecisions} className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Decision List */}
        <div className="col-span-4 space-y-3">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search by symbol or trade ID..."
              className="w-full pl-10 pr-4 py-2.5 bg-slate-900 border border-slate-800 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:border-amber-500 focus:outline-none"
            />
          </div>

          {/* List */}
          <div className="space-y-2 max-h-[70vh] overflow-y-auto">
            {filteredDecisions.map(decision => (
              <button
                key={decision.id}
                onClick={() => setSelectedDecision(decision)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  selectedDecision?.id === decision.id
                    ? 'bg-amber-500/10 border-amber-500/30'
                    : 'bg-slate-900 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-slate-200">{decision.symbol}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    decision.direction === 'long' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                  }`}>
                    {decision.direction}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>{decision.timestamp}</span>
                  <span className={`font-medium ${
                    decision.outcome === 'win' ? 'text-green-400' :
                    decision.outcome === 'loss' ? 'text-red-400' : 'text-blue-400'
                  }`}>
                    {decision.outcome === 'open' ? 'Open' : decision.pnl !== undefined ? `${decision.pnl > 0 ? '+' : ''}$${decision.pnl.toFixed(2)}` : '—'}
                  </span>
                </div>
                <div className="mt-1.5 w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div className="h-full bg-amber-400 rounded-full" style={{ width: `${decision.overall_confidence * 100}%` }} />
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Decision Detail */}
        <div className="col-span-8">
          {selectedDecision ? (
            <div className="space-y-4">
              {/* Decision Header */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      selectedDecision.direction === 'long' ? 'bg-green-500/10' : 'bg-red-500/10'
                    }`}>
                      <Zap className={`w-5 h-5 ${selectedDecision.direction === 'long' ? 'text-green-400' : 'text-red-400'}`} />
                    </div>
                    <div>
                      <div className="font-semibold text-slate-200">{selectedDecision.symbol} — {selectedDecision.direction.toUpperCase()}</div>
                      <div className="text-xs text-slate-500">{selectedDecision.timestamp} • ID: {selectedDecision.trade_id}</div>
                    </div>
                  </div>
                  <button
                    onClick={() => exportReport(selectedDecision.id)}
                    className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs transition-colors"
                  >
                    <Download className="w-3.5 h-3.5" /> Export Report
                  </button>
                </div>
                <div className="grid grid-cols-4 gap-4">
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Confidence</div>
                    <div className="text-lg font-bold text-amber-400">{(selectedDecision.overall_confidence * 100).toFixed(0)}%</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Risk:Reward</div>
                    <div className="text-lg font-bold text-slate-200">{selectedDecision.risk_assessment.risk_reward_ratio.toFixed(1)}:1</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Max Risk</div>
                    <div className="text-lg font-bold text-slate-200">{selectedDecision.risk_assessment.max_risk_pct.toFixed(1)}%</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Prop Firm</div>
                    <div className="text-lg font-bold">
                      {selectedDecision.risk_assessment.prop_firm_compliance
                        ? <CheckCircle className="w-5 h-5 text-green-400" />
                        : <AlertTriangle className="w-5 h-5 text-red-400" />}
                    </div>
                  </div>
                </div>
              </div>

              {/* Final Verdict */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
                <h3 className="text-sm font-semibold text-slate-300 mb-2 flex items-center gap-2">
                  <Eye className="w-4 h-4 text-amber-400" /> Decision Summary
                </h3>
                <p className="text-sm text-slate-300 leading-relaxed">{selectedDecision.final_verdict}</p>
              </div>

              {/* Factor Breakdown */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
                <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                  <Layers className="w-4 h-4 text-amber-400" /> Factor Contributions
                </h3>
                <div className="space-y-2">
                  {selectedDecision.factors.map((factor, idx) => {
                    const factorId = `${selectedDecision.id}_${idx}`
                    const isExpanded = expandedFactors.has(factorId)
                    return (
                      <div key={factorId} className="border border-slate-800 rounded-lg overflow-hidden">
                        <button
                          onClick={() => toggleFactor(factorId)}
                          className="w-full flex items-center justify-between p-3 hover:bg-slate-800/50 transition-colors"
                        >
                          <div className="flex items-center gap-3">
                            {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
                            <CategoryIcon category={factor.category} />
                            <span className="text-sm text-slate-200">{factor.name}</span>
                            <SignalBadge signal={factor.signal} />
                          </div>
                          <div className="flex items-center gap-3">
                            <div className="w-20 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                              <div className="h-full bg-amber-400 rounded-full" style={{ width: `${factor.weight * 100}%` }} />
                            </div>
                            <span className="text-xs text-slate-400 w-8 text-right">{(factor.weight * 100).toFixed(0)}%</span>
                          </div>
                        </button>
                        {isExpanded && (
                          <div className="px-4 pb-3 pt-1 border-t border-slate-800">
                            <p className="text-xs text-slate-400 mb-2">{factor.reasoning}</p>
                            <div className="grid grid-cols-3 gap-2">
                              {Object.entries(factor.data_points).map(([key, val]) => (
                                <div key={key} className="bg-slate-800 rounded p-2">
                                  <div className="text-xs text-slate-500">{key}</div>
                                  <div className="text-xs text-slate-200 font-medium">{String(val)}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* ML Contribution */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
                <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                  <Brain className="w-4 h-4 text-purple-400" /> ML Model Contribution
                </h3>
                <div className="grid grid-cols-3 gap-4 mb-4">
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Model</div>
                    <div className="text-sm font-medium text-slate-200">{selectedDecision.ml_contribution.model_name}</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Regime</div>
                    <div className="text-sm font-medium text-slate-200 capitalize">{selectedDecision.ml_contribution.regime_detected}</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="text-xs text-slate-500">Anomaly Score</div>
                    <div className={`text-sm font-medium ${selectedDecision.ml_contribution.anomaly_score > 0.5 ? 'text-red-400' : 'text-green-400'}`}>
                      {selectedDecision.ml_contribution.anomaly_score.toFixed(2)}
                    </div>
                  </div>
                </div>
                {/* Feature Importances */}
                <div className="space-y-1.5">
                  {selectedDecision.ml_contribution.feature_importances.slice(0, 8).map(fi => (
                    <div key={fi.feature} className="flex items-center gap-3">
                      <span className="text-xs text-slate-400 w-32 truncate">{fi.feature}</span>
                      <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div className="h-full bg-purple-400 rounded-full" style={{ width: `${fi.importance * 100}%` }} />
                      </div>
                      <span className="text-xs text-slate-500 w-10 text-right">{(fi.importance * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Risk Assessment */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
                <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                  <Shield className="w-4 h-4 text-green-400" /> Risk Assessment Reasoning
                </h3>
                <div className="space-y-3 text-sm">
                  <ReasoningRow label="Position Size" value={selectedDecision.risk_assessment.position_size_reason} />
                  <ReasoningRow label="Stop Loss" value={selectedDecision.risk_assessment.sl_placement_reason} />
                  <ReasoningRow label="Take Profit" value={selectedDecision.risk_assessment.tp_placement_reason} />
                  <ReasoningRow label="Correlation" value={selectedDecision.risk_assessment.correlation_check} />
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-12 text-center">
              <Eye className="w-12 h-12 text-slate-600 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-slate-300 mb-2">Select a Decision</h3>
              <p className="text-sm text-slate-500">Choose a trade decision from the list to view its full explainability breakdown</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function CategoryIcon({ category }: { category: string }) {
  const icons: Record<string, typeof Brain> = {
    technical: Activity,
    fundamental: BarChart2,
    sentiment: Eye,
    ml_model: Brain,
    risk: Shield,
    regime: Layers,
  }
  const Icon = icons[category] || Activity
  return <Icon className="w-3.5 h-3.5 text-slate-400" />
}

function SignalBadge({ signal }: { signal: string }) {
  const styles: Record<string, string> = {
    bullish: 'bg-green-500/10 text-green-400',
    bearish: 'bg-red-500/10 text-red-400',
    neutral: 'bg-slate-500/10 text-slate-400',
  }
  return <span className={`text-xs px-1.5 py-0.5 rounded ${styles[signal] || styles.neutral}`}>{signal}</span>
}

function ReasoningRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 p-2 bg-slate-800 rounded-lg">
      <span className="text-xs text-slate-500 w-24 shrink-0">{label}</span>
      <span className="text-xs text-slate-300">{value}</span>
    </div>
  )
}
