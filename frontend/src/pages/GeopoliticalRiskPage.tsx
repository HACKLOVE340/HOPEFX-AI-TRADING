/**
 * pages/GeopoliticalRiskPage.tsx
 *
 * Geopolitical risk intelligence dashboard.
 *
 * Layout:
 *   - Left column : GeopoliticalPanel (risk score, signal, events, recommendations)
 *   - Right column: World Monitor map section (curated deep-link views from
 *                   /api/news/geopolitical/world-monitor + embedded iframe)
 *
 * World Monitor (https://worldmonitor.app / github.com/koala73/worldmonitor) is a
 * URL-based open-source map dashboard — no API key required. The backend builds
 * deep-link URLs via WorldMonitorIntegration.get_gold_relevant_views().
 */

import React, { memo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { GeopoliticalPanel } from '../features/chart-bot';
import {
  fetchWorldMonitorViews,
  queryKeys,
  type WorldMonitorViews,
} from '../features/chart-bot/services/chart-api';

// ─── Region label map ─────────────────────────────────────────────────────────

const REGION_LABELS: Record<string, string> = {
  middle_east:     'Middle East',
  eastern_europe:  'Eastern Europe',
  asia_pacific:    'Asia Pacific',
  global_overview: 'Global Overview',
};

const REGION_ICONS: Record<string, string> = {
  middle_east:     '🛢',
  eastern_europe:  '⚔',
  asia_pacific:    '🌏',
  global_overview: '🌍',
};

// ─── World Monitor section ────────────────────────────────────────────────────

interface WorldMonitorSectionProps {
  data: WorldMonitorViews;
}

const WorldMonitorSection = memo(({ data }: WorldMonitorSectionProps) => {
  const regions = Object.keys(data.gold_relevant_views);
  const [activeRegion, setActiveRegion] = useState<string>(regions[0] ?? 'global_overview');

  const activeUrl = data.gold_relevant_views[activeRegion];

  return (
    <div style={s.wmCard}>
      {/* Header */}
      <div style={s.wmHeader}>
        <div style={s.wmTitleRow}>
          <span style={s.wmTitle}>WORLD MONITOR</span>
          <a
            href={data.base_url}
            target="_blank"
            rel="noopener noreferrer"
            style={s.wmExternalLink}
            title="Open worldmonitor.app"
          >
            ↗ worldmonitor.app
          </a>
        </div>
        <p style={s.wmSubtitle}>
          Live geopolitical intelligence map — regions relevant to XAU/USD
        </p>
      </div>

      {/* Region tabs */}
      <div style={s.wmTabs}>
        {regions.map((region) => (
          <button
            key={region}
            style={{
              ...s.wmTab,
              ...(activeRegion === region ? s.wmTabActive : {}),
            }}
            onClick={() => setActiveRegion(region)}
          >
            <span style={s.wmTabIcon}>{REGION_ICONS[region] ?? '🗺'}</span>
            {REGION_LABELS[region] ?? region.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      {/* Embedded iframe */}
      <div style={s.wmIframeWrap}>
        <iframe
          key={activeUrl}
          src={activeUrl}
          style={s.wmIframe}
          title={`World Monitor — ${REGION_LABELS[activeRegion] ?? activeRegion}`}
          sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      </div>

      {/* Deep-link buttons */}
      <div style={s.wmLinks}>
        <span style={s.wmLinksLabel}>OPEN IN NEW TAB</span>
        <div style={s.wmLinkRow}>
          {regions.map((region) => (
            <a
              key={region}
              href={data.gold_relevant_views[region]}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                ...s.wmLinkBtn,
                ...(activeRegion === region ? s.wmLinkBtnActive : {}),
              }}
              onClick={() => setActiveRegion(region)}
            >
              {REGION_ICONS[region] ?? '🗺'} {REGION_LABELS[region] ?? region.replace(/_/g, ' ')}
            </a>
          ))}
        </div>
      </div>

      {/* Active layer legend */}
      <div style={s.wmLegend}>
        {['conflicts', 'hotspots', 'sanctions', 'military', 'weather', 'outages'].map((layer) => (
          <span key={layer} style={s.wmLegendPill}>{layer}</span>
        ))}
      </div>
    </div>
  );
});

// ─── Loading / error fallback ─────────────────────────────────────────────────

const WorldMonitorFallback = memo(({ error }: { error?: boolean }) => (
  <div style={{ ...s.wmCard, ...s.wmFallback }}>
    <span style={s.wmTitle}>WORLD MONITOR</span>
    {error ? (
      <p style={s.wmFallbackText}>
        Map unavailable — backend could not reach worldmonitor.app.
        <br />
        <a
          href="https://worldmonitor.app"
          target="_blank"
          rel="noopener noreferrer"
          style={s.wmExternalLink}
        >
          Open worldmonitor.app directly ↗
        </a>
      </p>
    ) : (
      <p style={s.wmFallbackText}>Loading map views…</p>
    )}
  </div>
));

// ─── Page ─────────────────────────────────────────────────────────────────────

const GeopoliticalRiskPage: React.FC = () => {
  const {
    data: wmData,
    isLoading: wmLoading,
    isError: wmError,
  } = useQuery({
    queryKey: queryKeys.geoWorldMonitor(),
    queryFn: fetchWorldMonitorViews,
    staleTime: 60 * 60 * 1000,  // URLs are stable — refresh hourly
    retry: 1,
  });

  return (
    <div style={s.page}>
      <div style={s.pageHeader}>
        <h1 style={s.pageTitle}>Geopolitical Risk Intelligence</h1>
        <p style={s.pageSubtitle}>
          Live conflict, sanctions, and instability data — XAU/USD safe-haven impact
        </p>
      </div>

      <div style={s.grid}>
        {/* Left: risk panel */}
        <div style={s.leftCol}>
          <GeopoliticalPanel />
        </div>

        {/* Right: World Monitor map */}
        <div style={s.rightCol}>
          {wmLoading && !wmData ? (
            <WorldMonitorFallback />
          ) : wmError || !wmData ? (
            <WorldMonitorFallback error />
          ) : (
            <WorldMonitorSection data={wmData} />
          )}
        </div>
      </div>
    </div>
  );
};

export default GeopoliticalRiskPage;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  // Page shell
  page: {
    padding: '24px 28px',
    maxWidth: 1400,
    margin: '0 auto',
    fontFamily: 'monospace',
    color: '#e2e8f0',
  },
  pageHeader: {
    marginBottom: 24,
  },
  pageTitle: {
    margin: 0,
    fontSize: 22,
    fontWeight: 800,
    color: '#e2e8f0',
    letterSpacing: 0.5,
  },
  pageSubtitle: {
    margin: '6px 0 0',
    fontSize: 12,
    color: '#475569',
  },

  // Two-column grid
  grid: {
    display: 'grid',
    gridTemplateColumns: 'minmax(280px, 340px) 1fr',
    gap: 20,
    alignItems: 'start',
  },
  leftCol: {
    position: 'sticky' as const,
    top: 20,
  },
  rightCol: {
    minWidth: 0,
  },

  // World Monitor card
  wmCard: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    padding: '14px 16px',
    background: 'rgba(6,13,24,0.97)',
    border: '1px solid #1a2e4a',
    borderRadius: 8,
  },
  wmFallback: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 200,
    textAlign: 'center' as const,
  },
  wmFallbackText: {
    margin: 0,
    fontSize: 12,
    color: '#475569',
    lineHeight: 1.6,
  },

  // Header
  wmHeader: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  wmTitleRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  wmTitle: {
    fontSize: 11,
    fontWeight: 800,
    letterSpacing: 2,
    color: '#64748b',
  },
  wmSubtitle: {
    margin: 0,
    fontSize: 11,
    color: '#334155',
  },
  wmExternalLink: {
    fontSize: 11,
    color: '#3b82f6',
    textDecoration: 'none',
  },

  // Region tabs
  wmTabs: {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap' as const,
  },
  wmTab: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    padding: '5px 12px',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid #1e3a5f',
    borderRadius: 6,
    color: '#64748b',
    fontSize: 11,
    fontFamily: 'monospace',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  wmTabActive: {
    background: 'rgba(59,130,246,0.12)',
    border: '1px solid #3b82f6',
    color: '#93c5fd',
  },
  wmTabIcon: {
    fontSize: 13,
  },

  // Iframe
  wmIframeWrap: {
    position: 'relative' as const,
    width: '100%',
    paddingBottom: '56.25%',  // 16:9
    background: '#060d18',
    borderRadius: 6,
    overflow: 'hidden',
    border: '1px solid #1a2e4a',
  },
  wmIframe: {
    position: 'absolute' as const,
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    border: 'none',
    borderRadius: 6,
  },

  // Deep-link buttons
  wmLinks: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  wmLinksLabel: {
    fontSize: 9,
    color: '#334155',
    letterSpacing: 2,
    fontWeight: 700,
  },
  wmLinkRow: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 6,
  },
  wmLinkBtn: {
    padding: '4px 12px',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid #1e3a5f',
    borderRadius: 5,
    color: '#64748b',
    fontSize: 11,
    fontFamily: 'monospace',
    textDecoration: 'none',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  wmLinkBtnActive: {
    border: '1px solid #3b82f6',
    color: '#93c5fd',
  },

  // Layer legend
  wmLegend: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 4,
  },
  wmLegendPill: {
    padding: '2px 8px',
    borderRadius: 10,
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid #1e3a5f',
    fontSize: 9,
    color: '#334155',
    letterSpacing: 1,
  },
};
