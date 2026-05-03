/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    // Restrict to localhost and explicit tunnel hostnames; allowedHosts:true
    // opens DNS rebinding attack surface so we enumerate allowed hosts instead.
    allowedHosts: ['localhost', '127.0.0.1', '.gitpod.io', '.ona.io', '.preview.app.github.dev', '.gitpod.dev', 'all'],
    proxy: {
      // Forward all /api/* requests to the FastAPI backend
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Proxy the live WebSocket endpoint so the frontend can connect via a
      // relative URL (wss://<vite-host>/ws/live) instead of hardcoding port 8000.
      // This is required in Gitpod/Ona where each port has a distinct tunnel URL.
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      // NOTE: /nuclear and /nuclear-strategy API routes are now under /api/nuclear
      // and /api/nuclear-strategy respectively (prefix="/api/nuclear*" in
      // core/router_registry.py). All API calls for those routers go through
      // the '/api' proxy above. The browser-navigation routes /nuclear and
      // /nuclear-strategy are React SPA routes handled by Vite itself — do NOT
      // proxy them or Vite's HMR will be bypassed for those pages.
      // NOTE: /tca is mounted at /api/tca in the backend (prefix="/api/tca").
      // All TCA requests go through the '/api' proxy above — no separate entry needed.
      '/kyc': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/graphql': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // NOTE: /api/news/* is already covered by the '/api' proxy above.
      // The news router is mounted at prefix="/api/news" in the backend.
      // NOTE: do NOT proxy '/status' — that path is handled by the React
      // StatusPage component. Only /api/status/* goes to the backend.
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,

    // Vite 8 / Rolldown hoists shared modules (panels, UI primitives, store)
    // into the first chunk that imports them. The app-account chunk includes
    // the full shared component library because SubAccounts.tsx imports from
    // the components barrel. Raw size is ~963 kB but gzipped is ~289 kB —
    // well within acceptable range for a trading platform. The limit is raised
    // to suppress the false warning; the superadmin chunk is split separately.
    chunkSizeWarningLimit: 1000,
    // Vite 6 defaults to safari14 in its esbuild target, which cannot
    // transform destructuring-with-defaults used by @tanstack/react-query v5.
    // es2022 is supported by all modern browsers (Chrome 94+, Firefox 93+,
    // Safari 15.4+, Edge 94+) and resolves the esbuild transform error.
    target: 'es2022',
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          // ── Vendor: React runtime ──────────────────────────────────────────
          if (id.includes('node_modules/react/') ||
              id.includes('node_modules/react-dom/') ||
              id.includes('node_modules/react-router-dom/') ||
              id.includes('node_modules/scheduler/')) {
            return 'vendor-react';
          }
          // ── Vendor: TanStack Query ─────────────────────────────────────────
          if (id.includes('@tanstack/react-query')) return 'vendor-query';
          // ── Vendor: Zustand ────────────────────────────────────────────────
          if (id.includes('node_modules/zustand')) return 'vendor-state';
          // ── Vendor: Recharts + D3 (heavy) ──────────────────────────────────
          if (id.includes('node_modules/recharts') ||
              id.includes('node_modules/d3-') ||
              id.includes('node_modules/victory-')) {
            return 'vendor-recharts';
          }
          // ── Vendor: Lightweight Charts (TradingView) ───────────────────────
          if (id.includes('node_modules/lightweight-charts')) return 'vendor-lwcharts';
          // ── Vendor: Leaflet (only GlobalAttackMap) ─────────────────────────
          if (id.includes('node_modules/leaflet') ||
              id.includes('node_modules/react-leaflet')) {
            return 'vendor-leaflet';
          }
          // ── Vendor: Framer Motion ──────────────────────────────────────────
          if (id.includes('node_modules/framer-motion')) return 'vendor-motion';
          // ── Vendor: Radix UI ───────────────────────────────────────────────
          if (id.includes('node_modules/@radix-ui')) return 'vendor-radix';
          // ── Vendor: Axios ──────────────────────────────────────────────────
          if (id.includes('node_modules/axios')) return 'vendor-axios';
          // ── Shared: Trading panels (heavy — used across many pages) ────────
          // These panels import recharts, lightweight-charts, and d3. Giving
          // them their own chunk prevents them from inflating any page chunk
          // that imports from the components barrel (../components).
          if (id.includes('components/panels/') ||
              id.includes('components/CandleChart') ||
              id.includes('components/LineChart') ||
              id.includes('components/GlobalAttackMap') ||
              id.includes('components/FixApprovalQueue')) {
            return 'app-panels';
          }
          // ── Shared: UI primitives ──────────────────────────────────────────
          if (id.includes('components/ui/') ||
              id.includes('components/Badge') ||
              id.includes('components/DataTable') ||
              id.includes('components/EmptyState') ||
              id.includes('components/ErrorBanner') ||
              id.includes('components/MetricCard') ||
              id.includes('components/Modal') ||
              id.includes('components/PageHeader') ||
              id.includes('components/Spinner') ||
              id.includes('components/ThemeContext') ||
              id.includes('components/ThemeToggle')) {
            return 'app-ui';
          }
          // ── App: SuperAdmin dashboard + all its sections ───────────────────
          if (id.includes('pages/SuperAdminDashboard') ||
              id.includes('pages/superadmin/')) {
            return 'app-superadmin';
          }
          // ── App: AI / Nuclear feature (large) ─────────────────────────────
          if (id.includes('features/chart-bot') ||
              id.includes('pages/NuclearDashboardPage')) {
            return 'app-nuclear';
          }
          // ── App: Admin / security pages ────────────────────────────────────
          if (id.includes('pages/AdminPanel') ||
              id.includes('pages/SecurityDashboard') ||
              id.includes('pages/AuditLog') ||
              id.includes('pages/WhitelabelAdmin')) {
            return 'app-admin';
          }
          // ── App: Analytics pages ───────────────────────────────────────────
          if (id.includes('pages/Performance') ||
              id.includes('pages/CorrelationDashboard') ||
              id.includes('pages/TCADashboard') ||
              id.includes('pages/WalkForward') ||
              id.includes('pages/ABTesting')) {
            return 'app-analytics';
          }
          // ── App: Social / community pages ──────────────────────────────────
          if (id.includes('pages/CopyTrading') ||
              id.includes('pages/Leaderboard') ||
              id.includes('pages/SocialFeed') ||
              id.includes('pages/Marketplace') ||
              id.includes('pages/Affiliate')) {
            return 'app-social';
          }
          // ── App: Platform configuration (heavy — split from settings chunk) ─
          // PlatformConfiguration.tsx is ~55 kB and only loaded when the user
          // opens Settings → Platform Config.
          if (id.includes('pages/settings/PlatformConfiguration')) {
            return 'app-platform-config';
          }
          // ── App: Settings sub-sections ─────────────────────────────────────
          if (id.includes('pages/settings/') || id.includes('pages/Settings')) {
            return 'app-settings';
          }
          // ── App: Account pages ─────────────────────────────────────────────
          if (id.includes('pages/Profile') ||
              id.includes('pages/Wallet') ||
              id.includes('pages/SubAccounts') ||
              id.includes('pages/EliteDashboard') ||
              id.includes('pages/TwoFactorSetup')) {
            return 'app-account';
          }
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Exclude Playwright e2e specs — they run via `npm run test:e2e`, not vitest
    exclude: ['**/node_modules/**', '**/e2e/**'],
    // Per-test timeout: 10 s is generous for jsdom tests while still preventing
    // infinite hangs that would otherwise wait for the pool's 150 s worker limit.
    testTimeout: 10_000,
    // Hook timeout: 30 s covers beforeAll/afterAll environment setup in CI.
    hookTimeout: 30_000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: ['**/node_modules/**', '**/e2e/**'],
    },
  },
});
