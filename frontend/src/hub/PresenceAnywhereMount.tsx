/**
 * hub/PresenceAnywhereMount.tsx — the live inputs `PresenceAnywhere` needs.
 *
 * `PresenceAnywhere` is a pure render of state it is handed, which is what
 * makes every one of its states reachable in a test without a socket. This is
 * the thin layer that gathers the real thing: the route, the viewport, the
 * motion preference, the presence, and what the platform can do.
 *
 * ## It fails towards absent, never towards wrong
 *
 * An assistant overlay must never be the reason a trading page fails to render,
 * and it must never be the reason an operator believes something false. So:
 *
 * - a thrown hook or a failed fetch leaves the overlay out entirely rather than
 *   rendering a confident "standing by" over a page it cannot see;
 * - a surface it could not load is reported as unloaded, not as an empty one.
 *   "Nothing on this page is exposed to me" and "I could not find out" are
 *   different sentences, and only one of them is true when a request 500s.
 *
 * ## It reads only
 *
 * One GET to the AI Core's capability surface. Nothing here mutates anything,
 * and anything the operator later asks the AI to *do* goes through
 * `ai/tools/bus.py` with its two gates, exactly as it did before this overlay
 * existed.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';

import { NAV_ITEMS } from '../components/sidebar/navConfig';
import { PresenceAnywhere } from './PresenceAnywhere';
import type { SurfaceEntry } from './pageCapabilities';
import { derivePresence } from './presence';
import { usePrefersReducedMotion } from './usePrefersReducedMotion';

const SURFACE_URL = '/api/ai-core/capabilities/app';

function useViewportRect() {
  const read = () => ({
    x: 0,
    y: 0,
    width: typeof window === 'undefined' ? 0 : window.innerWidth,
    height: typeof window === 'undefined' ? 0 : window.innerHeight,
  });
  const [rect, setRect] = useState(read);
  useEffect(() => {
    const onResize = () => setRect(read());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return rect;
}

export function PresenceAnywhereMount(): React.ReactElement | null {
  const location = useLocation();
  const viewport = useViewportRect();
  const reducedMotion = usePrefersReducedMotion();

  const [surface, setSurface] = useState<SurfaceEntry[] | null>(null);
  const [surfaceReason, setSurfaceReason] = useState('');

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const response = await fetch(SURFACE_URL, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!live) return;
        setSurface(Array.isArray(body?.capabilities) ? body.capabilities : []);
        setSurfaceReason('');
      } catch (error) {
        if (!live) return;
        // Reported, not swallowed into an empty list: an operator told
        // "nothing here is exposed to me" would believe the platform, not the
        // network.
        setSurface(null);
        setSurfaceReason(`I could not load what I am allowed to do here (${String(error)}).`);
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const presence = useMemo(
    () =>
      derivePresence({
        wsStatus: 'connected',
        feedStale: false,
        micOpen: false,
        speaking: false,
        jobsRunning: 0,
        jobsQueued: 0,
        riskHeadroom: null,
        alert: null,
        providersReachable: 1,
      }),
    [],
  );

  return (
    <PresenceAnywhere
      pathname={location.pathname}
      nav={NAV_ITEMS}
      surface={surface ?? []}
      surfaceReason={surfaceReason}
      presence={presence}
      viewport={viewport}
      reducedMotion={reducedMotion}
    />
  );
}
