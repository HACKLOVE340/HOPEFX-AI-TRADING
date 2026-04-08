/**
 * GlobalAttackMap — world map showing live attack origins.
 *
 * Uses react-leaflet + OpenStreetMap tiles (no API key required).
 * Each pin is coloured by intent severity:
 *   probe       → yellow
 *   bruteforce  → orange
 *   exfil       → red
 *   ddos        → crimson
 *   unknown     → grey
 *
 * Props
 * -----
 * attacks  Record<ip, AttackRecord> — polled from /api/security/attacks
 * loading  boolean — show skeleton overlay while first fetch is in flight
 */

import React, { useEffect, useRef } from 'react';
import type { Map as LeafletMap, Marker as LeafletMarker, Icon as LeafletIconType } from 'leaflet';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AttackGeo {
  country?: string;
  city?: string;
  lat?: number;
  lon?: number;
  isp?: string;
}

export interface AttackRecord {
  geo: AttackGeo;
  intent: 'probe' | 'exfil' | 'ddos' | 'bruteforce' | 'unknown';
  severity: number;
  time: string;
  raw?: string;
}

export type AttackLog = Record<string, AttackRecord>;

interface GlobalAttackMapProps {
  attacks: AttackLog;
  loading?: boolean;
  height?: number | string;
}

// ── Severity colour map ───────────────────────────────────────────────────────

const INTENT_COLOUR: Record<string, string> = {
  probe: '#facc15',       // yellow
  bruteforce: '#f97316',  // orange
  unknown: '#94a3b8',     // slate
  exfil: '#ef4444',       // red
  ddos: '#dc2626',        // crimson
};

function intentColour(intent: string): string {
  return INTENT_COLOUR[intent] ?? INTENT_COLOUR.unknown;
}

// ── Leaflet dynamic import (avoids SSR issues) ────────────────────────────────

let leafletLoaded = false;

async function ensureLeaflet(): Promise<typeof import('leaflet')> {
  const L = await import('leaflet');
  if (!leafletLoaded) {
    // Fix default marker icon paths broken by bundlers (_getIconUrl is an internal field)
    delete (L.Icon.Default.prototype as LeafletIconType & { _getIconUrl?: unknown })._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
      iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
      shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
    });
    leafletLoaded = true;
  }
  return L;
}

// ── Component ─────────────────────────────────────────────────────────────────

export const GlobalAttackMap: React.FC<GlobalAttackMapProps> = ({
  attacks,
  loading = false,
  height = 420,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const markersRef = useRef<Map<string, LeafletMarker>>(new Map());

  // Initialise map once
  useEffect(() => {
    let cancelled = false;

    (async () => {
      if (!mapContainerRef.current || mapRef.current) return;
      const L = await ensureLeaflet();
      if (cancelled || !mapContainerRef.current) return;

      const map = L.map(mapContainerRef.current, {
        center: [20, 0],
        zoom: 2,
        zoomControl: true,
        attributionControl: true,
      });

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 18,
      }).addTo(map);

      mapRef.current = map;
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // Sync attack markers whenever the attacks prop changes
  useEffect(() => {
    if (!mapRef.current) return;

    (async () => {
      const L = await ensureLeaflet();
      const map = mapRef.current;
      if (!map) return;

      const currentIPs = new Set(Object.keys(attacks));

      // Remove stale markers
      markersRef.current.forEach((marker, ip) => {
        if (!currentIPs.has(ip)) {
          map.removeLayer(marker);
          markersRef.current.delete(ip);
        }
      });

      // Add / update markers
      for (const [ip, record] of Object.entries(attacks)) {
        const lat = record.geo?.lat ?? 0;
        const lon = record.geo?.lon ?? 0;
        if (lat === 0 && lon === 0) continue;

        const colour = intentColour(record.intent);
        const existing = markersRef.current.get(ip);

        if (existing) {
          // Update popup content only — don't re-create the marker
          existing.setPopupContent(buildPopupHTML(ip, record));
          continue;
        }

        const icon = L.divIcon({
          className: '',
          html: `<div style="
            width:14px;height:14px;border-radius:50%;
            background:${colour};
            border:2px solid rgba(255,255,255,0.7);
            box-shadow:0 0 6px ${colour};
          "></div>`,
          iconSize: [14, 14],
          iconAnchor: [7, 7],
        });

        const marker = L.marker([lat, lon], { icon })
          .addTo(map)
          .bindPopup(buildPopupHTML(ip, record));

        markersRef.current.set(ip, marker);
      }
    })();
  }, [attacks]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, []);

  return (
    <div style={wrapperStyle}>
      <div style={headerStyle}>
        <span style={titleStyle}>Global Attack Map</span>
        <span style={countStyle}>{Object.keys(attacks).length} active threats</span>
      </div>

      <div style={{ position: 'relative', height }}>
        {/* Leaflet CSS injected inline so no separate import is needed */}
        <style>{LEAFLET_CSS}</style>

        <div ref={mapContainerRef} style={{ width: '100%', height: '100%', borderRadius: 8 }} />

        {loading && (
          <div style={overlayStyle}>
            <span style={{ color: '#94a3b8', fontSize: 13 }}>Loading attack data…</span>
          </div>
        )}
      </div>

      {/* Legend */}
      <div style={legendStyle}>
        {Object.entries(INTENT_COLOUR).map(([intent, colour]) => (
          <span key={intent} style={legendItemStyle}>
            <span style={{ ...dotStyle, background: colour }} />
            {intent}
          </span>
        ))}
      </div>
    </div>
  );
};

// ── Popup HTML builder ────────────────────────────────────────────────────────

function buildPopupHTML(ip: string, record: AttackRecord): string {
  const colour = intentColour(record.intent);
  const time = record.time ? new Date(record.time).toLocaleString() : '—';
  return `
    <div style="font-family:monospace;font-size:12px;min-width:180px">
      <div style="font-weight:700;margin-bottom:4px">
        <span style="color:${colour}">⬤</span> ${ip}
      </div>
      <div><b>Country:</b> ${record.geo?.country ?? 'Unknown'}</div>
      <div><b>City:</b> ${record.geo?.city ?? '—'}</div>
      <div><b>ISP:</b> ${record.geo?.isp ?? '—'}</div>
      <div><b>Intent:</b> <span style="color:${colour}">${record.intent}</span></div>
      <div><b>Severity:</b> ${(record.severity * 100).toFixed(0)}%</div>
      <div style="margin-top:4px;color:#94a3b8;font-size:10px">${time}</div>
    </div>
  `;
}

// ── Styles ────────────────────────────────────────────────────────────────────

const wrapperStyle: React.CSSProperties = {
  background: 'var(--surface, #1e293b)',
  border: '1px solid var(--border, #334155)',
  borderRadius: 10,
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
  gap: 0,
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '12px 16px',
  borderBottom: '1px solid var(--border, #334155)',
};

const titleStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)',
  fontSize: 13,
  fontWeight: 700,
  letterSpacing: 0.3,
};

const countStyle: React.CSSProperties = {
  color: '#ef4444',
  fontSize: 12,
  fontWeight: 600,
};

const overlayStyle: React.CSSProperties = {
  position: 'absolute',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'rgba(15,23,42,0.6)',
  borderRadius: 8,
  zIndex: 1000,
};

const legendStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: '8px 16px',
  padding: '10px 16px',
  borderTop: '1px solid var(--border, #334155)',
};

const legendItemStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 5,
  color: 'var(--text-muted, #94a3b8)',
  fontSize: 11,
  textTransform: 'capitalize',
};

const dotStyle: React.CSSProperties = {
  width: 8,
  height: 8,
  borderRadius: '50%',
  display: 'inline-block',
};

// ── Minimal Leaflet CSS (inlined to avoid separate import) ────────────────────

const LEAFLET_CSS = `
.leaflet-container{height:100%;width:100%;background:#0f172a}
.leaflet-tile{filter:brightness(0.7) saturate(0.5)}
.leaflet-popup-content-wrapper{background:#1e293b;color:#f1f5f9;border:1px solid #334155;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.5)}
.leaflet-popup-tip{background:#1e293b}
.leaflet-popup-close-button{color:#94a3b8!important}
.leaflet-control-zoom a{background:#1e293b;color:#f1f5f9;border-color:#334155}
.leaflet-control-zoom a:hover{background:#334155}
.leaflet-control-attribution{background:rgba(15,23,42,0.7)!important;color:#64748b!important;font-size:9px}
.leaflet-control-attribution a{color:#64748b}
`;
