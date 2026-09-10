/**
 * SupportConsole — the operator's view of the support desk.
 *
 * Approved from a flow-prototype review surface (MASTER_OUTSTANDING §A7). The
 * prototype proved interaction intent; these are the rules it was approved on,
 * carried into production and held by `src/test/support_console.test.tsx`.
 *
 *  * **The page says which source is feeding it.** `support_queue` is a
 *    privileged channel and the server refuses it by role, so "live", "polling"
 *    and "refused" are three different states with three different labels. A
 *    console that stopped updating must never look like a quiet queue — that is
 *    the same defect class as a status rendered from a constant (D6).
 *  * **No control the server would refuse.** A ticket another operator holds
 *    offers no Claim button, and the composer stays disabled until this
 *    operator holds the ticket. The backend refuses both independently; the UI
 *    not offering them is the second refusal, not the only one.
 *  * **An escalation carries its reason.** The floor's own words travel to
 *    whoever takes over. "Needs a human" without the reason is not actionable.
 *  * **Absence is a state.** Empty, loading and failed are three distinct
 *    renders. An empty queue reads as finished work; a failed request says so
 *    where it sits rather than rendering as an empty queue.
 *
 * Queue state deliberately avoids the market palette. Green and red mean price
 * direction on this platform, so a red row must not read as "down": waiting is
 * amber, held-by-you is the accent, held-by-someone-else is slate.
 */

import React, { useCallback, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle, CheckCircle2, Inbox, Radio, RefreshCw, UserCheck, WifiOff,
} from 'lucide-react';
import { supportApi } from '../hooks/useApi';
import { useStore } from '../store';
import { useSupportQueue, type LiveSource } from '../hooks/useSupportQueue';

// ── types ────────────────────────────────────────────────────────────────────

interface Ticket {
  id: string;
  user_id: string;
  subject: string;
  status: string;
  category: string | null;
  department: string | null;
  needs_human: boolean;
  assigned_operator_id: string | null;
  escalation_reason: string | null;
  matched_on: string | null;
  created_at: string | null;
  first_response_at: string | null;
}

interface Message {
  author_kind: string;
  author_id: string | null;
  body: string;
  created_at: string | null;
}

// ── visual language (matches the approved prototype) ─────────────────────────

/**
 * Every value is a token from `frontend/src/index.css`, not a literal.
 *
 * The colour ratchet blocked the first version of this file — 25 hardcoded
 * hex values — and it was right to: 7,340 such literals are why the light/dark
 * toggle changes nothing and why a white-label tenant's brand colour cannot
 * reach the product. The queue semantics did not exist as tokens, so they were
 * added rather than inlined here.
 */
const C = {
  bg: 'var(--bg)', surface: 'var(--surface)', raised: 'var(--raised)',
  border: 'var(--border)', text: 'var(--text)', muted: 'var(--text-muted)',
  dim: 'var(--text-muted)', accent: 'var(--accent)',
  waiting: 'var(--q-waiting)', theirs: 'var(--q-theirs)', done: 'var(--q-done)',
  urgent: 'var(--q-urgent)', ok: 'var(--bull)',
  urgentBg: 'var(--q-urgent-bg)', urgentText: 'var(--q-urgent-text)',
  selectedBg: 'var(--q-selected-bg)', accentEdge: 'var(--q-accent-edge)',
  onAccent: 'var(--q-on-accent)',
} as const;

const panel: React.CSSProperties = {
  background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
};

const LIVE_LABEL: Record<LiveSource, { text: string; colour: string; Icon: typeof Radio }> = {
  live:    { text: 'live · support_queue', colour: C.ok,      Icon: Radio },
  poll:    { text: 'polling · socket quiet', colour: C.waiting, Icon: RefreshCw },
  refused: { text: 'poll only · channel refused for your role', colour: C.urgent, Icon: WifiOff },
};

function ownership(t: Ticket, me: string | null): 'waiting' | 'mine' | 'theirs' | 'done' {
  if (t.status === 'resolved') return 'done';
  if (!t.assigned_operator_id) return 'waiting';
  return t.assigned_operator_id === me ? 'mine' : 'theirs';
}

const EDGE: Record<string, string> = {
  waiting: C.waiting, mine: C.accent, theirs: C.theirs, done: C.done,
};

function age(iso: string | null): string {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d`;
}

/** The server's own words when it refuses. Never replaced with a generic line. */
function refusalText(err: unknown): string {
  const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string };
  return e?.response?.data?.detail || e?.message || 'The server refused that.';
}

// ── page ─────────────────────────────────────────────────────────────────────

export default function SupportConsole(): React.ReactElement {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [unassignedOnly, setUnassignedOnly] = useState(false);
  const [draft, setDraft] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmResolve, setConfirmResolve] = useState(false);

  const onLiveEvent = useCallback(() => {
    // The frame carries a queue row, but the queue is the authority. Refetching
    // keeps one source of truth rather than merging a partial row into a list
    // and hoping the two agree.
    void qc.invalidateQueries({ queryKey: ['support', 'queue'] });
    void qc.invalidateQueries({ queryKey: ['support', 'thread'] });
  }, [qc]);

  const live = useSupportQueue(onLiveEvent);

  const queue = useQuery({
    queryKey: ['support', 'queue', unassignedOnly],
    queryFn: async () => (await supportApi.queue(unassignedOnly)).data as { tickets: Ticket[]; count: number },
    // Polling is not a fallback bolted on after a failure — it is what keeps
    // the page correct when the socket is quiet, and the pill says which is
    // feeding it.
    refetchInterval: live.source === 'live' ? 30_000 : 10_000,
  });

  const thread = useQuery({
    queryKey: ['support', 'thread', selected],
    queryFn: async () => (await supportApi.thread(selected as string)).data as { ticket: Ticket; messages: Message[] },
    enabled: Boolean(selected),
  });

  const current = thread.data?.ticket ?? null;

  // Who this operator is, from the authenticated session — never inferred.
  //
  // The first version derived it from the queue: "the first ticket someone
  // holds must be mine". A test caught it immediately — a ticket held by
  // `ops-ren` rendered as "you", so the console showed another operator's
  // work as this operator's, offered Release on it, and hid the holder's name
  // exactly where it was needed. Guessing an identity is Rule 2 at its most
  // expensive: an unmeasured value presented as the best case.
  const me = useStore((st) => st.user?.id ?? null);

  const mine = Boolean(current?.assigned_operator_id && current.assigned_operator_id === me);
  const heldByOther = Boolean(current?.assigned_operator_id && current.assigned_operator_id !== me);

  const after = useCallback(() => {
    setActionError(null);
    void qc.invalidateQueries({ queryKey: ['support'] });
  }, [qc]);
  const onFail = useCallback((e: unknown) => setActionError(refusalText(e)), []);

  const claim   = useMutation({ mutationFn: (id: string) => supportApi.claim(id),   onSuccess: after, onError: onFail });
  const release = useMutation({ mutationFn: (id: string) => supportApi.release(id), onSuccess: after, onError: onFail });
  const resolve = useMutation({
    mutationFn: (id: string) => supportApi.resolve(id),
    onSuccess: () => { setConfirmResolve(false); after(); }, onError: onFail,
  });
  const reply = useMutation({
    mutationFn: (v: { id: string; body: string }) => supportApi.reply(v.id, v.body),
    onSuccess: () => { setDraft(''); after(); }, onError: onFail,
  });

  const L = LIVE_LABEL[live.source];

  return (
    <div style={{ background: C.bg, color: C.text, minHeight: '100%', padding: 16 }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Support console</h1>
        <span
          data-testid="live-source"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
            color: L.colour, border: `1px solid ${C.border}`, borderRadius: 99, padding: '3px 10px',
          }}
        >
          <L.Icon size={13} aria-hidden="true" />
          {L.text}
        </span>
        <button
          type="button"
          onClick={() => void qc.invalidateQueries({ queryKey: ['support'] })}
          style={{ marginLeft: 'auto', ...panel, color: C.muted, fontSize: 12, padding: '5px 11px', cursor: 'pointer' }}
        >
          <RefreshCw size={12} aria-hidden="true" style={{ marginRight: 5 }} />Refresh
        </button>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 340px) 1fr', gap: 14, alignItems: 'start' }}>
        {/* ── queue ─────────────────────────────────────────────────────── */}
        <section style={{ ...panel, overflow: 'hidden' }} aria-label="Operator queue">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', borderBottom: `1px solid ${C.border}` }}>
            <h2 style={{ margin: 0, fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', color: C.dim }}>
              Waiting on a person
            </h2>
            {queue.data ? (
              <span style={{ fontSize: 12, color: C.waiting, border: `1px solid ${C.border}`, borderRadius: 99, padding: '0 8px' }}>
                {queue.data.count}
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => setUnassignedOnly((v) => !v)}
              aria-pressed={unassignedOnly}
              style={{
                marginLeft: 'auto', fontSize: 11, cursor: 'pointer', padding: '3px 9px', borderRadius: 6,
                border: `1px solid ${unassignedOnly ? C.accent : C.border}`,
                color: unassignedOnly ? C.accent : C.muted, background: 'transparent',
              }}
            >
              Unassigned only
            </button>
          </div>

          {queue.isLoading ? (
            <p data-testid="queue-loading" style={{ padding: 24, color: C.dim, margin: 0 }}>Loading the queue…</p>
          ) : queue.isError ? (
            <p data-testid="queue-error" style={{ padding: 20, margin: 0, color: C.urgent, fontSize: 13 }}>
              <AlertTriangle size={14} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6 }} />
              The queue could not be loaded, so this is not an empty queue — it is an unknown one.
              {' '}{refusalText(queue.error)}
            </p>
          ) : (queue.data?.tickets.length ?? 0) === 0 ? (
            <div data-testid="queue-empty" style={{ padding: '32px 20px', textAlign: 'center' }}>
              <Inbox size={22} aria-hidden="true" style={{ color: C.ok }} />
              <p style={{ margin: '8px 0 4px', color: C.ok, fontWeight: 600 }}>Nothing is waiting.</p>
              <p style={{ margin: 0, color: C.dim, fontSize: 12.5 }}>Every escalated ticket has been answered.</p>
            </div>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 560, overflowY: 'auto' }}>
              {queue.data!.tickets.map((t) => {
                const own = ownership(t, me);
                return (
                  <li key={t.id}>
                    <button
                      type="button"
                      data-testid={`row-${t.id}`}
                      onClick={() => { setSelected(t.id); setActionError(null); setConfirmResolve(false); }}
                      aria-current={selected === t.id}
                      style={{
                        display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
                        background: selected === t.id ? C.selectedBg : 'transparent',
                        border: 'none', borderBottom: `1px solid ${C.border}`,
                        borderLeft: `3px solid ${EDGE[own]}`, padding: '10px 12px',
                        color: C.text, opacity: own === 'done' ? 0.55 : 1,
                      }}
                    >
                      <span style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                        <span style={{ flex: 1, minWidth: 0, fontWeight: 500, overflowWrap: 'anywhere' }}>{t.subject}</span>
                        <span style={{ fontSize: 11, color: C.dim }}>{age(t.created_at)}</span>
                      </span>
                      <span style={{ display: 'flex', gap: 6, marginTop: 5, flexWrap: 'wrap', fontSize: 10.5, color: C.muted }}>
                        <span style={{ border: `1px solid ${C.border}`, borderRadius: 3, padding: '0 6px' }}>{t.id}</span>
                        {t.department ? (
                          <span style={{ border: `1px solid ${C.accentEdge}`, color: C.accent, borderRadius: 3, padding: '0 6px' }}>
                            {t.department}
                          </span>
                        ) : null}
                        {t.assigned_operator_id ? (
                          <span style={{
                            border: `1px solid ${C.border}`, borderRadius: 3, padding: '0 6px',
                            color: own === 'mine' ? C.accent : C.theirs,
                          }}>
                            <UserCheck size={9} aria-hidden="true" style={{ verticalAlign: -1, marginRight: 3 }} />
                            {own === 'mine' ? 'you' : t.assigned_operator_id}
                          </span>
                        ) : null}
                      </span>
                      {/* The signature element: why the floor sent it, in its own words. */}
                      {t.escalation_reason ? (
                        <span style={{
                          display: 'block', marginTop: 6, fontSize: 11.5, lineHeight: 1.4,
                          color: C.urgentText, background: C.urgentBg, borderLeft: `2px solid ${C.urgent}`,
                          padding: '4px 8px', borderRadius: '0 3px 3px 0', overflowWrap: 'anywhere',
                        }}>
                          {t.escalation_reason}
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* ── thread ────────────────────────────────────────────────────── */}
        <section style={{ ...panel, display: 'flex', flexDirection: 'column', minWidth: 0 }} aria-label="Ticket thread">
          {!selected ? (
            <p style={{ padding: 40, textAlign: 'center', color: C.dim, margin: 0 }}>
              Pick a ticket to read it. Opening one does not claim it.
            </p>
          ) : thread.isLoading ? (
            <p style={{ padding: 24, color: C.dim, margin: 0 }}>Loading the thread…</p>
          ) : thread.isError ? (
            <p data-testid="thread-error" style={{ padding: 20, color: C.urgent, margin: 0 }}>
              {refusalText(thread.error)}
            </p>
          ) : current ? (
            <>
              <div style={{ padding: '12px 14px', borderBottom: `1px solid ${C.border}` }}>
                <h2 data-testid="thread-subject" style={{ margin: '0 0 6px', fontSize: 15 }}>{current.subject}</h2>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', fontSize: 10.5, color: C.muted }}>
                  <span style={{ border: `1px solid ${C.border}`, borderRadius: 3, padding: '0 6px' }}>{current.id}</span>
                  {current.category ? <span style={{ border: `1px solid ${C.border}`, borderRadius: 3, padding: '0 6px' }}>{current.category}</span> : null}
                  <span style={{ border: `1px solid ${C.border}`, borderRadius: 3, padding: '0 6px' }}>
                    {current.status === 'resolved' ? 'resolved'
                      : mine ? 'held by you'
                      : current.assigned_operator_id ? `held by ${current.assigned_operator_id}`
                      : 'unassigned'}
                  </span>
                </div>
              </div>

              {actionError ? (
                <p data-testid="action-error" style={{
                  margin: '12px 14px 0', padding: '9px 12px', borderRadius: 6, fontSize: 12.5,
                  background: C.urgentBg, border: `1px solid ${C.urgent}`, color: C.urgentText,
                }}>
                  {actionError}
                </p>
              ) : null}

              <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', padding: '10px 14px', borderBottom: `1px solid ${C.border}` }}>
                {mine ? (
                  <button
                    type="button" data-testid="act-release" onClick={() => release.mutate(current.id)}
                    disabled={release.isPending}
                    style={{ ...panel, padding: '6px 12px', fontSize: 12.5, cursor: 'pointer', color: C.text }}
                  >
                    Release
                  </button>
                ) : (
                  <button
                    type="button" data-testid="act-claim" onClick={() => claim.mutate(current.id)}
                    // A ticket someone else holds offers no working Claim: the
                    // server refuses it, and a button that gets refused is worse
                    // than no button.
                    disabled={heldByOther || current.status === 'resolved' || claim.isPending}
                    style={{
                      padding: '6px 12px', fontSize: 12.5, borderRadius: 6, fontWeight: 600,
                      border: `1px solid ${C.accent}`, background: C.accent, color: C.onAccent,
                      cursor: heldByOther ? 'not-allowed' : 'pointer',
                      opacity: heldByOther || current.status === 'resolved' ? 0.4 : 1,
                    }}
                  >
                    Claim
                  </button>
                )}

                {confirmResolve ? (
                  <>
                    <span style={{ fontSize: 12.5, color: C.waiting, alignSelf: 'center' }}>
                      Resolve this? A customer reply reopens it automatically.
                    </span>
                    <button
                      type="button" data-testid="act-resolve-confirm" onClick={() => resolve.mutate(current.id)}
                      style={{ ...panel, padding: '6px 12px', fontSize: 12.5, cursor: 'pointer', color: C.urgentText, borderColor: C.urgent }}
                    >
                      Yes, resolve
                    </button>
                    <button
                      type="button" onClick={() => setConfirmResolve(false)}
                      style={{ ...panel, padding: '6px 12px', fontSize: 12.5, cursor: 'pointer', color: C.muted }}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    type="button" data-testid="act-resolve" onClick={() => setConfirmResolve(true)}
                    disabled={!mine || current.status === 'resolved'}
                    style={{
                      ...panel, padding: '6px 12px', fontSize: 12.5, color: C.text,
                      cursor: mine ? 'pointer' : 'not-allowed', opacity: mine ? 1 : 0.4,
                    }}
                  >
                    Resolve
                  </button>
                )}
              </div>

              <ul style={{ listStyle: 'none', margin: 0, padding: 14, display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto', maxHeight: 380 }}>
                {(thread.data?.messages ?? []).map((m, i) => (
                  <li
                    key={`${m.created_at ?? i}-${i}`}
                    style={{
                      ...panel, padding: '9px 12px', maxWidth: '92%',
                      marginLeft: m.author_kind === 'operator' ? 'auto' : undefined,
                      borderLeft: `2px solid ${m.author_kind === 'ai' ? C.accent : m.author_kind === 'operator' ? C.ok : m.author_kind === 'system' ? C.waiting : C.muted}`,
                    }}
                  >
                    <span style={{ display: 'block', fontSize: 10.5, letterSpacing: '.05em', textTransform: 'uppercase', color: C.dim, marginBottom: 4 }}>
                      {m.author_id ?? m.author_kind}
                      {m.author_kind === 'ai' ? ' · AI' : ''}
                    </span>
                    <p style={{ margin: 0, overflowWrap: 'anywhere' }}>{m.body}</p>
                  </li>
                ))}
              </ul>

              <div style={{ marginTop: 'auto', borderTop: `1px solid ${C.border}`, padding: 14 }}>
                <label htmlFor="support-reply" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
                  Reply to the customer
                </label>
                <textarea
                  id="support-reply" data-testid="reply-box" value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  disabled={!mine || current.status === 'resolved'}
                  placeholder={mine ? 'Reply to the customer…' : 'Claim this ticket before replying.'}
                  style={{
                    width: '100%', minHeight: 60, background: C.bg, color: C.text,
                    border: `1px solid ${C.border}`, borderRadius: 6, padding: '8px 10px', resize: 'vertical',
                  }}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
                  <span style={{ flex: 1, fontSize: 11.5, color: C.dim }}>
                    {mine ? 'Sends as you, on the record.' : 'Two operators cannot hold one ticket.'}
                  </span>
                  <button
                    type="button" data-testid="act-send"
                    // Refused here as well as on the server. An empty body is a
                    // 422 there; sending it anyway would spend a round trip to
                    // learn what the page already knows.
                    onClick={() => { if (draft.trim()) reply.mutate({ id: current.id, body: draft.trim() }); }}
                    disabled={!mine || current.status === 'resolved' || reply.isPending}
                    style={{
                      padding: '6px 13px', fontSize: 12.5, borderRadius: 6, fontWeight: 600,
                      border: `1px solid ${C.accent}`, background: C.accent, color: C.onAccent,
                      cursor: mine ? 'pointer' : 'not-allowed', opacity: mine ? 1 : 0.4,
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

      <p style={{ marginTop: 14, fontSize: 11.5, color: C.dim, display: 'flex', gap: 6, alignItems: 'center' }}>
        <CheckCircle2 size={12} aria-hidden="true" />
        Escalations reach this queue from the triage floor. The AI cannot resolve what the floor escalated.
      </p>
    </div>
  );
}
