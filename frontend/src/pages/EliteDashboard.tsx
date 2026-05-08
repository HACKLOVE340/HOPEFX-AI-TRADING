// HOPEFX-AI-TRADING
// Copyright (c) 2025-2026
// Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
/**
 * EliteDashboard.tsx
 *
 * Tier 5 (Elite) exclusive dashboard.
 * Surfaces dedicated support tickets, custom development requests,
 * and account manager contact — all gated to Elite subscribers.
 *
 * Backend endpoints (all under /api/billing/elite/):
 *   GET  /account-manager
 *   POST /support/ticket
 *   GET  /support/tickets
 *   POST /custom-dev/request
 *   GET  /custom-dev/requests
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  eliteApi,
  type SupportTicketPayload,
  type CustomDevPayload,
} from '../hooks/useApi';
import { useStore } from '../store';
import { extractApiError } from '../lib/utils';

// ── Style helpers ─────────────────────────────────────────────────────────────

const s = {
  page:    { padding: '32px 40px', maxWidth: 1100, margin: '0 auto' } as React.CSSProperties,
  heading: { fontSize: 26, fontWeight: 800, color: '#f59e0b', marginBottom: 4 } as React.CSSProperties,
  sub:     { fontSize: 14, color: '#94a3b8', marginBottom: 32 } as React.CSSProperties,
  grid:    { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 32 } as React.CSSProperties,
  card:    { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 24 } as React.CSSProperties,
  cardH:   { fontSize: 16, fontWeight: 700, color: '#e2e8f0', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 } as React.CSSProperties,
  label:   { fontSize: 12, color: '#64748b', marginBottom: 4, display: 'block' } as React.CSSProperties,
  input:   { width: '100%', padding: '9px 12px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 13, outline: 'none', boxSizing: 'border-box' } as React.CSSProperties,
  textarea:{ width: '100%', padding: '9px 12px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 13, outline: 'none', resize: 'vertical', minHeight: 100, boxSizing: 'border-box' } as React.CSSProperties,
  select:  { width: '100%', padding: '9px 12px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 13, outline: 'none' } as React.CSSProperties,
  btn:     { padding: '10px 20px', background: '#f59e0b', color: '#0a0e1a', border: 'none', borderRadius: 6, fontWeight: 700, fontSize: 13, cursor: 'pointer' } as React.CSSProperties,
  btnSec:  { padding: '10px 20px', background: 'transparent', color: '#94a3b8', border: '1px solid #334155', borderRadius: 6, fontWeight: 600, fontSize: 13, cursor: 'pointer' } as React.CSSProperties,
  field:   { marginBottom: 14 } as React.CSSProperties,
  row:     { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '12px 0', borderBottom: '1px solid #1e293b' } as React.CSSProperties,
  amRow:   { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, fontSize: 13, color: '#94a3b8' } as React.CSSProperties,
  amVal:   { color: '#e2e8f0', fontWeight: 500 } as React.CSSProperties,
  success: { background: '#052e16', border: '1px solid #166534', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#4ade80', marginBottom: 16 } as React.CSSProperties,
  error:   { background: '#450a0a', border: '1px solid #991b1b', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#f87171', marginBottom: 16 } as React.CSSProperties,
  gate:    { textAlign: 'center', padding: '80px 40px' } as React.CSSProperties,
};

/** Return inline badge styles for a given hex colour. */
function badgeStyle(color: string): React.CSSProperties {
  return {
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: 10,
    fontSize: 11,
    fontWeight: 700,
    background: color + '22',
    color,
  };
}

const PRIORITY_COLORS: Record<string, string> = {
  urgent: '#ef4444',
  high:   '#f59e0b',
  normal: '#3b82f6',
};

const STATUS_COLORS: Record<string, string> = {
  open:        '#3b82f6',
  in_progress: '#f59e0b',
  resolved:    '#22c55e',
  closed:      '#64748b',
  submitted:   '#8b5cf6',
};

// ── Account Manager card ──────────────────────────────────────────────────────

interface AccountManager {
  name: string;
  email: string;
  phone: string;
  calendar_url: string;
  slack_channel: string;
  response_sla: Record<string, string>;
  support_hours: string;
}

function AccountManagerCard() {
  const [am, setAm]           = useState<AccountManager | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    eliteApi.accountManager()
      .then(r => { if (mounted) setAm(r.data as AccountManager); })
      .catch(() => { if (mounted) setAm(null); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  return (
    <div style={s.card}>
      <div style={s.cardH}>🎯 Your Dedicated Account Manager</div>
      {loading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : !am ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Account manager details unavailable.</div>
      ) : (
        <>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#f59e0b', marginBottom: 16 }}>{am.name}</div>
          {am.email && (
            <div style={s.amRow}>
              <span>📧</span>
              <span style={s.amVal}>{am.email}</span>
            </div>
          )}
          {am.phone && (
            <div style={s.amRow}>
              <span>📞</span>
              <span style={s.amVal}>{am.phone}</span>
            </div>
          )}
          {am.calendar_url && (
            <div style={s.amRow}>
              <span>📅</span>
              <a href={am.calendar_url} target="_blank" rel="noreferrer" style={{ color: '#3b82f6', fontSize: 13 }}>
                Book a call
              </a>
            </div>
          )}
          {am.slack_channel && (
            <div style={s.amRow}>
              <span>💬</span>
              <span style={s.amVal}>{am.slack_channel}</span>
            </div>
          )}
          <div style={{ marginTop: 16, padding: '12px', background: '#1e293b', borderRadius: 8 }}>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8, fontWeight: 600 }}>RESPONSE SLA</div>
            {Object.entries(am.response_sla).map(([priority, time]) => (
              <div key={priority} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                <span style={badgeStyle(PRIORITY_COLORS[priority] ?? '#64748b')}>{priority}</span>
                <span style={{ color: '#94a3b8' }}>{time}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12, fontSize: 12, color: '#64748b' }}>
            Support hours: <span style={{ color: '#e2e8f0' }}>{am.support_hours}</span>
          </div>
        </>
      )}
    </div>
  );
}

// ── Support Ticket form ───────────────────────────────────────────────────────

function SupportTicketForm({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState<SupportTicketPayload>({
    subject: '', message: '', priority: 'high', category: 'general',
  });
  const [loading, setLoading] = useState(false);
  const [msg, setMsg]         = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.subject.trim() || !form.message.trim()) return;
    setLoading(true);
    setMsg(null);
    try {
      const r = await eliteApi.createTicket(form);
      const data = r.data as { message: string };
      setMsg({ type: 'ok', text: data.message });
      setForm({ subject: '', message: '', priority: 'high', category: 'general' });
      onCreated();
    } catch (err: unknown) {
      setMsg({ type: 'err', text: extractApiError(err, 'Failed to submit ticket. Please try again.') });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={s.card}>
      <div style={s.cardH}>🎫 Submit Support Ticket</div>
      {msg && <div style={msg.type === 'ok' ? s.success : s.error}>{msg.text}</div>}
      <form onSubmit={submit}>
        <div style={s.field}>
          <label style={s.label}>Subject *</label>
          <input
            style={s.input}
            value={form.subject}
            onChange={e => setForm(f => ({ ...f, subject: e.target.value }))}
            placeholder="Describe your issue briefly"
            required
          />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
          <div>
            <label style={s.label}>Priority</label>
            <select
              style={s.select}
              value={form.priority}
              onChange={e => setForm(f => ({ ...f, priority: e.target.value as SupportTicketPayload['priority'] }))}
            >
              <option value="normal">Normal (24h SLA)</option>
              <option value="high">High (4h SLA)</option>
              <option value="urgent">Urgent (1h SLA)</option>
            </select>
          </div>
          <div>
            <label style={s.label}>Category</label>
            <select
              style={s.select}
              value={form.category}
              onChange={e => setForm(f => ({ ...f, category: e.target.value as SupportTicketPayload['category'] }))}
            >
              <option value="general">General</option>
              <option value="technical">Technical</option>
              <option value="billing">Billing</option>
              <option value="strategy">Strategy</option>
              <option value="api">API</option>
              <option value="onboarding">Onboarding</option>
            </select>
          </div>
        </div>
        <div style={s.field}>
          <label style={s.label}>Message * (min 20 characters)</label>
          <textarea
            style={s.textarea}
            value={form.message}
            onChange={e => setForm(f => ({ ...f, message: e.target.value }))}
            placeholder="Describe your issue in detail…"
            required
          />
        </div>
        <button type="submit" style={s.btn} disabled={loading}>
          {loading ? 'Submitting…' : 'Submit Ticket'}
        </button>
      </form>
    </div>
  );
}

// ── Ticket list ───────────────────────────────────────────────────────────────

interface Ticket {
  ticket_id: string;
  subject: string;
  priority: string;
  category: string;
  status: string;
  created_at: string;
}

function TicketList({ refresh }: { refresh: number }) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    eliteApi.listTickets()
      .then(r => { if (mounted) setTickets((r.data as { tickets: Ticket[] }).tickets ?? []); })
      .catch(() => { if (mounted) setTickets([]); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [refresh]);

  return (
    <div style={s.card}>
      <div style={s.cardH}>📋 My Support Tickets</div>
      {loading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : tickets.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>No tickets yet.</div>
      ) : (
        tickets.map(t => (
          <div key={t.ticket_id} style={s.row}>
            <div>
              <div style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 500, marginBottom: 4 }}>{t.subject}</div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={badgeStyle(PRIORITY_COLORS[t.priority] ?? '#64748b')}>{t.priority}</span>
                <span style={badgeStyle(STATUS_COLORS[t.status] ?? '#64748b')}>{t.status}</span>
                <span style={{ fontSize: 11, color: '#475569' }}>{t.category}</span>
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, color: '#475569', fontFamily: 'monospace' }}>{t.ticket_id}</div>
              <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
                {new Date(t.created_at).toLocaleDateString()}
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ── Custom Dev form ───────────────────────────────────────────────────────────

function CustomDevForm({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState<CustomDevPayload>({
    title: '',
    description: '',
    request_type: 'strategy',
    target_symbols: [],
    target_timeframes: [],
    budget_usd: undefined,
    deadline: undefined,
  });
  const [symbolsInput, setSymbolsInput] = useState('');
  const [loading, setLoading]           = useState(false);
  const [msg, setMsg]                   = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim() || form.description.length < 50) return;
    setLoading(true);
    setMsg(null);
    const payload: CustomDevPayload = {
      ...form,
      target_symbols: symbolsInput.split(',').map(sym => sym.trim()).filter(Boolean),
    };
    try {
      const r = await eliteApi.submitCustomDev(payload);
      const data = r.data as { message: string };
      setMsg({ type: 'ok', text: data.message });
      setForm({
        title: '', description: '', request_type: 'strategy',
        target_symbols: [], target_timeframes: [],
        budget_usd: undefined, deadline: undefined,
      });
      setSymbolsInput('');
      onCreated();
    } catch (err: unknown) {
      setMsg({ type: 'err', text: extractApiError(err, 'Failed to submit request. Please try again.') });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={s.card}>
      <div style={s.cardH}>🛠️ Custom Development Request</div>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 16 }}>
        Request bespoke strategies, indicators, broker integrations, or API extensions.
        Our team will provide a scoping estimate within 2 business days.
      </div>
      {msg && <div style={msg.type === 'ok' ? s.success : s.error}>{msg.text}</div>}
      <form onSubmit={submit}>
        <div style={s.field}>
          <label style={s.label}>Title *</label>
          <input
            style={s.input}
            value={form.title}
            onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
            placeholder="e.g. Gold momentum strategy with news filter"
            required
          />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
          <div>
            <label style={s.label}>Type *</label>
            <select
              style={s.select}
              value={form.request_type}
              onChange={e => setForm(f => ({ ...f, request_type: e.target.value as CustomDevPayload['request_type'] }))}
            >
              <option value="strategy">Trading Strategy</option>
              <option value="indicator">Custom Indicator</option>
              <option value="integration">Broker Integration</option>
              <option value="dashboard">Dashboard Widget</option>
              <option value="api">API Extension</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div>
            <label style={s.label}>Budget (USD, optional)</label>
            <input
              style={s.input}
              type="number"
              min={0}
              value={form.budget_usd ?? ''}
              onChange={e => setForm(f => ({ ...f, budget_usd: e.target.value ? Number(e.target.value) : undefined }))}
              placeholder="e.g. 5000"
            />
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
          <div>
            <label style={s.label}>Target Symbols (comma-separated)</label>
            <input
              style={s.input}
              value={symbolsInput}
              onChange={e => setSymbolsInput(e.target.value)}
              placeholder="XAUUSD, EURUSD, BTCUSD"
            />
          </div>
          <div>
            <label style={s.label}>Deadline (optional)</label>
            <input
              style={s.input}
              type="date"
              value={form.deadline ?? ''}
              onChange={e => setForm(f => ({ ...f, deadline: e.target.value || undefined }))}
            />
          </div>
        </div>
        <div style={s.field}>
          <label style={s.label}>Description * (min 50 characters)</label>
          <textarea
            style={{ ...s.textarea, minHeight: 140 }}
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            placeholder="Describe your requirements in detail: entry/exit logic, risk parameters, data sources, expected outputs…"
            required
          />
          <div style={{ fontSize: 11, color: form.description.length < 50 ? '#ef4444' : '#64748b', marginTop: 4 }}>
            {form.description.length}/50 minimum characters
          </div>
        </div>
        <button type="submit" style={s.btn} disabled={loading || form.description.length < 50}>
          {loading ? 'Submitting…' : 'Submit Request'}
        </button>
      </form>
    </div>
  );
}

// ── Custom Dev request list ───────────────────────────────────────────────────

interface DevRequest {
  request_id: string;
  title: string;
  request_type: string;
  status: string;
  created_at: string;
  budget_usd?: number;
}

function CustomDevList({ refresh }: { refresh: number }) {
  const [reqs, setReqs]       = useState<DevRequest[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    eliteApi.listCustomDevReqs()
      .then(r => { if (mounted) setReqs((r.data as { requests: DevRequest[] }).requests ?? []); })
      .catch(() => { if (mounted) setReqs([]); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [refresh]);

  return (
    <div style={s.card}>
      <div style={s.cardH}>📦 My Development Requests</div>
      {loading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : reqs.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>No requests yet.</div>
      ) : (
        reqs.map(r => (
          <div key={r.request_id} style={s.row}>
            <div>
              <div style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 500, marginBottom: 4 }}>{r.title}</div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={badgeStyle('#8b5cf6')}>{r.request_type}</span>
                <span style={badgeStyle(STATUS_COLORS[r.status] ?? '#64748b')}>{r.status}</span>
                {r.budget_usd != null && (
                  <span style={{ fontSize: 11, color: '#475569' }}>${r.budget_usd.toLocaleString()}</span>
                )}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, color: '#475569', fontFamily: 'monospace' }}>{r.request_id}</div>
              <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>
                {new Date(r.created_at).toLocaleDateString()}
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ── Root component ────────────────────────────────────────────────────────────

const EliteDashboard: React.FC = () => {
  const navigate = useNavigate();
  const role     = useStore(st => st.user?.role ?? 'user');
  const plan     = useStore(st => st.plan ?? 'free');

  const [ticketRefresh, setTicketRefresh] = useState(0);
  const [devRefresh,    setDevRefresh]    = useState(0);

  // Gate: only elite subscribers (and admins) can access this page
  const isElite = plan === 'elite' || role === 'admin' || role === 'superadmin';

  if (!isElite) {
    return (
      <div style={s.gate}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>⭐</div>
        <div style={{ fontSize: 22, fontWeight: 800, color: '#f59e0b', marginBottom: 8 }}>
          Elite Plan Required
        </div>
        <div style={{ fontSize: 14, color: '#94a3b8', maxWidth: 400, margin: '0 auto 24px' }}>
          Sub-accounts, dedicated support, and custom development are exclusive
          to Elite subscribers ($10,000/mo).
        </div>
        <button style={s.btn} onClick={() => navigate('/checkout')}>
          Upgrade to Elite
        </button>
        <button style={{ ...s.btnSec, marginLeft: 12 }} onClick={() => navigate('/pricing')}>
          View all plans
        </button>
      </div>
    );
  }

  return (
    <div style={s.page}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 4 }}>
        <div style={s.heading}>⭐ Elite Dashboard</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => navigate('/walk-forward')}
            style={{ padding: '7px 14px', background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.35)', borderRadius: 7, color: '#8b5cf6', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            📈 Walk-Forward
          </button>
          <button onClick={() => navigate('/ai-strategy')}
            style={{ padding: '7px 14px', background: 'rgba(6,182,212,0.12)', border: '1px solid rgba(6,182,212,0.35)', borderRadius: 7, color: '#06b6d4', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            🤖 AI Strategy
          </button>
          <button onClick={() => navigate('/leaderboard')}
            style={{ padding: '7px 14px', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)', borderRadius: 7, color: '#f59e0b', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            🏆 Leaderboard
          </button>
        </div>
      </div>
      <div style={s.sub}>
        Dedicated support · Custom development · Sub-accounts · White-label
      </div>

      {/* Account manager + ticket form */}
      <div style={s.grid}>
        <AccountManagerCard />
        <SupportTicketForm onCreated={() => setTicketRefresh(n => n + 1)} />
      </div>

      {/* Ticket list + custom dev form */}
      <div style={s.grid}>
        <TicketList refresh={ticketRefresh} />
        <CustomDevForm onCreated={() => setDevRefresh(n => n + 1)} />
      </div>

      {/* Custom dev request list — full width */}
      <CustomDevList refresh={devRefresh} />
    </div>
  );
};

export default EliteDashboard;
