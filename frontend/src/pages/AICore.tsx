/**
 * AICore — the operator's view of the AI control plane (plan Task 13, item 18).
 *
 * Every panel on this page reads a live endpoint under /api/ai-core. That is
 * the whole design constraint, and it is the D6 rule applied page-wide: the
 * surface this replaces rendered its status from constants, so a control plane
 * that had degraded looked exactly like one that had not.
 *
 * Three consequences, visible throughout:
 *
 *  * **Absence is a state, not a blank.** "No eval report", "no cache
 *    installed", "this provider has no credential" are rendered as findings
 *    with their own wording, because each of them is the reason something else
 *    is refusing, and hiding them turns a diagnosable gap into a silent one.
 *  * **A failed request never renders as a healthy value.** Each panel owns its
 *    own loading, error and empty state; a panel whose request failed says so
 *    where it sits rather than letting a neighbouring panel's success imply the
 *    page loaded.
 *  * **No control is decorative.** The only interactive elements are the
 *    workspace tabs and a refetch button, both of which do exactly what they
 *    say. Capabilities this role does not hold are rendered as text — a button
 *    the server would refuse is worse than no button.
 */

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity, AlertTriangle, BadgeCheck, Ban, Brain, CheckCircle2, CircleSlash,
  Coins, Database, KeyRound, Layers3, RefreshCw, ScrollText, ShieldCheck, XCircle,
} from 'lucide-react';
import { PageHeader, EmptyState, ErrorBanner } from '../components';
import { GenerationWorkbench } from '../components/ai/GenerationWorkbench';
import { PresencePanel } from '../components/ai/PresencePanel';
import { hubEnabled } from '../hub/flag';
import { PanelSkeleton } from '../components/ui/Skeleton';
import { aiCoreApi } from '../hooks/useApi';

// ── shared visual language (matches the intelligence workspaces) ──────────────

const COLOR = {
  ok: '#42d392',
  warn: '#f5b84b',
  bad: '#f36d78',
  info: '#73a7ff',
  muted: '#70809a',
  text: '#e7edf7',
  dim: '#a7b5c9',
} as const;

const panel: React.CSSProperties = {
  background: 'linear-gradient(145deg, rgba(16,25,42,.96), rgba(10,16,28,.96))',
  border: '1px solid #20304a',
  borderRadius: 12,
  padding: 16,
};

const label: React.CSSProperties = {
  color: COLOR.muted, fontSize: 10, fontWeight: 800,
  letterSpacing: '.09em', textTransform: 'uppercase',
};

/** Wide content scrolls inside its own box; the page body never scrolls sideways. */
const scrollBox: React.CSSProperties = { overflowX: 'auto', WebkitOverflowScrolling: 'touch' };

const cell: React.CSSProperties = {
  padding: '9px 10px', borderTop: '1px solid #1e2d44',
  fontSize: 12, color: COLOR.dim, textAlign: 'left', whiteSpace: 'nowrap',
};

const headCell: React.CSSProperties = { ...cell, ...label, borderTop: 'none', paddingBottom: 6 };

/** 44px minimum target, visible focus, pointer cursor — all three are required. */
const button: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 7, justifyContent: 'center',
  minHeight: 44, padding: '0 14px', borderRadius: 8,
  background: '#172740', border: '1px solid #2c4c7a', color: '#c9dcfb',
  fontSize: 12, fontWeight: 800, cursor: 'pointer',
};

/**
 * A yes/no fact, stated in words as well as colour.
 *
 * Colour alone would fail both the contrast rule and any operator who cannot
 * distinguish the two greens — and this page's whole job is being read
 * correctly under pressure.
 */
const Verdict: React.FC<{ ok: boolean; yes: string; no: string }> = ({ ok, yes, no }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: ok ? COLOR.ok : COLOR.bad, fontWeight: 800, fontSize: 12 }}>
    {ok ? <CheckCircle2 size={13} aria-hidden /> : <XCircle size={13} aria-hidden />}
    {ok ? yes : no}
  </span>
);

const Stat: React.FC<{ name: string; value: React.ReactNode; sub?: string; color?: string }> = ({ name, value, sub, color }) => (
  <div style={{ ...panel, padding: '12px 14px', flex: 1, minWidth: 150 }}>
    <div style={label}>{name}</div>
    <div style={{ fontSize: 20, fontWeight: 850, marginTop: 4, color: color ?? COLOR.text }}>{value}</div>
    {sub && <div style={{ color: COLOR.muted, fontSize: 10, marginTop: 3 }}>{sub}</div>}
  </div>
);

/**
 * One panel's request, rendered honestly in all four of its states.
 *
 * `error` carries its own retry, because an error with no recovery path leaves
 * the operator with nothing to do but reload the whole page.
 */
function PanelState({
  isLoading, isError, onRetry, what, children,
}: {
  isLoading: boolean; isError: boolean; onRetry: () => void; what: string; children: React.ReactNode;
}) {
  if (isLoading) return <PanelSkeleton />;
  if (isError) {
    return (
      <div>
        <ErrorBanner level="error" message={`Could not load ${what}. This panel is showing nothing rather than a stale or assumed value.`} />
        <button type="button" style={{ ...button, marginTop: 10 }} onClick={onRetry}>
          <RefreshCw size={14} aria-hidden /> Retry
        </button>
      </div>
    );
  }
  return <>{children}</>;
}

const Section: React.FC<{ title: string; icon: React.ElementType; note?: string; children: React.ReactNode }> = ({ title, icon: Icon, note, children }) => (
  <section style={{ ...panel, marginBottom: 14 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 4 }}>
      <Icon size={16} color={COLOR.info} aria-hidden />
      <h2 style={{ margin: 0, fontSize: 15, color: COLOR.text }}>{title}</h2>
    </div>
    {note && <p style={{ margin: '0 0 12px', color: COLOR.muted, fontSize: 11, lineHeight: 1.6, maxWidth: '72ch' }}>{note}</p>}
    {children}
  </section>
);

// ── response shapes (api/ai_core.py) ──────────────────────────────────────────

interface Summary {
  role: string; is_superadmin: boolean;
  reasoning_primary: string | null; reasoning_primary_reachable: boolean;
  fallback_available: boolean;
  providers_reachable: string[]; providers_unreachable: string[];
  local_inference_enabled: boolean;
  calls_recorded: number; calls_unserved: number; spent_usd: number; cache_enabled: boolean;
  /** Which of the AI's durable stores are installed. Optional so an older
   *  server, or a partial response, still renders the rest of the header. */
  durability?: {
    budget_shared: boolean;
    audit_durable: boolean;
    eval_report_shared: boolean;
    /** null when the eval schedule is off, which is the default. */
    eval_schedule_hours: number | null;
  };
}
interface ChainLeg { position: number; provider: string; model: string; reachable: boolean; local: boolean }
interface ChainRole { role: string; legs: ChainLeg[]; usable_legs: number; fallback_available: boolean; primary_reachable: boolean }
interface Chain {
  roles: ChainRole[]; providers: Record<string, boolean>;
  embedding: { provider: string; model: string };
  local_provider: string; local_inference_enabled: boolean;
}
interface Budget {
  scope: 'self' | 'platform'; operator: string; spent_usd: number;
  per_operator_ceiling_usd: number; headroom_usd: number;
  operators?: Record<string, number>;
  global_spent_usd?: number; global_ceiling_usd?: number; global_headroom_usd?: number;
}
interface CallRecord {
  at: string; operator: string; role: string; prompt_sha256: string;
  attempts: { provider?: string | null; model?: string; reason?: string; skipped?: boolean }[];
  served_by: string | null; model: string | null;
  latency_ms: number; cost_usd: number; tokens_in: number; tokens_out: number;
}
interface Calls { scope: string; calls: CallRecord[]; returned: number; total_visible: number; retention: string }
interface Cache { enabled: boolean; entries: number; hits: number; misses: number; hit_rate: number; ttl_s?: number; max_entries?: number; detail?: string }
interface Evals {
  report: { score: number; total: number; passed: number; failed_case_ids: string[]; ran_at: number } | null;
  promotion_allowed: boolean; promotion_detail: string; gate_target: string;
}
interface CapabilityRow {
  name: string; tier: string; min_role: string;
  requires_2fa: boolean; quorum_needs_superadmin: boolean; permitted: boolean;
}
interface Capabilities { role: string; is_superadmin: boolean; capabilities: CapabilityRow[]; tiers: Record<string, string[]>; quorum_needs_superadmin_kinds: string[] }

const REFETCH_MS = 30_000;

type Tab = 'Presence' | 'Workbench' | 'Overview' | 'Model chain' | 'Spend' | 'Calls' | 'Governance';

const TABS: { key: Tab; label: string }[] = [
  // First, and the default when the flag is on: §4 asks that the AI Core BE the
  // primary interface rather than a permanent dashboard. Nothing below it moved
  // or was removed — what changed is which one opens.
  { key: 'Presence', label: 'Presence' },
  { key: 'Workbench', label: 'Workbench' },
  { key: 'Overview', label: 'Overview' },
  { key: 'Model chain', label: 'Model chain' },
  { key: 'Spend', label: 'Spend' },
  { key: 'Calls', label: 'Calls' },
  { key: 'Governance', label: 'Governance' },
];

export const AICore: React.FC = () => {
  // What this page opens on.
  //
  // It used to land on Overview, and a comment here said that promoting another
  // tab "changes what this page IS" and was the owner's call rather than one to
  // slip in with a feature. The owner has since made that call: the AI Core is
  // the AI, not a status board about it. So with the flag on it opens on the
  // presence, and with the flag off it opens exactly where it always did.
  //
  // Every other tab is untouched and one click away, which is what makes this
  // reading of §4 cost nothing.
  const [tab, setTab] = useState<Tab>(hubEnabled() ? 'Presence' : 'Overview');

  const summary = useQuery<Summary>({
    queryKey: ['ai-core', 'summary'],
    queryFn: async () => (await aiCoreApi.summary()).data,
    refetchInterval: REFETCH_MS,
  });
  const chain = useQuery<Chain>({
    queryKey: ['ai-core', 'chain'],
    queryFn: async () => (await aiCoreApi.chain()).data,
    refetchInterval: REFETCH_MS,
  });
  const budget = useQuery<Budget>({
    queryKey: ['ai-core', 'budget'],
    queryFn: async () => (await aiCoreApi.budget()).data,
    refetchInterval: REFETCH_MS,
  });
  const calls = useQuery<Calls>({
    queryKey: ['ai-core', 'calls'],
    queryFn: async () => (await aiCoreApi.calls(50)).data,
    refetchInterval: REFETCH_MS,
  });
  const cache = useQuery<Cache>({
    queryKey: ['ai-core', 'cache'],
    queryFn: async () => (await aiCoreApi.cache()).data,
    refetchInterval: REFETCH_MS,
  });
  const evals = useQuery<Evals>({
    queryKey: ['ai-core', 'evals'],
    queryFn: async () => (await aiCoreApi.evals()).data,
    refetchInterval: REFETCH_MS,
  });
  const capabilities = useQuery<Capabilities>({
    queryKey: ['ai-core', 'capabilities'],
    queryFn: async () => (await aiCoreApi.capabilities()).data,
  });

  const refreshAll = () => {
    void summary.refetch(); void chain.refetch(); void budget.refetch();
    void calls.refetch(); void cache.refetch(); void evals.refetch(); void capabilities.refetch();
  };

  const s = summary.data;

  return (
    <div style={{ padding: '18px 20px 40px', maxWidth: 1360, margin: '0 auto' }}>
      <PageHeader
        title="AI Core"
        subtitle="Which model answers, what it cost, what was refused, and why — read live from the gateway."
        icon={Brain}
        actions={(
          <button type="button" style={button} onClick={refreshAll} aria-label="Refresh every AI Core panel">
            <RefreshCw size={14} aria-hidden /> Refresh
          </button>
        )}
      />

      {/* Tabs. Native buttons so keyboard order matches visual order. */}
      <div role="tablist" aria-label="AI Core workspaces" style={{ display: 'flex', gap: 8, margin: '14px 0', ...scrollBox }}>
        {TABS.map(({ key, label: text }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            style={{
              ...button,
              background: tab === key ? '#1d3358' : '#121c2e',
              borderColor: tab === key ? '#3a6099' : '#20304a',
              color: tab === key ? '#dbe9ff' : COLOR.dim,
            }}
          >
            {text}
          </button>
        ))}
      </div>

      {/* ── Workbench ───────────────────────────────────────────────────────── */}
      {/* The one tab that acts rather than reports. Its own component because
          it owns live state the read-only panels do not, and because a page
          that already renders six report sections should not also grow a job
          queue inline. */}
      {tab === 'Presence' && <PresencePanel providersReachable={s?.providers_reachable?.length} ready={!summary.isLoading} onExit={() => setTab('Overview')} />}

      {tab === 'Workbench' && <GenerationWorkbench />}

      {/* ── Overview ────────────────────────────────────────────────────────── */}
      {tab === 'Overview' && (
        <Section
          title="Control plane at a glance"
          icon={Activity}
          note="Every figure here is read at the moment of the request. A provider with no credential is reported as unreachable rather than omitted, because that is the reason a later leg never answers."
        >
          <PanelState isLoading={summary.isLoading} isError={summary.isError} onRetry={() => void summary.refetch()} what="the control-plane summary">
            {s && (
              <>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                  <Stat
                    name="Reasoning primary"
                    value={s.reasoning_primary ?? 'none configured'}
                    sub={s.reasoning_primary_reachable ? 'credential present' : 'no credential — this leg cannot answer'}
                    color={s.reasoning_primary_reachable ? COLOR.ok : COLOR.bad}
                  />
                  <Stat
                    name="Fallback"
                    value={<Verdict ok={s.fallback_available} yes="Available" no="Not available" />}
                    sub={s.fallback_available ? 'a second reachable leg exists' : 'one reachable leg — a fallback on paper only'}
                  />
                  <Stat name="Calls recorded" value={s.calls_recorded} sub="in the audit ring" />
                  <Stat
                    name="Calls unserved"
                    value={s.calls_unserved}
                    sub={s.calls_unserved ? 'every leg failed on these' : 'no call went unanswered'}
                    color={s.calls_unserved ? COLOR.bad : COLOR.ok}
                  />
                  <Stat name="Spend (you)" value={`$${s.spent_usd.toFixed(2)}`} sub="this month, your operator id" />
                </div>
                <div style={{ display: 'grid', gap: 8, fontSize: 12, color: COLOR.dim }}>
                  <div>
                    <strong style={{ color: COLOR.text }}>Reachable providers: </strong>
                    {s.providers_reachable.length ? s.providers_reachable.join(', ') : <span style={{ color: COLOR.bad }}>none — no model call can succeed</span>}
                  </div>
                  <div>
                    <strong style={{ color: COLOR.text }}>Unreachable: </strong>
                    {s.providers_unreachable.length ? s.providers_unreachable.join(', ') : 'none'}
                  </div>
                  {s.durability && (
                    <div>
                      <strong style={{ color: COLOR.text }}>State on restart: </strong>
                      {(() => {
                        const d = s.durability;
                        // Named by consequence, not by setting. "budget_shared:
                        // false" tells an operator nothing they can act on; "the
                        // ceiling resets on restart" tells them the number in
                        // the settings form is not the number that binds.
                        const perProcess = [
                          !d.budget_shared && 'the spend ceiling resets on restart and each worker holds its own full allowance',
                          !d.audit_durable && 'the call audit trail is in memory and is lost on restart',
                          !d.eval_report_shared && 'the promotion gate forgets its eval report on restart, and a worker that did not run the suite refuses promotion',
                        ].filter(Boolean) as string[];
                        return perProcess.length === 0 ? (
                          <span style={{ color: COLOR.ok }}>
                            spend, audit trail and eval report all survive a restart and are shared across workers
                          </span>
                        ) : (
                          <span style={{ color: COLOR.warn }}>{perProcess.join('; ')}</span>
                        );
                      })()}
                    </div>
                  )}
                  {s.durability && (
                    <div>
                      <strong style={{ color: COLOR.text }}>Eval schedule: </strong>
                      {/* Off is the default and a legitimate choice — every eval
                          case is a paid model call — so this is never styled as
                          a fault. Rendering it in red would push an operator to
                          switch on a recurring bill to clear a warning. */}
                      {s.durability.eval_schedule_hours == null
                        ? 'off — the suite is run by hand, and its report ages out after 24h'
                        : `every ${s.durability.eval_schedule_hours}h (each run is a paid model call)`}
                    </div>
                  )}
                  <div>
                    <strong style={{ color: COLOR.text }}>Local inference: </strong>
                    {s.local_inference_enabled
                      ? 'enabled — optional, and never a primary leg; capability drops sharply against a hosted model'
                      : 'not configured (optional, off by default)'}
                  </div>
                </div>
              </>
            )}
          </PanelState>
        </Section>
      )}

      {/* ── Model chain ─────────────────────────────────────────────────────── */}
      {tab === 'Model chain' && (
        <Section
          title="Model chain"
          icon={Layers3}
          note="The chain as resolved right now, primary first. A leg with no credential is skipped at dispatch, so a role showing three legs and one usable leg has no fallback in practice — that is reported as its own column rather than left to be inferred from the rows."
        >
          <PanelState isLoading={chain.isLoading} isError={chain.isError} onRetry={() => void chain.refetch()} what="the model chain">
            {chain.data && (
              <>
                {chain.data.roles.map((role) => (
                  <div key={role.role} style={{ marginBottom: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                      <span style={{ ...label, color: COLOR.text, fontSize: 12 }}>{role.role}</span>
                      <Verdict ok={role.fallback_available} yes="fallback available" no="no usable fallback" />
                      <span style={{ color: COLOR.muted, fontSize: 11 }}>{role.usable_legs} of {role.legs.length} legs usable</span>
                    </div>
                    <div style={scrollBox}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
                        <thead>
                          <tr>
                            <th style={headCell} scope="col">#</th>
                            <th style={headCell} scope="col">Provider</th>
                            <th style={headCell} scope="col">Model</th>
                            <th style={headCell} scope="col">Credential</th>
                          </tr>
                        </thead>
                        <tbody>
                          {role.legs.map((leg) => (
                            <tr key={`${role.role}-${leg.position}`}>
                              <td style={cell}>{leg.position === 0 ? 'primary' : `fallback ${leg.position}`}</td>
                              <td style={{ ...cell, color: COLOR.text }}>
                                {leg.provider}{leg.local ? ' (local)' : ''}
                              </td>
                              <td style={cell}>{leg.model}</td>
                              <td style={cell}><Verdict ok={leg.reachable} yes="present" no="missing" /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
                <p style={{ color: COLOR.muted, fontSize: 11, margin: '4px 0 0', lineHeight: 1.6, maxWidth: '72ch' }}>
                  Embeddings: <strong style={{ color: COLOR.dim }}>{chain.data.embedding.provider} · {chain.data.embedding.model}</strong>.
                  {' '}Credential presence is reported as a yes/no; the key itself never leaves the server.
                </p>
              </>
            )}
          </PanelState>
        </Section>
      )}

      {/* ── Spend ───────────────────────────────────────────────────────────── */}
      {tab === 'Spend' && (
        <Section
          title="Spend against the ceiling"
          icon={Coins}
          note="Checked before a call is issued, not after — a ceiling enforced after the money is spent is a report, not a limit. A cache hit is not charged."
        >
          <PanelState isLoading={budget.isLoading} isError={budget.isError} onRetry={() => void budget.refetch()} what="spend">
            {budget.data && (
              <>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                  <Stat name="Your spend" value={`$${budget.data.spent_usd.toFixed(2)}`} sub={`ceiling $${budget.data.per_operator_ceiling_usd.toFixed(2)} / month`} />
                  <Stat
                    name="Your headroom"
                    value={`$${budget.data.headroom_usd.toFixed(2)}`}
                    sub={budget.data.headroom_usd > 0 ? 'calls permitted' : 'exhausted — calls are refused'}
                    color={budget.data.headroom_usd > 0 ? COLOR.ok : COLOR.bad}
                  />
                  {budget.data.scope === 'platform' && (
                    <Stat
                      name="Platform spend"
                      value={`$${(budget.data.global_spent_usd ?? 0).toFixed(2)}`}
                      sub={`ceiling $${(budget.data.global_ceiling_usd ?? 0).toFixed(2)} / month`}
                    />
                  )}
                </div>
                {budget.data.scope === 'platform' && budget.data.operators ? (
                  <div style={scrollBox}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 420 }}>
                      <thead>
                        <tr>
                          <th style={headCell} scope="col">Operator</th>
                          <th style={headCell} scope="col">Spent this month</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(budget.data.operators).map(([operator, spent]) => (
                          <tr key={operator}>
                            <td style={{ ...cell, color: COLOR.text }}>{operator}</td>
                            <td style={cell}>${spent.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p style={{ color: COLOR.muted, fontSize: 11, margin: 0, lineHeight: 1.6, maxWidth: '72ch' }}>
                    You are seeing your own spend. The per-operator breakdown and the platform total are superadmin-only.
                  </p>
                )}
              </>
            )}
          </PanelState>
        </Section>
      )}

      {/* ── Calls ───────────────────────────────────────────────────────────── */}
      {tab === 'Calls' && (
        <Section
          title="Recent model calls"
          icon={ScrollText}
          note="Newest first. The prompt is never stored or returned — the digest is what makes two calls comparable without retaining position data. A row with no serving model is a call every leg refused."
        >
          <PanelState isLoading={calls.isLoading} isError={calls.isError} onRetry={() => void calls.refetch()} what="the call history">
            {calls.data && (calls.data.calls.length === 0 ? (
              <EmptyState
                icon={Database}
                title="No model calls recorded"
                description="Nothing has called the gateway in this process yet. This is an empty record, not a failed one."
              />
            ) : (
              <>
                <div style={scrollBox}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 780 }}>
                    <thead>
                      <tr>
                        <th style={headCell} scope="col">When</th>
                        <th style={headCell} scope="col">Role</th>
                        <th style={headCell} scope="col">Served by</th>
                        <th style={headCell} scope="col">Model</th>
                        <th style={headCell} scope="col">Latency</th>
                        <th style={headCell} scope="col">Cost</th>
                        <th style={headCell} scope="col">Prompt digest</th>
                      </tr>
                    </thead>
                    <tbody>
                      {calls.data.calls.map((call, index) => (
                        <tr key={`${call.at}-${index}`}>
                          <td style={cell}>{new Date(call.at).toLocaleTimeString()}</td>
                          <td style={cell}>{call.role}</td>
                          <td style={{ ...cell, color: call.served_by ? COLOR.ok : COLOR.bad, fontWeight: 700 }}>
                            {call.served_by ?? 'no leg served'}
                          </td>
                          <td style={cell}>{call.model ?? '—'}</td>
                          <td style={cell}>{call.latency_ms.toFixed(0)} ms</td>
                          <td style={cell}>${call.cost_usd.toFixed(4)}</td>
                          <td style={{ ...cell, fontFamily: 'ui-monospace, monospace', color: COLOR.muted }}>
                            {call.prompt_sha256.slice(0, 12)}…
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p style={{ color: COLOR.muted, fontSize: 11, margin: '10px 0 0' }}>
                  Showing {calls.data.returned} of {calls.data.total_visible} visible. Retention: {calls.data.retention}.
                </p>
              </>
            ))}
          </PanelState>
        </Section>
      )}

      {/* ── Governance: cache, evals, capabilities ──────────────────────────── */}
      {tab === 'Governance' && (
        <>
          <Section
            title="Response cache"
            icon={Database}
            note="A repeated identical query does not reach the paid tier. A failure is never cached, the key includes the tool state, and a hit is not charged."
          >
            <PanelState isLoading={cache.isLoading} isError={cache.isError} onRetry={() => void cache.refetch()} what="cache statistics">
              {cache.data && (cache.data.enabled ? (
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <Stat name="Entries" value={cache.data.entries} sub={cache.data.max_entries ? `bound ${cache.data.max_entries}` : undefined} />
                  <Stat name="Hits" value={cache.data.hits} />
                  <Stat name="Misses" value={cache.data.misses} />
                  <Stat name="Hit rate" value={`${(cache.data.hit_rate * 100).toFixed(1)}%`} />
                </div>
              ) : (
                <EmptyState
                  icon={CircleSlash}
                  title="No response cache installed"
                  description="Every call reaches a provider. This is reported rather than drawn as an idle cache, because a panel reading &quot;enabled&quot; for a store nothing consults is exactly the decorative control this page exists to remove."
                  serverNote={cache.data.detail ?? null}
                />
              ))}
            </PanelState>
          </Section>

          <Section
            title="Evaluation gate"
            icon={BadgeCheck}
            note="Promotion to canary is refused without a passing, recent report. The gate fails closed: no report means no promotion, and that state is shown rather than left blank."
          >
            <PanelState isLoading={evals.isLoading} isError={evals.isError} onRetry={() => void evals.refetch()} what="the eval report">
              {evals.data && (
                <>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
                    <Stat
                      name={`Promotion to ${evals.data.gate_target}`}
                      value={<Verdict ok={evals.data.promotion_allowed} yes="Permitted" no="Refused" />}
                      sub={evals.data.promotion_detail}
                    />
                    {evals.data.report ? (
                      <>
                        <Stat name="Score" value={evals.data.report.score.toFixed(2)} sub={`${evals.data.report.passed} of ${evals.data.report.total} cases passed`} />
                        <Stat
                          name="Failed cases"
                          value={evals.data.report.failed_case_ids.length}
                          color={evals.data.report.failed_case_ids.length ? COLOR.warn : COLOR.ok}
                          sub={evals.data.report.failed_case_ids.join(', ') || 'none'}
                        />
                      </>
                    ) : null}
                  </div>
                  {!evals.data.report && (
                    <EmptyState
                      icon={AlertTriangle}
                      title="No eval report"
                      description="No suite has been run in this process. The gate refuses on absent evidence — a gate that permits when it has no evidence is not a gate."
                    />
                  )}
                </>
              )}
            </PanelState>
          </Section>

          <Section
            title="What your role may do"
            icon={ShieldCheck}
            note="Resolved by the server, not inferred from the role name. Approval and execution are different privileges: an admin may contribute an approval, and only a superadmin may execute, roll back, or touch credentials, models or budgets — with a 2FA-verified token."
          >
            <PanelState isLoading={capabilities.isLoading} isError={capabilities.isError} onRetry={() => void capabilities.refetch()} what="your capabilities">
              {capabilities.data && (
                <div style={scrollBox}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 620 }}>
                    <caption style={{ ...label, textAlign: 'left', paddingBottom: 8 }}>
                      Signed in as {capabilities.data.role}
                    </caption>
                    <thead>
                      <tr>
                        <th style={headCell} scope="col">Action</th>
                        <th style={headCell} scope="col">Tier</th>
                        <th style={headCell} scope="col">Minimum role</th>
                        <th style={headCell} scope="col">2FA</th>
                        <th style={headCell} scope="col">You</th>
                      </tr>
                    </thead>
                    <tbody>
                      {capabilities.data.capabilities.map((row) => (
                        <tr key={row.name}>
                          <td style={{ ...cell, color: COLOR.text }}>{row.name.replace(/_/g, ' ')}</td>
                          <td style={cell}>{row.tier}</td>
                          <td style={cell}>{row.min_role}</td>
                          <td style={cell}>
                            {row.requires_2fa
                              ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: COLOR.warn }}><KeyRound size={12} aria-hidden /> required</span>
                              : '—'}
                          </td>
                          <td style={cell}>
                            {row.permitted
                              ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: COLOR.ok, fontWeight: 700 }}><CheckCircle2 size={12} aria-hidden /> permitted</span>
                              : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: COLOR.muted, fontWeight: 700 }}><Ban size={12} aria-hidden /> not permitted</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </PanelState>
          </Section>
        </>
      )}
    </div>
  );
};

export default AICore;
