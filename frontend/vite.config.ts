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
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
    },
  },
});
