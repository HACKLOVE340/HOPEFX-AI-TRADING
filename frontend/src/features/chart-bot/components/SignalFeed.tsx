/**
 * SignalFeed.tsx
 * Live ML signal feed with confidence levels, reasoning, regime badges,
 * and one-tap trade execution routed through the orchestrator smart router.
 */

import React, { useState, memo, useCallback } from 'react';
import { useChartBotStore } from '../store/chart-bot-store';
import { useSignals, usePlaceOrder } from '../hooks/useChartData';
import { COLORS } from '../utils/design-tokens';
import {
  formatPrice, formatConfidence, confidenceLabel, confidenceColor,
  regimeLabel, regimeColor, formatRelativeTime,
} from '../utils/formatters';
import type { MLSignal } from '../types';

// ─── Signal Card ──────────────────────────────────────────────────────────────

interface SignalCardProps {
  signal: MLSignal;
  isSelected: boolean;
  onSelect: (id: string) => void;
  onTrade: (signal: MLSignal, side: 'buy' | 'sell') => void;
  trading: boolean;
}

const SignalCard = memo(({ signal, isSelected, onSelect, onTrade, trading }: SignalCardProps) => {
  const isLong    = signal.direction === 'long';
  const isNeutral = signal.direction === 'neutral';
  const dirColor  = isLong ? COLORS.profit.base : isNeutral ? COLORS.text.muted : COLORS.loss.base;
  const confColor = confidenceColor(signal.confidence);
  const rColor    = regimeColor(signal.regime);
  const isExpired = signal.status === 'expired' || signal.status === 'cancelled';
  const rr        = signal.risk_reward;

  return (
    <div
      onClick={() => onSelect(signal.id)}
      style={{
        ...sc.card,
        borderColor: isSelected ? dirColor : COLORS.bg.border,
        background: isSelected ? `${dirColor}08` : COLORS.bg.surface,
        opacity: isExpired ? 0.45 : 1,
        cursor: 'pointer',
      }}
    >
      {/* Top row: direction + confidence */}
      <div style={sc.topRow}>
        <div style={scDynamic.dirBadge(dirColor)}>
          <span style={sc.dirArrow}>{isLong ? '▲' : isNeutral ? '—' : '▼'}</span>
          <span style={sc.dirText}>{signal.direction.toUpperCase()}</span>
        </div>

        <div style={sc.confSection}>
          <div style={sc.confBarBg}>
            <div style={{ ...sc.confBarFill, width: `${signal.confidence * 100}%`, background: confColor }} />
          </div>
          <span style={{ ...sc.confLabel, color: confColor }}>
            {formatConfidence(signal.confidence)} {confidenceLabel(signal.confidence)}
          </span>
        </div>

        <span style={{ ...sc.statusBadge, color: signal.status === 'active' ? COLORS.profit.base : COLORS.text.muted }}>
          {signal.status.toUpperCase()}
        </span>
      </div>

      {/* Price levels */}
      <div style={sc.priceRow}>
        <PriceLevel label="ENTRY" value={signal.entry_price} color={COLORS.text.primary} />
        <PriceLevel label="SL"    value={signal.stop_loss}   color={COLORS.loss.base} />
        <PriceLevel label="TP"    value={signal.take_profit} color={COLORS.profit.base} />
        <div style={scDynamic.rrBadge(rr >= 2 ? COLORS.profit.base : rr >= 1 ? COLORS.neon.gold : COLORS.loss.base)}>
          R:R {Number.isFinite(rr) ? rr.toFixed(1) : '—'}
        </div>
      </div>

      {/* Regime + model */}
      <div style={sc.metaRow}>
        <span style={{ ...sc.regimePill, color: rColor, background: `${rColor}18`, border: `1px solid ${rColor}33` }}>
          {regimeLabel(signal.regime)}
        </span>
        <span style={sc.modelLabel}>{signal.model}</span>
        <span style={sc.timeLabel}>{formatRelativeTime(new Date(signal.generated_at).getTime())}</span>
      </div>

      {/* Expanded: reasoning + features + trade buttons */}
      {isSelected && (
        <div style={sc.expanded}>
          {signal.reasoning && (
            <div style={sc.reasoning}>{signal.reasoning}</div>
          )}

          {signal.features?.length > 0 && (
            <div style={sc.features}>
              <span style={sc.featuresLabel}>TOP FEATURES</span>
              {signal.features
                .sort((a, b) => b.importance - a.importance)
                .slice(0, 4)
                .map((f) => (
                  <div key={f.name} style={sc.featureRow}>
                    <span style={sc.featureName}>{f.name}</span>
                    <div style={sc.featureBarBg}>
                      <div style={{
                        ...sc.featureBarFill,
                        width: `${f.importance * 100}%`,
                        background: f.direction === 'bullish' ? COLORS.profit.base
                                  : f.direction === 'bearish' ? COLORS.loss.base
                                  : COLORS.text.muted,
                      }} />
                    </div>
                    <span style={{ ...sc.featureVal, color: f.direction === 'bullish' ? COLORS.profit.base : f.direction === 'bearish' ? COLORS.loss.base : COLORS.text.muted }}>
                      {(f.importance * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
            </div>
          )}

          {/* Trade execution buttons */}
          {signal.status === 'active' && !isExpired && (
            <div style={sc.tradeRow}>
              <button
                onClick={(e) => { e.stopPropagation(); onTrade(signal, 'buy'); }}
                disabled={trading}
                style={{ ...sc.tradeBtn, ...sc.buyBtn, opacity: trading ? 0.5 : 1 }}
              >
                {trading ? '…' : '▲ BUY'}
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onTrade(signal, 'sell'); }}
                disabled={trading}
                style={{ ...sc.tradeBtn, ...sc.sellBtn, opacity: trading ? 0.5 : 1 }}
              >
                {trading ? '…' : '▼ SELL'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
});
SignalCard.displayName = 'SignalCard';

const PriceLevel = memo(({ label, value, color }: { label: string; value: number; color: string }) => (
  <div style={sc.priceLevel}>
    <span style={sc.priceLevelLabel}>{label}</span>
    <span style={{ ...sc.priceLevelVal, color }}>{formatPrice(value)}</span>
  </div>
));
PriceLevel.displayName = 'PriceLevel';

// ─── Trade Toast ──────────────────────────────────────────────────────────────

const TradeToast = memo(({ message, success }: { message: string; success: boolean }) => (
  <div style={{
    ...sf.toast,
    background: success ? COLORS.profit.bg : COLORS.loss.bg,
    border: `1px solid ${success ? COLORS.profit.border : COLORS.loss.border}`,
    color: success ? COLORS.profit.base : COLORS.loss.base,
  }}>
    {success ? '✓' : '✕'} {message}
  </div>
));
TradeToast.displayName = 'TradeToast';

// ─── Filter Bar ───────────────────────────────────────────────────────────────

type FilterType = 'all' | 'long' | 'short' | 'active';

const FilterBar = memo(({ active, onChange }: { active: FilterType; onChange: (f: FilterType) => void }) => {
  const filters: { key: FilterType; label: string }[] = [
    { key: 'all',    label: 'ALL'    },
    { key: 'active', label: 'ACTIVE' },
    { key: 'long',   label: 'LONG'   },
    { key: 'short',  label: 'SHORT'  },
  ];
  return (
    <div style={sf.filterBar}>
      {filters.map((f) => (
        <button
          key={f.key}
          onClick={() => onChange(f.key)}
          style={{ ...sf.filterBtn, ...(active === f.key ? sf.filterBtnActive : {}) }}
        >
          {f.label}
        </button>
      ))}
    </div>
  );
});
FilterBar.displayName = 'FilterBar';

// ─── Main Component ───────────────────────────────────────────────────────────

const SignalFeed: React.FC = () => {
  const symbol          = useChartBotStore((s) => s.symbol);
  const signalsStore    = useChartBotStore((s) => s.signals);
  const selectedId      = useChartBotStore((s) => s.selectedSignalId);
  const setSelectedId   = useChartBotStore((s) => s.setSelectedSignal);

  const { data: signalsFetched } = useSignals(symbol);
  const { mutate: placeOrder, isPending: trading } = usePlaceOrder();

  const [filter, setFilter]   = useState<FilterType>('all');
  const [toast, setToast]     = useState<{ message: string; success: boolean } | null>(null);

  // Merge store (live WS) + fetched signals, deduplicate by id
  const allSignals = React.useMemo(() => {
    const map = new Map<string, MLSignal>();
    (signalsFetched ?? []).forEach((s) => map.set(s.id, s));
    signalsStore.forEach((s) => map.set(s.id, s));
    return Array.from(map.values()).sort(
      (a, b) => new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime()
    );
  }, [signalsFetched, signalsStore]);

  const filtered = React.useMemo(() => {
    switch (filter) {
      case 'active': return allSignals.filter((s) => s.status === 'active');
      case 'long':   return allSignals.filter((s) => s.direction === 'long');
      case 'short':  return allSignals.filter((s) => s.direction === 'short');
      default:       return allSignals;
    }
  }, [allSignals, filter]);

  const handleSelect = useCallback((id: string) => {
    setSelectedId(selectedId === id ? null : id);
  }, [selectedId, setSelectedId]);

  const handleTrade = useCallback((signal: MLSignal, side: 'buy' | 'sell') => {
    placeOrder(
      {
        symbol:     signal.symbol,
        side,
        size:       0.01,
        order_type: 'market',
        stop_loss:  signal.stop_loss,
        take_profit:signal.take_profit,
        signal_id:  signal.id,
      },
      {
        onSuccess: (result) => {
          setToast({ message: `Order ${result.status} @ ${formatPrice(result.fill_price)}`, success: result.status === 'filled' });
          setTimeout(() => setToast(null), 4000);
        },
        onError: () => {
          setToast({ message: 'Order failed — check kill switch', success: false });
          setTimeout(() => setToast(null), 4000);
        },
      }
    );
  }, [placeOrder]);

  const activeCount = allSignals.filter((s) => s.status === 'active').length;

  return (
    <div style={sf.wrapper}>
      {/* Header */}
      <div style={sf.header}>
        <div style={sf.headerLeft}>
          <span style={sf.title}>ML SIGNALS</span>
          {activeCount > 0 && (
            <span style={sf.activeBadge}>{activeCount} ACTIVE</span>
          )}
        </div>
        <span style={sf.totalCount}>{allSignals.length} total</span>
      </div>

      {/* Filter */}
      <FilterBar active={filter} onChange={setFilter} />

      {/* Toast */}
      {toast && <TradeToast message={toast.message} success={toast.success} />}

      {/* Signal list */}
      <div style={sf.list}>
        {filtered.length === 0 ? (
          <div style={sf.empty}>No signals match this filter.</div>
        ) : (
          filtered.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              isSelected={selectedId === signal.id}
              onSelect={handleSelect}
              onTrade={handleTrade}
              trading={trading}
            />
          ))
        )}
      </div>
    </div>
  );
};

// ─── Dynamic style helpers ────────────────────────────────────────────────────

const scDynamic = {
  dirBadge: (color: string): React.CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 4,
    background: `${color}18`,
    border: `1px solid ${color}44`,
    borderRadius: 4, padding: '3px 7px', flexShrink: 0,
  }),
  rrBadge: (color: string): React.CSSProperties => ({
    fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700,
    color, background: `${color}18`,
    border: `1px solid ${color}33`,
    borderRadius: 4, padding: '2px 6px', marginLeft: 'auto',
  }),
};

// ─── Static styles ────────────────────────────────────────────────────────────

const sc: Record<string, React.CSSProperties> = {
  card: {
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 6,
    padding: '10px 12px',
    transition: 'border-color 150ms ease, background 150ms ease',
    userSelect: 'none',
  },
  topRow: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 },
  dirArrow: { fontSize: 10 },
  dirText: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, fontWeight: 700, letterSpacing: '0.06em' },
  confSection: { flex: 1, display: 'flex', flexDirection: 'column', gap: 3 },
  confBarBg: { height: 3, background: COLORS.bg.elevated, borderRadius: 2, overflow: 'hidden' },
  confBarFill: { height: '100%', borderRadius: 2, transition: 'width 400ms ease' },
  confLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, letterSpacing: '0.06em' },
  statusBadge: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, letterSpacing: '0.08em', flexShrink: 0 },
  priceRow: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' },
  priceLevel: { display: 'flex', flexDirection: 'column', gap: 1 },
  priceLevelLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 7, color: COLORS.text.muted, letterSpacing: '0.1em' },
  priceLevelVal: { fontFamily: '"JetBrains Mono", monospace', fontSize: 11, fontWeight: 700 },
  metaRow: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  regimePill: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, letterSpacing: '0.06em' },
  modelLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted },
  timeLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted, marginLeft: 'auto' },
  expanded: { marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8, borderTop: `1px solid ${COLORS.bg.border}`, paddingTop: 8 },
  reasoning: { fontFamily: '"Inter", sans-serif', fontSize: 11, color: COLORS.text.secondary, lineHeight: 1.5 },
  features: { display: 'flex', flexDirection: 'column', gap: 4 },
  featuresLabel: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted, letterSpacing: '0.1em', marginBottom: 2 },
  featureRow: { display: 'flex', alignItems: 'center', gap: 6 },
  featureName: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, color: COLORS.text.muted, width: 80, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  featureBarBg: { flex: 1, height: 3, background: COLORS.bg.elevated, borderRadius: 2, overflow: 'hidden' },
  featureBarFill: { height: '100%', borderRadius: 2 },
  featureVal: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, fontWeight: 700, width: 24, textAlign: 'right' },
  tradeRow: { display: 'flex', gap: 6 },
  tradeBtn: { flex: 1, border: 'none', borderRadius: 5, cursor: 'pointer', fontFamily: '"JetBrains Mono", monospace', fontSize: 11, fontWeight: 700, padding: '8px 0', letterSpacing: '0.06em', transition: 'opacity 150ms ease' },
  buyBtn:  { background: COLORS.profit.muted, color: COLORS.profit.strong },
  sellBtn: { background: COLORS.loss.muted,   color: COLORS.loss.strong   },
};

const sf: Record<string, React.CSSProperties> = {
  wrapper: { background: COLORS.bg.surface, border: `1px solid ${COLORS.bg.border}`, borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px 8px', borderBottom: `1px solid ${COLORS.bg.border}` },
  headerLeft: { display: 'flex', alignItems: 'center', gap: 8 },
  title: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, fontWeight: 700, color: COLORS.text.muted, letterSpacing: '0.12em' },
  activeBadge: { fontFamily: '"JetBrains Mono", monospace', fontSize: 8, fontWeight: 700, color: COLORS.profit.base, background: COLORS.profit.bg, border: `1px solid ${COLORS.profit.border}`, padding: '1px 6px', borderRadius: 3, letterSpacing: '0.06em' },
  totalCount: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted },
  filterBar: { display: 'flex', gap: 0, borderBottom: `1px solid ${COLORS.bg.border}` },
  filterBtn: { flex: 1, background: 'transparent', border: 'none', borderRight: `1px solid ${COLORS.bg.border}`, color: COLORS.text.muted, cursor: 'pointer', fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 600, padding: '6px 0', letterSpacing: '0.08em', transition: 'all 100ms ease' },
  filterBtnActive: { background: COLORS.bg.elevated, color: COLORS.neon.cyan },
  list: { overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 10px', maxHeight: 600 },
  empty: { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: COLORS.text.muted, padding: '20px', textAlign: 'center' },
  toast: { margin: '6px 10px', padding: '7px 12px', borderRadius: 5, fontFamily: '"JetBrains Mono", monospace', fontSize: 10, fontWeight: 700, letterSpacing: '0.06em' },
};

export default memo(SignalFeed);
