/**
 * FeedSettings
 *
 * Lets the user opt in/out of the public signal feed.
 * Reads current opt-in state from GET /api/feed/status
 * and writes via POST /api/feed/opt-in | /api/feed/opt-out.
 */
import { useState, useEffect, useCallback } from 'react'
import { Radio, Users, Eye, EyeOff, Loader2, AlertTriangle } from 'lucide-react'
import { useStore } from '../store/useStore'
import { extractApiError } from '../lib/utils'

interface FeedStatus {
  opted_in: boolean
  trader_id: string | null
  signal_count: number
  follower_count: number
}

export function FeedSettings() {
  const token = useStore((s) => s.token)

  const [status, setStatus]     = useState<FeedStatus | null>(null)
  const [loading, setLoading]   = useState(true)
  const [saving, setSaving]     = useState(false)
  const [error, setError]       = useState('')

  const authHeaders = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  const fetchStatus = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/feed/status', { headers: authHeaders })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setStatus(await res.json())
    } catch (e: unknown) {
      setError(extractApiError(e, 'Could not load feed status'))
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  const toggle = async () => {
    if (!status) return
    setSaving(true)
    setError('')
    const endpoint = status.opted_in ? '/api/feed/opt-out' : '/api/feed/opt-in'
    try {
      const res = await fetch(endpoint, { method: 'POST', headers: authHeaders })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await fetchStatus()
    } catch (e: unknown) {
      setError(extractApiError(e, 'Failed to update feed preference'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Signal Feed</h3>
        <p className="text-sm text-slate-400 mt-1">
          Control whether your ML signals are shared on the public feed and leaderboard.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 py-4">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading feed status…</span>
        </div>
      ) : status ? (
        <>
          {/* Opt-in toggle */}
          <div className="flex items-start justify-between gap-4 p-4 rounded-lg border border-slate-700 bg-slate-800/50">
            <div className="flex items-start gap-3">
              <div className={`p-2 rounded-lg mt-0.5 ${status.opted_in ? 'bg-amber-500/10 text-amber-400' : 'bg-slate-700 text-slate-500'}`}>
                <Radio className="w-5 h-5" />
              </div>
              <div>
                <p className="font-medium">
                  {status.opted_in ? 'Sharing signals publicly' : 'Signals are private'}
                </p>
                <p className="text-sm text-slate-400 mt-0.5">
                  {status.opted_in
                    ? 'Your high-confidence ML signals appear on the public feed and leaderboard.'
                    : 'Your signals are only visible to you. Enable to join the community feed.'}
                </p>
              </div>
            </div>
            <button
              onClick={toggle}
              disabled={saving}
              className={`relative inline-flex items-center shrink-0 cursor-pointer ${saving ? 'opacity-60' : ''}`}
              role="switch"
              aria-checked={status.opted_in}
            >
              {saving ? (
                <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
              ) : (
                <div className={`w-11 h-6 rounded-full transition-colors ${status.opted_in ? 'bg-amber-500' : 'bg-slate-700'}`}>
                  <div className={`absolute top-[2px] h-5 w-5 rounded-full bg-white shadow transition-transform ${status.opted_in ? 'translate-x-[22px]' : 'translate-x-[2px]'}`} />
                </div>
              )}
            </button>
          </div>

          {/* Stats — only shown when opted in */}
          {status.opted_in && (
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-800/50 rounded-lg border border-slate-700 p-4">
                <div className="flex items-center gap-2 text-slate-400 text-sm mb-1">
                  <Eye className="w-4 h-4" />
                  Signals shared
                </div>
                <p className="text-2xl font-bold">{status.signal_count.toLocaleString()}</p>
              </div>
              <div className="bg-slate-800/50 rounded-lg border border-slate-700 p-4">
                <div className="flex items-center gap-2 text-slate-400 text-sm mb-1">
                  <Users className="w-4 h-4" />
                  Followers
                </div>
                <p className="text-2xl font-bold">{status.follower_count.toLocaleString()}</p>
              </div>
            </div>
          )}

          {/* Privacy note */}
          <div className="rounded-lg bg-slate-800/30 border border-slate-700/50 p-4 space-y-2 text-sm text-slate-400">
            <div className="flex items-start gap-2">
              {status.opted_in
                ? <Eye className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
                : <EyeOff className="w-4 h-4 shrink-0 mt-0.5" />}
              <span>
                {status.opted_in
                  ? 'Only signals with confidence ≥ 70% are published. Your account balance and trade sizes are never shared.'
                  : 'Opting in shares only signal direction, symbol, and confidence. No personal or financial data is exposed.'}
              </span>
            </div>
            <p className="text-xs text-slate-500 pl-6">
              You can opt out at any time. Existing signals are removed from the feed within 60 seconds.
            </p>
          </div>
        </>
      ) : null}
    </div>
  )
}
