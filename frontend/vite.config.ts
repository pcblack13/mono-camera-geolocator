import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

/**
 * LandExplorer SPA — Vite config.
 *
 * The dev proxy (CONTRACT.md §2.5) is what lets `VITE_API_BASE_URL` stay at its
 * default `/api/v1` in every environment: same-origin in dev via this proxy,
 * same-origin in prod via nginx (infra/nginx/conf.d/landexplorer.conf). The SPA
 * therefore never needs a CORS preflight and never learns an absolute API host.
 *
 * ★ The proxy target is the API container, and it is the ONLY place the backend's
 *   address appears in the frontend. Keyed tile providers are proxied server-side
 *   (§7 endpoint 52) precisely so no provider key is ever reachable from here (L2).
 */
export default defineConfig(({ mode }) => ({
  plugins: [react()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        // ★ Overridable so the desktop app's managed API (port 8123) can back a dev
        //   frontend: `VITE_PROXY_TARGET=http://localhost:8123 npm run dev`. The
        //   default stays the classic dev backend on 8000.
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        // ★ 30 min, NOT the 60s it used to mirror from nginx. The old value was sized
        //   for the job long-poll (needs >30s) and severed every request that outlived
        //   a minute — which is precisely what a multi-GB video upload or a large DEM's
        //   in-request crop+reproject does. The browser then reports a generic network
        //   error mid-upload, with nothing wrong on the server. Dev-only config; prod
        //   nginx sets its own timeouts in infra/nginx/conf.d.
        timeout: 1_800_000,
        proxyTimeout: 1_800_000,
      },
    },
  },

  build: {
    // ★ Vite 5 targets browsers that support the features Konva/Leaflet rely on.
    target: 'es2022',
    outDir: 'dist',
    sourcemap: mode !== 'production',
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Keep the three heavy, independently-cacheable subsystems out of the
        // entry chunk. A surveyor on cellular reloads the app far more often
        // than Leaflet or Konva change.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          mui: ['@mui/material', '@mui/icons-material', '@emotion/react', '@emotion/styled'],
          canvas: ['konva', 'react-konva'],
          map: ['leaflet', 'react-leaflet'],
          // ★ The globe engine. Only the lazy monitor pages and the 3D terrain pane
          //   import it; keeping it in its own chunk is what guarantees the projects
          //   list never downloads it.
          globe: ['maplibre-gl'],
        },
      },
    },
  },
}));
