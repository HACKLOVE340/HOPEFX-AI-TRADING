/**
 * pages/GeopoliticalRiskPage.tsx
 *
 * Geopolitical risk intelligence dashboard.
 *
 * Layout:
 *   - Left column : GeopoliticalPanel (risk score, signal, events, recommendations)
 *   - Right column: World Monitor map section — crisis hotspots, all regions,
 *                   live layer selector, embedded iframe deep-links
 */

import React, { memo, useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader, CrossLinkBar } from '../components';
import { useQuery } from '@tanstack/react-query';
import { GeopoliticalPanel } from '../features/chart-bot';
import {
  fetchWorldMonitorViews,
  queryKeys,
  type WorldMonitorViews,
} from '../features/chart-bot/services/chart-api';

// ─── Constants ────────────────────────────────────────────────────────────────

const CRISIS_ICONS: Record<string, string> = {
  ukraine_russia:   '⚔',
  israel_gaza:      '🔥',
  red_sea_houthi:   '🚢',
  taiwan_strait:    '🌏',
  sudan_africa:     '🌍',
  korea_peninsula:  '☢',
};

const REGION_ICONS: Record<string, string> = {
  global:                    '🌐',
  americas:                  '🌎',
  europe:                    '🏛',
  middle_east_north_africa:  '🛢',
  asia_pacific:              '🌏',
  africa:                    '🌍',
  oceania:                   '🪸',
};

const LAYER_ICONS: Record<string, string> = {
  conflicts:    '⚔',
  hotspots:     '🔴',
  sanctions:    '🚫',
  weather:      '🌩',
  outages:      '⚡',
  natural:      '🌋',
  military:     '🪖',
  protests:     '✊',
  nuclear:      '☢',
  pipelines:    '🛢',
  cables:       '🔌',
  datacenters:  '🖥',
};

const LAYER_COLORS: Record<string, string> = {
  conflicts:    '#ff0033',
  hotspots:     '#ff4444',
  sanctions:    '#ff6600',
  weather:      '#3b82f6',
  outages:      '#f59e0b',
  natural:      '#ef4444',
  military:     '#8b5cf6',
  protests:     '#f97316',
  nuclear:      '#22d3ee',
  pipelines:    '#84cc16',
  cables:       '#06b6d4',
  datacenters:  '#6366f1',
};

type TabGroup = 'crisis' | 'regions' | 'gold';

// ─── Layer selector ───────────────────────────────────────────────────────────

interface LayerSelectorProps {
  allLayers: string[];
  active: Set<string>;
  onChange: (layer: string) => void;
}

const LayerSelector = memo(({ allLayers, active, onChange }: LayerSelectorProps) => (
  <div style={s.layerGrid}>
    {allLayers.map((layer) => {
      const on = active.has(layer);
      const color = LAYER_COLORS[layer] ?? '#64748b';
      return (
        <button
          key={layer}
          style={{
            ...s.layerBtn,
            borderColor: on ? color : '#1e3a5f',
            background: on ? `${color}18` : 'rgba(255,255,255,0.02)',
            color: on ? color : '#475569',
          }}
          onClick={() => onChange(layer)}
          title={`Toggle ${layer} layer`}
        >
          <span>{LAYER_ICONS[layer] ?? '●'}</span>
          {layer}
        </button>
      );
    })}
  </div>
));

// ─── World Monitor section ────────────────────────────────────────────────────

interface WorldMonitorSectionProps {
  data: WorldMonitorViews;
}

const WorldMonitorSection = memo(({ data }: WorldMonitorSectionProps) => {
  const [tabGroup, setTabGroup] = useState<TabGroup>('crisis');
  const [activeCrisis, setActiveCrisis] = useState<string>(
    Object.keys(data.crisis_views)[0] ?? 'ukraine_russia',
  );
  const [activeRegion, setActiveRegion] = useState<string>('global');
  const [activeGold, setActiveGold] = useState<string>(
    Object.keys(data.gold_relevant_views)[0] ?? 'global_overview',
  );
  const [activeLayers, setActiveLayers] = useState<Set<string>>(
    () => new Set(data.available_layers ?? []),
  );

  const toggleLayer = (layer: string) => {
    setActiveLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layer)) { next.delete(layer); } else { next.add(layer); }
      return next;
    });
  };

  // Build iframe URL by injecting active layers into the selected base URL
  const baseUrl = useMemo(() => {
    if (tabGroup === 'crisis') return data.crisis_views[activeCrisis] ?? data.full_global_url;
    if (tabGroup === 'regions') return data.all_region_views[activeRegion] ?? data.full_global_url;
    return data.gold_relevant_views[activeGold] ?? data.full_global_url;
  }, [tabGroup, activeCrisis, activeRegion, activeGold, data]);

  const iframeUrl = useMemo(() => {
    if (!baseUrl || activeLayers.size === 0) return baseUrl;
    const layerStr = [...activeLayers].join(',');
    return baseUrl.replace(/layers=[^&]*/i, `layers=${layerStr}`);
  }, [baseUrl, activeLayers]);

  const crisisKeys = Object.keys(data.crisis_views);
  const regionKeys = Object.keys(data.all_region_views);
  const goldKeys = Object.keys(data.gold_relevant_views);

  const GOLD_LABELS: Record<string, string> = {
    middle_east:     'Middle East',
    eastern_europe:  'Eastern Europe',
    asia_pacific:    'Asia Pacific',
    global_overview: 'Global Overview',
  };

  return (
    <div style={s.wmCard}>
      {/* ── Header ── */}
      <div style={s.wmHeader}>
        <div style={s.wmTitleRow}>
          <span style={s.wmTitle}>WORLD MONITOR  <span style={s.liveDot}>● LIVE</span></span>
          <a href={data.base_url} target="_blank" rel="noopener noreferrer" style={s.wmExtLink}>
            ↗ worldmonitor.app
          </a>
        </div>
        <p style={s.wmSubtitle}>
          Real-time geopolitical intelligence · conflicts · sanctions · military · nuclear · infrastructure
        </p>
      </div>

      {/* ── Group selector ── */}
      <div style={s.groupRow}>
        {(['crisis', 'regions', 'gold'] as TabGroup[]).map((g) => (
          <button
            key={g}
            style={{ ...s.groupBtn, ...(tabGroup === g ? s.groupBtnActive : {}) }}
            onClick={() => setTabGroup(g)}
          >
            {g === 'crisis' ? '🔥 Crisis Zones' : g === 'regions' ? '🌐 All Regions' : '🥇 Gold Intel'}
          </button>
        ))}
      </div>

      {/* ── Tabs for active group ── */}
      <div style={s.tabRow}>
        {tabGroup === 'crisis' && crisisKeys.map((key) => (
          <button
            key={key}
            style={{ ...s.tab, ...(activeCrisis === key ? s.tabActive : {}) }}
            onClick={() => setActiveCrisis(key)}
          >
            {CRISIS_ICONS[key] ?? '⚑'} {data.crisis_labels[key] ?? key.replace(/_/g, ' ')}
          </button>
        ))}
        {tabGroup === 'regions' && regionKeys.map((key) => (
          <button
            key={key}
            style={{ ...s.tab, ...(activeRegion === key ? s.tabActive : {}) }}
            onClick={() => setActiveRegion(key)}
          >
            {REGION_ICONS[key] ?? '🗺'} {data.region_labels[key] ?? key.replace(/_/g, ' ')}
          </button>
        ))}
        {tabGroup === 'gold' && goldKeys.map((key) => (
          <button
            key={key}
            style={{ ...s.tab, ...(activeGold === key ? s.tabActive : {}) }}
            onClick={() => setActiveGold(key)}
          >
            {REGION_ICONS[key] ?? '🗺'} {GOLD_LABELS[key] ?? key.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      {/* ── Embedded iframe ── */}
      <div style={s.iframeWrap}>
        <iframe
          key={iframeUrl}
          src={iframeUrl}
          style={s.iframe}
          title="World Monitor — Live Geopolitical Intelligence"
          sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      </div>

      {/* ── Layer selector ── */}
      <div style={s.layerSection}>
        <div style={s.layerHeader}>
          <span style={s.sectionLabel}>ACTIVE LAYERS</span>
          <div style={s.layerActions}>
            <button style={s.layerActionBtn} onClick={() => setActiveLayers(new Set(data.available_layers ?? []))}>
              ALL
            </button>
            <button style={s.layerActionBtn} onClick={() => setActiveLayers(new Set(['conflicts', 'hotspots', 'military', 'sanctions']))}>
              TACTICAL
            </button>
            <button style={s.layerActionBtn} onClick={() => setActiveLayers(new Set(['nuclear', 'military', 'conflicts']))}>
              NUCLEAR
            </button>
            <button style={s.layerActionBtn} onClick={() => setActiveLayers(new Set())}>
              CLEAR
            </button>
          </div>
        </div>
        {data.available_layers && (
          <LayerSelector allLayers={data.available_layers} active={activeLayers} onChange={toggleLayer} />
        )}
      </div>

      {/* ── Open in new tab ── */}
      <div style={s.openRow}>
        <span style={s.sectionLabel}>OPEN IN NEW TAB →</span>
        <a href={iframeUrl} target="_blank" rel="noopener noreferrer" style={s.openBtn}>
          Current View ↗
        </a>
        <a href={data.full_global_url} target="_blank" rel="noopener noreferrer" style={s.openBtn}>
          Full Global ↗
        </a>
        <a href={data.base_url} target="_blank" rel="noopener noreferrer" style={s.openBtn}>
          WorldMonitor ↗
        </a>
      </div>
    </div>
  );
});

// ─── Loading / error fallback ─────────────────────────────────────────────────

const WorldMonitorFallback = memo(({ error }: { error?: boolean }) => (
  <div style={{ ...s.wmCard, ...s.fallback }}>
    <span style={s.wmTitle}>WORLD MONITOR</span>
    {error ? (
      <p style={s.fallbackText}>
        Map unavailable — backend could not reach worldmonitor.app.
        <br />
        <a href="https://worldmonitor.app" target="_blank" rel="noopener noreferrer" style={s.wmExtLink}>
          Open worldmonitor.app directly ↗
        </a>
      </p>
    ) : (
      <p style={s.fallbackText}>Loading WorldMonitor intelligence…</p>
    )}
  </div>
));

// ─── Page ─────────────────────────────────────────────────────────────────────

const GeopoliticalRiskPage: React.FC = () => {
  const { data: wmData, isLoading: wmLoading, isError: wmError } = useQuery({
    queryKey: queryKeys.geoWorldMonitor(),
    queryFn: fetchWorldMonitorViews,
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });

  return (
    <div style={s.page}>
      <PageHeader
        title="Geopolitical Risk Intelligence"
        icon="🌍"
        subtitle="Live conflict, sanctions, nuclear, infrastructure and instability data — XAU/USD safe-haven impact"
        breadcrumbs={[
          { label: 'Dashboard',    href: '/dashboard' },
          { label: 'Analytics',    href: '/performance' },
          { label: 'Geopolitical Risk' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <Link to="/research"
              style={{ background: 'rgba(139,92,246,0.1)', border: '1px solid rgba(139,92,246,0.3)', borderRadius: 8, color: '#a78bfa', fontSize: 12, fontWeight: 600, padding: '7px 14px', textDecoration: 'none' }}>
              🔬 Research
            </Link>
            <Link to="/correlation"
              style={{ background: 'rgba(96,165,250,0.1)', border: '1px solid rgba(96,165,250,0.3)', borderRadius: 8, color: '#60a5fa', fontSize: 12, fontWeight: 600, padding: '7px 14px', textDecoration: 'none' }}>
              📊 Correlation
            </Link>
            <Link to="/nuclear"
              style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, color: '#f87171', fontSize: 12, fontWeight: 600, padding: '7px 14px', textDecoration: 'none' }}>
              ☢ Nuclear AI
            </Link>
            <Link
              to="/trade"
              state={{ signal: { symbol: 'XAU/USD', direction: 'BUY' } }}
              style={{ background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)', borderRadius: 8, color: '#4ade80', fontSize: 12, fontWeight: 600, padding: '7px 14px', textDecoration: 'none' }}
              title="Gold tends to rally during geopolitical risk — buy XAU/USD"
            >
              ⚡ Trade XAU/USD
            </Link>
          </div>
        }
      />

      <div style={s.grid}>
        <div style={s.leftCol}>
          <GeopoliticalPanel />
        </div>
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

      <CrossLinkBar title="Related" style={{ marginTop: 8 }} links={[
        { label: 'Research',          href: '/research',    icon: '🔬', color: '#a78bfa' },
        { label: 'Correlation',       href: '/correlation', icon: '🔗', color: '#60a5fa' },
        { label: 'Economic Calendar', href: '/calendar',    icon: '📅', color: '#f97316' },
        { label: 'Nuclear AI',        href: '/nuclear',     icon: '☢️', color: '#ef4444' },
        { label: 'Signal Feed',       href: '/signals',     icon: '📡', color: '#4ade80' },
        { label: 'Trade XAU/USD',     href: '/trade',       icon: '⚡', color: '#fbbf24' },
      ]} />
    </div>
  );
};

export default GeopoliticalRiskPage;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    padding: '24px 28px',
    maxWidth: 1500,
    margin: '0 auto',
    fontFamily: 'monospace',
    color: '#e2e8f0',
  },
  pageHeader: { marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 },
  pageTitle: {
    margin: 0,
    fontSize: 22,
    fontWeight: 800,
    color: '#e2e8f0',
    letterSpacing: 0.5,
  },
  pageSubtitle: { margin: '6px 0 0', fontSize: 12, color: '#475569' },

  grid: {
    display: 'grid',
    gridTemplateColumns: 'minmax(260px, 320px) 1fr',
    gap: 20,
    alignItems: 'start',
  },
  leftCol: { position: 'sticky' as const, top: 20 },
  rightCol: { minWidth: 0 },

  wmCard: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    padding: '14px 16px',
    background: 'rgba(6,13,24,0.97)',
    border: '1px solid #1a2e4a',
    borderRadius: 8,
  },
  fallback: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 200,
    textAlign: 'center' as const,
  },
  fallbackText: { margin: 0, fontSize: 12, color: '#475569', lineHeight: 1.6 },

  wmHeader: { display: 'flex', flexDirection: 'column', gap: 4 },
  wmTitleRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  wmTitle: { fontSize: 11, fontWeight: 800, letterSpacing: 2, color: '#64748b' },
  liveDot: { color: '#00ff88', fontSize: 9, letterSpacing: 1, animation: 'pulse 2s infinite' },
  wmSubtitle: { margin: 0, fontSize: 11, color: '#334155' },
  wmExtLink: { fontSize: 11, color: '#3b82f6', textDecoration: 'none' },

  groupRow: { display: 'flex', gap: 6 },
  groupBtn: {
    padding: '5px 14px',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid #1e3a5f',
    borderRadius: 6,
    color: '#64748b',
    fontSize: 11,
    fontFamily: 'monospace',
    cursor: 'pointer',
  },
  groupBtnActive: {
    background: 'rgba(59,130,246,0.15)',
    border: '1px solid #3b82f6',
    color: '#93c5fd',
  },

  tabRow: { display: 'flex', flexWrap: 'wrap' as const, gap: 5 },
  tab: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    padding: '4px 10px',
    background: 'rgba(255,255,255,0.02)',
    border: '1px solid #1e3a5f',
    borderRadius: 5,
    color: '#64748b',
    fontSize: 10,
    fontFamily: 'monospace',
    cursor: 'pointer',
    whiteSpace: 'nowrap' as const,
  },
  tabActive: {
    background: 'rgba(239,68,68,0.12)',
    border: '1px solid #ef4444',
    color: '#fca5a5',
  },

  iframeWrap: {
    position: 'relative' as const,
    width: '100%',
    paddingBottom: '60%',
    background: '#060d18',
    borderRadius: 6,
    overflow: 'hidden',
    border: '1px solid #1a2e4a',
  },
  iframe: {
    position: 'absolute' as const,
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    border: 'none',
    borderRadius: 6,
  },

  layerSection: { display: 'flex', flexDirection: 'column', gap: 8 },
  layerHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  sectionLabel: {
    fontSize: 9,
    color: '#334155',
    letterSpacing: 2,
    fontWeight: 700,
  },
  layerActions: { display: 'flex', gap: 4 },
  layerActionBtn: {
    padding: '2px 8px',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid #1e3a5f',
    borderRadius: 4,
    color: '#475569',
    fontSize: 9,
    fontFamily: 'monospace',
    cursor: 'pointer',
    letterSpacing: 1,
  },
  layerGrid: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 5,
  },
  layerBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '3px 9px',
    border: '1px solid',
    borderRadius: 4,
    fontSize: 10,
    fontFamily: 'monospace',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    letterSpacing: 0.3,
  },

  openRow: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap' as const,
    gap: 6,
  },
  openBtn: {
    padding: '3px 10px',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid #1e3a5f',
    borderRadius: 4,
    color: '#3b82f6',
    fontSize: 10,
    fontFamily: 'monospace',
    textDecoration: 'none',
    cursor: 'pointer',
  },
};
