/**
 * Risk/Reward Calculator
 *
 * Wires to:
 *   GET /api/risk/live-price/:symbol   — live mid price for entry auto-fill
 *   GET /api/risk/calculator/history   — saved calculation history
 *   POST /api/risk/calculator/history  — save a calculation
 *   DELETE /api/risk/calculator/history/:id — delete saved calc
 */

import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader, EmptyState } from '../components';
import { useStore, selectAccount, selectFeedLive } from '../store';
import { riskCalcApi } from '../hooks/useApi';
import { useDataFreshness } from '../hooks/useDataFreshness';
import { StaleDataNotice } from '../components/ui/StaleDataNotice';
import {
  useInstrumentSpecs,
  BUILTIN_SPECS,
  type InstrumentSpec,
} from '../hooks/useInstrumentSpecs';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface CalcState {
  symbol: string;
  accountBalance: string;
  riskPercent: string;
  entryPrice: string;
  stopLoss: string;
  takeProfit: string;
  leverage: string;
}

export interface CalcResult {
  rrRatio: number;
  riskAmount: number;
  rewardAmount: number;
  pipValue: number;
  stopPips: number;
  tpPips: number;
  lotSize: number;
  marginRequired: number;
  maxLoss: number;
  breakEvenWinRate: number;
}

interface SavedCalc {
  id: string;
  symbol: string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  lot_size: number;
  rr_ratio: number;
  risk_amount: number;
  reward_amount: number;
  saved_at: string;
  label?: string;
}

// ─── Symbol config ────────────────────────────────────────────────────────────

/**
 * `quoteIsUsd` says whether a pip is already worth its face value in dollars.
 *
 * A pip is worth `pipSize * contractSize` **in the quote currency**. For every
 * pair here except USD/JPY the quote currency is USD, so that figure is the
 * dollar value directly. USD/JPY is quoted in yen: one pip on a standard lot is
 * ¥1,000, which at ~150 ¥/$ is about $6.67 — not $1,000.
 *
 * Treating it as dollars overstated pip value by roughly 150×, and since lot
 * size is derived by dividing risk by it, the suggested position was ~150×
 * too small. On a position-sizing tool that is the whole output.
 */

// ─── Calculation logic ────────────────────────────────────────────────────────

export function calculate(
  state: CalcState,
  specs: Record<string, InstrumentSpec> = BUILTIN_SPECS,
): CalcResult | null {
  const balance  = parseFloat(state.accountBalance);
  const riskPct  = parseFloat(state.riskPercent) / 100;
  const entry    = parseFloat(state.entryPrice);
  const sl       = parseFloat(state.stopLoss);
  const tp       = parseFloat(state.takeProfit);
  const leverage = parseFloat(state.leverage) || 1;
  const sym      = specs[state.symbol];

  if (!sym || isNaN(balance) || isNaN(entry) || isNaN(sl) || isNaN(tp) || entry <= 0) return null;
  if (sl === entry || tp === entry) return null;

  const stopDist = Math.abs(entry - sl);
  const tpDist   = Math.abs(tp - entry);
  if (stopDist === 0) return null;

  const rrRatio  = tpDist / stopDist;
  const stopPips = stopDist / sym.pipSize;
  const tpPips   = tpDist  / sym.pipSize;

  const riskAmount   = balance * riskPct;
  const rewardAmount = riskAmount * rrRatio;

  // Pip value per lot, converted to USD. `pipSize * contractSize` is denominated
  // in the QUOTE currency; for a USD-quoted pair that is already dollars. For
  // USD/JPY the quote is yen and the price IS the USD/JPY rate, so dividing by
  // it converts ¥ to $.
  const pipValueQuoteCcy = sym.pipSize * sym.contractSize;
  const pipValuePerLot   = sym.quoteIsUsd ? pipValueQuoteCcy : pipValueQuoteCcy / entry;
  const lotSize        = stopPips > 0 && pipValuePerLot > 0 ? riskAmount / (stopPips * pipValuePerLot) : 0;
  const pipValue       = pipValuePerLot * lotSize;

  const notional       = entry * sym.contractSize * lotSize;
  const marginRequired = leverage > 0 ? notional / leverage : 0;
  const maxLoss        = stopPips * pipValue;

  // break-even win rate = 1 / (1 + R:R)
  const breakEvenWinRate = (1 / (1 + rrRatio)) * 100;

  return {
    rrRatio,
    riskAmount,
    rewardAmount,
    pipValue,
    stopPips,
    tpPips,
    lotSize,
    marginRequired,
    maxLoss,
    breakEvenWinRate,
  };
}

/**
 * Why `calculate` returned nothing.
 *
 * `calculate` has six independent `return null` branches and the page rendered
 * one sentence for all of them: "Fill in all fields to see results." For four of
 * those branches that sentence is wrong — the fields *are* filled — so a user
 * who typed a stop loss equal to their entry, or picked an instrument the server
 * catalogue does not carry, saw a blank Results panel and an instruction they
 * had already followed. This is the same shape as the drift banner reading
 * "Stable" when no statistics existed: absence rendered as a tidy answer instead
 * of a reason.
 *
 * Returns `null` when a result is computable, so `explainMissingResult(...) ===
 * null` and `calculate(...) !== null` must always agree — pinned by a test.
 */
export function explainMissingResult(
  state: CalcState,
  specs: Record<string, InstrumentSpec> = BUILTIN_SPECS,
): string | null {
  if (!specs[state.symbol]) {
    return `No contract specification for ${state.symbol}. Pick an instrument from the list — sizing needs its pip and lot size.`;
  }

  const fields: Array<[keyof CalcState, string]> = [
    ['accountBalance', 'account balance'],
    ['entryPrice',     'entry price'],
    ['stopLoss',       'stop loss'],
    ['takeProfit',     'take profit'],
  ];
  const missing = fields
    .filter(([key]) => !Number.isFinite(parseFloat(state[key])))
    .map(([, label]) => label);
  if (missing.length > 0) {
    return `Enter the ${missing.join(', ')} to see results.`;
  }

  const entry = parseFloat(state.entryPrice);
  if (entry <= 0) return 'Entry price must be greater than zero.';
  if (parseFloat(state.stopLoss) === entry) {
    return 'Stop loss is the same as the entry price, so the trade risks nothing and cannot be sized.';
  }
  if (parseFloat(state.takeProfit) === entry) {
    return 'Take profit is the same as the entry price, so there is no reward to compare the risk against.';
  }
  return null;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

const Label: React.FC<{ text: string }> = ({ text }) => (
  <div style={s.label}>{text}</div>
);

const Input: React.FC<{
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  prefix?: string;
  suffix?: string;
}> = ({ value, onChange, placeholder, prefix, suffix }) => (
  <div style={s.inputWrap}>
    {prefix && <span style={s.inputAddon}>{prefix}</span>}
    <input
      style={s.input}
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
    />
    {suffix && <span style={s.inputAddon}>{suffix}</span>}
  </div>
);

const ResultRow: React.FC<{ label: string; value: string; highlight?: boolean }> = ({
  label, value, highlight,
}) => (
  <div style={{ ...s.resultRow, ...(highlight ? s.resultRowHighlight : {}) }}>
    <span style={s.resultLabel}>{label}</span>
    <span style={{ ...s.resultValue, ...(highlight ? { color: '#f8fafc', fontWeight: 700 } : {}) }}>
      {value}
    </span>
  </div>
);

// ─── Main component ───────────────────────────────────────────────────────────

const RiskCalculator: React.FC = () => {
  const account = useStore(selectAccount);
  const prices  = useStore((s) => s.prices);
  const feedLive = useStore(selectFeedLive);
  // F5-01: pip and contract sizes come from the server's instrument catalogue,
  // which is what the backtester and the order path use. The built-in table is
  // still the offline default — a backend test fails CI if it disagrees with the
  // server's — but which one is in use is rendered rather than swallowed,
  // because this page's whole output is derived from these numbers (F1-01).
  const instruments = useInstrumentSpecs();

  const [state, setState] = useState<CalcState>({
    symbol:         'XAU/USD',
    accountBalance: '10000',
    riskPercent:    '1',
    entryPrice:     '',
    stopLoss:       '',
    takeProfit:     '',
    leverage:       '100',
  });

  const [livePrice, setLivePrice]   = useState<number | null>(null);
  const [livePriceAge, setLivePriceAge] = useState<number>(0);
  // F1-01: the price fetch below fell back to store prices invisibly, while
  // that price is the input to position sizing.
  const freshness = useDataFreshness('the live price');
  const [history, setHistory]       = useState<SavedCalc[]>([]);
  const [saving, setSaving]         = useState(false);
  const [saveMsg, setSaveMsg]       = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const [calcLabel, setCalcLabel]   = useState('');
  const priceTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const ageTimerRef   = useRef<ReturnType<typeof setInterval> | null>(null);

  // Auto-populate balance from live account data
  useEffect(() => {
    const bal = account?.balance;
    if (bal != null && Number.isFinite(bal) && bal > 0) {
      setState((prev) => ({ ...prev, accountBalance: bal.toFixed(2) }));
    }
  }, [account?.balance]);

  // Live price feed: poll /api/risk/live-price/:symbol every 5s
  useEffect(() => {
    let mounted = true;
    const fetchPrice = async () => {
      try {
        const res = await riskCalcApi.livePrice(state.symbol.replace('/', '_'));
        const d = res.data as { mid?: number; price?: number; bid?: number; ask?: number };
        const price = d.mid ?? d.price ?? (d.bid && d.ask ? (d.bid + d.ask) / 2 : null);
        if (price && mounted) {
          setLivePrice(price);
          setLivePriceAge(0);
          // Only auto-fill entry if user hasn't typed one
          setState(prev => prev.entryPrice === '' ? { ...prev, entryPrice: price.toFixed(price < 10 ? 5 : 2) } : prev);
        }
      } catch {
        // F1-01: this silently fell back to store prices while the page went on
        // computing a position size from them. The number the trader sizes
        // against must never look current when the fetch failed.
        freshness.markFailed('the live price');
      }
    };
    fetchPrice();
    priceTimerRef.current = setInterval(fetchPrice, 5000);
    ageTimerRef.current   = setInterval(() => setLivePriceAge(a => a + 1), 1000);
    return () => {
      mounted = false;
      if (priceTimerRef.current) clearInterval(priceTimerRef.current);
      if (ageTimerRef.current)   clearInterval(ageTimerRef.current);
    };
  }, [state.symbol]);

  // Fallback: use store prices if API unavailable.
  //
  // F1-02: those store prices come off the WebSocket, so when the feed stalls
  // this fallback quietly seeds the entry price with a figure that stopped
  // moving — and the entry price is what every number on this page is computed
  // from. The HTTP path already says when it failed; this says when the thing
  // it falls back to is no longer live.
  useEffect(() => {
    if (livePrice) return;
    if (!feedLive && prices[state.symbol]) freshness.markFailed('a live price');
  }, [feedLive, prices, state.symbol, livePrice, freshness]);

  useEffect(() => {
    if (livePrice) return;
    const tick = prices[state.symbol];
    if (tick?.mid && tick.mid > 0) {
      setState((prev) => prev.entryPrice === '' ? { ...prev, entryPrice: tick.mid.toFixed(2) } : prev);
    }
  }, [state.symbol, prices, livePrice]);

  // Load history
  const loadHistory = useCallback(async () => {
    try {
      const res = await riskCalcApi.history();
      const d = res.data as SavedCalc[] | { history?: SavedCalc[] };
      setHistory(Array.isArray(d) ? d : (d.history ?? []));
    } catch { setHistory([]); }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const set = useCallback((key: keyof CalcState) => (v: string) =>
    setState((prev) => ({ ...prev, [key]: v })), []);

  const result = calculate(state, instruments.specs);

  const handleSave = async () => {
    if (!result) return;
    setSaving(true);
    setSaveMsg('');
    try {
      await riskCalcApi.saveCalc({
        symbol:       state.symbol,
        entry_price:  parseFloat(state.entryPrice),
        stop_loss:    parseFloat(state.stopLoss),
        take_profit:  parseFloat(state.takeProfit),
        lot_size:     result.lotSize,
        rr_ratio:     result.rrRatio,
        risk_amount:  result.riskAmount,
        reward_amount: result.rewardAmount,
        label:        calcLabel || undefined,
      });
      setSaveMsg('✓ Saved');
      setCalcLabel('');
      await loadHistory();
    } catch { setSaveMsg('⚠ Save failed'); }
    finally { setSaving(false); setTimeout(() => setSaveMsg(''), 3000); }
  };

  const handleDeleteHistory = async (id: string) => {
    try {
      await riskCalcApi.deleteCalc(id);
      setHistory(prev => prev.filter(h => h.id !== id));
    } catch { /* non-fatal */ }
  };

  const loadFromHistory = (h: SavedCalc) => {
    setState(prev => ({
      ...prev,
      symbol:      h.symbol,
      entryPrice:  h.entry_price.toString(),
      stopLoss:    h.stop_loss.toString(),
      takeProfit:  h.take_profit.toString(),
    }));
    setShowHistory(false);
  };

  const rrColor =
    !result          ? '#64748b' :
    result.rrRatio >= 2 ? '#4ade80' :
    result.rrRatio >= 1 ? '#facc15' :
    '#f87171';

  return (
    <div className="page-content">
      <PageHeader
        title="Risk / Reward Calculator"
        icon="🧮"
        subtitle="Calculate position size, pip value, and margin before every trade."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Trade', href: '/trade' },
          { label: 'Risk Calculator' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {/* Live price indicator. The green dot must not appear while the
                fetch is failing — the price feeding position sizing would then
                look current when it is not (F1-01). */}
            {livePrice && !freshness.failed && (
              <div style={{ fontSize: 11, color: livePriceAge < 10 ? '#22c55e' : '#f59e0b', fontFamily: 'monospace', padding: '4px 10px', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 6 }}>
                ● {state.symbol} {livePrice.toFixed(livePrice < 10 ? 5 : 2)} <span style={{ color: '#475569' }}>{livePriceAge}s</span>
              </div>
            )}
            <button onClick={() => setShowHistory(h => !h)}
              style={{ padding: '6px 12px', background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.35)', borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
              📋 History {history.length > 0 ? `(${history.length})` : ''}
            </button>
            <Link to="/trade" style={{ padding: '6px 12px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              ⚡ Trade
            </Link>
            <Link to="/journal" style={{ padding: '6px 12px', background: 'rgba(74,222,128,0.12)', border: '1px solid rgba(74,222,128,0.35)', borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              📓 Journal
            </Link>
            <Link to="/prop-firm" style={{ padding: '6px 12px', background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.35)', borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              🛡 Prop Firm
            </Link>
          </div>
        }
      />

      <StaleDataNotice failed={freshness.failed} what={freshness.what} />
      {instruments.source === 'builtin' && !instruments.loading && (
        <div
          role="status"
          aria-live="polite"
          style={{
            display: 'flex', alignItems: 'flex-start', gap: 8,
            padding: '8px 12px', borderRadius: 6, marginBottom: 12,
            background: 'rgba(255,184,0,0.1)', border: '1px solid rgba(255,184,0,0.3)',
            fontSize: 12, color: '#ffb800',
          }}
        >
          <span aria-hidden="true">⚠</span>
          <span>
            Couldn&apos;t reach the instrument catalogue — sizing from the
            built-in specification. It is checked against the server on every
            build, so the numbers should agree, but they have not been confirmed
            for this session.
          </span>
        </div>
      )}

      <div style={s.grid}>
        {/* ── Inputs ── */}
        <div style={s.card}>
          <div style={s.cardTitle}>Trade Setup</div>

          <Label text="Symbol" />
          <select
            style={s.select}
            value={state.symbol}
            onChange={(e) => setState((p) => ({ ...p, symbol: e.target.value }))}
          >
            {Object.entries(instruments.specs).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>

          <Label text="Account Balance" />
          <Input value={state.accountBalance} onChange={set('accountBalance')} prefix="$" placeholder="10000" />

          <Label text="Risk Per Trade" />
          <Input value={state.riskPercent} onChange={set('riskPercent')} suffix="%" placeholder="1" />

          <Label text="Leverage" />
          <Input value={state.leverage} onChange={set('leverage')} suffix=":1" placeholder="100" />

          <div style={s.divider} />

          <Label text="Entry Price" />
          <Input value={state.entryPrice} onChange={set('entryPrice')} placeholder="2350.00" />

          <Label text="Stop Loss" />
          <Input value={state.stopLoss} onChange={set('stopLoss')} placeholder="2340.00" />

          <Label text="Take Profit" />
          <Input value={state.takeProfit} onChange={set('takeProfit')} placeholder="2380.00" />
        </div>

        {/* ── Results ── */}
        <div style={s.card}>
          <div style={s.cardTitle}>Results</div>

          {/* R:R ratio — big display */}
          <div style={s.rrDisplay}>
            <div style={s.rrLabel}>Risk : Reward</div>
            <div style={{ ...s.rrValue, color: rrColor }}>
              {result ? `1 : ${result.rrRatio.toFixed(2)}` : '—'}
            </div>
            {result && (
              <div style={s.rrSub}>
                Break-even win rate: {result.breakEvenWinRate.toFixed(1)}%
              </div>
            )}
          </div>

          <div style={s.divider} />

          {result ? (
            <>
              <ResultRow label="Risk Amount"      value={`$${result.riskAmount.toFixed(2)}`}   highlight />
              <ResultRow label="Reward Amount"    value={`$${result.rewardAmount.toFixed(2)}`} highlight />
              <ResultRow label="Stop Loss Pips"   value={result.stopPips.toFixed(1)} />
              <ResultRow label="Take Profit Pips" value={result.tpPips.toFixed(1)} />
              <ResultRow label="Lot Size"         value={result.lotSize.toFixed(4)} />
              <ResultRow label="Pip Value"        value={`$${result.pipValue.toFixed(4)}`} />
              <ResultRow label="Margin Required"  value={`$${result.marginRequired.toFixed(2)}`} />
              <ResultRow label="Max Loss"         value={`$${result.maxLoss.toFixed(2)}`} />
            </>
          ) : (
            <div style={s.placeholder} role="status" aria-live="polite">
              {explainMissingResult(state, instruments.specs) ?? 'Fill in all fields to see results.'}
            </div>
          )}
        </div>

        {/* ── Visual bar ── */}
        <div style={s.card}>
          <div style={s.cardTitle}>Trade Visualizer</div>
          {result ? (
            <TradeVisualizer
              entry={parseFloat(state.entryPrice)}
              sl={parseFloat(state.stopLoss)}
              tp={parseFloat(state.takeProfit)}
            />
          ) : (
            <div style={s.placeholder}>Enter entry, stop loss, and take profit to visualize.</div>
          )}

          {result && (
            <>
              <Link
                to="/trade"
                state={{
                  signal: {
                    symbol: state.symbol,
                    direction: parseFloat(state.takeProfit) > parseFloat(state.entryPrice) ? 'BUY' : 'SELL',
                    // Entry price and the sized position carry across too. Without
                    // them the trade ticket kept the stop and target that were
                    // calculated against THIS entry, then filled at a different
                    // one — so the risk the user just sized disappeared silently.
                    entry_price: parseFloat(state.entryPrice),
                    quantity: result.lotSize,
                    stop_loss: parseFloat(state.stopLoss),
                    take_profit: parseFloat(state.takeProfit),
                  }
                }}
                style={{
                  display: 'block', width: '100%', padding: '10px 0', borderRadius: 8,
                  background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)',
                  color: '#60a5fa', fontSize: 14, fontWeight: 700, textDecoration: 'none',
                  textAlign: 'center', marginBottom: 10, boxSizing: 'border-box',
                }}
              >
                ⚡ Apply to Trade — {state.symbol}
              </Link>
              {/* Save calculation */}
              <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
                <input
                  value={calcLabel}
                  onChange={e => setCalcLabel(e.target.value)}
                  placeholder="Label (optional)"
                  style={{ flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#f8fafc', fontSize: 12, padding: '6px 10px', outline: 'none' }}
                />
                <button onClick={() => void handleSave()} disabled={saving}
                  style={{ padding: '6px 14px', background: '#8b5cf6', color: '#fff', border: 'none', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', opacity: saving ? 0.6 : 1 }}>
                  {saving ? '…' : '💾 Save'}
                </button>
                {saveMsg && <span style={{ fontSize: 11, color: saveMsg.startsWith('✓') ? '#22c55e' : '#f87171', alignSelf: 'center' }}>{saveMsg}</span>}
              </div>
            </>
          )}

          <div style={s.divider} />
          <div style={s.cardTitle}>Quick Tips</div>
          <div style={s.tipList}>
            <div style={s.tip}>✅ Minimum R:R of 1:2 recommended</div>
            <div style={s.tip}>✅ Risk no more than 1–2% per trade</div>
            <div style={s.tip}>✅ At 1:2 R:R you only need 34% win rate to be profitable</div>
            <div style={s.tip}>⚠️ Higher leverage = higher margin efficiency but more risk</div>
          </div>
        </div>
      </div>

      {/* ── Saved history panel ── */}
      {showHistory && (
        <div style={{ marginTop: 24, background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={s.cardTitle}>Saved Calculations</div>
            <button onClick={() => setShowHistory(false)} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 16 }}>✕</button>
          </div>
          {history.length === 0 ? (
            <EmptyState
              icon="🧮"
              title="No saved calculations yet"
              description="Run a calculation above and save it to build your history."
              compact
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {history.map(h => (
                <div key={h.id} style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 2 }}>
                      {h.label || h.symbol} · 1:{Number.isFinite(h.rr_ratio) ? h.rr_ratio.toFixed(2) : '—'} R:R
                    </div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>
                      Entry {h.entry_price} · SL {h.stop_loss} · TP {h.take_profit} · {h.lot_size.toFixed(4)} lots
                    </div>
                    <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
                      {new Date(h.saved_at).toLocaleString()}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button onClick={() => loadFromHistory(h)}
                      style={{ padding: '4px 10px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 5, color: '#60a5fa', fontSize: 11, cursor: 'pointer' }}>
                      Load
                    </button>
                    <button onClick={() => void handleDeleteHistory(h.id)}
                      style={{ padding: '4px 10px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 5, color: '#f87171', fontSize: 11, cursor: 'pointer' }}>
                      ✕
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ─── Trade Visualizer ─────────────────────────────────────────────────────────

const TradeVisualizer: React.FC<{ entry: number; sl: number; tp: number }> = ({
  entry, sl, tp,
}) => {
  const isLong = tp > entry;
  const low    = Math.min(sl, entry, tp);
  const high   = Math.max(sl, entry, tp);
  const range  = high - low || 1;

  const pct = (v: number) => ((v - low) / range) * 100;

  const levels = [
    { label: isLong ? 'Take Profit' : 'Stop Loss', price: tp,    color: isLong ? '#4ade80' : '#f87171' },
    { label: 'Entry',                               price: entry, color: '#60a5fa' },
    { label: isLong ? 'Stop Loss' : 'Take Profit', price: sl,    color: isLong ? '#f87171' : '#4ade80' },
  ].sort((a, b) => b.price - a.price);

  return (
    <div style={s.vizWrap}>
      <div style={s.vizBar}>
        {/* TP zone */}
        <div style={{
          ...s.vizZone,
          bottom: `${pct(Math.min(entry, tp))}%`,
          height: `${Math.abs(pct(tp) - pct(entry))}%`,
          background: isLong ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)',
          borderLeft: `3px solid ${isLong ? '#4ade80' : '#f87171'}`,
        }} />
        {/* SL zone */}
        <div style={{
          ...s.vizZone,
          bottom: `${pct(Math.min(entry, sl))}%`,
          height: `${Math.abs(pct(sl) - pct(entry))}%`,
          background: isLong ? 'rgba(248,113,113,0.15)' : 'rgba(74,222,128,0.15)',
          borderLeft: `3px solid ${isLong ? '#f87171' : '#4ade80'}`,
        }} />
        {/* Price lines */}
        {levels.map((l) => (
          <div key={l.label} style={{ ...s.vizLine, bottom: `${pct(l.price)}%`, borderTopColor: l.color }}>
            <span style={{ ...s.vizLineLabel, color: l.color }}>{l.label}</span>
            <span style={{ ...s.vizLinePrice, color: l.color }}>{l.price.toFixed(2)}</span>
          </div>
        ))}
      </div>

      {/* Cross-links */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: '16px 0', borderTop: '1px solid #1e293b', marginTop: 8 }}>
        <Link to="/prop-firm" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🛡️ Prop Firm</Link>
        <Link to="/journal" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📓 Trade Journal</Link>
        <Link to="/trade" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>⚡ Trade</Link>
        <Link to="/portfolio" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>💼 Portfolio</Link>
        <Link to="/performance" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>📊 Performance</Link>
      </div>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    background: '#0f172a',
    color: '#f8fafc',
    fontFamily: "'Inter', system-ui, sans-serif",
    padding: '24px',
  },
  header: { marginBottom: 32 },
  title: { fontSize: 28, fontWeight: 700, margin: 0, color: '#f8fafc' },
  subtitle: { fontSize: 14, color: '#94a3b8', marginTop: 8 },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
    gap: 24,
  },
  card: {
    background: '#1e293b',
    borderRadius: 12,
    padding: 24,
    border: '1px solid #334155',
  },
  cardTitle: {
    fontSize: 14,
    fontWeight: 600,
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    marginBottom: 16,
  },
  label: { fontSize: 13, color: '#94a3b8', marginBottom: 6, marginTop: 12 },
  inputWrap: {
    display: 'flex',
    alignItems: 'center',
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 8,
    overflow: 'hidden',
  },
  input: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    outline: 'none',
    color: '#f8fafc',
    fontSize: 15,
    padding: '10px 12px',
  },
  inputAddon: {
    padding: '0 10px',
    color: '#64748b',
    fontSize: 13,
    background: '#1e293b',
    borderRight: '1px solid #334155',
    height: '100%',
    display: 'flex',
    alignItems: 'center',
  },
  select: {
    width: '100%',
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 8,
    color: '#f8fafc',
    fontSize: 15,
    padding: '10px 12px',
    outline: 'none',
  },
  divider: { height: 1, background: '#334155', margin: '20px 0' },
  rrDisplay: { textAlign: 'center', padding: '16px 0' },
  rrLabel: { fontSize: 13, color: '#94a3b8', marginBottom: 8 },
  rrValue: { fontSize: 48, fontWeight: 800, lineHeight: 1 },
  rrSub: { fontSize: 13, color: '#64748b', marginTop: 8 },
  resultRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 0',
    borderBottom: '1px solid #1e293b',
  },
  resultRowHighlight: { background: '#1e293b', borderRadius: 6, padding: '8px 12px', marginBottom: 4 },
  resultLabel: { fontSize: 13, color: '#94a3b8' },
  resultValue: { fontSize: 14, color: '#cbd5e1', fontWeight: 500 },
  placeholder: { color: '#475569', fontSize: 14, textAlign: 'center', padding: '32px 0' },
  vizWrap: { padding: '16px 0' },
  vizBar: {
    position: 'relative',
    height: 240,
    background: '#0f172a',
    borderRadius: 8,
    border: '1px solid #334155',
    overflow: 'hidden',
  },
  vizZone: { position: 'absolute', left: 0, right: 0 },
  vizLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    borderTop: '2px dashed',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    padding: '0 12px 4px',
  },
  vizLineLabel: { fontSize: 11, fontWeight: 600 },
  vizLinePrice: { fontSize: 11 },
  tipList: { display: 'flex', flexDirection: 'column', gap: 8 },
  tip: { fontSize: 13, color: '#94a3b8', lineHeight: 1.5 },
};

export default RiskCalculator;
