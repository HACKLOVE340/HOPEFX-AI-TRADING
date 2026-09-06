/**
 * hub/contracts.shared.ts — the browser half of `ai/hub/contracts.py`.
 *
 * The Python module is the authority: it is where the invariants are enforced,
 * because a request rejected at the server boundary is rejected for every
 * client. This mirrors the vocabulary so the frontend can name a surface kind
 * without a round trip, and so a typo is a TypeScript error rather than an
 * empty panel.
 *
 * Kept deliberately small. Duplicating the *rules* here would give two places
 * for them to drift; duplicating the *vocabulary* is what lets the workspace
 * engine run in a test with no server at all.
 */

export const SURFACE_KINDS = [
  'chart', 'image', 'video', 'document', 'table', 'map',
  'terminal', 'code', 'camera', 'news', 'research', 'simulation',
  'heatmap', 'network', 'timeline', 'distribution', 'agent_activity', 'text',
] as const;

export type SurfaceKind = (typeof SURFACE_KINDS)[number];

export const PRIORITIES = ['critical', 'primary', 'secondary', 'background', 'on_demand'] as const;
export type Priority = (typeof PRIORITIES)[number];

export interface SurfaceRequest {
  kind: SurfaceKind;
  /** Why this surface should exist, in the AI's own words. */
  intent: string;
  priority?: Priority;
  data?: Record<string, unknown>;
  /** Stable across re-requests, so asking twice updates rather than duplicates. */
  key?: string;
}
