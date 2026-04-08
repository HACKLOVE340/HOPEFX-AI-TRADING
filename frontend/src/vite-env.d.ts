/// <reference types="vite/client" />

/**
 * Augment Vite's ImportMetaEnv with all HOPEFX-specific VITE_ env vars.
 * Add new entries here when adding new VITE_ variables to .env files.
 */
interface ImportMetaEnv {
  /** Backend REST API base URL (e.g. https://api.hopefx.com) — defaults to /api */
  readonly VITE_API_URL?: string;
  /** WebSocket endpoint for price/signal streaming — defaults to /ws/live */
  readonly VITE_WS_URL?: string;
  /** WebSocket endpoint for nuclear risk dashboard — defaults to /ws/live */
  readonly VITE_NUCLEAR_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
