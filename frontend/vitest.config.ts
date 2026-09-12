import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Vitest config — CONTRACT.md §13.1 (IU-23..28): "MSW mocks every endpoint — no
 * backend runs." Nothing in this suite may open a socket.
 *
 * Kept as a separate file (§2.5) rather than a `test` key on vite.config.ts so the
 * app build never loads the test toolchain.
 */
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  test: {
    globals: true,
    environment: 'jsdom',
    // IU-29 owns src/__tests__/**; setup lives with it.
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
    restoreMocks: true,
    clearMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.d.ts',
        'src/__tests__/**',
        'src/main.tsx',
        // Machine-generated from openapi.json; CI gates it on drift, not coverage.
        'src/api/generated/**',
      ],
    },
  },
});
