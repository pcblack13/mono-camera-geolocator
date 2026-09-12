/**
 * Hook barrel — `src/api/hooks/index.ts`.
 *
 * ★ NOT IN §2.5's tree. Added "in the spirit of the tree" (§2) and flagged in the
 *   IU-24 report: IU-26/27/28 are written in parallel against §2.5's file list, so
 *   both `from '@/api/hooks/useGcps'` and `from '@/api/hooks'` resolve. The
 *   per-file paths §2.5 names are unchanged and remain canonical.
 */

// ── projects · images · annotations · revisions ──────────────────────────────
export {
  useCreateProject,
  useDeleteProject,
  useProject,
  useProjects,
  useUpdateProject,
  type DeleteProjectVariables,
  type UpdateProjectVariables,
} from './useProjects';

// ★ Gates the 3D terrain view — a project with no DEM must not render flat ground.
export { useProjectDem } from './useProjectDem';
export {
  useImageCamera,
  useSaveImageCamera,
  type SaveImageCameraVariables,
} from './useImageCamera';

// ── albums ★ collections of projects, many-to-many ──────────────────────────
export {
  useAddProjectToAlbum,
  useAlbum,
  useAlbumProjects,
  useAlbums,
  useCreateAlbum,
  useDeleteAlbum,
  useRemoveProjectFromAlbum,
  useUpdateAlbum,
  type AlbumMembershipVariables,
  type DeleteAlbumVariables,
  type UpdateAlbumVariables,
} from './useAlbums';

export {
  useDeleteImage,
  useImage,
  useImageMetadata,
  useImages,
  type DeleteImageVariables,
} from './useImages';

export {
  useImageUpload,
  useUploaderRegistration,
  type UploadImageVariables,
} from './useImageUpload';

// ── videos ★ scrub → capture a frame → a real image ──────────────────────────
export {
  useCaptureFrame,
  useDeleteVideo,
  useUploadVideo,
  useVideo,
  useAllVideos,
  useVideos,
  type CaptureFrameVariables,
  type DeleteVideoVariables,
  type UploadVideoVariables,
} from './useVideos';

export {
  useAnnotation,
  useAnnotations,
  useBulkUpsertAnnotations,
  useCreateAnnotation,
  useDeleteAllAnnotations,
  useDeleteAnnotation,
  useUpdateAnnotation,
  type BulkUpsertVariables,
  type CreateAnnotationVariables,
  type DeleteAllAnnotationsVariables,
  type DeleteAnnotationVariables,
  type UpdateAnnotationVariables,
} from './useAnnotations';

export {
  useAnnotationVersion,
  useAnnotationVersions,
  useCreateRevision,
  useImageAnnotationVersions,
  useProjectRevisions,
  useRestoreRevision,
  useRevision,
  type CreateRevisionVariables,
  type RestoreRevisionVariables,
} from './useRevisions';

// ── jobs ─────────────────────────────────────────────────────────────────────
export { isJobActive, useJob } from './useJob';

// ── ★ GCPs — the deliverable (SCOPE.md §5) ───────────────────────────────────
export { useCreateGcp, useGcp, useGcps, useGcpsForMatch, useGcpsGeoJson } from './useGcps';
/** ★ The cross-project overview behind the dashboard map — `GET /gcps`. */
export {
  isEndpointAbsent,
  useGcpOverview,
  useGcpOverviewState,
  type GcpOverviewState,
  type GcpOverviewStatus,
} from './useGcpOverview';
export {
  useAdjustGcp,
  useResetGcp,
  type AdjustGcpVariables,
  type ResetGcpVariables,
} from './useAdjustGcp';
export {
  useRecomputeDeferral,
  useRecomputeGcps,
  type RecomputeGcpsVariables,
} from './useRecomputeGcps';

// ── capabilities · providers ─────────────────────────────────────────────────
export {
  DEFERRED_TOOLTIP,
  isFeatureDeferred,
  useCapabilities,
  useFeatureDeferral,
  useIsFeatureDeferred,
  type DeferralState,
  type DeferredFeature,
} from './useCapabilities';

export {
  useAvailableProviders,
  useDefaultProvider,
  useProvider,
  useProviders,
} from './useProviders';

// ── batch · exports ──────────────────────────────────────────────────────────
export {
  useBatch,
  useBatches,
  useBatchMatchDeferral,
  useBatchUpload,
  useCancelBatch,
  useCreateBatch,
  type BatchUploadVariables,
} from './useBatch';

export {
  isExportDownloadable,
  useDeleteExport,
  useExport,
  useExports,
  useStartExport,
  type StartExportVariables,
} from './useExport';

// ── ★ THE DEFERRED SURFACE — SCOPE.md §4 ─────────────────────────────────────
// Every hook below calls an endpoint that returns 501 in this build. Each ships a
// `use*Deferral()` companion that yields `{ disabled, tooltip }` — use it. Rendering
// a live control over any of these produces the dead spinner rule 4 forbids.
export {
  useMatchDeferral,
  useMatchResult,
  useMatchResults,
  useSelectMatchResult,
  useStartMatch,
  type SelectMatchResultVariables,
  type StartMatchVariables,
} from './useMatch';

export {
  useAcceptSuggestions,
  useSuggestions,
  useSuggestionsDeferral,
  useSuggestLandmarks,
  type AcceptSuggestionsVariables,
  type SuggestLandmarksVariables,
} from './useSuggestions';

export {
  useSegment,
  useSemantics,
  useSemanticsDeferral,
  type SegmentVariables,
} from './useSemantics';
export { usePose, usePoseDeferral } from './usePose';
export { useHeatmap, useHeatmapDeferral } from './useHeatmap';
export {
  useDriftReferences,
  useDriftMonitors,
  useFreezeReference,
  useDriftCheck,
  useStartDriftMonitor,
  useStopDriftMonitor,
} from './useDrift';
