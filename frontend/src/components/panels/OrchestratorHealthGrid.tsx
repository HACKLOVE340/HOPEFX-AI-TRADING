/**
 * components/panels/OrchestratorHealthGrid.tsx
 * Visual health map of all data-layer components and feeds.
 *
 * Wires to:
 *   GET /api/data-layer/health  — OrchestratorHealth (every 10s)
 *   GET /api/data-layer/feeds   — per-feed health (every 15s)
 */

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { dataLayerApi } from '../../hooks/useApi';
import { Panel } from '../ui/Panel';
import { PanelSkeleton } from '../ui/Skeleton';
import { withPanelGuard } from '../ui/withPanelGuard';
import { cn } from '../../lib/utils';
import type { OrchestratorHealth, ComponentHealth } from '../../types';

// ── Feed health types (from /api/data-layer/feeds) ────────────────────────────

interface FeedHealth {
  // API returns "gold_feed" (singular) — accept both for forward-compat
  gold_feed?:   Record<string, unknown>;
  gold_feeds?:  Record<string, unknown>;
  news_feeds?:  Record<string, unknown>;
  macro_bridge?: Record<string, unknown>;
  cache_stats?:  Record<string, unknown>;
  dqe_health?:   Record<string, unknown>;
}

/** Resolve whichever key the API sends for gold feed data. */
function goldFeeds(d: FeedHealth): Record<string, unknown> {
  return d.gold_feeds ?? d.gold_feed ?? {};
}

// ── Status helpers ────────────────────────────────────────────────────────────

type StatusLevel = 'ok' | 'degraded' | 'error' | 'offline' | 'unknown';

function statusColor(s: StatusLevel | string): string {
  switch (s) {
    case 'ok':       return '#00e676';
    case 'degraded': return '#ffb800';
    case 'error':    return '#ff1744';
    case 'offline':  return '#475569';
    default:         return '#334155';
  }
}

function statusBg(s: StatusLevel | string): string {
  switch (s) {
    case 'ok':       return 'bg-[#00e676]/10';
    case 'degraded': return 'bg-[#ffb800]/10';
    case 'error':    return 'bg-[#ff1744]/10';
    case 'offline':  return 'bg-[#475569]/10';
    default:         return 'bg-[#334155]/10';
  }
}

function overallStatus(health: OrchestratorHealth): StatusLevel {
  return (health.status as StatusLevel) ?? 'unknown';
}

// ── Component cell ────────────────────────────────────────────────────────────

function ComponentCell({
  name,
  health,
}: {
  name: string;
  health: ComponentHealth | Record<string, unknown>;
}) {
  const status = (health as ComponentHealth).status ?? 'unknown';
  const latency = (health as ComponentHealth).latency_ms;
  const error   = (health as ComponentHealth).error;
  const color   = statusColor(status);

  return (
    <div
      className={cn(
        'flex flex-col gap-1 px-2.5 py-2 rounded border transition-colors',
        statusBg(status),
        'border-[#1e2d3d]',
      )}
      title={error ?? undefined}
    >
      <div className="flex items-center gap-1.5">
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{ background: color, boxShadow: status === 'ok' ? `0 0 4px ${color}` : 'none' }}
        />
        <span className="text-[10px] font-semibold text-slate-300 truncate capitalize">
          {name.replace(/_/g, ' ')}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span
          className="text-[9px] font-bold uppercase tracking-wider"
          style={{ color }}
        >
          {status}
        </span>
        {latency != null && (
          <span className="text-[9px] text-slate-600 tabular-nums">{latency.toFixed(0)}ms</span>
        )}
      </div>
      {error && (
        <span className="text-[9px] text-[#ff1744] truncate" title={error}>
          {error.slice(0, 40)}
        </span>
      )}
    </div>
  );
}

// ── Feed row ──────────────────────────────────────────────────────────────────

function FeedRow({ name, data }: { name: string; data: unknown }) {
  const obj = (data ?? {}) as Record<string, unknown>;
  const status = (obj.status as string) ?? (obj.healthy ? 'ok' : 'unknown');
  const color  = statusColor(status);

  return (
    <div className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-[#0d1421] border border-[#1e2d3d]">
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{ background: color }}
      />
      <span className="text-[10px] text-slate-300 flex-1 truncate capitalize">
        {name.replace(/_/g, ' ')}
      </span>
      <span className="text-[9px] font-semibold uppercase" style={{ color }}>
        {status}
      </span>
    </div>
  );
}

// ── Overall status badge ──────────────────────────────────────────────────────

function OverallBadge({ health }: { health: OrchestratorHealth }) {
  const s     = overallStatus(health);
  const color = statusColor(s);
  const uptime = health.uptime_seconds
    ? (() => {
        const h = Math.floor(health.uptime_seconds / 3600);
        const m = Math.floor((health.uptime_seconds % 3600) / 60);
        return h > 0 ? `${h}h ${m}m` : `${m}m`;
      })()
    : null;

  return (
    <div className="flex items-center gap-2">
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase"
        style={{ color, background: `${color}18` }}
      >
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
        {s}
      </span>
      {uptime && (
        <span className="text-[10px] text-slate-500">up {uptime}</span>
      )}
      {health.quality_score != null && (
        <span className={cn(
          'text-[10px] font-semibold',
          health.quality_score >= 0.8 ? 'text-[#00e676]' :
          health.quality_score >= 0.5 ? 'text-[#ffb800]' : 'text-[#ff1744]',
        )}>
          Q: {(health.quality_score * 100).toFixed(0)}%
        </span>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type Tab = 'components' | 'feeds';

function OrchestratorHealthGridInner() {
  const [tab, setTab] = useState<Tab>('components');

  const healthQ = useQuery<OrchestratorHealth>({
    queryKey: ['orchestrator', 'health'],
    queryFn:  async () => { const r = await dataLayerApi.health(); return r.data; },
    refetchInterval: 10_000,
    staleTime:       5_000,
  });

  const feedsQ = useQuery<FeedHealth>({
    queryKey: ['orchestrator', 'feeds'],
    queryFn:  async () => { const r = await dataLayerApi.feeds(); return r.data; },
    refetchInterval: 15_000,
    staleTime:       7_500,
    enabled: tab === 'feeds',
  });

  const health = healthQ.data;

  const headerRight = health ? <OverallBadge health={health} /> : undefined;

  return (
    <Panel title="Orchestrator Health" headerRight={headerRight}>
      <div className="flex flex-col gap-3">

        {/* Tab bar */}
        <div className="flex gap-1">
          {(['components', 'feeds'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                'px-3 py-1 rounded text-[11px] font-semibold border transition-colors capitalize',
                tab === t
                  ? 'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa]'
                  : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
              )}
            >
              {t}
            </button>
          ))}
        </div>

        {/* ── Components tab ───────────────────────────────────────────────── */}
        {tab === 'components' && (
          <>
            {healthQ.isLoading && <PanelSkeleton rows={6} />}
            {healthQ.isError && (
              <div className="text-[11px] text-[#ff1744]">Failed to load health data</div>
            )}
            {health && (
              <>
                {Object.keys(health.components ?? {}).length === 0 ? (
                  <div className="text-[11px] text-slate-500 text-center py-4">
                    No component data available
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-1.5">
                    {Object.entries(health.components).map(([name, comp]) => (
                      <ComponentCell key={name} name={name} health={comp} />
                    ))}
                  </div>
                )}

                {/* Latest tick strip */}
                {health.latest_tick && (
                  <div className="flex gap-3 px-2.5 py-2 rounded bg-[#0d1421] border border-[#1e2d3d] text-[10px]">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-slate-500">Symbol</span>
                      <span className="text-slate-200 font-semibold">{health.latest_tick.symbol}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-slate-500">Mid</span>
                      <span className="text-slate-200 tabular-nums">{health.latest_tick.mid?.toFixed(2)}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-slate-500">Source</span>
                      <span className="text-[#60a5fa]">{health.latest_tick.source}</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-slate-500">Quality</span>
                      <span className="text-[#00e676]">{health.latest_tick.quality}</span>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* ── Feeds tab ────────────────────────────────────────────────────── */}
        {tab === 'feeds' && (
          <>
            {feedsQ.isLoading && <PanelSkeleton rows={5} />}
            {feedsQ.isError && (
              <div className="text-[11px] text-[#ff1744]">Failed to load feed health</div>
            )}
            {feedsQ.data && (
              <div className="flex flex-col gap-3">
                {/* Gold feeds */}
                {Object.keys(goldFeeds(feedsQ.data)).length > 0 && (
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
                      Gold Feeds
                    </div>
                    <div className="flex flex-col gap-1">
                      {Object.entries(goldFeeds(feedsQ.data)).map(([name, data]) => (
                        <FeedRow key={name} name={name} data={data} />
                      ))}
                    </div>
                  </div>
                )}

                {/* News feeds */}
                {Object.keys(feedsQ.data.news_feeds ?? {}).length > 0 && (
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
                      News Feeds
                    </div>
                    <div className="flex flex-col gap-1">
                      {Object.entries(feedsQ.data.news_feeds ?? {}).map(([name, data]) => (
                        <FeedRow key={name} name={name} data={data} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Cache stats */}
                {Object.keys(feedsQ.data.cache_stats ?? {}).length > 0 && (
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
                      Cache
                    </div>
                    <div className="grid grid-cols-2 gap-1.5">
                      {Object.entries(feedsQ.data.cache_stats ?? {}).map(([k, v]) => (
                        <div key={k} className="flex justify-between px-2 py-1 rounded bg-[#0d1421] border border-[#1e2d3d]">
                          <span className="text-[10px] text-slate-500 capitalize">{k.replace(/_/g, ' ')}</span>
                          <span className="text-[10px] text-slate-300 tabular-nums font-mono">
                            {typeof v === 'number' ? v.toLocaleString() : String(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}

// ── Exports ───────────────────────────────────────────────────────────────────

export { OrchestratorHealthGridInner as OrchestratorHealthGrid };
export const OrchestratorHealthGridGuarded = withPanelGuard(OrchestratorHealthGridInner, 'Orchestrator Health', 6);
export default OrchestratorHealthGridInner;
