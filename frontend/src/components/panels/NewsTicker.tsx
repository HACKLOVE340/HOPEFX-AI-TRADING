/**
 * components/panels/NewsTicker.tsx
 * Scrolling live news ticker sourced from WebSocket newsItems in Zustand store.
 * Shows the latest headlines with sentiment color-coding.
 */

import React, { useEffect, useRef, useState } from 'react';
import { useStore, selectNewsItems } from '../../store';

interface NewsItem {
  id?: string;
  headline?: string;
  title?: string;
  sentiment?: number | string;
  source?: string;
  url?: string | null;
  published_at?: string | null;
  timestamp?: string;
}

const sentimentColor = (s: number | string | undefined): string => {
  if (s === undefined || s === null) return '#64748b';
  const val = typeof s === 'string' ? parseFloat(s) : s;
  if (val > 0.2)  return '#00e676';
  if (val < -0.2) return '#ff1744';
  return '#fbbf24';
};

const sentimentLabel = (s: number | string | undefined): string => {
  if (s === undefined || s === null) return '';
  const val = typeof s === 'string' ? parseFloat(s) : s;
  if (val > 0.2)  return '▲';
  if (val < -0.2) return '▼';
  return '◆';
};

export function NewsTicker() {
  const newsItems = useStore(selectNewsItems) as NewsItem[];
  const [paused, setPaused]   = useState(false);
  const [expanded, setExpanded] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);

  if (newsItems.length === 0) return null;

  const displayed = newsItems.slice(0, 20);

  return (
    <div style={{
      background: '#060d18',
      borderBottom: '1px solid #1a2e4a',
      display: 'flex',
      alignItems: 'center',
      height: expanded ? 'auto' : 28,
      flexShrink: 0,
      overflow: 'hidden',
      position: 'relative',
    }}>
      {/* Label */}
      <div style={{
        padding: '0 10px',
        borderRight: '1px solid #1a2e4a',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: 5,
        flexShrink: 0,
        background: '#0d1421',
      }}>
        <span style={{ fontSize: 8, color: '#ff1744', fontWeight: 900, letterSpacing: 2 }}>● LIVE</span>
        <span style={{ fontSize: 9, color: '#475569', fontWeight: 700, letterSpacing: 1.5 }}>NEWS</span>
      </div>

      {!expanded ? (
        /* Scrolling ticker */
        <div
          style={{ flex: 1, overflow: 'hidden', cursor: 'pointer' }}
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
          onClick={() => setExpanded(true)}
          title="Click to expand news feed"
        >
          <div
            ref={trackRef}
            style={{
              display: 'flex',
              gap: 0,
              animation: paused ? 'none' : `tickerScroll ${displayed.length * 8}s linear infinite`,
              whiteSpace: 'nowrap',
            }}
          >
            {[...displayed, ...displayed].map((item, i) => {
              const text = item.headline || item.title || '';
              const color = sentimentColor(item.sentiment);
              return (
                <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '0 24px' }}>
                  <span style={{ fontSize: 10, color, fontWeight: 700 }}>{sentimentLabel(item.sentiment)}</span>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>{text}</span>
                  {item.source && (
                    <span style={{ fontSize: 9, color: '#334155' }}>— {item.source}</span>
                  )}
                  <span style={{ fontSize: 9, color: '#1e293b', marginLeft: 8 }}>◇</span>
                </span>
              );
            })}
          </div>
        </div>
      ) : (
        /* Expanded news list */
        <div style={{ flex: 1, maxHeight: 240, overflowY: 'auto', padding: '4px 0' }}>
          {displayed.map((item, i) => {
            const text = item.headline || item.title || '';
            const color = sentimentColor(item.sentiment);
            const ts = item.published_at || item.timestamp;
            return (
              <div key={i} style={{
                display: 'flex', alignItems: 'flex-start', gap: 8,
                padding: '5px 12px', borderBottom: '1px solid #0d1421',
              }}>
                <span style={{ fontSize: 11, color, flexShrink: 0, marginTop: 1 }}>{sentimentLabel(item.sentiment)}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {item.url ? (
                    <a href={item.url} target="_blank" rel="noopener noreferrer"
                      style={{ fontSize: 11, color: '#cbd5e1', textDecoration: 'none', lineHeight: 1.4 }}>
                      {text}
                    </a>
                  ) : (
                    <span style={{ fontSize: 11, color: '#cbd5e1', lineHeight: 1.4 }}>{text}</span>
                  )}
                  <div style={{ display: 'flex', gap: 8, marginTop: 2 }}>
                    {item.source && <span style={{ fontSize: 9, color: '#475569' }}>{item.source}</span>}
                    {ts && <span style={{ fontSize: 9, color: '#334155' }}>{new Date(ts).toLocaleTimeString()}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Collapse/expand button */}
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          padding: '0 10px', height: '100%',
          background: 'transparent', border: 'none',
          borderLeft: '1px solid #1a2e4a',
          color: '#334155', cursor: 'pointer', fontSize: 12,
          flexShrink: 0,
        }}
        title={expanded ? 'Collapse news' : 'Expand news'}
      >
        {expanded ? '▲' : '▼'}
      </button>

      <style>{`
        @keyframes tickerScroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}
