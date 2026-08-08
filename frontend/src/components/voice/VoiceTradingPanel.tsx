/**
 * VoiceTradingPanel — spoken trading commands, SUPER-ADMIN ONLY.
 *
 * Self-gates: renders nothing unless the current user is a superadmin. This is a
 * money-moving surface, so it follows three hard rules:
 *   1. It NEVER auto-executes. Every privileged intent (trade / kill switch) goes
 *      through an explicit confirmation modal that the user must approve.
 *   2. It routes through the existing trading API, which is itself invariant-gated
 *      server-side (pre-trade risk gate, kill switch, staleness/drift checks).
 *      This panel adds NO new order path and weakens NO gate.
 *   3. Parsing is done by the pure `parseVoiceCommand` parser; unrecognised
 *      speech falls back to a harmless "chat" intent and is ignored here.
 *
 * Read-only queries (P&L, balance, positions, risk) are answered aloud without a
 * confirmation step. Trade/kill-switch require confirmation.
 */
import React, { useCallback, useState } from 'react';
import { useStore, selectUser } from '../../store';
import { isSuperAdmin } from '../../lib/subscription';
import { useVoice } from '../../hooks/useVoice';
import { parseVoiceCommand, describeIntent, type VoiceIntent } from '../../lib/voiceCommands';
import { tradingApi } from '../../hooks/useApi';
import { describeSubmitFailure } from '../../lib/utils';
import { useToast } from '../Toast';

const VoiceTradingPanel: React.FC = () => {
  const user = useStore(selectUser);
  const voice = useVoice();
  const toast = useToast();
  const [pending, setPending] = useState<VoiceIntent | null>(null);
  const [heard, setHeard] = useState('');
  const [busy, setBusy] = useState(false);

  // Hard gate: only a superadmin may use voice trading commands.
  const allowed = !!user && isSuperAdmin(user.role);

  const onFinal = useCallback((text: string) => {
    setHeard(text);
    const intent = parseVoiceCommand(text);
    if (intent.kind === 'trade' || intent.kind === 'kill_switch') {
      // Privileged → require explicit confirmation. Never auto-execute.
      setPending(intent);
    } else if (intent.kind === 'query') {
      void answerQuery(intent.topic);
    } else {
      toast.info(`Heard: "${text}" — not a recognised trading command.`);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const answerQuery = useCallback(async (topic: 'pnl' | 'balance' | 'positions' | 'risk') => {
    try {
      if (topic === 'positions') {
        const res = await tradingApi.positions();
        const list = (res.data as { positions?: unknown[] })?.positions ?? (Array.isArray(res.data) ? res.data : []);
        const n = Array.isArray(list) ? list.length : 0;
        say(`You have ${n} open position${n === 1 ? '' : 's'}.`);
      } else if (topic === 'risk') {
        const res = await tradingApi.riskMetrics();
        const d = res.data as { daily_drawdown?: number; exposure?: number };
        say(`Risk: drawdown ${fmtPct(d.daily_drawdown)}, exposure ${fmtNum(d.exposure)}.`);
      } else {
        const res = await tradingApi.account();
        const d = res.data as { balance?: number; equity?: number; pnl?: number; unrealized_pnl?: number };
        if (topic === 'balance') say(`Balance ${fmtNum(d.balance ?? d.equity)}.`);
        else say(`P and L ${fmtNum(d.pnl ?? d.unrealized_pnl)}.`);
      }
    } catch {
      say('Sorry, I could not fetch that right now.');
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const say = (msg: string) => { toast.info(msg); voice.speak(msg); };

  const confirm = useCallback(async () => {
    if (!pending) return;
    setBusy(true);
    try {
      if (pending.kind === 'trade') {
        await tradingApi.placeOrder({
          symbol: pending.symbol,
          side: pending.side,
          quantity: pending.quantity,
          order_type: 'market',
        });
        const msg = `${pending.side.toUpperCase()} ${pending.quantity} ${pending.symbol} submitted.`;
        toast.success(msg);
        voice.speak(msg);
      } else if (pending.kind === 'kill_switch') {
        await tradingApi.emergencyStop();
        const msg = 'Kill switch activated. Trading halted.';
        toast.warning(msg);
        voice.speak(msg);
      }
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      // F2-01: the old fallback said "Command failed. Nothing was executed." —
      // out loud, and on a timeout it is a flat assertion of something we do
      // not know. For a trade it invites a duplicate; for the kill switch it
      // tells the operator trading is still running when it may already have
      // been halted, which is the more dangerous direction of the two.
      const what = pending.kind === 'kill_switch' ? 'kill switch' : 'order';
      const msg = status === 403
        ? 'Rejected by the server risk gate.'
        : describeSubmitFailure(e, what).message;
      toast.error(msg);
      voice.speak(msg);
    } finally {
      setBusy(false);
      setPending(null);
    }
  }, [pending, toast, voice]);

  const cancel = useCallback(() => { setPending(null); voice.cancelSpeak(); }, [voice]);

  if (!allowed) return null;
  if (!voice.sttSupported) {
    return (
      <div style={panelStyle}>
        <div style={{ color: '#94a3b8', fontSize: 13 }}>
          🎙️ Voice trading is unavailable — this browser has no speech recognition.
        </div>
      </div>
    );
  }

  return (
    <div style={panelStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#fca5a5' }}>🎙️ Voice Trading</span>
        <span style={{ fontSize: 10, fontWeight: 800, color: '#fca5a5', background: '#450a0a', border: '1px solid #dc2626', borderRadius: 6, padding: '1px 7px' }}>
          SUPER ADMIN
        </span>
      </div>
      <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 10px', lineHeight: 1.5 }}>
        Say e.g. <em>“buy 1 lot gold”</em>, <em>“sell 0.5 XAUUSD”</em>, <em>“what's my P&amp;L”</em>,
        or <em>“kill switch”</em>. Trades and the kill switch always ask for confirmation before anything runs.
      </p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button
          type="button"
          onClick={() => (voice.listening ? voice.stopListening() : voice.startListening(onFinal))}
          style={{
            background: voice.listening ? '#dc2626' : '#1e293b',
            border: `1px solid ${voice.listening ? '#ef4444' : '#334155'}`,
            borderRadius: 9, color: voice.listening ? '#fff' : '#e2e8f0',
            cursor: 'pointer', fontSize: 13, fontWeight: 700, padding: '9px 16px',
          }}
        >
          {voice.listening ? '⏹ Stop' : '🎤 Speak command'}
        </button>
        {voice.transcript && (
          <span style={{ fontSize: 13, color: '#94a3b8', fontStyle: 'italic' }}>“{voice.transcript}”</span>
        )}
      </div>

      {pending && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 10000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={cancel}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#0d1421', border: '1px solid #334155', borderRadius: 14,
              padding: 24, maxWidth: 420, width: '90%', boxShadow: '0 20px 60px rgba(0,0,0,0.6)',
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 800, color: '#f1f5f9', marginBottom: 8 }}>
              {pending.kind === 'kill_switch' ? '⚠️ Confirm kill switch' : 'Confirm trade'}
            </div>
            {heard && <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>Heard: “{heard}”</div>}
            <div style={{
              fontSize: 16, fontWeight: 800,
              color: pending.kind === 'kill_switch' ? '#fca5a5' : '#60a5fa',
              background: '#0f1e35', border: '1px solid #1e3a5f', borderRadius: 9, padding: '12px 14px', marginBottom: 16,
            }}>
              {describeIntent(pending)}
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={cancel}
                disabled={busy}
                style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 9, color: '#94a3b8', cursor: 'pointer', fontSize: 13, fontWeight: 700, padding: '9px 18px' }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void confirm()}
                disabled={busy}
                style={{
                  background: pending.kind === 'kill_switch' ? '#dc2626' : '#3b82f6',
                  border: 'none', borderRadius: 9, color: '#fff', cursor: busy ? 'wait' : 'pointer',
                  fontSize: 13, fontWeight: 800, padding: '9px 18px',
                }}
              >
                {busy ? '…' : pending.kind === 'kill_switch' ? 'Activate kill switch' : 'Place order'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const panelStyle: React.CSSProperties = {
  background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: 16,
};

function fmtNum(v: number | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : 'unknown';
}
function fmtPct(v: number | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : 'unknown';
}

export default VoiceTradingPanel;
