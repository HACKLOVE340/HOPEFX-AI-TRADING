/**
 * GeopoliticalPanel.tsx
 *
 * Displays live geopolitical risk intelligence from /api/news/geopolitical/*.
 * Polls every 5 minutes (matching the backend cache TTL).
 *
 * Shows:
 * - Global risk score gauge
 * - Gold outlook direction badge
 * - Active conflicts / sanctions / hotspots counts
 * - Top 5 key events with severity badges
 * - Trading recommendations
 */

import React, { memo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  fetchGeopoliticalAssessment,
  fetchGeopoliticalSignal,
  queryKeys,
  type GeopoliticalAssessment,
  type GeopoliticalSignal,
} from '../services/chart-api';

// ─── Severity colour map ──────────────────────────────────────────────────────

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#ff0033',
  high:     '#ff6600',
  medium:   '#ffcc00',
  low:      '#00cc66',
  info:     '#3399ff',
};

const OUTLOOK_COLORS: Record<string, string> = {
  strongly_bullish: '#00ff88',
  bullish:          '#00cc66',
  neutral:          '#94a3b8',
  bearish:          '#ff6600',
  strongly_bearish: '#ff0033',
};

// ─── Sub-components ───────────────────────────────────────────────────────────

const RiskGauge = memo(({ score }: { score: number }) => {
  const color =
    score >= 70 ? '#ff0033' :
    score >= 50 ? '#ff6600' :
    score >= 30 ? '#ffcc00' : '#00cc66';

  return (
    <div style={s.gaugeWrap}>
      <div style={s.gaugeHeader}>
        <span style={s.gaugeLabel}>GLOBAL RISK</span>
        <span style={{ ...s.gaugeScore, color }}>{score.toFixed(0)}/100</span>
      </div>
      <div style={s.gaugeTrack}>
        <div
          style={{
            ...s.gaugeFill,
            width: `${score}%`,
            background: `linear-gradient(90deg, #00ff88 0%, ${color} 100%)`,
            boxShadow: score >= 70 ? `0 0 8px ${color}` : 'none',
          }}
        />
        {[30, 50, 70].map((pct) => (
          <div key={pct} style={{ ...s.gaugeMarker, left: `${pct}%` }} />
        ))}
      </div>
    </div>
  );
});

const OutlookBadge = memo(({ outlook }: { outlook: string }) => {
  const color = OUTLOOK_COLORS[outlook] ?? '#94a3b8';
  const label = outlook.replace(/_/g, ' ').toUpperCase();
  return (
    <div style={{ ...s.outlookBadge, borderColor: color, color }}>
      {label}
    </div>
  );
});

const SignalBadge = memo(({ signal }: { signal: GeopoliticalSignal }) => {
  const dirColor =
    signal.direction === 'BUY'  ? '#00ff88' :
    signal.direction === 'SELL' ? '#ff0033' : '#94a3b8';
  return (
    <div style={s.signalRow}>
      <span style={{ ...s.dirBadge, background: dirColor, color: '#000' }}>
        {signal.direction}
      </span>
      <span style={s.signalMeta}>
        str {(signal.strength * 100).toFixed(0)}% · conf {(signal.confidence * 100).toFixed(0)}%
      </span>
    </div>
  );
});

const CountRow = memo(({ label, value, color }: { label: string; value: number; color: string }) => (
  <div style={s.countRow}>
    <span style={s.countLabel}>{label}</span>
    <span style={{ ...s.countValue, color }}>{value}</span>
  </div>
));

const EventItem = memo(({ event }: { event: GeopoliticalAssessment['key_events'][0] }) => {
  const color = SEVERITY_COLORS[event.severity] ?? '#94a3b8';
  return (
    <div style={s.eventItem}>
      <div style={{ ...s.severityDot, background: color }} />
      <div style={s.eventContent}>
        <span style={s.eventTitle}>{event.title}</span>
        <span style={s.eventMeta}>
          {event.region} · {event.source} · risk {event.risk_score.toFixed(0)}
        </span>
      </div>
    </div>
  );
});

// ─── Main panel ───────────────────────────────────────────────────────────────

interface Props {
  className?: string;
}

const GeopoliticalPanel = memo(({ className }: Props) => {
  const { data: assessment, isLoading: loadingAssessment, error: errAssessment } =
    useQuery({
      queryKey: queryKeys.geoAssessment(),
      queryFn: fetchGeopoliticalAssessment,
      refetchInterval: 5 * 60 * 1000, // 5 min — matches backend cache TTL
      staleTime: 4 * 60 * 1000,
      retry: 2,
    });

  const { data: signal, isLoading: loadingSignal } =
    useQuery({
      queryKey: queryKeys.geoSignal(),
      queryFn: fetchGeopoliticalSignal,
      refetchInterval: 5 * 60 * 1000,
      staleTime: 4 * 60 * 1000,
      retry: 2,
    });

  if (loadingAssessment && !assessment) {
    return (
      <div style={s.panel} className={className}>
        <div style={s.loading}>Loading geopolitical intelligence…</div>
      </div>
    );
  }

  if (errAssessment && !assessment) {
    return (
      <div style={s.panel} className={className}>
        <div style={s.error}>Geopolitical data unavailable</div>
      </div>
    );
  }

  if (!assessment) return null;

  const topEvents = assessment.key_events.slice(0, 5);

  return (
    <div style={s.panel} className={className}>
      {/* Header */}
      <div style={s.header}>
        <span style={s.title}>GEOPOLITICAL RISK</span>
        <span style={s.timestamp}>
          {new Date(assessment.timestamp).toLocaleTimeString()}
        </span>
      </div>

      {/* Risk gauge */}
      <RiskGauge score={assessment.global_risk_score} />

      {/* Gold outlook + signal */}
      <div style={s.outlookRow}>
        <OutlookBadge outlook={assessment.gold_outlook} />
        {signal && !loadingSignal && <SignalBadge signal={signal} />}
      </div>

      {/* Counts */}
      <div style={s.countsGrid}>
        <CountRow label="Conflicts"  value={assessment.active_conflicts} color="#ff0033" />
        <CountRow label="Sanctions"  value={assessment.sanctions_count}  color="#ff6600" />
        <CountRow label="Hotspots"   value={assessment.hotspots}         color="#ffcc00" />
      </div>

      {/* High-risk regions */}
      {assessment.high_risk_regions.length > 0 && (
        <div style={s.regionsRow}>
          {assessment.high_risk_regions.slice(0, 4).map((r) => (
            <span key={r} style={s.regionPill}>{r}</span>
          ))}
        </div>
      )}

      {/* Key events */}
      {topEvents.length > 0 && (
        <div style={s.eventsSection}>
          <span style={s.sectionLabel}>KEY EVENTS</span>
          {topEvents.map((evt, i) => (
            <EventItem key={i} event={evt} />
          ))}
        </div>
      )}

      {/* Recommendations */}
      {assessment.trading_recommendations.length > 0 && (
        <div style={s.recsSection}>
          <span style={s.sectionLabel}>RECOMMENDATIONS</span>
          {assessment.trading_recommendations.slice(0, 3).map((rec, i) => (
            <div key={i} style={s.recItem}>› {rec}</div>
          ))}
        </div>
      )}
    </div>
  );
});

export default GeopoliticalPanel;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  panel: {
    display: 'flex', flexDirection: 'column', gap: 10,
    padding: '12px 14px',
    background: 'rgba(6,13,24,0.97)',
    border: '1px solid #1a2e4a',
    borderRadius: 8,
    color: '#e2e8f0',
    fontFamily: 'monospace',
    fontSize: 12,
    minWidth: 240,
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  },
  title: {
    fontSize: 11, fontWeight: 800, letterSpacing: 2, color: '#64748b',
  },
  timestamp: {
    fontSize: 10, color: '#334155',
  },
  loading: { color: '#475569', textAlign: 'center', padding: 16 },
  error:   { color: '#ff6600', textAlign: 'center', padding: 16 },

  // Gauge
  gaugeWrap: { display: 'flex', flexDirection: 'column', gap: 4 },
  gaugeHeader: { display: 'flex', justifyContent: 'space-between' },
  gaugeLabel: { fontSize: 10, color: '#475569', letterSpacing: 1.5, fontWeight: 700 },
  gaugeScore: { fontSize: 12, fontWeight: 700 },
  gaugeTrack: {
    position: 'relative', height: 6, background: '#1a2e4a', borderRadius: 3,
  },
  gaugeFill: {
    position: 'absolute', left: 0, top: 0, height: '100%',
    borderRadius: 3, transition: 'width 0.6s ease',
  },
  gaugeMarker: {
    position: 'absolute', top: -2, width: 1, height: 10,
    background: '#334155', transform: 'translateX(-50%)',
  },

  // Outlook + signal
  outlookRow: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  outlookBadge: {
    padding: '3px 10px', border: '1px solid', borderRadius: 4,
    fontSize: 11, fontWeight: 800, letterSpacing: 1,
  },
  signalRow: { display: 'flex', alignItems: 'center', gap: 6 },
  dirBadge: {
    padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 800,
  },
  signalMeta: { fontSize: 10, color: '#64748b' },

  // Counts
  countsGrid: { display: 'flex', gap: 12 },
  countRow: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 },
  countLabel: { fontSize: 9, color: '#475569', letterSpacing: 1.5, fontWeight: 700 },
  countValue: { fontSize: 18, fontWeight: 900 },

  // Regions
  regionsRow: { display: 'flex', flexWrap: 'wrap', gap: 4 },
  regionPill: {
    padding: '2px 8px', borderRadius: 10,
    background: 'rgba(255,255,255,0.04)', border: '1px solid #1e3a5f',
    fontSize: 10, color: '#94a3b8',
  },

  // Events
  eventsSection: { display: 'flex', flexDirection: 'column', gap: 6 },
  sectionLabel: { fontSize: 9, color: '#475569', letterSpacing: 2, fontWeight: 700 },
  eventItem: { display: 'flex', alignItems: 'flex-start', gap: 8 },
  severityDot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0, marginTop: 3 },
  eventContent: { display: 'flex', flexDirection: 'column', gap: 1 },
  eventTitle: { fontSize: 11, color: '#cbd5e1', lineHeight: 1.3 },
  eventMeta: { fontSize: 9, color: '#475569' },

  // Recommendations
  recsSection: { display: 'flex', flexDirection: 'column', gap: 4 },
  recItem: { fontSize: 10, color: '#94a3b8', lineHeight: 1.4 },
};
