# Symbol-switch and missing-trades bugs — 2026-07-27

Two reproducible symptoms the user reported, both root-caused in the frontend
and fixed. Neither needed a market feed to diagnose — they are state/format
bugs, not data-availability issues.

## Symptom B: "trades enter but I can't see them"

**Root cause — a strict-equality symbol filter hid open positions.** The order
API validates every symbol to canonical MT5 form, so a filled trade is stored
and returned as `XAUUSD`. But the symbol-scoped positions panel filtered with:

```ts
positions.filter((p) => p.symbol === symbol)   // symbol = "XAU/USD" (UI form)
```

`"XAUUSD" === "XAU/USD"` is `false`, so **every open position was filtered out**
of the panel next to order entry — the user's real trade simply vanished.
(The unfiltered "All Positions" tab did show it, which is why the trade "was
entering" but wasn't visible where they were looking.)

The same strict `===` hid AI signals for the selected symbol on both trade
pages.

**Fix.** A shared, format-tolerant comparator in `lib/utils.ts`:

```ts
canonicalSymbol(s)  // "XAU/USD" | "xau_usd" | "XAU-USD" → "XAUUSD"
sameSymbol(a, b)    // true when a and b are the same instrument, any formatting
```

Applied everywhere symbol equality decides whether the user sees their own data:
`PositionsTable`, both trade pages' signal panels, and the chart-bot live-tick
matcher (which previously only stripped slashes, not underscores).

**Also:** placing an order now invalidates the `trades` query alongside
`positions`/`account` (order-entry form, voice panel's mutation hook, and
emergency-stop), so a new trade appears immediately instead of after the 30s
poll.

## Symptom A: "I click another symbol but the chart won't change"

**Root cause — the chart never cleared the previous symbol's candles.** Both
chart surfaces (chart-bot `CoreChart` and the Trade page `ChartPanel`) applied
new bars but early-returned when the incoming data was empty or errored:

```ts
if (!bars) return;   // ← leaves the OLD symbol's candles on screen
```

On every symbol switch the data goes momentarily empty while the new request is
in flight, and for any symbol without a configured feed it stays empty (a 503).
So the picker updated, the header showed the new symbol — but the chart kept
painting the previous instrument's candles. On a trading app that is worse than
a blank chart: it shows one instrument's price action under another's name.

**Fix.** When the selected symbol has no bars (loading, error, or no feed), the
chart now clears its candle/volume/MA series so it is honestly empty until the
selected symbol's data arrives. The chart-bot effect also depends on `symbol`
so a switch always re-runs.

This does **not** invent data: symbols with no feed still show an empty chart
and the existing "no data" state. Once `TWELVE_API_KEY` is set (see
AUDIT_2026-07-27.md), switching fully repopulates. The fix guarantees the chart
never misrepresents a stale symbol as the current one.

## Verification

- `canonicalSymbol` / `sameSymbol` unit tests, including the exact position-
  filter scenario that returned 0 before and 2 after — `src/test/utils.test.ts`.
- `tsc --noEmit` clean; `vite build` clean; full vitest suite 1139/1139.

## Files

- `frontend/src/lib/utils.ts` — new `canonicalSymbol` / `sameSymbol`.
- `frontend/src/components/panels/PositionsTable.tsx` — position filter.
- `frontend/src/pages/Trade.tsx`, `Trading.tsx` — signal filters, chart clear.
- `frontend/src/components/panels/OrderEntryForm.tsx` — invalidate `trades`.
- `frontend/src/features/chart-bot/components/CoreChart.tsx` — clear stale bars.
- `frontend/src/features/chart-bot/hooks/useOrchestratorWS.ts` — tick matcher.
- `frontend/src/features/chart-bot/hooks/useChartData.ts` — invalidate `trades`.
