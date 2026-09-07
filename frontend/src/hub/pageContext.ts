/**
 * hub/pageContext.ts — what page the operator is on, and what is wrong with it.
 *
 * Owner request, 2026-09-07: the presence should appear on any screen and be
 * able to diagnose the page around it.
 *
 * ## Derived from the app, not from a list of pages
 *
 * `NAV_ITEMS` is already the single source of truth for routes. A hand-written
 * per-page table here would be correct on the day it was written and wrong by
 * the next release — which is exactly the failure `ai/hub/app_surface.py` was
 * built to avoid on the server side.
 *
 * ## An unknown route is unknown
 *
 * Falling back to the nearest page would have the AI describing a screen the
 * operator is not looking at, confidently. `known: false` with the path in the
 * reason is the only honest answer.
 *
 * ## "Not inspected" is not "healthy"
 *
 * A page with no landmarks reported and a page with nothing wrong look
 * identical, and only one of them is something the AI should say out loud. So
 * `inspected` is separate from `problems`, and an uninspected page says why.
 * That is §22's rule — an unmeasured thing is absent, never zero — applied to
 * the page rather than to a gauge.
 *
 * ## No DOM
 *
 * Landmarks are handed in. The overlay reads them from the document; this
 * decides what they mean, and stays testable without a browser.
 */

export interface NavLike {
  path: string;
  label: string;
  group: string;
  plan?: string;
  featureKey?: string;
}

export interface Landmark {
  id: string;
  /** ARIA role or element kind, as the overlay found it. */
  role: string;
  label: string;
  /** The data behind it is known to be old. */
  stale?: boolean;
  /** What went wrong, in the page's own words. */
  error?: string;
}

export interface PageProblem {
  id: string;
  problem: string;
}

export interface PageContext {
  known: boolean;
  path: string;
  label: string;
  area: string;
  landmarks: Landmark[];
  problems: PageProblem[];
  /** False when no landmarks were supplied, so `problems: []` cannot be read as "healthy". */
  inspected: boolean;
  /** Empty only when the page is known AND inspected AND sound. */
  reason: string;
}

export interface DescribeRequest {
  pathname: string;
  nav: readonly NavLike[];
  landmarks?: readonly Landmark[];
}

/** True when `pathname` is `path` or sits beneath it at a path boundary. */
function matches(pathname: string, path: string): boolean {
  if (pathname === path) return true;
  // The boundary check is what stops `/trademark` matching `/trade`.
  return pathname.startsWith(path.endsWith('/') ? path : `${path}/`);
}

export function describePage(request: DescribeRequest): PageContext {
  const { pathname, nav } = request;
  const landmarks = [...(request.landmarks ?? [])];

  // Longest match wins, so `/trade/history` beats `/trade` for a nested route.
  const item = nav
    .filter((n) => matches(pathname, n.path))
    .sort((a, b) => b.path.length - a.path.length)[0];

  if (item === undefined) {
    return {
      known: false,
      path: pathname,
      label: '',
      area: '',
      landmarks,
      problems: [],
      inspected: landmarks.length > 0,
      reason: `no navigation entry matches ${pathname}, so this page cannot be described without guessing`,
    };
  }

  const problems: PageProblem[] = [];
  for (const landmark of landmarks) {
    if (landmark.error) problems.push({ id: landmark.id, problem: landmark.error });
    else if (landmark.stale) problems.push({ id: landmark.id, problem: 'stale' });
  }

  const inspected = landmarks.length > 0;
  return {
    known: true,
    path: item.path,
    label: item.label,
    area: item.group,
    landmarks,
    problems,
    inspected,
    reason: inspected ? '' : 'no landmarks were reported, so the page was not inspected and is not known to be sound',
  };
}
