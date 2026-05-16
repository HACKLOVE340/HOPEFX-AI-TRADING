/// <reference types="vite/client" />

/**
 * Augment Vite's ImportMetaEnv with all HOPEFX-specific VITE_ env vars.
 * Add new entries here when adding new VITE_ variables to .env files.
 *
 * Development (default — leave all blank):
 *   Vite dev server proxies /api/* → http://localhost:8000 and
 *   /ws/* → ws://localhost:8000 automatically. All VITE_ vars can be empty.
 *
 * Production — same origin (recommended):
 *   Nginx proxies /api/* and /ws/* on the same domain. Leave all blank.
 *
 * Production — split origin (CDN SPA + separate API domain):
 *   Set VITE_API_URL and VITE_WS_URL to your API domain.
 */
interface ImportMetaEnv {
  /** Backend REST API base URL (e.g. https://api.hopefx.com) — defaults to /api */
  readonly VITE_API_URL?: string;
  /** WebSocket endpoint for price/signal streaming — defaults to auto-detected wss://host/ws/live */
  readonly VITE_WS_URL?: string;
  /** WebSocket endpoint for nuclear chart-bot — defaults to auto-detected wss://host/ws/live */
  readonly VITE_NUCLEAR_WS_URL?: string;
  /** App environment label shown in UI (development | staging | production) */
  readonly VITE_APP_ENV?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
