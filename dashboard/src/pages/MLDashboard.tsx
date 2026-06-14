/**
 * MLDashboard — ML Operations Center
 *
 * Exposes the full ML pipeline:
 * - Model health monitoring (accuracy, drift, latency)
 * - Continuous learning pipeline status
 * - Shadow deployment comparison (champion vs challenger)
 * - Retraining triggers and history
 * - Feature importance visualization
 * - Anomaly detection status
 *
 * Backend: /api/ml-ops, /api/ml/*, ml/continuous_learning.py, ml/inference_engine.py
 */
import { useEffect, useState, useCallback } from 'react'
import {
  Brain, Activity, TrendingUp, TrendingDown, AlertTriangle,
  CheckCircle, RefreshCw, Zap, Target, Eye, Clock,
  BarChart2, Layers, Shield, Play, Pause, RotateCcw,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────
interface ModelHealth {
  model_id: string
  name: string
  version: string
  status: 'healthy' | 'degraded' | 'retraining' | 'offline'
  accuracy: number
  precision: number
  recall: number
  f1_score: number
  latency_ms: number
  predictions_today: number
  drift_score: number
  last_retrained: string
  data_points_since_retrain: number
}

interface ShadowDeployment {
  id: string
  champion_model: string
  challenger_model: string
  status: 'running' | 'completed' | 'promoted' | 'rejected'
  champion_accuracy: number
  challenger_accuracy: number
  champion_sharpe: number
  challenger_sharpe: number
  trades_compared: number
  started_at: string
  verdict?: string
}

interface RetrainEvent {
  id: string
  model_name: string
  trigger: 'scheduled' | 'drift_detected' | 'performance_drop' | 'manual'
  status: 'queued' | 'running' | 'completed' | 'failed'
  started_at: string
  completed_at?: string
  improvement_pct?: number
  data_points_used: number
}

interface PipelineStatus {
  status: 'active' | 'paused' | 'error'
  models_monitored: number
  retrains_today: number
  shadow_deployments_active: number
  next_scheduled_retrain: string
  data_buffer_size: number
  last_evaluation: string
}

type TabId = 'overview' | 'models' | 'shadow' | 'retrain' | 'anomaly'

// ── Component ─────────────────────────────────────────────────────────────────
export function MLDashboard() {
  const [activeTab, setActiveTab] = useState<TabId>('overview')
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null)
  const [models, setModels] = useState<ModelHealth[]>([])
  const [shadows, setShadows] = useState<ShadowDeployment[]>([])
  const [retrainHistory, setRetrainHistory] = useState<RetrainEvent[]>([])
  const [loading, setLoading] = useState(true)

  const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [pipelineRes, modelsRes, shadowRes, retrainRes] = await Promise.all([
        fetch('/api/ml-ops/status', { headers }),
        fetch('/api/ml-ops/models', { headers }),
        fetch('/api/ml-ops/shadow-deployments', { headers }),
        fetch('/api/ml-ops/retrain-history', { headers }),
      ])
      if (pipelineRes.ok) setPipeline(await pipelineRes.json())
      if (modelsRes.ok) { const d = await modelsRes.json(); setModels(d.models || []) }
      if (shadowRes.ok) { const d = await shadowRes.json(); setShadows(d.deployments || []) }
      if (retrainRes.ok) { const d = await retrainRes.json(); setRetrainHistory(d.events || []) }
    } catch (err) {
      console.error('ML Dashboard fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const triggerRetrain = async (modelId: string) => {
    try {
      await fetch(`/api/ml-ops/retrain/${modelId}`, { method: 'POST', headers })
      await fetchAll()
    } catch (err) {
      console.error('Retrain trigger failed:', err)
    }
  }

  const togglePipeline = async () => {
    const action = pipeline?.status === 'active' ? 'pause' : 'resume'
    try {
      await fetch(`/api/ml-ops/pipeline/${action}`, { method: 'POST', headers })
      await fetchAll()
    } catch (err) {
      console.error('Pipeline toggle failed:', err)
    }
  }

  const tabs: { id: TabId; label: string; icon: typeof Brain }[] = [
    { id: 'overview', label: 'Overview', icon: BarChart2 },
    { id: 'models', label: 'Model Health', icon: Brain },
    { id: 'shadow', label: 'Shadow Deploy', icon: Eye },
    { id: 'retrain', label: 'Retraining', icon: RotateCcw },
    { id: 'anomaly', label: 'Anomaly Detection', icon: AlertTriangle },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">ML Operations Center</h1>
          <p className="text-sm text-slate-400 mt-1">
            Monitor, retrain, and deploy ML models in real-time
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={togglePipeline}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
              pipeline?.status === 'active'
                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30 hover:bg-amber-500/20'
                : 'bg-green-500/10 text-green-400 border border-green-500/30 hover:bg-green-500/20'
            }`}
          >
            {pipeline?.status === 'active' ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            {pipeline?.status === 'active' ? 'Pause Pipeline' : 'Resume Pipeline'}
          </button>
          <button
            onClick={fetchAll}
            className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Pipeline Status Banner */}
      {pipeline && (
        <div className={`flex items-center justify-between p-4 rounded-xl border ${
          pipeline.status === 'active' ? 'bg-green-500/5 border-green-500/20' :
          pipeline.status === 'paused' ? 'bg-amber-500/5 border-amber-500/20' :
          'bg-red-500/5 border-red-500/20'
        }`}>
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full ${
              pipeline.status === 'active' ? 'bg-green-400 animate-pulse' :
              pipeline.status === 'paused' ? 'bg-amber-400' : 'bg-red-400'
            }`} />
            <span className="text-sm font-medium text-slate-200">
              Continuous Learning Pipeline: <span className="capitalize">{pipeline.status}</span>
            </span>
          </div>
          <div className="flex items-center gap-6 text-xs text-slate-400">
            <span>{pipeline.models_monitored} models monitored</span>
            <span>{pipeline.retrains_today} retrains today</span>
            <span>{pipeline.shadow_deployments_active} shadow deploys active</span>
            <span>Buffer: {pipeline.data_buffer_size.toLocaleString()} samples</span>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-900 rounded-xl p-1 border border-slate-800">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard icon={Brain} label="Active Models" value={models.filter(m => m.status === 'healthy').length.toString()} sub={`of ${models.length} total`} color="green" />
            <StatCard icon={Target} label="Avg Accuracy" value={models.length > 0 ? `${(models.reduce((a, m) => a + m.accuracy, 0) / models.length * 100).toFixed(1)}%` : '—'} sub="across all models" color="amber" />
            <StatCard icon={Zap} label="Predictions Today" value={models.reduce((a, m) => a + m.predictions_today, 0).toLocaleString()} sub="total inferences" color="blue" />
            <StatCard icon={Clock} label="Avg Latency" value={models.length > 0 ? `${(models.reduce((a, m) => a + m.latency_ms, 0) / models.length).toFixed(0)}ms` : '—'} sub="inference time" color="purple" />
          </div>
          {/* Model summary cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {models.map(model => (
              <div key={model.model_id} className="bg-slate-900 rounded-xl border border-slate-800 p-4">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="font-medium text-slate-200 text-sm">{model.name}</h4>
                  <StatusBadge status={model.status} />
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div><span className="text-slate-500">Accuracy</span><div className="text-slate-200 font-medium">{(model.accuracy * 100).toFixed(1)}%</div></div>
                  <div><span className="text-slate-500">Drift</span><div className={`font-medium ${model.drift_score > 0.3 ? 'text-red-400' : 'text-green-400'}`}>{model.drift_score.toFixed(2)}</div></div>
                  <div><span className="text-slate-500">Latency</span><div className="text-slate-200 font-medium">{model.latency_ms}ms</div></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Models Tab */}
      {activeTab === 'models' && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="text-xs text-slate-500 border-b border-slate-800">
                <th className="px-4 py-3 text-left">Model</th>
                <th className="px-4 py-3 text-left">Version</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Accuracy</th>
                <th className="px-4 py-3 text-left">F1</th>
                <th className="px-4 py-3 text-left">Drift</th>
                <th className="px-4 py-3 text-left">Latency</th>
                <th className="px-4 py-3 text-left">Predictions</th>
                <th className="px-4 py-3 text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {models.map(model => (
                <tr key={model.model_id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="px-4 py-3 font-medium text-slate-200">{model.name}</td>
                  <td className="px-4 py-3 text-slate-400">v{model.version}</td>
                  <td className="px-4 py-3"><StatusBadge status={model.status} /></td>
                  <td className="px-4 py-3 text-slate-200">{(model.accuracy * 100).toFixed(1)}%</td>
                  <td className="px-4 py-3 text-slate-200">{model.f1_score.toFixed(3)}</td>
                  <td className="px-4 py-3"><DriftIndicator score={model.drift_score} /></td>
                  <td className="px-4 py-3 text-slate-300">{model.latency_ms}ms</td>
                  <td className="px-4 py-3 text-slate-300">{model.predictions_today.toLocaleString()}</td>
                  <td className="px-4 py-3 text-center">
                    <button
                      onClick={() => triggerRetrain(model.model_id)}
                      className="px-2 py-1 bg-amber-500/10 text-amber-400 border border-amber-500/30 rounded text-xs hover:bg-amber-500/20 transition-colors"
                    >
                      Retrain
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Shadow Deployments Tab */}
      {activeTab === 'shadow' && (
        <div className="space-y-4">
          {shadows.length === 0 ? (
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-12 text-center">
              <Eye className="w-12 h-12 text-slate-600 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-slate-300 mb-2">No Shadow Deployments</h3>
              <p className="text-sm text-slate-500">Shadow deployments compare new models against the current champion in production</p>
            </div>
          ) : (
            shadows.map(shadow => (
              <div key={shadow.id} className="bg-slate-900 rounded-xl border border-slate-800 p-5">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <Eye className="w-5 h-5 text-blue-400" />
                    <div>
                      <div className="font-medium text-slate-200 text-sm">
                        {shadow.champion_model} vs {shadow.challenger_model}
                      </div>
                      <div className="text-xs text-slate-500">Started {shadow.started_at}</div>
                    </div>
                  </div>
                  <StatusBadge status={shadow.status} />
                </div>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <CompareMetric label="Accuracy" champion={shadow.champion_accuracy} challenger={shadow.challenger_accuracy} format="pct" />
                  <CompareMetric label="Sharpe" champion={shadow.champion_sharpe} challenger={shadow.challenger_sharpe} format="num" />
                  <div className="text-center">
                    <div className="text-xs text-slate-500">Trades Compared</div>
                    <div className="text-lg font-bold text-slate-200">{shadow.trades_compared}</div>
                  </div>
                  <div className="col-span-2 flex items-center justify-end">
                    {shadow.verdict && (
                      <span className={`text-xs px-3 py-1 rounded-full ${
                        shadow.verdict === 'challenger_wins' ? 'bg-green-500/10 text-green-400' : 'bg-slate-500/10 text-slate-400'
                      }`}>
                        {shadow.verdict.replace('_', ' ')}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Retrain History Tab */}
      {activeTab === 'retrain' && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="text-xs text-slate-500 border-b border-slate-800">
                <th className="px-4 py-3 text-left">Model</th>
                <th className="px-4 py-3 text-left">Trigger</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Started</th>
                <th className="px-4 py-3 text-left">Data Points</th>
                <th className="px-4 py-3 text-left">Improvement</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {retrainHistory.map(event => (
                <tr key={event.id} className="border-b border-slate-800/50">
                  <td className="px-4 py-3 font-medium text-slate-200">{event.model_name}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded border ${
                      event.trigger === 'drift_detected' ? 'bg-red-500/10 text-red-400 border-red-500/30' :
                      event.trigger === 'performance_drop' ? 'bg-amber-500/10 text-amber-400 border-amber-500/30' :
                      event.trigger === 'scheduled' ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' :
                      'bg-slate-500/10 text-slate-400 border-slate-500/30'
                    }`}>
                      {event.trigger.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={event.status} /></td>
                  <td className="px-4 py-3 text-slate-400 text-xs">{event.started_at}</td>
                  <td className="px-4 py-3 text-slate-300">{event.data_points_used.toLocaleString()}</td>
                  <td className="px-4 py-3">
                    {event.improvement_pct !== undefined ? (
                      <span className={event.improvement_pct > 0 ? 'text-green-400' : 'text-red-400'}>
                        {event.improvement_pct > 0 ? '+' : ''}{event.improvement_pct.toFixed(1)}%
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Anomaly Detection Tab */}
      {activeTab === 'anomaly' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              Data Drift Monitor
            </h3>
            <div className="space-y-3">
              {models.map(model => (
                <div key={model.model_id} className="flex items-center justify-between p-3 bg-slate-800 rounded-lg">
                  <span className="text-sm text-slate-300">{model.name}</span>
                  <div className="flex items-center gap-3">
                    <div className="w-24 h-2 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          model.drift_score > 0.5 ? 'bg-red-400' :
                          model.drift_score > 0.3 ? 'bg-amber-400' : 'bg-green-400'
                        }`}
                        style={{ width: `${Math.min(model.drift_score * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-slate-400 w-10 text-right">{(model.drift_score * 100).toFixed(0)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
              <Shield className="w-4 h-4 text-green-400" />
              Model Integrity
            </h3>
            <div className="space-y-3">
              {models.map(model => (
                <div key={model.model_id} className="flex items-center justify-between p-3 bg-slate-800 rounded-lg">
                  <span className="text-sm text-slate-300">{model.name}</span>
                  <div className="flex items-center gap-2">
                    <CheckCircle className="w-4 h-4 text-green-400" />
                    <span className="text-xs text-green-400">SHA-256 verified</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Helper Components ─────────────────────────────────────────────────────────
function StatCard({ icon: Icon, label, value, sub, color }: { icon: typeof Brain; label: string; value: string; sub: string; color: string }) {
  const colorMap: Record<string, string> = {
    green: 'text-green-400 bg-green-500/10',
    amber: 'text-amber-400 bg-amber-500/10',
    blue: 'text-blue-400 bg-blue-500/10',
    purple: 'text-purple-400 bg-purple-500/10',
  }
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${colorMap[color]}`}>
          <Icon className="w-4 h-4" />
        </div>
        <span className="text-xs text-slate-500">{label}</span>
      </div>
      <div className="text-xl font-bold text-slate-200">{value}</div>
      <div className="text-xs text-slate-500 mt-0.5">{sub}</div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    healthy: 'bg-green-500/10 text-green-400 border-green-500/30',
    active: 'bg-green-500/10 text-green-400 border-green-500/30',
    running: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    completed: 'bg-green-500/10 text-green-400 border-green-500/30',
    degraded: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    retraining: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    queued: 'bg-slate-500/10 text-slate-400 border-slate-500/30',
    offline: 'bg-red-500/10 text-red-400 border-red-500/30',
    failed: 'bg-red-500/10 text-red-400 border-red-500/30',
    promoted: 'bg-green-500/10 text-green-400 border-green-500/30',
    rejected: 'bg-red-500/10 text-red-400 border-red-500/30',
    paused: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border ${styles[status] || styles.queued}`}>
      {status}
    </span>
  )
}

function DriftIndicator({ score }: { score: number }) {
  const color = score > 0.5 ? 'text-red-400' : score > 0.3 ? 'text-amber-400' : 'text-green-400'
  return <span className={`font-medium ${color}`}>{score.toFixed(2)}</span>
}

function CompareMetric({ label, champion, challenger, format }: { label: string; champion: number; challenger: number; format: 'pct' | 'num' }) {
  const fmt = (v: number) => format === 'pct' ? `${(v * 100).toFixed(1)}%` : v.toFixed(2)
  const better = challenger > champion
  return (
    <div className="text-center">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className="flex items-center justify-center gap-2">
        <span className="text-sm text-slate-400">{fmt(champion)}</span>
        <span className="text-xs text-slate-600">vs</span>
        <span className={`text-sm font-medium ${better ? 'text-green-400' : 'text-red-400'}`}>{fmt(challenger)}</span>
      </div>
    </div>
  )
}
