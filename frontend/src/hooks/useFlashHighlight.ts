/**
 * hooks/useFlashHighlight.ts
 *
 * Returns a CSS background color that flashes green on positive change and
 * red on negative change whenever `value` changes, then fades back to
 * transparent. Used for real-time row highlights on price/P&L updates.
 *
 * Usage:
 *   const flash = useFlashHighlight(tick.mid);
 *   <tr style={{ background: flash }}>…</tr>
 */

import { useEffect, useRef, useState } from 'react';

type FlashColor = string; // rgba or 'transparent'

const FLASH_DURATION_MS = 600;

export function useFlashHighlight(value: number | undefined | null): FlashColor {
  const prevRef  = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [color, setColor] = useState<FlashColor>('transparent');

  useEffect(() => {
    if (value == null) return;
    const prev = prevRef.current;
    prevRef.current = value;

    if (prev === null) return; // first render — no flash

    if (value === prev) return;

    const flash = value > prev
      ? 'rgba(0, 230, 118, 0.18)'   // green
      : 'rgba(255, 23,  68, 0.18)'; // red

    setColor(flash);

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setColor('transparent'), FLASH_DURATION_MS);
  }, [value]);

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  return color;
}

/**
 * Batch version — returns a map of id → flash color.
 * Useful for tables where many rows update simultaneously.
 */
export function useFlashMap(
  entries: { id: string; value: number | undefined | null }[],
): Record<string, FlashColor> {
  const prevRef  = useRef<Record<string, number>>({});
  const timersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const [colors, setColors] = useState<Record<string, FlashColor>>({});

  useEffect(() => {
    const updates: Record<string, FlashColor> = {};
    let hasUpdate = false;

    for (const { id, value } of entries) {
      if (value == null) continue;
      const prev = prevRef.current[id];
      prevRef.current[id] = value;

      if (prev === undefined) continue;
      if (value === prev) continue;

      updates[id] = value > prev
        ? 'rgba(0, 230, 118, 0.18)'
        : 'rgba(255, 23,  68, 0.18)';
      hasUpdate = true;

      if (timersRef.current[id]) clearTimeout(timersRef.current[id]);
      timersRef.current[id] = setTimeout(() => {
        setColors((c) => ({ ...c, [id]: 'transparent' }));
      }, FLASH_DURATION_MS);
    }

    if (hasUpdate) {
      setColors((c) => ({ ...c, ...updates }));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(entries.map((e) => ({ id: e.id, v: e.value })))]);

  useEffect(() => () => {
    Object.values(timersRef.current).forEach(clearTimeout);
  }, []);

  return colors;
}
