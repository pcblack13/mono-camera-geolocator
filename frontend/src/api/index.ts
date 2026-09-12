/**
 * API barrel — `src/api/index.ts`.
 *
 * ★ NOT IN §2.5's tree. Added "in the spirit of the tree" (§2) and flagged in the
 *   IU-24 report, for the same reason as `hooks/index.ts`: IU-26/27/28 are authored in
 *   parallel and both `from '@/api/client'` and `from '@/api'` should resolve. §2.5's
 *   per-file paths are unchanged and remain canonical.
 *
 * ★ `generated/schema.ts` is deliberately NOT re-exported — it is machine-generated,
 *   currently an empty placeholder, and nothing should reach it through a barrel. See
 *   its header.
 */

// ── ★ the client — the only fetch() in the app ───────────────────────────────
export {
  API_BASE_URL,
  buildUrl,
  etagFor,
  fetchJson,
  forgetEtag,
  hasDeferredMarker,
  isDeferredError,
  rememberEtag,
  request,
  upload,
  type FeatureMarker,
  type HttpMethod,
  type Parsed,
  type QueryParams,
  type QueryScalar,
  type QueryValue,
  type RequestOptions,
  type UploadOptions,
} from './client';

export { createQueryClient, queryClient } from './queryClient';
export { qk, type GcpListKeyParams } from './queryKeys';

// ── resource modules ─────────────────────────────────────────────────────────
export { albumsApi } from './albums';
export { camerasApi } from './cameras';
export { projectsApi } from './projects';
export {
  imagesApi,
  isUploadAccepted,
  type ImageUploadForm,
  type ImageUploadResponse,
  type ThumbnailParams,
} from './images';
export { videosApi } from './videos';
export { annotationsApi, type AnnotationFilters } from './annotations';
export { revisionsApi, type RevisionDetailParams, type RevisionFilters } from './revisions';
export { jobsApi } from './jobs';
// ★ DEM processing (gis.dem) — stateless raster transformation, no project entity.
export { demApi } from './dem';

// ★ The photograph's entered camera — from its setup page, one per image.
export { imageCameraApi } from './imageCamera';
export { matchesApi, type StartMatchOptions } from './matches';
export { gcpsApi, isRecomputeDryRun, type GcpCreate, type GcpRecomputeResponse } from './gcps';
export { suggestionsApi } from './suggestions';
export { semanticsApi } from './semantics';
export { poseApi } from './pose';
export { heatmapApi } from './heatmap';
export {
  providersApi,
  type ProviderFilters,
  type StaticImageParams,
  type TileParams,
} from './providers';
export { capabilitiesApi } from './capabilities';
export { batchApi, type BatchUploadForm } from './batch';
export { ALWAYS_AVAILABLE_FORMATS, exportsApi } from './exports';

// ── hooks ────────────────────────────────────────────────────────────────────
export * from './hooks';
