/**
 * `imageSetupDraftStore` — the Image-setup page's UNSAVED work, outside the component.
 *
 * ★ WHY: the setup page held its form (15 hand-typed calibration/position fields)
 *   and the freshly-uploaded photo in `useState` — so pressing the DEM card's
 *   "Process new DEM…" (which navigates to the DEM page) unmounted the page and
 *   THREW AWAY everything the surveyor had typed (field report on 1.2.5). Same
 *   class of bug the DEM page itself had on 1.2.1 (`demFormStore` is the same
 *   medicine). Module state survives the round trip; a reload still starts clean.
 *
 * ★ KEYED per (project, image): `${projectId}:${imageId ?? 'new'}` — a draft for
 *   one photograph must never resurface under another. Cleared on successful save
 *   and when the photo it described is deleted.
 *
 * ★ DELIBERATELY NOT `persist`ed: a half-filled calibration resurrected days later
 *   is a trap, not a convenience. The scope is exactly one app session.
 */

import { create } from 'zustand';

/** Structural mirror of the page's `SetupImage` (kept here to avoid a page import). */
export interface DraftSetupImage {
  id: string;
  filename: string;
  width: number;
  height: number;
  gcp_count: number;
  annotation_count: number;
}

export interface ImageSetupDraft {
  /** The form's strings, exactly as typed. Null = the form never materialised. */
  form: Record<string, string> | null;
  /** New-image mode's uploaded photo, so returning re-adopts it. */
  uploadedImage: DraftSetupImage | null;
}

interface ImageSetupDraftState {
  byKey: Record<string, ImageSetupDraft>;
  set: (key: string, draft: ImageSetupDraft) => void;
  clear: (key: string) => void;
}

export const useImageSetupDraftStore = create<ImageSetupDraftState>()((set) => ({
  byKey: {},
  set: (key, draft) => set((s) => ({ byKey: { ...s.byKey, [key]: draft } })),
  clear: (key) =>
    set((s) => {
      if (!(key in s.byKey)) return s;
      const next = { ...s.byKey };
      delete next[key];
      return { byKey: next };
    }),
}));
