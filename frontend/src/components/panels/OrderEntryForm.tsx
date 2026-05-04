/**
 * components/panels/OrderEntryForm.tsx
 * Production order entry form: market/limit/stop, quantity, SL, TP.
 *
 * Wires to:
 *   POST /api/trading/orders
 *   GET  /api/trading/account  (for balance / margin display)
 *
 * Backend OrderRequest schema:
 *   { symbol, side: "buy"|"sell", quantity, order_type: "market"|"limit"|"stop", price? }
 */

import React, { useState, useCallback, useEffect, useRef, useId } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useStore, selectIsBlackout } from '../../store';
import { tradingApi } from '../../hooks/useApi';
import { Panel } from '../ui/Panel';
import { withPanelGuard } from '../ui/withPanelGuard';
import { fmtPrice, cn } from '../../lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

type Side      = 'buy' | 'sell';
type OrderType = 'market' | 'limit' | 'stop';

interface OrderPayload {
  symbol:     string;
  side:       Side;
  quantity:   number;
  order_type: OrderType;
  price?:     number;
  stop_loss?:   number;
  take_profit?: number;
}

// ── Field ─────────────────────────────────────────────────────────────────────

function Field({
  label,
  id,
  children,
  hint,
}: {
  label: string;
  id: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </label>
      {children}
      {hint && <span className="text-[10px] text-slate-600">{hint}</span>}
    </div>
  );
}

function NumInput({
  id,
  value,
  onChange,
  placeholder,
  step = '0.01',
  min,
  disabled,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  step?: string;
  min?: string;
  disabled?: boolean;
}) {
  return (
    <input
      id={id}
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      step={step}
      min={min}
      disabled={disabled}
      className={cn(
        'w-full bg-[#0d1421] border border-[#1e2d3d] rounded px-2.5 py-1.5',
        'text-[12px] text-slate-200 placeholder-slate-600',
        'focus:outline-none focus:border-[#3b82f6] transition-colors',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        '[appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none',
      )}
    />
  );
}

// ── Risk preview ──────────────────────────────────────────────────────────────

function RiskPreview({
  side,
  entry,
  sl,
  tp,
  qty,
}: {
  side: Side;
  entry: number;
  sl: string;
  tp: string;
  qty: string;
}) {
  const slNum  = parseFloat(sl)  || 0;
  const tpNum  = parseFloat(tp)  || 0;
  const qtyNum = parseFloat(qty) || 0;

  if (!entry || !qtyNum) return null;

  const slDist = slNum > 0
    ? Math.abs(entry - slNum)
    : null;
  const tpDist = tpNum > 0
    ? Math.abs(tpNum - entry)
    : null;
  const rr = slDist && tpDist && slDist > 0
    ? (tpDist / slDist).toFixed(2)
    : null;
  const maxLoss = slDist ? (slDist * qtyNum).toFixed(2) : null;

  if (!slDist && !tpDist) return null;

  return (
    <div className="flex gap-3 px-2.5 py-2 rounded bg-[#0d1421] border border-[#1e2d3d] text-[10px]">
      {maxLoss && (
        <div className="flex flex-col gap-0.5">
          <span className="text-slate-500">Max loss</span>
          <span className="text-[#ff1744] font-semibold">${maxLoss}</span>
        </div>
      )}
      {rr && (
        <div className="flex flex-col gap-0.5">
          <span className="text-slate-500">R:R</span>
          <span className={cn('font-semibold', parseFloat(rr) >= 2 ? 'text-[#00e676]' : 'text-[#ffb800]')}>
            1:{rr}
          </span>
        </div>
      )}
      {slDist && (
        <div className="flex flex-col gap-0.5">
          <span className="text-slate-500">SL dist</span>
          <span className="text-slate-300">{fmtPrice(slDist)}</span>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface OrderEntryFormProps {
  symbol?:       string;
  defaultSide?:  Side;
  defaultSl?:    string;
  defaultTp?:    string;
  onOrderPlaced?: () => void;
}

// Fallback symbol list — slash format matches WebSocket price_tick symbol keys.
const FALLBACK_SYMBOLS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD'];
const ORDER_TYPES: { value: OrderType; label: string }[] = [
  { value: 'market', label: 'Market' },
  { value: 'limit',  label: 'Limit'  },
  { value: 'stop',   label: 'Stop'   },
];

function OrderEntryFormInner({ symbol: symbolProp, defaultSide, defaultSl, defaultTp, onOrderPlaced }: OrderEntryFormProps) {
  const uid        = useId();
  const prices     = useStore((s) => s.prices);
  const account    = useStore((s) => s.account);
  const isBlackout = useStore(selectIsBlackout);
  const qc         = useQueryClient();

  // Derive available symbols from live price keys so the selector always
  // matches what the backend is actually sending. Fall back to the static
  // list until the first tick arrives.
  const liveSymbols = Object.keys(prices);
  const symbols = liveSymbols.length > 0 ? liveSymbols : FALLBACK_SYMBOLS;

  const [symbol,    setSymbol]    = useState(symbolProp ?? symbols[0] ?? 'XAU/USD');
  const [side,      setSide]      = useState<Side>(defaultSide ?? 'buy');
  const [orderType, setOrderType] = useState<OrderType>('market');
  const [qty,       setQty]       = useState('0.01');
  const [limitPx,   setLimitPx]   = useState('');
  const [sl,        setSl]        = useState(defaultSl ?? '');
  const [tp,        setTp]        = useState(defaultTp ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [result,    setResult]    = useState<{ ok: boolean; msg: string } | null>(null);
  const resultTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-clear the result banner after 4 seconds so it doesn't linger.
  useEffect(() => {
    if (!result) return;
    if (resultTimer.current) clearTimeout(resultTimer.current);
    resultTimer.current = setTimeout(() => setResult(null), 4_000);
    return () => {
      if (resultTimer.current) clearTimeout(resultTimer.current);
    };
  }, [result]);

  const tick       = prices[symbol];
  const entryPrice = orderType === 'market'
    ? (side === 'buy' ? tick?.ask : tick?.bid) ?? 0
    : parseFloat(limitPx) || 0;

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setResult(null);

    const qtyNum = parseFloat(qty);
    if (!qtyNum || qtyNum <= 0) {
      setResult({ ok: false, msg: 'Quantity must be > 0' });
      return;
    }
    if ((orderType === 'limit' || orderType === 'stop') && !parseFloat(limitPx)) {
      setResult({ ok: false, msg: 'Price required for limit/stop orders' });
      return;
    }

    // Client-side SL direction validation — catches obvious mistakes before
    // the round-trip to the backend. The backend PreTradeGate also validates.
    const slNum = parseFloat(sl);
    if (slNum > 0 && entryPrice > 0) {
      if (side === 'buy' && slNum >= entryPrice) {
        setResult({ ok: false, msg: 'Stop loss must be below entry price for a buy order' });
        return;
      }
      if (side === 'sell' && slNum <= entryPrice) {
        setResult({ ok: false, msg: 'Stop loss must be above entry price for a sell order' });
        return;
      }
    }
    const tpNum = parseFloat(tp);
    if (tpNum > 0 && entryPrice > 0) {
      if (side === 'buy' && tpNum <= entryPrice) {
        setResult({ ok: false, msg: 'Take profit must be above entry price for a buy order' });
        return;
      }
      if (side === 'sell' && tpNum >= entryPrice) {
        setResult({ ok: false, msg: 'Take profit must be below entry price for a sell order' });
        return;
      }
    }

    const payload: OrderPayload = {
      symbol,
      side,
      quantity:   qtyNum,
      order_type: orderType,
    };
    if (orderType !== 'market' && limitPx) payload.price = parseFloat(limitPx);
    if (sl) payload.stop_loss   = parseFloat(sl);
    if (tp) payload.take_profit = parseFloat(tp);

    setSubmitting(true);
    try {
      await tradingApi.placeOrder(payload);
      setResult({ ok: true, msg: `${side.toUpperCase()} ${qtyNum} ${symbol} placed` });
      setQty('0.01');
      setSl('');
      setTp('');
      setLimitPx('');
      qc.invalidateQueries({ queryKey: ['positions'] });
      onOrderPlaced?.();
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (e as { message?: string })?.message ??
        'Order failed';
      setResult({ ok: false, msg: detail });
    } finally {
      setSubmitting(false);
    }
  }, [symbol, side, orderType, qty, limitPx, sl, tp, qc, onOrderPlaced]);

  return (
    <Panel title="Order Entry">
      {/* Blackout banner — shown when a high-impact macro event is imminent.
          The backend PreTradeGate will also block the order, but we disable
          the form here so the trader gets immediate feedback before submitting. */}
      {isBlackout && (
        <div className="flex items-center gap-2 px-3 py-2 mb-2 rounded bg-[#ff3b5c]/10 border border-[#ff3b5c]/30">
          <span className="text-[#ff3b5c] text-sm font-bold">⚠</span>
          <span className="text-[11px] text-[#ff3b5c] font-semibold">
            Trading paused — high-impact event blackout active
          </span>
        </div>
      )}
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">

        {/* Symbol selector (only shown when no symbol prop) */}
        {!symbolProp && (
          <Field label="Symbol" id={`${uid}-sym`}>
            <select
              id={`${uid}-sym`}
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="w-full bg-[#0d1421] border border-[#1e2d3d] rounded px-2.5 py-1.5 text-[12px] text-slate-200 focus:outline-none focus:border-[#3b82f6]"
            >
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </Field>
        )}

        {/* Live price strip */}
        {tick && (
          <div className="flex gap-4 px-2.5 py-2 rounded bg-[#0d1421] border border-[#1e2d3d] text-[11px]">
            <div className="flex flex-col gap-0.5">
              <span className="text-slate-500">Bid</span>
              <span className="text-[#ff1744] font-semibold tabular-nums">{fmtPrice(tick.bid)}</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-slate-500">Ask</span>
              <span className="text-[#00e676] font-semibold tabular-nums">{fmtPrice(tick.ask)}</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-slate-500">Spread</span>
              <span className="text-slate-400 tabular-nums">{fmtPrice(tick.ask - tick.bid, 3)}</span>
            </div>
            {account && (
              <div className="flex flex-col gap-0.5 ml-auto">
                <span className="text-slate-500">Balance</span>
                <span className="text-slate-300 tabular-nums">${account.balance?.toLocaleString()}</span>
              </div>
            )}
          </div>
        )}

        {/* Buy / Sell toggle */}
        <div className="grid grid-cols-2 gap-1.5">
          {(['buy', 'sell'] as Side[]).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSide(s)}
              className={cn(
                'py-2 rounded font-bold text-[13px] border transition-colors',
                side === s && s === 'buy'
                  ? 'bg-[#00e676]/15 border-[#00e676]/50 text-[#00e676]'
                  : side === s && s === 'sell'
                  ? 'bg-[#ff1744]/15 border-[#ff1744]/50 text-[#ff1744]'
                  : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
              )}
            >
              {s === 'buy' ? '▲ Buy' : '▼ Sell'}
            </button>
          ))}
        </div>

        {/* Order type tabs */}
        <div className="flex gap-1">
          {ORDER_TYPES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setOrderType(value)}
              className={cn(
                'flex-1 py-1 rounded text-[11px] font-semibold border transition-colors',
                orderType === value
                  ? 'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa]'
                  : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Quantity */}
        <Field label="Quantity (lots)" id={`${uid}-qty`} hint="Min 0.01 lot">
          <NumInput
            id={`${uid}-qty`}
            value={qty}
            onChange={setQty}
            placeholder="0.01"
            step="0.01"
            min="0.01"
          />
        </Field>

        {/* Limit / Stop price */}
        {orderType !== 'market' && (
          <Field
            label={orderType === 'limit' ? 'Limit Price' : 'Stop Price'}
            id={`${uid}-px`}
          >
            <NumInput
              id={`${uid}-px`}
              value={limitPx}
              onChange={setLimitPx}
              placeholder={tick ? fmtPrice(entryPrice) : '0.00'}
              step="0.01"
            />
          </Field>
        )}

        {/* SL / TP row */}
        <div className="grid grid-cols-2 gap-2">
          <Field label="Stop Loss" id={`${uid}-sl`}>
            <NumInput
              id={`${uid}-sl`}
              value={sl}
              onChange={setSl}
              placeholder="Optional"
              step="0.01"
            />
          </Field>
          <Field label="Take Profit" id={`${uid}-tp`}>
            <NumInput
              id={`${uid}-tp`}
              value={tp}
              onChange={setTp}
              placeholder="Optional"
              step="0.01"
            />
          </Field>
        </div>

        {/* Risk preview */}
        <RiskPreview side={side} entry={entryPrice} sl={sl} tp={tp} qty={qty} />

        {/* Submit — also disabled during macro blackout windows */}
        <button
          type="submit"
          disabled={submitting || isBlackout}
          title={isBlackout ? 'Trading paused — blackout window active' : undefined}
          className={cn(
            'w-full py-2.5 rounded font-bold text-[13px] border-none transition-colors',
            'disabled:opacity-40 disabled:cursor-not-allowed',
            side === 'buy'
              ? 'bg-[#00e676] text-[#0d1421] hover:bg-[#00c853]'
              : 'bg-[#ff1744] text-white hover:bg-[#d50000]',
          )}
        >
          {isBlackout
            ? '⚠ Blackout — trading paused'
            : submitting
            ? 'Placing…'
            : `${side === 'buy' ? '▲ Buy' : '▼ Sell'} ${qty || '0'} ${symbol}`}
        </button>

        {/* Result message */}
        {result && (
          <div
            role="alert"
            className={cn(
              'px-3 py-2 rounded text-[11px] font-medium border',
              result.ok
                ? 'bg-[#00e676]/10 border-[#00e676]/20 text-[#00e676]'
                : 'bg-[#ff1744]/10 border-[#ff1744]/20 text-[#ff1744]',
            )}
          >
            {result.msg}
          </div>
        )}
      </form>
    </Panel>
  );
}

// ── Exports ───────────────────────────────────────────────────────────────────

export { OrderEntryFormInner as OrderEntryForm };
export const OrderEntryFormGuarded = withPanelGuard(OrderEntryFormInner, 'Order Entry', 6);
export default OrderEntryFormInner;
