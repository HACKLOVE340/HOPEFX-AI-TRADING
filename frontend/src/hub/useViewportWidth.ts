/**
 * hub/useViewportWidth.ts — the one piece of layout input that needs a browser.
 *
 * `hub/layout.ts` is a pure function so every placement rule is testable
 * without a DOM. That only works if the viewport arrives as a number from
 * outside, which is this hook and nothing else.
 *
 * Server-rendered and test environments have no `window`, so it returns a
 * desktop width rather than throwing or reporting zero. Zero would be worse
 * than a guess: it is below every breakpoint, so the whole plane would collapse
 * to one column for one frame on every mount.
 */

import { useEffect, useState } from 'react';

const ASSUMED = 1280;

function read(): number {
  if (typeof window === 'undefined') return ASSUMED;
  return window.innerWidth || ASSUMED;
}

export function useViewportWidth(): number {
  const [width, setWidth] = useState<number>(read);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onResize = () => setWidth(read());
    window.addEventListener('resize', onResize);
    // Orientation change on mobile fires resize inconsistently across browsers,
    // so it is listened for directly rather than hoped for.
    window.addEventListener('orientationchange', onResize);
    onResize();
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, []);

  return width;
}
