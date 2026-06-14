/**
 * Onboarding Wizard — 5-step guided setup.
 * Shown on first login, skip-able, resumable via localStorage.
 * Steps: broker → risk level → prop firm rules → first backtest → paper trading
 *
 * Post-onboarding destination is role-aware:
 *   superadmin → /superadmin
 *   admin      → /audit
 *   trader/user → /dashboard
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { useStore } from '../store';
import { extractApiError } from '../lib/utils';
import type { UserRole } from '../store';

function resolvePostOnboardingPath(role: UserRole | undefined): string {
  if (role === 'superadmin') return '/superadmin';
  if (role === 'admin') return '/audit';
  return '/dashboard';
}

const STORAGE_KEY = 'hopefx_onboarding_step';

type Broker        = 'oanda' | 'alpaca' | 'paper';
type RiskLevel     = 'conservative' | 'moderate' | 'aggressive';
type PropFirmChoice = 'ftmo' | 'the5ers' | 'none';

interface WizardState {
  broker: Broker | null;
  riskLevel: RiskLevel | null;
  propFirm: PropFirmChoice | null;
  backtestDone: boolean;
  paperStarted: boolean;
}

const STEPS = [
  { icon: '⚡', label: 'Connect Broker' },
  { icon: '🛡️', label: 'Risk Level' },
  { icon: '📊', label: 'Prop Firm Rules' },
  { icon: '▶', label: 'First Backtest' },
  { icon: '📈', label: 'Paper Trading' },
];

// ── Step indicator ────────────────────────────────────────────────────────────

const StepIndicator: React.FC<{ current: number; total: number }> = ({ current, total }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 32 }}>
    {Array.from({ length: total }).map((_, i) => {
      const done   = i < current;
      const active = i === current;
      return (
        <React.Fragment key={i}>
          <div style={{
            width: 36, height: 36, borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, fontWeight: 700,
            background: done ? '#f59e0b' : active ? 'transparent' : 'transparent',
            border: `2px solid ${done ? '#f59e0b' : active ? '#f59e0b' : '#334155'}`,
            color: done ? '#0f172a' : active ? '#fbbf24' : '#475569',
            flexShrink: 0,
          }}>
            {done ? '✓' : STEPS[i].icon}
          </div>
          {i < total - 1 && (
            <div style={{ flex: 1, height: 2, background: i < current ? '#f59e0b' : '#334155' }} />
          )}
        </React.Fragment>
      );
    })}
  </div>
);

// ── Step 1: Broker ────────────────────────────────────────────────────────────

const Step1Broker: React.FC<{ state: WizardState; setState: (s: WizardState) => void }> = ({ state, setState }) => {
  const brokers: { id: Broker; name: string; desc: string }[] = [
    { id: 'oanda',  name: 'OANDA',         desc: 'Best for XAUUSD — free practice account, instant setup' },
    { id: 'alpaca', name: 'Alpaca',         desc: 'US stocks & crypto — commission-free paper trading' },
    { id: 'paper',  name: 'Paper Trading',  desc: 'No broker needed — simulated fills, zero risk' },
  ];
  return (
    <div>
      <h2 style={s.stepTitle}>Connect your broker</h2>
      <p style={s.stepSub}>Choose where HOPEFX will place trades. You can change this later.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {brokers.map((b) => (
          <button key={b.id} onClick={() => setState({ ...state, broker: b.id })}
            style={{
              ...s.optionBtn,
              border: `1px solid ${state.broker === b.id ? '#f59e0b' : '#334155'}`,
              background: state.broker === b.id ? '#1c1a0a' : '#1e293b',
            }}>
            <div style={{ fontWeight: 600, color: '#f1f5f9', textAlign: 'left' }}>{b.name}</div>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 2, textAlign: 'left' }}>{b.desc}</div>
          </button>
        ))}
      </div>
      {state.broker === 'oanda' && (
        <div style={s.infoBox}>
          Add <code style={s.code}>BROKER_OANDA_TOKEN</code> and{' '}
          <code style={s.code}>BROKER_OANDA_ACCOUNT</code> to your{' '}
          <code style={s.code}>.env</code> file.{' '}
          <a href="https://www.oanda.com/us-en/trading/accounts/open-account/" target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>
            Get a free practice account →
          </a>
        </div>
      )}
    </div>
  );
};

// ── Step 2: Risk Level ────────────────────────────────────────────────────────

const Step2Risk: React.FC<{ state: WizardState; setState: (s: WizardState) => void }> = ({ state, setState }) => {
  const levels: { id: RiskLevel; name: string; desc: string; risk: string }[] = [
    { id: 'conservative', name: 'Conservative', desc: '0.5% risk per trade, max 2% daily loss', risk: '0.5%' },
    { id: 'moderate',     name: 'Moderate',     desc: '1% risk per trade, max 3% daily loss',   risk: '1%'   },
    { id: 'aggressive',   name: 'Aggressive',   desc: '2% risk per trade, max 5% daily loss',   risk: '2%'   },
  ];
  return (
    <div>
      <h2 style={s.stepTitle}>Set your risk level</h2>
      <p style={s.stepSub}>This controls position sizing and kill-switch thresholds.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {levels.map((l) => (
          <button key={l.id} onClick={() => setState({ ...state, riskLevel: l.id })}
            style={{
              ...s.optionBtn,
              border: `1px solid ${state.riskLevel === l.id ? '#f59e0b' : '#334155'}`,
              background: state.riskLevel === l.id ? '#1c1a0a' : '#1e293b',
            }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{l.name}</span>
              <span style={{ fontSize: 13, color: '#fbbf24', fontWeight: 700 }}>{l.risk} / trade</span>
            </div>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 2, textAlign: 'left' }}>{l.desc}</div>
          </button>
        ))}
      </div>
    </div>
  );
};

// ── Step 3: Prop Firm ─────────────────────────────────────────────────────────

const Step3PropFirm: React.FC<{ state: WizardState; setState: (s: WizardState) => void }> = ({ state, setState }) => {
  const firms: { id: PropFirmChoice; name: string; desc: string }[] = [
    { id: 'ftmo',     name: 'FTMO',     desc: '5% daily loss, 10% max drawdown, 10% profit target' },
    { id: 'the5ers',  name: 'The5ers',  desc: '4% daily loss, 6% max drawdown, 8% profit target'  },
    { id: 'none',     name: 'No Prop Firm', desc: 'Personal account — custom risk rules'          },
  ];
  return (
    <div>
      <h2 style={s.stepTitle}>Prop firm rules</h2>
      <p style={s.stepSub}>HOPEFX will enforce these rules automatically — you can never accidentally breach them.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {firms.map((f) => (
          <button key={f.id} onClick={() => setState({ ...state, propFirm: f.id })}
            style={{
              ...s.optionBtn,
              border: `1px solid ${state.propFirm === f.id ? '#f59e0b' : '#334155'}`,
              background: state.propFirm === f.id ? '#1c1a0a' : '#1e293b',
            }}>
            <div style={{ fontWeight: 600, color: '#f1f5f9', textAlign: 'left' }}>{f.name}</div>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 2, textAlign: 'left' }}>{f.desc}</div>
          </button>
        ))}
      </div>
    </div>
  );
};

// ── Step 4: Backtest ──────────────────────────────────────────────────────────

const Step4Backtest: React.FC<{ state: WizardState; setState: (s: WizardState) => void }> = ({ state, setState }) => {
  const [running, setRunning]       = useState(false);
  const [result, setResult]         = useState<{ return_pct: number; trades: number; win_rate: number } | null>(null);
  const [backtestErr, setBacktestErr] = useState<string | null>(null);

  const runBacktest = async () => {
    setRunning(true);
    setBacktestErr(null);
    try {
      const res = await api.post<{ total_return?: number; total_trades?: number; win_rate?: number; metrics?: { total_return?: number; total_trades?: number; win_rate?: number } }>('/backtesting/run',
        { symbol: 'XAUUSD', strategy: 'ml_ensemble', period_days: 30 }
      );
      const data = res.data;
      setResult({
        return_pct: data.total_return ?? data.metrics?.total_return ?? 0,
        trades:     data.total_trades ?? data.metrics?.total_trades ?? 0,
        win_rate:   data.win_rate ?? data.metrics?.win_rate ?? 0,
      });
      setState({ ...state, backtestDone: true });
    } catch (err: unknown) {
      setBacktestErr(extractApiError(err, 'Backtest failed. Ensure the backtesting API is running.'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <h2 style={s.stepTitle}>Run your first backtest</h2>
      <p style={s.stepSub}>Test the ML ensemble strategy on 30 days of XAUUSD data.</p>
      {backtestErr && (
        <div style={s.errorBox}>{backtestErr}</div>
      )}
      {!result ? (
        <button onClick={runBacktest} disabled={running} style={{ ...s.primaryBtn, opacity: running ? 0.6 : 1 }}>
          {running ? '⟳ Running backtest…' : '▶ Run Backtest (XAUUSD, 30 days)'}
        </button>
      ) : (
        <div style={s.resultBox}>
          <div style={{ color: '#4ade80', fontWeight: 600, marginBottom: 12 }}>✓ Backtest complete</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, textAlign: 'center' }}>
            <div>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#f1f5f9' }}>{result.return_pct.toFixed(1)}%</div>
              <div style={{ fontSize: 12, color: '#64748b' }}>Return</div>
            </div>
            <div>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#f1f5f9' }}>{result.trades}</div>
              <div style={{ fontSize: 12, color: '#64748b' }}>Trades</div>
            </div>
            <div>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#f1f5f9' }}>{result.win_rate.toFixed(0)}%</div>
              <div style={{ fontSize: 12, color: '#64748b' }}>Win Rate</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Step 5: Paper Trading ─────────────────────────────────────────────────────

const Step5Paper: React.FC<{ state: WizardState; setState: (s: WizardState) => void }> = ({ state, setState }) => {
  const [starting, setStarting] = useState(false);
  const [paperErr, setPaperErr] = useState<string | null>(null);

  const startPaper = async () => {
    setStarting(true);
    setPaperErr(null);
    try {
      await api.post('/trading/paper/start');
      setState({ ...state, paperStarted: true });
    } catch (err: unknown) {
      setPaperErr(extractApiError(err, 'Failed to start paper trading. Ensure the trading API is running.'));
    } finally {
      setStarting(false);
    }
  };

  return (
    <div>
      <h2 style={s.stepTitle}>Start paper trading</h2>
      <p style={s.stepSub}>HOPEFX will begin generating AI signals and placing simulated orders. No real money at risk.</p>
      {paperErr && <div style={s.errorBox}>{paperErr}</div>}
      {!state.paperStarted ? (
        <button onClick={startPaper} disabled={starting}
          style={{ ...s.primaryBtn, background: '#059669', opacity: starting ? 0.6 : 1 }}>
          {starting ? '⟳ Starting…' : '📈 Launch Paper Trading'}
        </button>
      ) : (
        <div style={{ ...s.resultBox, border: '1px solid #14532d', background: '#052e16' }}>
          <div style={{ color: '#4ade80', fontWeight: 600 }}>✓ Paper trading active!</div>
          <div style={{ fontSize: 13, color: '#86efac', marginTop: 4 }}>
            Head to the Dashboard to watch your first AI signals.
          </div>
        </div>
      )}
    </div>
  );
};

// ── Main wizard ───────────────────────────────────────────────────────────────

const Onboarding: React.FC = () => {
  const navigate  = useNavigate();
  const user      = useStore((s) => s.user);
  const savedStep = parseInt(localStorage.getItem(STORAGE_KEY) ?? '0', 10);
  const [step, setStep] = useState(Math.min(savedStep, STEPS.length - 1));
  const [state, setState] = useState<WizardState>({
    broker: null, riskLevel: null, propFirm: null, backtestDone: false, paperStarted: false,
  });

  const destination = resolvePostOnboardingPath(user?.role);
  const saveStep = (n: number) => { setStep(n); localStorage.setItem(STORAGE_KEY, String(n)); };

  // Persist the chosen risk level into the user's trading preferences so the
  // onboarding selection actually takes effect (previously the wizard's choices
  // were discarded on finish). Merge into existing prefs to avoid clobbering
  // other settings; best-effort so completing onboarding is never blocked.
  const RISK_MAP: Record<RiskLevel, { max_risk_per_trade: number; max_daily_drawdown: number }> = {
    conservative: { max_risk_per_trade: 0.5, max_daily_drawdown: 2 },
    moderate:     { max_risk_per_trade: 1,   max_daily_drawdown: 3 },
    aggressive:   { max_risk_per_trade: 2,   max_daily_drawdown: 5 },
  };
  const persistOnboarding = async () => {
    if (!state.riskLevel) return;
    try {
      const cur = await api.get('/settings/trading').then((r) => r.data).catch(() => ({}));
      await api.post('/settings/trading', { ...(cur ?? {}), ...RISK_MAP[state.riskLevel] });
    } catch { /* non-fatal — never block completing onboarding */ }
  };

  // Persist best-effort in the background — never block navigation on it.
  const finish = () => { void persistOnboarding(); localStorage.setItem(STORAGE_KEY, 'done'); navigate(destination); };
  const skip     = () => { localStorage.setItem(STORAGE_KEY, 'done'); navigate(destination); };

  const canAdvance = () => {
    if (step === 0) return state.broker !== null;
    if (step === 1) return state.riskLevel !== null;
    if (step === 2) return state.propFirm !== null;
    if (step === 3) return state.backtestDone;
    return true;
  };

  const stepProps = { state, setState };

  return (
    <div style={s.shell}>
      <div style={s.wizard}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 800, color: '#fbbf24', margin: '0 0 4px' }}>HOPEFX Setup</h1>
            <p style={{ fontSize: 13, color: '#475569', margin: 0 }}>Step {step + 1} of {STEPS.length}</p>
          </div>
          <button onClick={skip} style={s.skipBtn}>✕ Skip</button>
        </div>

        <StepIndicator current={step} total={STEPS.length} />

        {/* Step content */}
        <div style={s.stepCard}>
          {step === 0 && <Step1Broker {...stepProps} />}
          {step === 1 && <Step2Risk {...stepProps} />}
          {step === 2 && <Step3PropFirm {...stepProps} />}
          {step === 3 && <Step4Backtest {...stepProps} />}
          {step === 4 && <Step5Paper {...stepProps} />}
        </div>

        {/* Navigation */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 16 }}>
          <button onClick={() => saveStep(step - 1)} disabled={step === 0}
            style={{ ...s.navBtn, opacity: step === 0 ? 0.3 : 1 }}>
            ‹ Back
          </button>
          {step < STEPS.length - 1 ? (
            <button onClick={() => saveStep(step + 1)} disabled={!canAdvance()}
              style={{ ...s.nextBtn, opacity: !canAdvance() ? 0.4 : 1 }}>
              Next ›
            </button>
          ) : (
            <button onClick={finish} style={{ ...s.nextBtn, background: '#059669' }}>
              Go to Dashboard ›
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  shell:      { minHeight: '100vh', background: '#020617', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 },
  wizard:     { width: '100%', maxWidth: 520 },
  stepCard:   { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24, minHeight: 280 },
  stepTitle:  { fontSize: 20, fontWeight: 700, color: '#f1f5f9', margin: '0 0 8px' },
  stepSub:    { fontSize: 14, color: '#64748b', margin: '0 0 20px' },
  optionBtn:  { width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px', cursor: 'pointer', transition: 'border-color 0.15s' },
  infoBox:    { background: '#0c1a2e', border: '1px solid #1e3a5f', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#93c5fd', marginTop: 12 },
  code:       { background: '#1e293b', borderRadius: 4, padding: '1px 5px', fontFamily: 'monospace', fontSize: 12 },
  primaryBtn: { width: '100%', background: '#f59e0b', border: 'none', borderRadius: 8, color: '#0f172a', fontSize: 15, fontWeight: 700, cursor: 'pointer', padding: '14px 0' },
  resultBox:  { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: 16 },
  errorBox:   { background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 6, padding: '8px 12px', fontSize: 13, color: '#f87171', marginBottom: 12 },
  skipBtn:    { background: 'transparent', border: 'none', color: '#475569', cursor: 'pointer', fontSize: 13, padding: '4px 8px' },
  navBtn:     { background: 'transparent', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 14, padding: '8px 12px' },
  nextBtn:    { background: '#f59e0b', border: 'none', borderRadius: 8, color: '#0f172a', fontSize: 14, fontWeight: 700, cursor: 'pointer', padding: '10px 24px' },
};

export default Onboarding;
