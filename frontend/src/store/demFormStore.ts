/**
 * `demFormStore` — the DEM processing page's working state, OUTSIDE the component.
 *
 * ★ WHY A STORE AND NOT `useState`: the Workspace rail unmounts the whole DemPage
 *   subtree on every tab switch (`ProjectsPage` renders exactly one tab). With local
 *   state, stepping out to Image setup and back threw away the picked file, the
 *   camera position, the radius — everything a surveyor had typed (reported in the
 *   field on 1.2.1). Module state survives the unmount; a reload still starts clean.
 *
 * ★ DELIBERATELY NOT `persist`ed: `File` handles cannot be serialized, and a
 *   half-filled form resurrected days later is a trap, not a convenience. The scope
 *   is exactly one app session.
 *
 * Setters accept a value OR an updater function — `Dispatch<SetStateAction<T>>`
 * compatible, so the page swaps `useState` for these without touching call sites.
 */

import { create } from 'zustand';

import type { DemProcessResponse, DemSource } from '../types/dem';

type SetStateAction<T> = T | ((prev: T) => T);

const resolve = <T>(action: SetStateAction<T>, prev: T): T =>
  typeof action === 'function' ? (action as (p: T) => T)(prev) : action;

export interface CornerInput {
  lat: string;
  lon: string;
}

export const EMPTY_CORNERS: CornerInput[] = [
  { lat: '', lon: '' },
  { lat: '', lon: '' },
  { lat: '', lon: '' },
  { lat: '', lon: '' },
];

/** How the area of interest is defined. */
export type AoiMode = 'camera' | 'corners' | 'none';

export interface DemParams {
  aoiMode: AoiMode;
  /** Camera station — free text so DMS and decimal both work; the server parses. */
  cameraLat: string;
  cameraLon: string;
  /** Working radius in TRUE ground metres. */
  radiusM: string;
  corners: CornerInput[];
  /** Percent in the UI, fraction on the wire. */
  tolerancePct: number;
  /** ★ Always true — the toggle was removed; see the Stage-2 note in the form. */
  reproject: true;
  targetSrid: number | null;
}

export const DEFAULT_PARAMS: DemParams = {
  aoiMode: 'camera',
  cameraLat: '',
  cameraLon: '',
  radiusM: '1500',
  corners: EMPTY_CORNERS,
  tolerancePct: 10,
  reproject: true as const,
  targetSrid: null,
};

export type Stage = 'idle' | 'ready' | 'processing' | 'done' | 'error';

interface DemFormState {
  /** Browser pick = bytes; desktop pick = a path the local API opens directly. */
  file: DemSource | null;
  params: DemParams;
  stage: Stage;
  uploadPct: number;
  result: DemProcessResponse | null;
  errorMessage: string | null;
  setFile: (a: SetStateAction<DemSource | null>) => void;
  setParams: (a: SetStateAction<DemParams>) => void;
  setStage: (a: SetStateAction<Stage>) => void;
  setUploadPct: (a: SetStateAction<number>) => void;
  setResult: (a: SetStateAction<DemProcessResponse | null>) => void;
  setErrorMessage: (a: SetStateAction<string | null>) => void;
}

export const useDemFormStore = create<DemFormState>()((set) => ({
  file: null,
  params: DEFAULT_PARAMS,
  stage: 'idle',
  uploadPct: 0,
  result: null,
  errorMessage: null,
  setFile: (a) => set((s) => ({ file: resolve(a, s.file) })),
  setParams: (a) => set((s) => ({ params: resolve(a, s.params) })),
  setStage: (a) => set((s) => ({ stage: resolve(a, s.stage) })),
  setUploadPct: (a) => set((s) => ({ uploadPct: resolve(a, s.uploadPct) })),
  setResult: (a) => set((s) => ({ result: resolve(a, s.result) })),
  setErrorMessage: (a) => set((s) => ({ errorMessage: resolve(a, s.errorMessage) })),
}));
