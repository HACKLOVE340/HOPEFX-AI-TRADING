/**
 * components/panels/MacroCalendar.tsx
 * Macro economic calendar with gold impact scoring.
 * Shows upcoming events, impact level, gold impact score, surprise %.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { Badge } from '../ui/Badge';
import { impactColor, fmtDateTime, cn } from '../../lib/utils';
import type { MacroEvent } from '../../types';

// ── Impact score bar ──────────────────────────────────────────────────────────

function ImpactBar({ score, impact }: { score: number; impact: string }) {
  const color = impactColor(impact);
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-12 h-1 bg-[#1e2d3d] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${score * 100}%`, backgroundColor: color }}
        />
      </div>
      <span className="font-mono tabular-nums text-[10px]" style={{ color }}>
        {(score * 100).toFixed(0)}
      </span>
    </div>
  );
}

// ── Event row ─────────────────────────────────────────────────────────────────

function EventRow({ event, onPlanTrade }: { event: MacroEvent; onPlanTrade?: () => void }) {
  const now       = Date.now();
  const eventTime = new Date(event.scheduled_at).getTime();
  const isPast    = eventTime < now;
  const isImminent = !isPast && eventTime - now < 30 * 60 * 1000; // within 30 min

  const impactVariant =
    event.impact === 'high'   ? 'high' :
    event.impact === 'medium' ? 'medium' :
    event.impact === 'low'    ? 'low' : 'default';

  const hasSurprise = event.surprise_pct != null;
  const surpriseColor =
    hasSurprise && event.surprise_pct! > 0  ? '#00e676' :
    hasSurprise && event.surprise_pct! < 0  ? '#ff1744' : '#ffb800';

  return (
    <div
      className={cn(
        'flex flex-col gap-1.5 py-2.5 px-4 border-b border-[#1e2d3d] last:border-0 transition-colors',
        isPast      && 'opacity-50',
        isImminent  && 'bg-[#ffb800]/5 border-l-2 border-l-[#ffb800]',
      )}
    >
      {/* Top row: time + impact badge */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'font-mono tabular-nums text-[10px]',
              isImminent ? 'text-[#ffb800] font-semibold' : 'text-slate-500',
            )}
          >
            {fmtDateTime(event.scheduled_at)}
          </span>
          <span className="text-[9px] text-slate-700 uppercase">{event.country}</span>
        </div>
        <div className="flex items-center gap-2">
          {!isPast && event.impact === 'high' && onPlanTrade && (
            <button
              onClick={onPlanTrade}
              className="text-[9px] font-bold px-1.5 py-0.5 rounded"
              style={{ background: 'rgba(255,184,0,0.12)', border: '1px solid rgba(255,184,0,0.3)', color: '#ffb800', cursor: 'pointer' }}
            >
              ⚡ Plan
            </button>
          )}
          <Badge variant={impactVariant} dot>{event.impact}</Badge>
        </div>
      </div>

      {/* Event name */}
      <p className="text-[11px] text-slate-200 font-medium leading-snug">{event.name}</p>

      {/* Bottom row: gold impact + forecast/actual */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-slate-600 uppercase tracking-wider">Gold Impact</span>
          <ImpactBar score={event.gold_impact_score} impact={event.impact} />
        </div>

        <div className="flex items-center gap-3 text-[10px] font-mono">
          {event.forecast != null && (
            <span className="text-slate-500">
              F: <span className="text-slate-300">{event.forecast}</span>
            </span>
          )}
          {event.actual != null && (
            <span className="text-slate-500">
              A: <span className="text-slate-200 font-semibold">{event.actual}</span>
            </span>
          )}
          {hasSurprise && (
            <span style={{ color: surpriseColor }} className="font-semibold">
              {event.surprise_pct! >= 0 ? '+' : ''}{event.surprise_pct!.toFixed(1)}%
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function MacroCalendar() {
  const navigate = useNavigate();
  const macro = useStore((s) => s.macro);

  const events      = macro?.upcoming_events ?? [];
  const isBlackout  = macro?.is_blackout ?? false;
  const impactScore = macro?.impact_score ?? 0;

  const headerRight = (
    <div className="flex items-center gap-3">
      {isBlackout && (
        <span className="text-[10px] font-semibold text-[#ff3b5c] uppercase tracking-wider animate-pulse">
          ⚠ BLACKOUT
        </span>
      )}
      <div className="flex items-center gap-1.5">
        <span className="text-[9px] text-slate-600 uppercase tracking-wider">Impact</span>
        <span
          className="font-mono tabular-nums text-xs font-semibold"
          style={{ color: impactColor(impactScore > 0.6 ? 'high' : impactScore > 0.3 ? 'medium' : 'low') }}
        >
          {(impactScore * 100).toFixed(0)}
        </span>
      </div>
    </div>
  );

  return (
    <Panel title="Macro Calendar" headerRight={headerRight} noPad bodyClass="p-0">
      <div className="flex flex-col h-full overflow-y-auto scrollbar-terminal">
        {/* Blackout banner */}
        {isBlackout && (
          <div className="flex items-center gap-2 px-4 py-2 bg-[#ff3b5c]/10 border-b border-[#ff3b5c]/20">
            <span className="text-[10px] text-[#ff3b5c] font-semibold">
              Trading blackout window active — high-impact event imminent
            </span>
          </div>
        )}

        {/* Macro features strip */}
        {macro?.macro_features && Object.keys(macro.macro_features).length > 0 && (
          <div className="flex items-center gap-4 px-4 py-2 border-b border-[#1e2d3d] overflow-x-auto scrollbar-terminal">
            {Object.entries(macro.macro_features)
              .filter(([, v]) => v != null)
              .slice(0, 6)
              .map(([key, val]) => (
                <div key={key} className="flex flex-col items-center shrink-0">
                  <span className="text-[9px] text-slate-600 uppercase tracking-wider">
                    {key.replace('macro_', '').replace(/_/g, ' ')}
                  </span>
                  <span className="font-mono tabular-nums text-[11px] text-slate-300">
                    {typeof val === 'number' ? val.toFixed(3) : String(val)}
                  </span>
                </div>
              ))}
          </div>
        )}

        {/* Events list */}
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-24 text-slate-600 text-xs">
            No upcoming events in next 24h
          </div>
        ) : (
          events.map((e) => (
            <EventRow key={`${e.scheduled_at}-${e.name}`} event={e} onPlanTrade={() => navigate('/trade')} />
          ))
        )}
      </div>
    </Panel>
  );
}

// ── Guarded export (ErrorBoundary + Suspense) ─────────────────────────────────
import { withPanelGuard } from '../ui/withPanelGuard';
export const MacroCalendarGuarded = withPanelGuard(MacroCalendar, 'Macro Calendar', 4);
