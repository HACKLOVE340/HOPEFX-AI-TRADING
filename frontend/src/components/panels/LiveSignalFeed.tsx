/**
 * components/panels/LiveSignalFeed.tsx
 * Live signal feed — filter tabs, clickable signal detail with Place Trade,
 * animated pulse on new signals, rich green/red cards.
 */

import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { Badge } from '../ui/Badge';
import { ConfidenceBar } from '../ui/ConfidenceBar';
import { fmtPrice, fmtRelative, confColor, dirColor, cn } from '../../lib/utils';
import type { Signal } from '../../types';

type Filter = 'all' | 'long' | 'short' | 'active' | 'recent';

// ── Direction arrow ───────────────────────────────────────────────────────────
function DirectionArrow({ direction }: { direction: string }) {
  if (direction === 'long')  return <span className="text-[#00e676] text-base leading-none">▲</span>;
  if (direction === 'short') return <span className="text-[#ff1744] text-base leading-none">▼</span>;
  return <span className="text-slate-500 text-base leading-none">◆</span>;
}

// ── Signal detail modal ───────────────────────────────────────────────────────
function SignalDetailModal({ signal, onClose }: { signal: Signal; onClose: () => void }) {
  const navigate = useNavigate();
  const isLong = signal.direction === 'long';
  const accentColor = isLong ? '#00e676' : '#ff1744';
  const rr = signal.risk_reward ??
    (signal.entry_price > 0 && signal.stop_loss > 0 && signal.take_profit > 0
      ? Math.abs(signal.take_profit - signal.entry_price) /
        Math.abs(signal.entry_price - signal.stop_loss)
      : null);

  const handlePlaceTrade = () => {
    onClose();
    navigate('/trade', { state: { signal } });
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#0d1421', border: `1px solid ${accentColor}40`,
          borderRadius: 12, width: '100%', maxWidth: 480,
          boxShadow: `0 0 40px ${accentColor}20`,
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          background: `${accentColor}10`, borderBottom: `1px solid ${accentColor}30`,
          padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 22 }}>{isLong ? '▲' : '▼'}</span>
            <div>
              <div style={{ fontSize: 16, fontWeight: 800, color: '#f1f5f9', fontFamily: 'monospace' }}>
                {signal.symbol.replace('_', '/')}
              </div>
              <div style={{ fontSize: 11, color: accentColor, fontWeight: 700, letterSpacing: 1 }}>
                {signal.direction.toUpperCase()} · {signal.status.toUpperCase()}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: '#64748b', fontSize: 20, cursor: 'pointer' }}
          >×</button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Confidence */}
          <div>
            <div style={{ fontSize: 10, color: '#64748b', letterSpacing: 1.5, marginBottom: 6 }}>CONFIDENCE</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <ConfidenceBar value={signal.confidence} height="sm" className="flex-1" />
              <span style={{ fontSize: 14, fontWeight: 800, color: confColor(signal.confidence), fontFamily: 'monospace' }}>
                {(signal.confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>

          {/* Price levels grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            {[
              { label: 'ENTRY', value: fmtPrice(signal.entry_price), color: '#e2e8f0' },
              { label: 'STOP LOSS', value: fmtPrice(signal.stop_loss), color: '#ff1744' },
              { label: 'TAKE PROFIT', value: fmtPrice(signal.take_profit), color: '#00e676' },
            ].map(({ label, value, color }) => (
              <div key={label} style={{
                background: '#111827', border: '1px solid #1e2d3d',
                borderRadius: 8, padding: '10px 12px',
              }}>
                <div style={{ fontSize: 9, color: '#64748b', letterSpacing: 1.5, marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color, fontFamily: 'monospace' }}>{value}</div>
              </div>
            ))}
          </div>

          {/* R:R + Model */}
          <div style={{ display: 'flex', gap: 12 }}>
            {rr != null && (
              <div style={{
                flex: 1, background: '#111827', border: '1px solid #1e2d3d',
                borderRadius: 8, padding: '10px 12px',
              }}>
                <div style={{ fontSize: 9, color: '#64748b', letterSpacing: 1.5, marginBottom: 4 }}>RISK : REWARD</div>
                <div style={{
                  fontSize: 16, fontWeight: 900, fontFamily: 'monospace',
                  color: rr >= 2 ? '#00e676' : rr >= 1 ? '#ffb800' : '#ff3b5c',
                }}>
                  1 : {rr.toFixed(2)}
                </div>
              </div>
            )}
            <div style={{
              flex: 2, background: '#111827', border: '1px solid #1e2d3d',
              borderRadius: 8, padding: '10px 12px',
            }}>
              <div style={{ fontSize: 9, color: '#64748b', letterSpacing: 1.5, marginBottom: 4 }}>MODEL</div>
              <div style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                {signal.model || '—'}
              </div>
            </div>
          </div>

          {/* Timestamp */}
          <div style={{ fontSize: 11, color: '#475569', textAlign: 'right' }}>
            Generated {fmtRelative(signal.generated_at)}
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              onClick={handlePlaceTrade}
              style={{
                flex: 1, padding: '12px 0',
                background: `${accentColor}20`, border: `1px solid ${accentColor}60`,
                borderRadius: 8, color: accentColor, fontSize: 14, fontWeight: 800,
                cursor: 'pointer', fontFamily: 'inherit', letterSpacing: 0.5,
              }}
            >
              {isLong ? '▲' : '▼'} Place Trade
            </button>
            <button
              onClick={onClose}
              style={{
                padding: '12px 20px',
                background: 'transparent', border: '1px solid #334155',
                borderRadius: 8, color: '#64748b', fontSize: 13,
                cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Signal card ───────────────────────────────────────────────────────────────
function SignalCard({ signal, isNew, onClick }: { signal: Signal; isNew: boolean; onClick: () => void }) {
  const isLong = signal.direction === 'long';
  const isExpired = signal.status === 'expired' || signal.status === 'cancelled';
  const accentColor = isLong ? '#00e676' : '#ff1744';
  const rr = signal.risk_reward ??
    (signal.entry_price > 0 && signal.stop_loss > 0 && signal.take_profit > 0
      ? Math.abs(signal.take_profit - signal.entry_price) /
        Math.abs(signal.entry_price - signal.stop_loss)
      : null);

  return (
    <div
      onClick={onClick}
      style={{
        borderLeft: `3px solid ${isExpired ? '#334155' : accentColor}`,
        background: isNew ? `${accentColor}08` : 'transparent',
        padding: '10px 12px',
        borderBottom: '1px solid #1e2d3d',
        cursor: 'pointer',
        transition: 'background 0.2s ease',
        opacity: isExpired ? 0.45 : 1,
        animation: isNew ? 'signalPulse 1.5s ease-out' : undefined,
      }}
      onMouseEnter={(e) => { if (!isExpired) (e.currentTarget as HTMLDivElement).style.background = `${accentColor}10`; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = isNew ? `${accentColor}08` : 'transparent'; }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, color: accentColor }}>{isLong ? '▲' : '▼'}</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#e2e8f0', fontFamily: 'monospace', letterSpacing: 0.5 }}>
            {signal.symbol.replace('_', '/')}
          </span>
          <span style={{
            fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 4,
            background: `${accentColor}18`, color: accentColor, letterSpacing: 1,
          }}>
            {signal.direction.toUpperCase()}
          </span>
          {isNew && (
            <span style={{
              fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 4,
              background: '#fbbf2420', color: '#fbbf24', letterSpacing: 1,
              animation: 'signalPulse 1s ease infinite',
            }}>
              NEW
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            fontSize: 9, padding: '1px 6px', borderRadius: 4,
            background: signal.status === 'active' ? '#00e67618' : '#33415518',
            color: signal.status === 'active' ? '#00e676' : '#64748b',
          }}>
            {signal.status}
          </span>
          <span style={{ fontSize: 9, color: '#475569', fontFamily: 'monospace' }}>{fmtRelative(signal.generated_at)}</span>
        </div>
      </div>

      {/* Confidence bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <ConfidenceBar value={signal.confidence} height="sm" className="flex-1" />
        <span style={{ fontSize: 11, fontWeight: 700, color: confColor(signal.confidence), fontFamily: 'monospace', minWidth: 32, textAlign: 'right' }}>
          {(signal.confidence * 100).toFixed(0)}%
        </span>
      </div>

      {/* Price levels */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 4 }}>
        <div>
          <div style={{ fontSize: 9, color: '#64748b', letterSpacing: 1 }}>ENTRY</div>
          <div style={{ fontSize: 11, color: '#e2e8f0', fontFamily: 'monospace' }}>{fmtPrice(signal.entry_price)}</div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: '#ff174490', letterSpacing: 1 }}>SL</div>
          <div style={{ fontSize: 11, color: '#ff1744', fontFamily: 'monospace' }}>{fmtPrice(signal.stop_loss)}</div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: '#00e67690', letterSpacing: 1 }}>TP</div>
          <div style={{ fontSize: 11, color: '#00e676', fontFamily: 'monospace' }}>{fmtPrice(signal.take_profit)}</div>
        </div>
      </div>

      {/* Footer */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6 }}>
        <span style={{ fontSize: 9, color: '#475569', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 140 }}>
          {signal.model}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {rr != null && (
            <span style={{
              fontSize: 10, fontWeight: 700, fontFamily: 'monospace',
              color: rr >= 2 ? '#00e676' : rr >= 1 ? '#ffb800' : '#ff3b5c',
            }}>
              R:R {rr.toFixed(1)}
            </span>
          )}
          <span style={{ fontSize: 9, color: '#3b82f6' }}>tap for details →</span>
        </div>
      </div>
    </div>
  );
}

// ── Position row ──────────────────────────────────────────────────────────────
function PositionRow({ pos }: { pos: import('../../types').Position }) {
  const pnlColor = (pos.unrealized_pnl ?? 0) >= 0 ? '#00e676' : '#ff1744';
  const isLong = pos.side === 'long' || pos.side === 'buy';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '8px 12px', borderBottom: '1px solid #1e2d3d',
      borderLeft: `3px solid ${isLong ? '#00e676' : '#ff1744'}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: isLong ? '#00e676' : '#ff1744', fontSize: 12 }}>{isLong ? '▲' : '▼'}</span>
        <span style={{ fontSize: 11, color: '#e2e8f0', fontFamily: 'monospace' }}>{pos.symbol.replace('_', '/')}</span>
        <span style={{ fontSize: 10, color: '#64748b', fontFamily: 'monospace' }}>×{pos.size}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 10, color: '#475569', fontFamily: 'monospace' }}>@ {fmtPrice(pos.entry_price)}</span>
        <span style={{ fontSize: 11, fontWeight: 700, color: pnlColor, fontFamily: 'monospace' }}>
          {(pos.unrealized_pnl ?? 0) >= 0 ? '+' : ''}${(pos.unrealized_pnl ?? 0).toFixed(2)}
        </span>
      </div>
    </div>
  );
}

// ── Filter tabs ───────────────────────────────────────────────────────────────
const FILTERS: { id: Filter; label: string; color: string }[] = [
  { id: 'all',    label: 'ALL',    color: '#64748b' },
  { id: 'active', label: 'ACTIVE', color: '#00e676' },
  { id: 'long',   label: 'LONG ▲', color: '#00e676' },
  { id: 'short',  label: 'SHORT ▼', color: '#ff1744' },
  { id: 'recent', label: 'RECENT', color: '#94a3b8' },
];

// ── Main component ────────────────────────────────────────────────────────────
export function LiveSignalFeed() {
  const signals   = useStore((s) => s.signals);
  const positions = useStore((s) => s.positions);
  const [filter, setFilter]           = useState<Filter>('all');
  const [selected, setSelected]       = useState<Signal | null>(null);
  const [newSignalIds, setNewSignalIds] = useState<Set<string>>(new Set());
  const prevIdsRef = useRef<Set<string>>(new Set());

  // Detect newly arrived signals and pulse them
  useEffect(() => {
    const currentIds = new Set(signals.map((s) => s.id));
    const added = [...currentIds].filter((id) => !prevIdsRef.current.has(id));
    if (added.length > 0) {
      setNewSignalIds((prev) => new Set([...prev, ...added]));
      setTimeout(() => {
        setNewSignalIds((prev) => {
          const next = new Set(prev);
          added.forEach((id) => next.delete(id));
          return next;
        });
      }, 4000);
    }
    prevIdsRef.current = currentIds;
  }, [signals]);

  const filtered = signals.filter((s) => {
    if (filter === 'active') return s.status === 'active';
    if (filter === 'long')   return s.direction === 'long';
    if (filter === 'short')  return s.direction === 'short';
    if (filter === 'recent') return s.status !== 'active';
    return true;
  });

  const activeCount = signals.filter((s) => s.status === 'active').length;
  const openPositions = positions.filter((p) => p.unrealized_pnl !== undefined);

  const headerRight = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#00e676', fontWeight: 700 }}>
        {activeCount} active
      </span>
      <span style={{ fontSize: 10, color: '#334155' }}>|</span>
      <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#64748b' }}>
        {openPositions.length} pos
      </span>
    </div>
  );

  return (
    <>
      <style>{`
        @keyframes signalPulse {
          0%   { box-shadow: 0 0 0 0 rgba(0,230,118,0.4); }
          70%  { box-shadow: 0 0 0 8px rgba(0,230,118,0); }
          100% { box-shadow: 0 0 0 0 rgba(0,230,118,0); }
        }
      `}</style>

      {selected && (
        <SignalDetailModal signal={selected} onClose={() => setSelected(null)} />
      )}

      <Panel title="Signals & Positions" headerRight={headerRight} noPad bodyClass="p-0">
        {/* Filter tabs */}
        <div style={{
          display: 'flex', gap: 4, padding: '8px 10px',
          borderBottom: '1px solid #1e2d3d', flexWrap: 'wrap',
        }}>
          {FILTERS.map(({ id, label, color }) => (
            <button
              key={id}
              onClick={() => setFilter(id)}
              style={{
                padding: '3px 10px', borderRadius: 4,
                background: filter === id ? `${color}20` : 'transparent',
                border: `1px solid ${filter === id ? `${color}60` : '#1e293b'}`,
                color: filter === id ? color : '#475569',
                fontSize: 9, fontWeight: 700, letterSpacing: 1,
                cursor: 'pointer', fontFamily: 'monospace',
                transition: 'all 0.15s ease',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {/* Open positions */}
          {filter === 'all' && openPositions.length > 0 && (
            <div style={{ borderBottom: '1px solid #1e2d3d' }}>
              <div style={{ padding: '6px 12px', background: '#111827' }}>
                <span style={{ fontSize: 9, color: '#64748b', letterSpacing: 1.5, textTransform: 'uppercase' }}>Open Positions</span>
              </div>
              {openPositions.map((p) => <PositionRow key={p.id} pos={p} />)}
            </div>
          )}

          {/* Signals */}
          {filtered.length > 0 ? (
            filtered.map((s) => (
              <SignalCard
                key={s.id}
                signal={s}
                isNew={newSignalIds.has(s.id)}
                onClick={() => setSelected(s)}
              />
            ))
          ) : (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              justifyContent: 'center', padding: '32px 16px', gap: 8,
            }}>
              <span style={{ fontSize: 24, opacity: 0.3 }}>📡</span>
              <span style={{ fontSize: 11, color: '#475569' }}>
                {signals.length === 0 ? 'Awaiting signals from inference engine…' : `No ${filter} signals`}
              </span>
            </div>
          )}
        </div>
      </Panel>
    </>
  );
}

// ── Guarded export ────────────────────────────────────────────────────────────
import { withPanelGuard } from '../ui/withPanelGuard';
export const LiveSignalFeedGuarded = withPanelGuard(LiveSignalFeed, 'Signal Feed', 5);
