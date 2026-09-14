/**
 * Who is responsible for the "where to next" footer on this page.
 *
 * 40 of 74 pages end in nothing — no outbound link in the content area at all,
 * so the reader can only leave by the sidebar. Fixing that by editing 74 files
 * would fix it once: the 75th page would ship as a cul-de-sac like the 40.
 *
 * So `PageSurface`, which already wraps every route, renders a derived footer
 * as a FALLBACK. The problem with a fallback is the 34 pages that already have
 * one — they would get two.
 *
 * This is how they don't. `RelatedPages` claims the slot when it mounts, and
 * the fallback only renders when nothing claimed it. One place decides, the
 * page's own footer always wins, and a page gets onward navigation by existing
 * rather than by someone remembering.
 */

import React, { createContext, useContext, useEffect } from 'react';

interface RelatedSlot {
  /** Called by a real footer to say the page handles this itself. */
  claim: () => void;
  /** Called on unmount, so navigating away frees the slot again. */
  release: () => void;
}

const noop = () => undefined;
const RelatedSlotContext = createContext<RelatedSlot>({ claim: noop, release: noop });

export const RelatedSlotProvider: React.FC<{
  value: RelatedSlot;
  children: React.ReactNode;
}> = ({ value, children }) => (
  <RelatedSlotContext.Provider value={value}>{children}</RelatedSlotContext.Provider>
);

/**
 * Claim the page's footer slot for as long as this component is mounted.
 *
 * A layout effect rather than a passive one: the fallback must not paint and
 * then vanish, which reads as a flash of a wrong footer on every navigation.
 */
export function useClaimRelatedSlot(active = true): void {
  const { claim, release } = useContext(RelatedSlotContext);
  useEffect(() => {
    if (!active) return undefined;
    claim();
    return release;
  }, [active, claim, release]);
}
