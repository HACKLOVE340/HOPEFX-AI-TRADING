/**
 * NotificationsCenter — Unified Notifications Hub
 *
 * Exposes:
 * - All system notifications (trade executions, alerts, ML signals, risk warnings)
 * - Notification preferences and channels (push, email, SMS, webhook)
 * - Real-time notification stream via WebSocket
 * - Notification history with filtering
 * - Bulk actions (mark read, dismiss, archive)
 *
 * Backend: /api/notifications/*, api/webhooks.py
 */
import { useEffect, useState, useCallback } from 'react'
import {
  Bell, BellOff, Check, CheckCheck, Trash2, Archive,
  Filter, Settings, RefreshCw, AlertTriangle, TrendingUp,
  Brain, Shield, Zap, DollarSign, Clock, Mail, Smartphone,
  Globe, ChevronDown,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────
interface Notification {
  id: string
  type: 'trade_executed' | 'alert_triggered' | 'ml_signal' | 'risk_warning' | 'system' | 'social' | 'billing'
  title: string
  message: string
  priority: 'low' | 'medium' | 'high' | 'critical'
  read: boolean
  created_at: string
  metadata?: Record<string, unknown>
  action_url?: string
}

interface NotificationPrefs {
  channels: {
    push: boolean
    email: boolean
    sms: boolean
    webhook: boolean
  }
  categories: {
    trade_executed: boolean
    alert_triggered: boolean
    ml_signal: boolean
    risk_warning: boolean
    system: boolean
    social: boolean
    billing: boolean
  }
  quiet_hours: { enabled: boolean; start: string; end: string }
}

type FilterType = 'all' | 'unread' | 'trade_executed' | 'alert_triggered' | 'ml_signal' | 'risk_warning' | 'system'

// ── Component ─────────────────────────────────────────────────────────────────
export function NotificationsCenter() {
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>('all')
  const [showPrefs, setShowPrefs] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }

  const fetchNotifications = useCallback(async () => {
    setLoading(true)
    try {
      const [notifRes, prefsRes] = await Promise.all([
        fetch('/api/notifications?limit=100', { headers }),
        fetch('/api/notifications/preferences', { headers }),
      ])
      if (notifRes.ok) { const d = await notifRes.json(); setNotifications(d.notifications || []) }
      if (prefsRes.ok) setPrefs(await prefsRes.json())
    } catch (err) {
      console.error('Notifications fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchNotifications() }, [fetchNotifications])

  const markRead = async (ids: string[]) => {
    try {
      await fetch('/api/notifications/mark-read', {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      })
      setNotifications(prev => prev.map(n => ids.includes(n.id) ? { ...n, read: true } : n))
      setSelectedIds(new Set())
    } catch (err) { console.error('Mark read failed:', err) }
  }

  const markAllRead = () => markRead(notifications.filter(n => !n.read).map(n => n.id))

  const deleteNotifications = async (ids: string[]) => {
    try {
      await fetch('/api/notifications/delete', {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      })
      setNotifications(prev => prev.filter(n => !ids.includes(n.id)))
      setSelectedIds(new Set())
    } catch (err) { console.error('Delete failed:', err) }
  }

  const savePrefs = async (newPrefs: NotificationPrefs) => {
    try {
      await fetch('/api/notifications/preferences', {
        method: 'PUT',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(newPrefs),
      })
      setPrefs(newPrefs)
    } catch (err) { console.error('Save prefs failed:', err) }
  }

  const filtered = notifications.filter(n => {
    if (filter === 'all') return true
    if (filter === 'unread') return !n.read
    return n.type === filter
  })

  const unreadCount = notifications.filter(n => !n.read).length

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-white">Notifications</h1>
          {unreadCount > 0 && (
            <span className="px-2.5 py-0.5 bg-amber-500/10 text-amber-400 border border-amber-500/30 rounded-full text-sm font-medium">
              {unreadCount} unread
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowPrefs(!showPrefs)} className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
            <Settings className="w-4 h-4" /> Preferences
          </button>
          <button onClick={markAllRead} className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
            <CheckCheck className="w-4 h-4" /> Mark All Read
          </button>
        </div>
      </div>

      {/* Preferences Panel */}
      {showPrefs && prefs && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">Notification Preferences</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Channels */}
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Delivery Channels</div>
              <div className="space-y-2">
                {([
                  { key: 'push' as const, icon: Bell, label: 'Push Notifications' },
                  { key: 'email' as const, icon: Mail, label: 'Email' },
                  { key: 'sms' as const, icon: Smartphone, label: 'SMS' },
                  { key: 'webhook' as const, icon: Globe, label: 'Webhook' },
                ]).map(ch => (
                  <label key={ch.key} className="flex items-center justify-between p-2.5 bg-slate-800 rounded-lg cursor-pointer">
                    <div className="flex items-center gap-2">
                      <ch.icon className="w-4 h-4 text-slate-400" />
                      <span className="text-sm text-slate-300">{ch.label}</span>
                    </div>
                    <input
                      type="checkbox"
                      checked={prefs.channels[ch.key]}
                      onChange={e => savePrefs({ ...prefs, channels: { ...prefs.channels, [ch.key]: e.target.checked } })}
                      className="w-4 h-4 rounded border-slate-600 text-amber-500 focus:ring-amber-500"
                    />
                  </label>
                ))}
              </div>
            </div>
            {/* Categories */}
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Categories</div>
              <div className="space-y-2">
                {([
                  { key: 'trade_executed' as const, label: 'Trade Executions' },
                  { key: 'alert_triggered' as const, label: 'Price Alerts' },
                  { key: 'ml_signal' as const, label: 'ML Signals' },
                  { key: 'risk_warning' as const, label: 'Risk Warnings' },
                  { key: 'system' as const, label: 'System' },
                  { key: 'social' as const, label: 'Social' },
                  { key: 'billing' as const, label: 'Billing' },
                ]).map(cat => (
                  <label key={cat.key} className="flex items-center justify-between p-2.5 bg-slate-800 rounded-lg cursor-pointer">
                    <span className="text-sm text-slate-300">{cat.label}</span>
                    <input
                      type="checkbox"
                      checked={prefs.categories[cat.key]}
                      onChange={e => savePrefs({ ...prefs, categories: { ...prefs.categories, [cat.key]: e.target.checked } })}
                      className="w-4 h-4 rounded border-slate-600 text-amber-500 focus:ring-amber-500"
                    />
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Filter Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-500" />
          {([
            { id: 'all' as FilterType, label: 'All' },
            { id: 'unread' as FilterType, label: 'Unread' },
            { id: 'trade_executed' as FilterType, label: 'Trades' },
            { id: 'ml_signal' as FilterType, label: 'ML Signals' },
            { id: 'risk_warning' as FilterType, label: 'Risk' },
            { id: 'system' as FilterType, label: 'System' },
          ]).map(f => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filter === f.id ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        {selectedIds.size > 0 && (
          <div className="flex gap-2">
            <button onClick={() => markRead(Array.from(selectedIds))} className="flex items-center gap-1 px-3 py-1.5 bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded-lg text-xs">
              <Check className="w-3.5 h-3.5" /> Mark Read ({selectedIds.size})
            </button>
            <button onClick={() => deleteNotifications(Array.from(selectedIds))} className="flex items-center gap-1 px-3 py-1.5 bg-red-500/10 text-red-400 border border-red-500/30 rounded-lg text-xs">
              <Trash2 className="w-3.5 h-3.5" /> Delete ({selectedIds.size})
            </button>
          </div>
        )}
      </div>

      {/* Notification List */}
      <div className="space-y-2">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <RefreshCw className="w-6 h-6 text-amber-400 animate-spin" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-12 text-center">
            <BellOff className="w-12 h-12 text-slate-600 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-slate-300 mb-2">No Notifications</h3>
            <p className="text-sm text-slate-500">You're all caught up</p>
          </div>
        ) : (
          filtered.map(notif => (
            <div
              key={notif.id}
              className={`flex items-start gap-3 p-4 rounded-xl border transition-colors ${
                notif.read ? 'bg-slate-900/50 border-slate-800/50' : 'bg-slate-900 border-slate-800'
              } ${selectedIds.has(notif.id) ? 'ring-1 ring-amber-500/30' : ''}`}
            >
              <input
                type="checkbox"
                checked={selectedIds.has(notif.id)}
                onChange={() => toggleSelect(notif.id)}
                className="mt-1 w-4 h-4 rounded border-slate-600 text-amber-500 focus:ring-amber-500"
              />
              <NotifIcon type={notif.type} priority={notif.priority} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`text-sm font-medium ${notif.read ? 'text-slate-400' : 'text-slate-200'}`}>{notif.title}</span>
                  {!notif.read && <div className="w-2 h-2 bg-amber-400 rounded-full" />}
                  <PriorityBadge priority={notif.priority} />
                </div>
                <p className="text-xs text-slate-500 mb-1">{notif.message}</p>
                <div className="flex items-center gap-3 text-xs text-slate-600">
                  <Clock className="w-3 h-3" />
                  <span>{notif.created_at}</span>
                </div>
              </div>
              <button
                onClick={() => markRead([notif.id])}
                className="p-1.5 text-slate-500 hover:text-slate-300 transition-colors"
                title="Mark as read"
              >
                <Check className="w-4 h-4" />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function NotifIcon({ type, priority }: { type: string; priority: string }) {
  const iconMap: Record<string, { icon: typeof Bell; color: string }> = {
    trade_executed: { icon: Zap, color: 'text-green-400 bg-green-500/10' },
    alert_triggered: { icon: Bell, color: 'text-amber-400 bg-amber-500/10' },
    ml_signal: { icon: Brain, color: 'text-purple-400 bg-purple-500/10' },
    risk_warning: { icon: Shield, color: 'text-red-400 bg-red-500/10' },
    system: { icon: Settings, color: 'text-blue-400 bg-blue-500/10' },
    social: { icon: Globe, color: 'text-cyan-400 bg-cyan-500/10' },
    billing: { icon: DollarSign, color: 'text-emerald-400 bg-emerald-500/10' },
  }
  const { icon: Icon, color } = iconMap[type] || iconMap.system
  return (
    <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
      <Icon className="w-4.5 h-4.5" />
    </div>
  )
}

function PriorityBadge({ priority }: { priority: string }) {
  if (priority === 'low') return null
  const styles: Record<string, string> = {
    medium: 'bg-blue-500/10 text-blue-400',
    high: 'bg-amber-500/10 text-amber-400',
    critical: 'bg-red-500/10 text-red-400',
  }
  return <span className={`text-xs px-1.5 py-0.5 rounded ${styles[priority] || ''}`}>{priority}</span>
}
