/**
 * Support — the customer's own tickets.
 *
 * The mirror of `SupportConsole`, and the differences are the point.
 *
 *  * **A customer can tell who answered.** Every reply is attributed, and an
 *    AI reply says so. On a trading platform, letting a machine's answer pass
 *    as a person's is an honesty problem before it is a regulatory one.
 *  * **An escalated ticket says a person is coming.** Not silence, and never a
 *    fake "the assistant is typing": the floor removed the AI from this
 *    conversation deliberately, and the customer is owed that fact rather than
 *    a spinner that never resolves.
 *  * **The triage internals are not here.** `matched_on`, `escalation_reason`
 *    and `assigned_operator_id` are stripped server-side by
 *    `TicketView.as_customer_dict`. This page reads neither, so a future
 *    endpoint change cannot quietly surface them — two independent refusals.
 *  * **Absence is a state.** Empty, loading and failed are three renders. An
 *    error that reads as "you have no tickets" sends a customer away believing
 *    they never wrote in.
 *
 * Every colour is a token from `index.css`; the page holds no literals, so the
 * light theme and white-label branding reach it.
 */

import React, { useCallback, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Bot, LifeBuoy, Plus, User, UserCheck } from 'lucide-react';
import { supportApi } from '../hooks/useApi';

interface MyTicket {
  id: string;
  subject: string;
  status: string;
  category: string | null;
  department: string | null;
  needs_human: boolean;
  created_at: string | null;
  first_response_at: string | null;
}

interface Message {
  author_kind: string;
  author_id: string | null;
  body: string;
  created_at: string | null;
}

const C = {
  bg: 'var(--bg)', surface: 'var(--surface)', border: 'var(--border)',
  text: 'var(--text)', muted: 'var(--text-muted)', accent: 'var(--accent)',
  waiting: 'var(--q-waiting)', ok: 'var(--bull)', urgent: 'var(--q-urgent)',
  urgentBg: 'var(--q-urgent-bg)', urgentText: 'var(--q-urgent-text)',
  selectedBg: 'var(--q-selected-bg)', onAccent: 'var(--q-on-accent)',
} as const;

const panel: React.CSSProperties = {
  background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
};

const MAX_SUBJECT = 200;
const MAX_BODY = 8_000;

/** Who wrote this, in words a customer reads — never a bare role name. */
const AUTHOR: Record<string, { label: string; Icon: typeof User; colour: string }> = {
  customer: { label: 'You',                       Icon: User,      colour: C.muted },
  ai:       { label: 'HOPEFX assistant · AI',     Icon: Bot,       colour: C.accent },
  operator: { label: 'HOPEFX support',            Icon: UserCheck, colour: C.ok },
  system:   { label: 'Automatic update',          Icon: LifeBuoy,  colour: C.waiting },
};

function refusalText(err: unknown): string {
  const e = err as { response?: { data?: { detail?: string } }; message?: string };
  return e?.response?.data?.detail || e?.message || 'That did not go through.';
}

function when(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
}

export default function Support(): React.ReactElement {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [reply, setReply] = useState('');
  const [error, setError] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ['support', 'mine'],
    queryFn: async () => (await supportApi.myTickets()).data as { tickets: MyTicket[] },
  });

  const thread = useQuery({
    queryKey: ['support', 'mine', selected],
    queryFn: async () => (await supportApi.myThread(selected as string)).data as { ticket: MyTicket; messages: Message[] },
    enabled: Boolean(selected),
    // A customer watching for a reply should see it arrive without reloading.
    // There is no live channel on this surface: `support_queue` is
    // operator-only, and giving customers one would be a channel carrying
    // other people's tickets.
    refetchInterval: 15_000,
  });

  const done = useCallback(() => {
    setError(null);
    void qc.invalidateQueries({ queryKey: ['support', 'mine'] });
  }, [qc]);

  const open = useMutation({
    mutationFn: (v: { subject: string; body: string }) => supportApi.open(v.subject, v.body),
    onSuccess: () => { setComposing(false); setSubject(''); setBody(''); done(); },
    onError: (e) => setError(refusalText(e)),
  });
  const say = useMutation({
    mutationFn: (v: { id: string; body: string }) => supportApi.say(v.id, v.body),
    onSuccess: () => { setReply(''); done(); void qc.invalidateQueries({ queryKey: ['support', 'mine', selected] }); },
    onError: (e) => setError(refusalText(e)),
  });

  const current = thread.data?.ticket ?? null;
  const resolved = current?.status === 'resolved';

  return (
    <div style={{ background: C.bg, color: C.text, minHeight: '100%', padding: 16 }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Support</h1>
        <button
          type="button" data-testid="new-ticket"
          onClick={() => { setComposing(true); setSelected(null); setError(null); }}
          style={{
            marginLeft: 'auto', padding: '6px 13px', fontSize: 12.5, borderRadius: 6, fontWeight: 600,
            border: `1px solid ${C.accent}`, background: C.accent, color: C.onAccent, cursor: 'pointer',
          }}
        >
          <Plus size={13} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 5 }} />
          New ticket
        </button>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 320px) 1fr', gap: 14, alignItems: 'start' }}>
        {/* ── my tickets ─────────────────────────────────────────────────── */}
        <section style={{ ...panel, overflow: 'hidden' }} aria-label="My tickets">
          <h2 style={{
            margin: 0, padding: '10px 12px', fontSize: 11, letterSpacing: '.08em',
            textTransform: 'uppercase', color: C.muted, borderBottom: `1px solid ${C.border}`,
          }}>
            My tickets
          </h2>

          {list.isLoading ? (
            <p style={{ padding: 22, color: C.muted, margin: 0 }}>Loading your tickets…</p>
          ) : list.isError ? (
            <p data-testid="list-error" style={{ padding: 18, margin: 0, color: C.urgent, fontSize: 13 }}>
              <AlertTriangle size={14} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6 }} />
              Your tickets could not be loaded, so this is not an empty list — it is an unknown one.
              {' '}{refusalText(list.error)}
            </p>
          ) : (list.data?.tickets.length ?? 0) === 0 ? (
            <div data-testid="no-tickets" style={{ padding: '28px 18px', textAlign: 'center' }}>
              <LifeBuoy size={22} aria-hidden="true" style={{ color: C.accent }} />
              <p style={{ margin: '8px 0 4px', fontWeight: 600 }}>No tickets yet.</p>
              <p style={{ margin: 0, color: C.muted, fontSize: 12.5 }}>
                Ask us anything about your account, the platform or a trade that did not behave.
              </p>
            </div>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 520, overflowY: 'auto' }}>
              {list.data!.tickets.map((t) => (
                <li key={t.id}>
                  <button
                    type="button" data-testid={`mine-${t.id}`}
                    onClick={() => { setSelected(t.id); setComposing(false); setError(null); }}
                    aria-current={selected === t.id}
                    style={{
                      display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
                      background: selected === t.id ? C.selectedBg : 'transparent',
                      border: 'none', borderBottom: `1px solid ${C.border}`,
                      borderLeft: `3px solid ${t.status === 'resolved' ? C.border : t.needs_human ? C.waiting : C.accent}`,
                      padding: '10px 12px', color: C.text,
                    }}
                  >
                    <span style={{ display: 'block', fontWeight: 500, overflowWrap: 'anywhere' }}>{t.subject}</span>
                    <span style={{ display: 'block', marginTop: 4, fontSize: 11.5, color: C.muted }}>
                      {t.status === 'resolved'
                        ? 'Resolved'
                        : t.needs_human
                          ? 'With our support team'
                          : t.first_response_at ? 'Answered' : 'Open'}
                      {t.created_at ? ` · ${when(t.created_at)}` : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* ── thread / composer ──────────────────────────────────────────── */}
        <section style={{ ...panel, display: 'flex', flexDirection: 'column', minWidth: 0 }} aria-label="Ticket">
          {composing ? (
            <div style={{ padding: 16 }}>
              <h2 style={{ margin: '0 0 12px', fontSize: 15 }}>Tell us what is happening</h2>

              {error ? (
                <p data-testid="compose-error" style={{
                  margin: '0 0 12px', padding: '9px 12px', borderRadius: 6, fontSize: 12.5,
                  background: C.urgentBg, border: `1px solid ${C.urgent}`, color: C.urgentText,
                }}>{error}</p>
              ) : null}

              <label htmlFor="ticket-subject" style={{ display: 'block', fontSize: 12, color: C.muted, marginBottom: 4 }}>
                Subject
              </label>
              <input
                id="ticket-subject" data-testid="subject-input" value={subject} maxLength={MAX_SUBJECT}
                onChange={(e) => setSubject(e.target.value)}
                style={{
                  width: '100%', background: C.bg, color: C.text, border: `1px solid ${C.border}`,
                  borderRadius: 6, padding: '8px 10px', marginBottom: 12,
                }}
              />

              <label htmlFor="ticket-body" style={{ display: 'block', fontSize: 12, color: C.muted, marginBottom: 4 }}>
                What happened
              </label>
              <textarea
                id="ticket-body" data-testid="body-input" value={body} maxLength={MAX_BODY}
                onChange={(e) => setBody(e.target.value)}
                style={{
                  width: '100%', minHeight: 130, background: C.bg, color: C.text,
                  border: `1px solid ${C.border}`, borderRadius: 6, padding: '8px 10px', resize: 'vertical',
                }}
              />

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
                <span style={{ flex: 1, fontSize: 11.5, color: C.muted }}>
                  Our assistant answers what it can. Anything about your money, your account or a
                  complaint always goes to a person.
                </span>
                <button
                  type="button" onClick={() => { setComposing(false); setError(null); }}
                  style={{ ...panel, padding: '6px 12px', fontSize: 12.5, color: C.muted, cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="button" data-testid="submit-ticket"
                  // Refused here as well as on the server: an empty body is a
                  // 422 there, and spending a round trip to learn what the page
                  // already knows is not a better experience.
                  onClick={() => {
                    if (!subject.trim() || !body.trim()) {
                      setError('Please give the ticket a subject and tell us what happened.');
                      return;
                    }
                    open.mutate({ subject: subject.trim(), body: body.trim() });
                  }}
                  disabled={open.isPending}
                  style={{
                    padding: '6px 13px', fontSize: 12.5, borderRadius: 6, fontWeight: 600,
                    border: `1px solid ${C.accent}`, background: C.accent, color: C.onAccent, cursor: 'pointer',
                  }}
                >
                  {open.isPending ? 'Sending…' : 'Send'}
                </button>
              </div>
            </div>
          ) : !selected ? (
            <p style={{ padding: 40, textAlign: 'center', color: C.muted, margin: 0 }}>
              Pick a ticket to read it, or start a new one.
            </p>
          ) : thread.isLoading ? (
            <p style={{ padding: 22, color: C.muted, margin: 0 }}>Loading…</p>
          ) : thread.isError ? (
            <p data-testid="thread-error" style={{ padding: 18, color: C.urgent, margin: 0 }}>
              {refusalText(thread.error)}
            </p>
          ) : current ? (
            <>
              <div style={{ padding: '12px 14px', borderBottom: `1px solid ${C.border}` }}>
                <h2 data-testid="thread-subject" style={{ margin: 0, fontSize: 15 }}>{current.subject}</h2>
              </div>

              {current.needs_human && !resolved ? (
                <p data-testid="human-coming" style={{
                  margin: '12px 14px 0', padding: '10px 12px', borderRadius: 6, fontSize: 12.5,
                  background: C.selectedBg, border: `1px solid ${C.border}`, color: C.text,
                }}>
                  <UserCheck size={14} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6, color: C.waiting }} />
                  <strong>Someone from our team is handling this.</strong>{' '}
                  We have taken our assistant off this conversation on purpose — it is not the right
                  thing to answer it. You will get a reply here.
                </p>
              ) : null}

              <ul style={{ listStyle: 'none', margin: 0, padding: 14, display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto', maxHeight: 420 }}>
                {(thread.data?.messages ?? []).map((m, i) => {
                  const who = AUTHOR[m.author_kind] ?? { label: 'HOPEFX', Icon: LifeBuoy, colour: C.muted };
                  const isMe = m.author_kind === 'customer';
                  return (
                    <li
                      key={`${m.created_at ?? i}-${i}`} data-testid={`msg-${i}`}
                      style={{
                        ...panel, padding: '9px 12px', maxWidth: '92%',
                        marginLeft: isMe ? 'auto' : undefined,
                        borderLeft: `2px solid ${who.colour}`,
                      }}
                    >
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: who.colour, marginBottom: 4 }}>
                        <who.Icon size={11} aria-hidden="true" />
                        {who.label}
                        {m.created_at ? <span style={{ color: C.muted }}>· {when(m.created_at)}</span> : null}
                      </span>
                      <p style={{ margin: 0, overflowWrap: 'anywhere' }}>{m.body}</p>
                    </li>
                  );
                })}
              </ul>

              <div style={{ marginTop: 'auto', borderTop: `1px solid ${C.border}`, padding: 14 }}>
                {error ? (
                  <p data-testid="reply-error" style={{
                    margin: '0 0 10px', padding: '8px 11px', borderRadius: 6, fontSize: 12.5,
                    background: C.urgentBg, border: `1px solid ${C.urgent}`, color: C.urgentText,
                  }}>{error}</p>
                ) : null}
                <label htmlFor="my-reply" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
                  Add to this ticket
                </label>
                <textarea
                  id="my-reply" data-testid="my-reply" value={reply} maxLength={MAX_BODY}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder={resolved ? 'Replying reopens this ticket.' : 'Add anything else…'}
                  style={{
                    width: '100%', minHeight: 60, background: C.bg, color: C.text,
                    border: `1px solid ${C.border}`, borderRadius: 6, padding: '8px 10px', resize: 'vertical',
                  }}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
                  <span style={{ flex: 1, fontSize: 11.5, color: C.muted }}>
                    {resolved ? 'This ticket is resolved — replying reopens it.' : 'We will reply here.'}
                  </span>
                  <button
                    type="button" data-testid="send-reply"
                    onClick={() => { if (reply.trim()) say.mutate({ id: current.id, body: reply.trim() }); }}
                    disabled={say.isPending}
                    style={{
                      padding: '6px 13px', fontSize: 12.5, borderRadius: 6, fontWeight: 600,
                      border: `1px solid ${C.accent}`, background: C.accent, color: C.onAccent, cursor: 'pointer',
                    }}
                  >
                    Send
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </section>
      </div>
    </div>
  );
}
