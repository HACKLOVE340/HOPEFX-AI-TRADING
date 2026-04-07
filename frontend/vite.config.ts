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
    // Allow all external hostnames (required for Gitpod/Ona preview tunnels)
    allowedHosts: true,
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
      // Backend routers mounted outside /api — must be proxied explicitly so
      // Vite dev server forwards them instead of returning 404.
      '/nuclear': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/nuclear-strategy': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/tca': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/kyc': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/graphql': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // NOTE: do NOT proxy '/status' — that path is handled by the React
      // StatusPage component. Only /api/status/* goes to the backend.
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 600,
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
          // ── App: Account / settings pages ──────────────────────────────────
          if (id.includes('pages/Profile') ||
              id.includes('pages/Wallet') ||
              id.includes('pages/SubAccounts') ||
              id.includes('pages/TwoFactorSetup') ||
              id.includes('pages/Settings')) {
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
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: ['**/node_modules/**', '**/e2e/**'],
    },
  },
});
