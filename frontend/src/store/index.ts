/**
 * The Zustand store barrel — `src/store/` (CONTRACT.md §2.5), owned by IU-25.
 *
 * ★ **L7 — THE STORE HOLDS NO SERVER DATA.** From the API ⇒ React Query
 *   (`src/api/`, IU-24). Browser-only ⇒ here. The rule that decides it (§3.0):
 *   **if it survives a hard refresh on another machine, it is server state.**
 *
 *   The two deliberate overlaps, both documented at their site:
 *     · `annotationStore.draft` — an in-flight edit, autosaved to the server, which
 *       is the only draft truth.
 *     · `correspondenceStore` — an OPEN manual correspondence, which becomes server
 *       state only at commit.
 *   Neither holds a fetched row; both hold a user's current interaction.
 *
 * ★ **§2.5 names `src/store/`; 50-frontend.md §3.4 says `src/state/`.** CONTRACT wins
 *   (§0, precedence, absolute). This directory is `store/`.
 *
 * ★ **Nine stores, not eight.** §8.5's eight, plus `correspondenceStore` — SCOPE.md
 *   §5's manual GCP mode, which is this build's core interaction and which the
 *   contract (written for an automatic engine) has no home for. Added "in the spirit
 *   of the tree" (§2) and flagged.
 *
 * ★ **Subscribe with a SELECTOR, always** (§3.7). `useStore()` with no selector is
 *   banned by lint. Object/array selectors use `useShallow`. `selectionStore` ships
 *   `isSelectedSelector`/`isHoveredSelector` for exactly this reason.
 */

// ── tool ─────────────────────────────────────────────────────────────────────
export type { ToolId, ToolOptions, ToolState } from './toolStore';
export { useToolStore } from './toolStore';

// ── annotation ★ the command pattern ─────────────────────────────────────────
export type { AnnotationDraftState, AnnotationState, InProgressShape } from './annotationStore';
export { isGcpCandidateKind, isTempId, newClientId, useAnnotationStore } from './annotationStore';

// ── viewer ★ the coordinate model ────────────────────────────────────────────
export type {
  ImageAdjustments,
  ViewerState,
  ViewerTransform,
  ViewportContext,
} from './viewerStore';
export {
  adjustmentsToFilterCss,
  currentFitScale,
  stagePointToImage,
  useViewerStore,
} from './viewerStore';

// ── map ──────────────────────────────────────────────────────────────────────
export type { MapState } from './mapStore';
export {
  GCP_REVEAL_ZOOM,
  VIEW_EPSILON_DEG,
  VIEW_EPSILON_ZOOM,
  useMapStore,
  viewsEqual,
} from './mapStore';

// ── selection ★ the cross-pane bus ───────────────────────────────────────────
export type {
  EntityKind,
  FocusOrigin,
  SelectionMode,
  SelectionRef,
  SelectionState,
} from './selectionStore';
export { isHoveredSelector, isSelectedSelector, useSelectionStore } from './selectionStore';

// ── workspace ────────────────────────────────────────────────────────────────
export type { PaneSizes, WorkspaceState, WorkspaceTab } from './workspaceStore';
export { useWorkspaceStore } from './workspaceStore';

// ★ COMPARE REMOVED (1.2.6) — the side-by-side compare control and its Independent /
//   Linked / Swipe modes are gone from the UI. Linked and Swipe were produced by
//   automatic matching, which this build defers, leaving one working option that was
//   simply the normal layout. `compareStore.ts` and `CompareView.tsx` are deleted
//   with it; nothing imports them.

// ── upload ───────────────────────────────────────────────────────────────────
export type { UploadItem, UploadState, Uploader, UploadStatus } from './uploadStore';
export { useUploadStore } from './uploadStore';

// ── correspondence ★ SCOPE.md §5 — MANUAL GCP MODE ───────────────────────────
export type {
  CorrespondenceMode,
  CorrespondenceState,
  CorrespondenceStatus,
  OpenCorrespondenceMarkers,
} from './correspondenceStore';
export { openMarkers, useCorrespondenceStore } from './correspondenceStore';

export type { OfflineCacheState } from './offlineCacheStore';
export { useOfflineCacheStore } from './offlineCacheStore';

export type { AutoCacheState } from './autoCacheStore';
export { useAutoCacheStore } from './autoCacheStore';
