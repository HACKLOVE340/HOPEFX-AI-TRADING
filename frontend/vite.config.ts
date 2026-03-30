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
          // Core React runtime
          if (id.includes('node_modules/react/') ||
              id.includes('node_modules/react-dom/') ||
              id.includes('node_modules/react-router-dom/') ||
              id.includes('node_modules/scheduler/')) {
            return 'vendor-react';
          }
          // TanStack Query
          if (id.includes('@tanstack/react-query')) return 'vendor-query';
          // Zustand
          if (id.includes('node_modules/zustand')) return 'vendor-state';
          // Recharts (heavy — split separately)
          if (id.includes('node_modules/recharts') ||
              id.includes('node_modules/d3-') ||
              id.includes('node_modules/victory-')) {
            return 'vendor-recharts';
          }
          // Lightweight charts (TradingView)
          if (id.includes('node_modules/lightweight-charts')) return 'vendor-lwcharts';
          // Leaflet (map — only used in GlobalAttackMap)
          if (id.includes('node_modules/leaflet') ||
              id.includes('node_modules/react-leaflet')) {
            return 'vendor-leaflet';
          }
          // Framer Motion
          if (id.includes('node_modules/framer-motion')) return 'vendor-motion';
          // Radix UI primitives
          if (id.includes('node_modules/@radix-ui')) return 'vendor-radix';
          // Panel components are lazy-loaded via dynamic import() in
          // TradingDashboard — Rollup splits them automatically; no manual
          // chunk needed (avoids circular dependency with vendor-recharts).
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
