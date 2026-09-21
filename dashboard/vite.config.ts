import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  // This bundle is always served under /godmode/ — core/page_routes.py mounts
  // dashboard/dist there in both configurations (alongside the main app, and
  // as the sole UI with / redirecting to it). Without a base, Vite emitted
  // absolute `/assets/...` URLs, so the page at /godmode/ asked the *root*
  // mount for its JavaScript. That directory holds the main app's build with
  // different content hashes, so the request fell through to the SPA catch-all
  // and came back as index.html — HTML delivered for a <script src>, and a
  // blank GodMode.
  base: '/godmode/',
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'HOPEFX GodMode',
        short_name: 'HOPEFX',
        description: 'Professional AI Trading Platform',
        theme_color: '#FFD700',
        background_color: '#0f172a',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/godmode/',
        scope: '/godmode/',
        icons: [
          {
            src: '/godmode/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any maskable'
          },
          {
            src: '/godmode/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any maskable'
          }
        ]
      },
      workbox: {
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/api\.hopefx\.io\/.*/i,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 60 * 60 // 1 hour
              }
            }
          }
        ]
      }
    })
  ],
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})
