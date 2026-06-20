/**
 * indicators.ts
 * Pure client-side technical-indicator math for the chart overlays.
 * All functions take ascending-time OHLCV bars and return lightweight-charts
 * LineData[] (or grouped series for Bollinger Bands). No side effects.
 */

import type { LineData, UTCTimestamp } from 'lightweight-charts';
import type { OHLCVBar } from '../types';

function toTime(bar: OHLCVBar): UTCTimestamp {
  const ts = bar.time;
  return (ts > 1e10 ? Math.floor(ts / 1000) : Math.floor(ts)) as UTCTimestamp;
}

/** Exponential moving average, seeded with the SMA of the first `period` closes. */
export function ema(bars: OHLCVBar[], period: number): LineData[] {
  if (bars.length < period || period <= 0) return [];
  const k = 2 / (period + 1);
  const out: LineData[] = [];
  let prev = 0;
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    const c = bars[i].close;
    if (i < period) {
      sum += c;
      if (i === period - 1) {
        prev = sum / period;
        out.push({ time: toTime(bars[i]), value: prev });
      }
      continue;
    }
    prev = c * k + prev * (1 - k);
    out.push({ time: toTime(bars[i]), value: prev });
  }
  return out;
}

/** Bollinger Bands (SMA ± mult·σ) over `period` closes. */
export function bollinger(
  bars: OHLCVBar[],
  period = 20,
  mult = 2,
): { upper: LineData[]; middle: LineData[]; lower: LineData[] } {
  const upper: LineData[] = [];
  const middle: LineData[] = [];
  const lower: LineData[] = [];
  if (bars.length < period || period <= 0) return { upper, middle, lower };
  for (let i = period - 1; i < bars.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += bars[j].close;
    const mean = sum / period;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const d = bars[j].close - mean;
      variance += d * d;
    }
    const sd = Math.sqrt(variance / period);
    const t = toTime(bars[i]);
    middle.push({ time: t, value: mean });
    upper.push({ time: t, value: mean + mult * sd });
    lower.push({ time: t, value: mean - mult * sd });
  }
  return { upper, middle, lower };
}

/** Wilder's Relative Strength Index (0–100). */
export function rsi(bars: OHLCVBar[], period = 14): LineData[] {
  const out: LineData[] = [];
  if (bars.length <= period || period <= 0) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const ch = bars[i].close - bars[i - 1].close;
    if (ch >= 0) gain += ch;
    else loss -= ch;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  const rsiVal = (ag: number, al: number): number => (al === 0 ? 100 : 100 - 100 / (1 + ag / al));
  out.push({ time: toTime(bars[period]), value: rsiVal(avgGain, avgLoss) });
  for (let i = period + 1; i < bars.length; i++) {
    const ch = bars[i].close - bars[i - 1].close;
    const g = ch > 0 ? ch : 0;
    const l = ch < 0 ? -ch : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    out.push({ time: toTime(bars[i]), value: rsiVal(avgGain, avgLoss) });
  }
  return out;
}
