/**
 * `toolStore` — CONTRACT.md §8.5 / 50-frontend.md §3.4.
 *
 * Owns: `activeTool` · `previousTool` · `options`. Persisted: `options` only.
 *
 * ★ L7 — browser-only state. Nothing here comes from or goes to the API.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

/** The mandated annotation toolbar: cursor · point · polygon · polyline (SCOPE.md §3). */
export type ToolId = 'cursor' | 'point' | 'polygon' | 'polyline';

export interface ToolOptions {
  snapToVertex: boolean;
  /** ★ In ORIGINAL image px (§8.6) — NOT screen px. A snap radius that changes
   *  meaning with the zoom level would snap to a different vertex at 2× than at 1×. */
  snapRadiusPx: number;
  closePolygonOnDoubleClick: boolean;
  /** Auto-name `P1`, `P2`, … on create. */
  autoLabel: boolean;
  labelPrefix: string;
}

export interface ToolState {
  activeTool: ToolId;
  /** For the space-bar temporary-pan / hold-to-cursor gesture. */
  previousTool: ToolId;
  options: ToolOptions;

  setTool: (t: ToolId) => void;
  restorePreviousTool: () => void;
  setOption: <K extends keyof ToolOptions>(k: K, v: ToolOptions[K]) => void;
  resetOptions: () => void;
}

const DEFAULT_OPTIONS: ToolOptions = {
  snapToVertex: true,
  snapRadiusPx: 8,
  closePolygonOnDoubleClick: true,
  autoLabel: true,
  labelPrefix: 'P',
};

export const useToolStore = create<ToolState>()(
  devtools(
    persist(
      (set, get) => ({
        activeTool: 'cursor',
        previousTool: 'cursor',
        options: DEFAULT_OPTIONS,

        setTool: (t) =>
          set(
            (s) =>
              // ★ Setting the tool to the one already active must NOT overwrite
              //   `previousTool` — otherwise the space-bar gesture (cursor → pan →
              //   restore) loses the tool it was meant to come back to.
              s.activeTool === t ? s : { previousTool: s.activeTool, activeTool: t },
            false,
            'tool/setTool',
          ),

        restorePreviousTool: () => get().setTool(get().previousTool),

        setOption: (k, v) =>
          set((s) => ({ options: { ...s.options, [k]: v } }), false, `tool/setOption:${String(k)}`),

        resetOptions: () => set({ options: DEFAULT_OPTIONS }, false, 'tool/resetOptions'),
      }),
      {
        name: 'landexplorer.tool',
        version: 1,
        // ★ Only `options` survives a reload. `activeTool` is deliberately NOT
        //   persisted: reopening the app in `polygon` mode and clicking the image
        //   would start drawing a shape the user never asked for.
        partialize: (s) => ({ options: s.options }),
        merge: (persisted, current) => {
          const p = persisted as { options?: Partial<ToolOptions> } | undefined;
          // Discard unknown/partial shapes rather than trusting localStorage — an
          // older build's payload must never leave a required field undefined.
          return { ...current, options: { ...DEFAULT_OPTIONS, ...(p?.options ?? {}) } };
        },
      },
    ),
    { name: 'toolStore' },
  ),
);
