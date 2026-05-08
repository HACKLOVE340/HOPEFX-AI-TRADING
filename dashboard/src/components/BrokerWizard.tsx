/**
 * BrokerWizard
 *
 * Guides the user through selecting, configuring, and testing a broker
 * connection. On mount it fetches the current connection status from
 * GET /api/broker/status so the UI reflects the live state.
 */
import { useState, useEffect } from 'react'
import {
  CheckCircle, XCircle, Loader, ExternalLink,
  ChevronRight, RefreshCw, WifiOff, Wifi,
} from 'lucide-react'
import { useStore } from '../store/useStore'
import { extractApiError } from '../lib/utils'

interface BrokerConfig {
  type: string
  apiKey: string
  accountId: string
  practice: boolean
}

interface TestResult {
  ok: boolean
  latency_ms?: number
  balance?: number | string
  currency?: string
  error?: string
}

interface BrokerStatus {
  connected: boolean
  broker_type: string
  balance: number | null
  currency: string | null
  open_positions: number
  error?: string
}

const BROKERS = [
  {
    id: 'paper',
    name: 'Paper Trading',
    description: 'Simulated trading — no real money, no API keys needed',
    fields: [] as string[],
    docsUrl: null,
  },
  {
    id: 'oanda',
    name: 'OANDA',
    description: 'Forex & CFD broker — free practice account available',
    fields: ['apiKey', 'accountId'],
    docsUrl: 'https://developer.oanda.com/rest-live-v20/introduction/',
    keyLabel: 'API Token',
    keyHelp: 'Generate at: OANDA Portal → Manage API Access',
    accountLabel: 'Account ID',
    accountHelp: 'Format: 001-001-XXXXXXX-001 (shown on OANDA dashboard)',
  },
  {
    id: 'alpaca',
    name: 'Alpaca',
    description: 'Commission-free US stocks & crypto',
    fields: ['apiKey', 'accountId'],
    docsUrl: 'https://alpaca.markets/docs/api-documentation/',
    keyLabel: 'API Key ID',
    keyHelp: 'Generate at: Alpaca Dashboard → API Keys',
    accountLabel: 'Secret Key',
    accountHelp: 'Shown once at creation — store it securely',
  },
  {
    id: 'mt5',
    name: 'MetaTrader 5',
    description: 'Connect via MT5 bridge — requires MT5 terminal running locally',
    fields: ['apiKey', 'accountId'],
    docsUrl: 'https://www.mql5.com/en/docs/integration/python_metatrader5',
    keyLabel: 'MT5 Password',
    keyHelp: 'Your MT5 account password',
    accountLabel: 'MT5 Login',
    accountHelp: 'Your MT5 account number (e.g. 12345678)',
    serverField: true,
  },
  {
    id: 'ctrader',
    name: 'cTrader',
    description: 'Connect via cTrader Open API',
    fields: ['apiKey', 'accountId'],
    docsUrl: 'https://help.ctrader.com/open-api/',
    keyLabel: 'Client ID',
    keyHelp: 'From cTrader ID portal → Applications',
    accountLabel: 'Client Secret',
    accountHelp: 'From cTrader ID portal → Applications',
  },
]

type Step = 'status' | 'select' | 'configure' | 'test' | 'done'

export function BrokerWizard() {
  const token = useStore((s) => s.token)

  const [step, setStep]               = useState<Step>('status')
  const [selectedBroker, setSelectedBroker] = useState('paper')
  const [config, setConfig]           = useState<BrokerConfig>({ type: 'paper', apiKey: '', accountId: '', practice: true })
  const [mtServer, setMtServer]       = useState('')
  const [testing, setTesting]         = useState(false)
  const [testResult, setTestResult]   = useState<TestResult | null>(null)
  const [status, setStatus]           = useState<BrokerStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)

  const broker = BROKERS.find((b) => b.id === selectedBroker)!

  // Load current connection status on mount
  useEffect(() => {
    fetchStatus()
  }, [])

  const fetchStatus = async () => {
    setStatusLoading(true)
    try {
      const res = await fetch('/api/broker/status')
      if (res.ok) {
        const data = await res.json()
        setStatus(data.broker ?? data)
      }
    } catch {
      // non-fatal — status stays null
    } finally {
      setStatusLoading(false)
    }
  }

  const handleSelectBroker = (id: string) => {
    setSelectedBroker(id)
    setConfig((c) => ({ ...c, type: id }))
    setTestResult(null)
    setStep(id === 'paper' ? 'test' : 'configure')
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    const start = Date.now()
    try {
      const body: Record<string, unknown> = { ...config }
      if ((broker as any).serverField && mtServer) body.server = mtServer
      const res = await fetch('/api/broker/test-connection', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      const result: TestResult = { ...data, latency_ms: Date.now() - start }
      setTestResult(result)
      if (data.ok) {
        setStep('done')
        fetchStatus() // refresh status card
      }
    } catch (e: unknown) {
      setTestResult({
        ok: false,
        error: extractApiError(e, 'Network error'),
        latency_ms: Date.now() - start,
      })
    } finally {
      setTesting(false)
    }
  }

  const reset = () => {
    setStep('select')
    setTestResult(null)
    setConfig({ type: 'paper', apiKey: '', accountId: '', practice: true })
    setMtServer('')
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Broker Connection</h3>
        <p className="text-sm text-slate-400 mt-1">
          Connect your broker to receive live prices and execute trades.
        </p>
      </div>

      {/* Current status card */}
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-sm font-medium text-slate-300">Current connection</span>
          <button
            onClick={fetchStatus}
            disabled={statusLoading}
            className="text-slate-500 hover:text-slate-300 transition-colors"
            title="Refresh status"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${statusLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        {statusLoading ? (
          <div className="h-5 w-40 bg-slate-700 rounded animate-pulse" />
        ) : status ? (
          <div className="flex items-center gap-2">
            {status.connected ? (
              <Wifi className="w-4 h-4 text-emerald-400" />
            ) : (
              <WifiOff className="w-4 h-4 text-slate-500" />
            )}
            <span className={`text-sm font-medium ${status.connected ? 'text-emerald-400' : 'text-slate-500'}`}>
              {status.connected
                ? `${status.broker_type.toUpperCase()} — ${
                    status.balance != null
                      ? `${Number(status.balance).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${status.currency ?? 'USD'}`
                      : 'connected'
                  }`
                : `Not connected${status.error ? ` (${status.error})` : ''}`}
            </span>
            {status.connected && (
              <button
                onClick={() => setStep('select')}
                className="ml-auto text-xs text-amber-400 hover:text-amber-300"
              >
                Change broker
              </button>
            )}
          </div>
        ) : (
          <span className="text-sm text-slate-500">Status unavailable</span>
        )}
      </div>

      {/* Only show wizard when not already connected, or user clicked Change */}
      {(step !== 'status' || !status?.connected) && (
        <>
          {/* Step indicator */}
          <div className="flex items-center gap-2 text-xs text-slate-500">
            {(['select', 'configure', 'test', 'done'] as const).map((s, i) => (
              <span key={s} className="flex items-center gap-1">
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
                  step === s
                    ? 'bg-amber-500 text-slate-950'
                    : (['select','configure','test','done'] as string[]).indexOf(step) > i
                    ? 'bg-emerald-500 text-white'
                    : 'bg-slate-700 text-slate-400'
                }`}>
                  {i + 1}
                </span>
                <span className={step === s ? 'text-amber-400' : ''}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </span>
                {i < 3 && <ChevronRight className="w-3 h-3" />}
              </span>
            ))}
          </div>

          {/* Step 1: Select */}
          {step === 'select' && (
            <div className="space-y-3">
              {BROKERS.map((b) => (
                <button
                  key={b.id}
                  onClick={() => handleSelectBroker(b.id)}
                  className="w-full flex items-center justify-between p-4 rounded-lg border border-slate-700 hover:border-amber-500/50 hover:bg-amber-500/5 transition-colors text-left"
                >
                  <div>
                    <p className="font-medium">{b.name}</p>
                    <p className="text-sm text-slate-400">{b.description}</p>
                  </div>
                  <ChevronRight className="w-5 h-5 text-slate-500 shrink-0" />
                </button>
              ))}
            </div>
          )}

          {/* Step 2: Configure */}
          {step === 'configure' && broker.fields.length > 0 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <button onClick={() => setStep('select')} className="text-sm text-slate-400 hover:text-slate-200">← Back</button>
                <span className="text-slate-600">/</span>
                <span className="text-sm font-medium">{broker.name}</span>
                {broker.docsUrl && (
                  <a href={broker.docsUrl} target="_blank" rel="noopener noreferrer"
                    className="ml-auto flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300">
                    API Docs <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">
                  {(broker as any).keyLabel ?? 'API Key'}
                </label>
                <input type="password" value={config.apiKey}
                  onChange={(e) => setConfig((c) => ({ ...c, apiKey: e.target.value }))}
                  placeholder="Paste your key here"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-amber-500" />
                {(broker as any).keyHelp && (
                  <p className="text-xs text-slate-500 mt-1">{(broker as any).keyHelp}</p>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">
                  {(broker as any).accountLabel ?? 'Account ID'}
                </label>
                <input type="text" value={config.accountId}
                  onChange={(e) => setConfig((c) => ({ ...c, accountId: e.target.value }))}
                  placeholder={(broker as any).accountHelp ?? 'Account ID'}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-amber-500" />
                {(broker as any).accountHelp && (
                  <p className="text-xs text-slate-500 mt-1">{(broker as any).accountHelp}</p>
                )}
              </div>

              {/* MT5 server field */}
              {(broker as any).serverField && (
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1">MT5 Server</label>
                  <input type="text" value={mtServer}
                    onChange={(e) => setMtServer(e.target.value)}
                    placeholder="e.g. MetaQuotes-Demo"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-amber-500" />
                  <p className="text-xs text-slate-500 mt-1">Shown in MT5 terminal → File → Open an Account</p>
                </div>
              )}

              {/* OANDA practice toggle */}
              {broker.id === 'oanda' && (
                <div className="flex items-center gap-3">
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" className="sr-only peer" checked={config.practice}
                      onChange={(e) => setConfig((c) => ({ ...c, practice: e.target.checked }))} />
                    <div className="w-11 h-6 bg-slate-700 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-amber-500" />
                  </label>
                  <span className="text-sm">
                    {config.practice
                      ? <span className="text-emerald-400">Practice mode (no real money)</span>
                      : <span className="text-red-400 font-medium">⚠ Live mode — real money</span>}
                  </span>
                </div>
              )}

              <button onClick={() => setStep('test')}
                disabled={!config.apiKey || !config.accountId}
                className="w-full py-2.5 bg-amber-500 text-slate-950 rounded-lg font-medium hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed">
                Continue to Test Connection
              </button>
            </div>
          )}

          {/* Step 3: Test */}
          {step === 'test' && (
            <div className="space-y-4">
              <button onClick={() => setStep(broker.fields.length > 0 ? 'configure' : 'select')}
                className="text-sm text-slate-400 hover:text-slate-200">← Back</button>

              <div className="p-4 rounded-lg bg-slate-800 border border-slate-700 text-sm space-y-1">
                <p className="font-medium mb-2">Connection details</p>
                <p className="text-slate-400">Broker: <span className="text-slate-200">{broker.name}</span></p>
                {config.apiKey && (
                  <p className="text-slate-400 font-mono">Key: {config.apiKey.slice(0, 8)}••••••••</p>
                )}
                {config.accountId && (
                  <p className="text-slate-400">Account: <span className="text-slate-200">{config.accountId}</span></p>
                )}
                {broker.id === 'oanda' && (
                  <p className="text-slate-400">Mode: <span className={config.practice ? 'text-emerald-400' : 'text-red-400'}>
                    {config.practice ? 'Practice' : 'Live'}
                  </span></p>
                )}
              </div>

              <button onClick={handleTest} disabled={testing}
                className="w-full py-2.5 bg-amber-500 text-slate-950 rounded-lg font-medium hover:bg-amber-400 disabled:opacity-60 flex items-center justify-center gap-2">
                {testing ? <><Loader className="w-4 h-4 animate-spin" />Testing…</> : 'Test Connection'}
              </button>

              {testResult && (
                <div className={`p-4 rounded-lg border ${testResult.ok ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                  <div className="flex items-center gap-2 mb-2">
                    {testResult.ok
                      ? <CheckCircle className="w-5 h-5 text-emerald-400" />
                      : <XCircle className="w-5 h-5 text-red-400" />}
                    <span className={`font-medium ${testResult.ok ? 'text-emerald-400' : 'text-red-400'}`}>
                      {testResult.ok ? 'Connection successful' : 'Connection failed'}
                    </span>
                  </div>
                  {testResult.ok && testResult.balance != null && (
                    <p className="text-sm text-slate-300">
                      Balance: {Number(testResult.balance).toLocaleString(undefined, { minimumFractionDigits: 2 })} {testResult.currency ?? 'USD'}
                    </p>
                  )}
                  {testResult.latency_ms != null && (
                    <p className="text-xs text-slate-400 mt-1">Latency: {testResult.latency_ms}ms</p>
                  )}
                  {testResult.error && (
                    <p className="text-sm text-red-300 mt-1">{testResult.error}</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Step 4: Done */}
          {step === 'done' && (
            <div className="text-center space-y-4 py-4">
              <CheckCircle className="w-12 h-12 text-emerald-400 mx-auto" />
              <div>
                <p className="text-lg font-semibold text-emerald-400">Broker connected!</p>
                <p className="text-sm text-slate-400 mt-1">
                  {broker.name} is ready.{' '}
                  {config.practice ? 'Paper trading mode active.' : 'Live trading mode active.'}
                </p>
              </div>
              <button onClick={reset} className="text-sm text-amber-400 hover:text-amber-300">
                Connect a different broker
              </button>
            </div>
          )}
        </>
      )}

      {/* Already connected — show change option */}
      {step === 'status' && status?.connected && (
        <button onClick={() => setStep('select')}
          className="w-full py-2.5 border border-slate-700 rounded-lg text-slate-400 hover:bg-slate-800 text-sm transition-colors">
          Change broker connection
        </button>
      )}
    </div>
  )
}
