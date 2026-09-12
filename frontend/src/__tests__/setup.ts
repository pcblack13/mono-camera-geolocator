/**
 * Vitest global setup — the file `vitest.config.ts` already names as `setupFiles`.
 *
 * The config referenced it from the start (IU-29's slot); it had simply never been
 * written, so every attempt to run a test failed to collect. Minimal on purpose: matchers
 * and the two browser APIs jsdom does not implement but MUI and the workspace rely on.
 */

import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

import { __resetSurvivingState } from '../lib/survivingState';

afterEach(() => {
  cleanup();
  // ★ Surviving state outlives a component by design — and would outlive a TEST
  //   by accident. Every test starts with empty slots.
  __resetSurvivingState();
});

// ── jsdom gaps ──────────────────────────────────────────────────────────────

// MUI's `useMediaQuery` calls this on every render; jsdom has no implementation.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// ★ `Workspace` computes its layout from a ResizeObserver ("space wins over
//   breakpoint", §1.4). jsdom has none, and without a stub the component throws on
//   mount — which is precisely the class of runtime failure these tests exist to catch,
//   so it must be stubbed rather than worked around in the component.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  } as unknown as typeof ResizeObserver;
}
