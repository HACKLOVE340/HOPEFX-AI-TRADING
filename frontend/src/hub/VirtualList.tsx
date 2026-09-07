/**
 * hub/VirtualList.tsx — the consumer `virtualization.ts` never had.
 *
 * §26 asks the plane to render large workspaces efficiently. `windowFor` was
 * built in Phase D1 and decides which slice of a list to draw; measured before
 * this file existed, it was called from no component. `SurfaceView`'s table
 * and headline renderers mapped over every item, so a surface carrying five
 * thousand rows put five thousand nodes in the document.
 *
 * ## Below the threshold this does nothing at all
 *
 * Virtualising a six-row table costs a scroll container, a spacer and two
 * measurements to save nothing, and it breaks find-in-page and
 * copy-the-whole-table for the overwhelmingly common case. So a short list
 * renders whole and this component gets out of the way.
 *
 * ## An unmeasured viewport renders a window, not everything and not nothing
 *
 * `windowFor` already refuses to invent a viewport: it falls back to
 * `UNMEASURED_FALLBACK_ROWS` and says the window was not measured. That is the
 * behaviour kept here — the ref is null on the first render, and rendering the
 * whole list for that frame is exactly the freeze this exists to prevent.
 *
 * ## The count is announced, because the window is a lie by omission
 *
 * A reader — screen reader or human — seeing fifty rows of five thousand has
 * no way to tell the list is longer. §27's rule that colour is never the only
 * indicator has the same shape here: the scrollbar is not an indicator
 * everybody has. So the row count is stated, and the container carries
 * `aria-rowcount` with the real total rather than the rendered one.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import { textPalette } from './a11yContrast';
import { windowFor } from './virtualization';

const MUTED = textPalette('standard').muted;

/**
 * Lists shorter than this render whole.
 *
 * Chosen against what the hub actually shows: the largest fixed table in
 * `surfaceData.ts` is well under this, so no surface on screen today pays for
 * a scroll container it does not need.
 */
export const VIRTUALIZE_ABOVE = 60;

export interface VirtualListProps<T> {
  items: readonly T[];
  /** Row height in CSS pixels. Uniform — `windowFor` takes one height. */
  itemHeight: number;
  /** Height of the scroll container. */
  height: number;
  renderItem: (item: T, index: number) => React.ReactNode;
  keyFor: (item: T, index: number) => string;
  /** Named for the reader, e.g. "rows" or "headlines". */
  noun?: string;
  label?: string;
}

export function VirtualList<T>({
  items,
  itemHeight,
  height,
  renderItem,
  keyFor,
  noun = 'rows',
  label,
}: VirtualListProps<T>): React.ReactElement {
  const [scrollTop, setScrollTop] = useState(0);
  const [measuredHeight, setMeasuredHeight] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const onScroll = useCallback((event: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
  }, []);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const box = element.getBoundingClientRect();
    // Zero means not laid out. `windowFor` treats an unmeasured viewport as
    // unmeasured rather than as a zero-height one, so pass null and let it.
    setMeasuredHeight(box.height > 0 ? box.height : null);
  }, [height, items.length]);

  const view = windowFor({
    count: items.length,
    itemHeight,
    viewportHeight: measuredHeight ?? height,
    scrollTop,
  });

  const slice = items.slice(view.start, view.end);

  return (
    <div
      ref={ref}
      onScroll={onScroll}
      role="group"
      aria-label={label}
      // The real total, not the rendered one. A reader given the window's
      // length would believe the list is fifty items long.
      aria-rowcount={items.length}
      style={{ height, overflowY: 'auto', overflowX: 'hidden' }}
    >
      <div style={{ height: view.totalHeight, position: 'relative' }}>
        <div style={{ position: 'absolute', top: view.offsetTop, left: 0, right: 0 }}>
          {slice.map((item, i) => (
            <div key={keyFor(item, view.start + i)} style={{ height: itemHeight }}>
              {renderItem(item, view.start + i)}
            </div>
          ))}
        </div>
      </div>
      <p
        // Stated, not implied by a scrollbar. See the module docstring.
        // The colour comes from the §27 palette rather than a literal: every
        // token there is re-measured against every surface on each test run,
        // and a hex typed here is a colour nobody measured.
        style={{ margin: 0, position: 'sticky', bottom: 0, fontSize: 10.5, color: MUTED }}
      >
        {`${items.length} ${noun}`}
        {view.measured ? '' : ` · window not measured: ${view.reason}`}
      </p>
    </div>
  );
}
