/**
 * Whitelabel / Reseller Admin — dashboard version (Tailwind)
 * Wires to: GET /api/whitelabel/tenants  |  POST /api/whitelabel/tenants
 */
import { useState, useEffect } from 'react'
import { Tag, Plus, Globe, Users, DollarSign, Settings, Copy, Check, Trash2 } from 'lucide-react'
import axios from 'axios'

interface Tenant {
  id: string
  name: string
  domain: string
  plan: 'starter' | 'professional' | 'enterprise' | 'elite'
  users: number
  revenue_usd: number
  status: 'active' | 'suspended' | 'trial'
  created_at: string
  branding: { primary_color: string; logo_url: string }
}

const PLAN_COLORS: Record<string, string> = {
  starter:      'bg-slate-500/20 text-slate-400 border-slate-500/30',
  professional: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  enterprise:   'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  elite:        'bg-amber-500/20 text-amber-400 border-amber-500/30',
}

const STATUS_COLORS: Record<string, string> = {
  active:    'bg-green-500/20 text-green-400',
  suspended: 'bg-red-500/20 text-red-400',
  trial:     'bg-purple-500/20 text-purple-400',
}

export default function WhitelabelAdmin() {
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDomain, setNewDomain] = useState('')
  const [newPlan, setNewPlan] = useState<'starter' | 'professional' | 'enterprise' | 'elite'>('starter')
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await axios.get('/api/whitelabel/tenants')
      setTenants(r.data.tenants ?? r.data ?? [])
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to load tenants.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const addTenant = async () => {
    if (!newName.trim() || !newDomain.trim()) return
    try {
      const res = await axios.post('/api/whitelabel/tenants', { name: newName, domain: newDomain, plan: newPlan })
      setTenants(prev => [...prev, res.data.tenant ?? res.data])
      setNewName(''); setNewDomain(''); setShowAdd(false)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to create tenant.')
    }
  }

  const copyApiKey = (id: string) => {
    navigator.clipboard.writeText(`hopefx_wl_${id}_${Math.random().toString(36).slice(2, 10)}`)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const totalRevenue = tenants.reduce((s, t) => s + t.revenue_usd, 0)
  const totalUsers   = tenants.reduce((s, t) => s + t.users, 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Tag className="w-7 h-7 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Whitelabel Admin</h1>
            <p className="text-sm text-slate-400">Manage reseller tenants, branding, and API keys.</p>
          </div>
        </div>
        <button onClick={() => setShowAdd(s => !s)}
          className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-900 font-semibold rounded-lg text-sm transition-colors">
          <Plus className="w-4 h-4" />
          Add Tenant
        </button>
      </div>

      {error && <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>}
      {loading && <div className="text-center py-8 text-slate-500 text-sm">Loading tenants…</div>}

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { icon: Users,       label: 'Total Tenants', value: tenants.length.toString() },
          { icon: Globe,       label: 'Total Users',   value: totalUsers.toLocaleString() },
          { icon: DollarSign,  label: 'MRR',           value: `$${totalRevenue.toLocaleString()}` },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Icon className="w-4 h-4 text-amber-400" />
              <span className="text-xs text-slate-500 uppercase tracking-wider">{label}</span>
            </div>
            <div className="text-2xl font-bold text-slate-100">{value}</div>
          </div>
        ))}
      </div>

      {/* Add tenant form */}
      {showAdd && (
        <div className="bg-slate-900 rounded-xl border border-amber-500/30 p-6 space-y-4">
          <h2 className="text-sm font-semibold text-amber-400 uppercase tracking-wider">New Tenant</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-slate-500 mb-1">Tenant Name</label>
              <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="AlphaFX Pro"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500" />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Domain</label>
              <input value={newDomain} onChange={e => setNewDomain(e.target.value)} placeholder="app.example.com"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500" />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Plan</label>
              <select value={newPlan} onChange={e => setNewPlan(e.target.value as typeof newPlan)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none">
                <option value="starter">Starter</option>
                <option value="professional">Professional</option>
                <option value="enterprise">Enterprise</option>
                <option value="elite">Elite</option>
              </select>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={addTenant}
              className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-900 font-semibold rounded-lg text-sm transition-colors">
              Create Tenant
            </button>
            <button onClick={() => setShowAdd(false)}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Tenant table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-slate-300">Tenants</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                {['Tenant', 'Domain', 'Plan', 'Users', 'Revenue', 'Status', 'Actions'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tenants.map(t => (
                <tr key={t.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold text-white"
                        style={{ background: t.branding.primary_color }}>
                        {t.name[0]}
                      </div>
                      <span className="font-medium text-slate-200">{t.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs font-mono">{t.domain}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full border capitalize ${PLAN_COLORS[t.plan]}`}>{t.plan}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-300">{t.users}</td>
                  <td className="px-4 py-3 text-slate-300">${t.revenue_usd.toLocaleString()}/mo</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${STATUS_COLORS[t.status]}`}>{t.status}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button onClick={() => copyApiKey(t.id)} title="Copy API key"
                        className="p-1.5 text-slate-500 hover:text-amber-400 transition-colors">
                        {copiedId === t.id ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
                      </button>
                      <button title="Settings"
                        className="p-1.5 text-slate-500 hover:text-blue-400 transition-colors">
                        <Settings className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => setTenants(prev => prev.filter(x => x.id !== t.id))} title="Remove"
                        className="p-1.5 text-slate-500 hover:text-red-400 transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
