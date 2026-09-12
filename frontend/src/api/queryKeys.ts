/**
 * ★ THE QUERY KEY FACTORY — `src/api/queryKeys.ts` (§8.3).
 *
 * **One place. No stringly-typed keys anywhere.** A key typed by hand at a call site
 * is a cache entry nothing can invalidate, and the bug it produces — stale GCPs
 * rendered next to fresh ones — is invisible until someone exports.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ★★ EVERY MEMBER OF §8.3 IS REPRODUCED VERBATIM, AND KEEPS ITS EXACT KEY.
 *    Nothing below renames, re-shapes or re-orders one. IU-26/27/28 code against
 *    §8.3 in parallel with this file and must find what they read there.
 *
 * ★★ WHAT IS ADDED, AND WHY IT HAD TO BE — **§8.3's keys for nested collections omit
 *    the query parameters those endpoints accept.** `qk.gcps.forImage(id)` is the
 *    key for `GET /images/{id}/gcps`, which takes `GcpListParams` (endpoint 38) —
 *    so `?source=manual` and `?is_stale=true` **hash to the same key and serve each
 *    other's data.** For a GCP table that is not a cosmetic bug: it renders a set of
 *    survey coordinates that answers a filter nobody asked for, and L12 ("refuse
 *    rather than answer wrongly") is the law it breaks. The same hole exists on
 *    `images.list`, `annotations.forImage`, `annotations.versions`,
 *    `matches.forImage`, `suggestions.forImage`, `semantics.forImage`,
 *    `heatmap.forImage` and `projects.revisions`.
 *
 *    §8.3 already solves this correctly for `projects` and `jobs` — `lists()` is the
 *    invalidation PREFIX and `list(f)` is the leaf that carries the filter. The fix
 *    is to finish applying the factory's own idiom:
 *
 *      - **The §8.3 member keeps its key and becomes the invalidation prefix.**
 *        `invalidateQueries({ queryKey: qk.gcps.forImage(id) })` invalidates every
 *        filtered variant, because the prefix matches all of them. This is the
 *        behaviour callers already expect from it.
 *      - **A `…Filtered` sibling appends the filter object and is what the query
 *        actually uses.** Its key is a strict extension of the prefix, so the
 *        hierarchy stays intact.
 *
 *    Unfiltered reads pass `{}` and get `[…prefix, {}]`. React Query hashes object
 *    keys deterministically (stable key order), so `{a:1,b:2}` and `{b:2,a:1}` are
 *    one entry.
 *
 *    Endpoints 28, 29, 51, 55 and 60 had **no key at all** in §8.3; they are added in
 *    the same style. All additions are flagged in the IU-24 report.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import type { Uuid } from '../types/common';
import type { AlbumFilters } from '../types/album';
import type { ProjectFilters } from '../types/project';
import type { JobFilters } from '../types/job';
import type { ImageFilters } from '../types/image';
import type { GcpFilters, GcpOverviewFilters } from '../types/gcp';
import type { AnnotationVersionFilters } from '../types/annotation';
import type { MatchFilters } from '../types/match';
import type { SuggestionFilters } from '../types/suggestion';
import type { SemanticFilters } from '../types/semantic';
import type { ExportFilters } from '../types/export';
import type { BatchFilters } from '../types/batch';
import type { HeatmapParams } from '../types/heatmap';
import type { ProviderId } from '../types/geo';

import type { AnnotationFilters } from './annotations';
import type { RevisionFilters, RevisionDetailParams } from './revisions';
import type { ProviderFilters } from './providers';

/** Endpoint 38's cache key inputs — `GcpListParams` plus the response-shaping `format`. */
export type GcpListKeyParams = GcpFilters & { format?: 'json' | 'geojson' };

export const qk = {
  all: ['landexplorer'] as const,
  capabilities: () => [...qk.all, 'capabilities'] as const,
  providers: () => [...qk.all, 'providers'] as const,

  /** ★ ADDED — endpoint 50 takes `ProviderListParams`; `qk.providers()` is the prefix. */
  providersFiltered: (f: ProviderFilters) => [...qk.providers(), f] as const,
  /** ★ ADDED — endpoint 51 `GET /imagery/providers/{provider}` had no key. */
  providerDetail: (name: ProviderId) => [...qk.providers(), 'detail', name] as const,

  projects: {
    all: () => [...qk.all, 'projects'] as const,
    lists: () => [...qk.projects.all(), 'list'] as const,
    list: (f: ProjectFilters) => [...qk.projects.lists(), f] as const,
    details: () => [...qk.projects.all(), 'detail'] as const,
    detail: (id: Uuid) => [...qk.projects.details(), id] as const,
    revisions: (id: Uuid) => [...qk.projects.detail(id), 'revisions'] as const,

    /** ★ ADDED — endpoint 23 takes `RevisionListParams`. */
    revisionsFiltered: (id: Uuid, f: RevisionFilters) => [...qk.projects.revisions(id), f] as const,
  },

  /** The project's own elevation source — gates the 3D terrain view. */
  projectDem: (id: Uuid) => [...qk.all, 'projects', 'detail', id, 'dem'] as const,

  /** The photograph's ENTERED camera (intrinsics + position + tilt), per image. */
  imageCamera: (id: Uuid) => [...qk.all, 'images', 'detail', id, 'camera'] as const,

  /**
   * ★ ADDED — albums (collections of projects, many-to-many).
   *
   * Same idiom as `projects`: `lists()` is the invalidation PREFIX, `list(f)` the
   * filtered leaf. `projects(id)` nests under `detail(id)` so deleting or renaming
   * an album invalidates its member list with one prefix.
   *
   * ★ A membership write must ALSO invalidate `qk.projects.lists()` — the project
   *   rows carry `albums: AlbumRef[]`, so their chips are stale the instant a
   *   toggle lands. The hooks in `hooks/useAlbums.ts` do both, every time.
   */
  albums: {
    all: () => [...qk.all, 'albums'] as const,
    lists: () => [...qk.albums.all(), 'list'] as const,
    list: (f: AlbumFilters) => [...qk.albums.lists(), f] as const,
    details: () => [...qk.albums.all(), 'detail'] as const,
    detail: (id: Uuid) => [...qk.albums.details(), id] as const,
    projects: (id: Uuid) => [...qk.albums.detail(id), 'projects'] as const,
    projectsFiltered: (id: Uuid, f: ProjectFilters) => [...qk.albums.projects(id), f] as const,
  },

  images: {
    all: () => [...qk.all, 'images'] as const,
    lists: () => [...qk.images.all(), 'list'] as const,
    list: (projectId: Uuid) => [...qk.images.lists(), projectId] as const,
    details: () => [...qk.images.all(), 'detail'] as const,
    detail: (id: Uuid) => [...qk.images.details(), id] as const,
    metadata: (id: Uuid) => [...qk.images.detail(id), 'metadata'] as const,

    /** ★ ADDED — endpoint 10 takes `ImageListParams` (status, q, sort, paging). */
    listFiltered: (projectId: Uuid, f: ImageFilters) => [...qk.images.list(projectId), f] as const,
  },

  /**
   * ★ ADDED — videos, a FRAME SOURCE for images. Same idiom as `images`: `lists()` is
   *   the invalidation PREFIX, `list(projectId)` the leaf. Capturing a frame writes a
   *   new IMAGE, so `useCaptureFrame` invalidates `qk.images.lists()` — not this tree.
   */
  videos: {
    all: () => [...qk.all, 'videos'] as const,
    lists: () => [...qk.videos.all(), 'list'] as const,
    list: (projectId: Uuid) => [...qk.videos.lists(), projectId] as const,
    /** ★ Every video across every project — the Workspace's Video editor tab. Sits
     *  under `lists()` so the upload/delete invalidations cover it for free. */
    listAll: () => [...qk.videos.lists(), 'all-projects'] as const,
    details: () => [...qk.videos.all(), 'detail'] as const,
    detail: (id: Uuid) => [...qk.videos.details(), id] as const,
  },

  annotations: {
    all: () => [...qk.all, 'annotations'] as const,
    forImage: (imageId: Uuid) => [...qk.annotations.all(), 'image', imageId] as const,
    detail: (id: Uuid) => [...qk.annotations.all(), 'detail', id] as const,
    versions: (imageId: Uuid) => [...qk.annotations.forImage(imageId), 'versions'] as const,
    atRevision: (imageId: Uuid, seq: number) =>
      [...qk.annotations.forImage(imageId), 'revision', seq] as const,

    /** ★ ADDED — endpoint 16 takes `AnnotationListParams`. */
    forImageFiltered: (imageId: Uuid, f: AnnotationFilters) =>
      [...qk.annotations.forImage(imageId), f] as const,
    /** ★ ADDED — endpoint 27 takes `AnnotationVersionListParams`. */
    versionsFiltered: (imageId: Uuid, f: AnnotationVersionFilters) =>
      [...qk.annotations.versions(imageId), f] as const,
    /** ★ ADDED — endpoint 28 `GET /annotations/{id}/versions` had no key. */
    versionsForAnnotation: (annotationId: Uuid, f: AnnotationVersionFilters) =>
      [...qk.annotations.detail(annotationId), 'versions', f] as const,
    /**
     * ★ ADDED — endpoint 29 `GET /annotation-versions/{version_id}` had no key.
     *   ★ `version_id` is a **number**, not a `Uuid`: `annotation_versions.id` is
     *   `BIGSERIAL` and is the one id in this API serialised as a JSON number (§6.1).
     */
    version: (versionId: number) => [...qk.annotations.all(), 'version', versionId] as const,
  },

  revisions: {
    all: () => [...qk.all, 'revisions'] as const,
    detail: (id: Uuid) => [...qk.revisions.all(), 'detail', id] as const,

    /** ★ ADDED — endpoint 25 takes `include_snapshot` / `image_id`, which change the body. */
    detailWith: (id: Uuid, p: RevisionDetailParams) => [...qk.revisions.detail(id), p] as const,
  },

  suggestions: {
    all: () => [...qk.all, 'suggestions'] as const,
    forImage: (imageId: Uuid) => [...qk.suggestions.all(), 'image', imageId] as const,

    /** ★ ADDED — endpoint 44 takes `SuggestionListParams`. */
    forImageFiltered: (imageId: Uuid, f: SuggestionFilters) =>
      [...qk.suggestions.forImage(imageId), f] as const,
  },

  jobs: {
    all: () => [...qk.all, 'jobs'] as const,
    lists: () => [...qk.jobs.all(), 'list'] as const,
    list: (f: JobFilters) => [...qk.jobs.lists(), f] as const,
    details: () => [...qk.jobs.all(), 'detail'] as const,
    detail: (id: Uuid) => [...qk.jobs.details(), id] as const,
  },

  matches: {
    all: () => [...qk.all, 'matches'] as const,
    forImage: (imageId: Uuid) => [...qk.matches.all(), 'image', imageId] as const,
    detail: (id: Uuid) => [...qk.matches.all(), 'detail', id] as const,

    /** ★ ADDED — endpoint 34 takes `MatchResultListParams`. */
    forImageFiltered: (imageId: Uuid, f: MatchFilters) =>
      [...qk.matches.forImage(imageId), f] as const,
  },

  gcps: {
    all: () => [...qk.all, 'gcps'] as const,
    forImage: (imageId: Uuid) => [...qk.gcps.all(), 'image', imageId] as const,
    forMatch: (matchId: Uuid) => [...qk.gcps.all(), 'match', matchId] as const,
    detail: (id: Uuid) => [...qk.gcps.all(), 'detail', id] as const,

    /**
     * ★ ADDED — endpoint 38 takes `GcpListParams` **+ `format`**. See the header.
     *
     * ★ `format` is part of the key, not just the query: `format=geojson` returns a
     *   `GeoJsonFeatureCollection` and `format=json` returns a `Page[GcpRead]` — two
     *   incompatible shapes at one URL. Keyed without it, whichever loaded first
     *   would be handed to the other's consumer and the render would throw on a
     *   missing `items`.
     */
    forImageFiltered: (imageId: Uuid, f: GcpListKeyParams) =>
      [...qk.gcps.forImage(imageId), f] as const,
    /** ★ ADDED — endpoint 64 takes `GcpListParams`. */
    forMatchFiltered: (matchId: Uuid, f: GcpFilters) => [...qk.gcps.forMatch(matchId), f] as const,

    /**
     * ★ ADDED — `GET /gcps`, the CROSS-PROJECT overview behind the dashboard map.
     *
     * ★ Keyed under `gcps.all()` on purpose: creating or deleting a GCP anywhere
     *   already invalidates `qk.gcps.all()`, so the dashboard map stays truthful
     *   without a single extra invalidation site.
     */
    overviews: () => [...qk.gcps.all(), 'overview'] as const,
    overview: (f: GcpOverviewFilters) => [...qk.gcps.overviews(), f] as const,
  },

  semantics: {
    all: () => [...qk.all, 'semantics'] as const,
    forImage: (imageId: Uuid) => [...qk.semantics.all(), 'image', imageId] as const,

    /** ★ ADDED — endpoint 46 takes `SemanticFeatureListParams`. */
    forImageFiltered: (imageId: Uuid, f: SemanticFilters) =>
      [...qk.semantics.forImage(imageId), f] as const,
  },

  pose: { forImage: (imageId: Uuid) => [...qk.all, 'pose', imageId] as const },

  /** Live object detection — availability is machine state, sessions are polled raw. */
  detection: {
    all: () => [...qk.all, 'detection'] as const,
    availability: () => [...qk.detection.all(), 'availability'] as const,
  },

  /** Camera drift — the frozen references library, and the monitors' one status poll. */
  /**
   * ★ LUT builds and the on-disk bundle library. These were string keys in five
   *   components with THREE spellings, so invalidations missed each other — a new
   *   table did not appear in the detection pickers, and the accuracy page
   *   invalidated a key nothing queried. One factory, every consumer.
   */
  lut: {
    all: () => [...qk.all, 'lut'] as const,
    builds: () => [...qk.lut.all(), 'builds'] as const,
    build: (buildId: string) => [...qk.lut.builds(), buildId] as const,
    library: () => [...qk.lut.all(), 'library'] as const,
  },
  /** The processed-DEM library folder; `refresh` is the host page's bump counter. */
  demLibrary: {
    all: () => [...qk.all, 'dem-library'] as const,
    list: (refresh: number) => [...qk.demLibrary.all(), refresh] as const,
  },
  drift: {
    all: () => [...qk.all, 'drift'] as const,
    references: () => [...qk.drift.all(), 'references'] as const,
    status: () => [...qk.drift.all(), 'status'] as const,
  },

  /**
   * The accuracy check (Stages D/E/F) — one stored state per photograph, plus the
   * runs that produce it.
   *
   * ★ `state` is keyed per image and is the ONLY thing the page reads: the result
   *   lives on disk server-side, so a reload — or a visit tomorrow — rebuilds the
   *   whole page from this one query rather than from a run that has since expired.
   */
  accuracy: {
    all: () => [...qk.all, 'accuracy'] as const,
    state: (imageId: Uuid) => [...qk.accuracy.all(), 'image', imageId] as const,
    run: (runId: string) => [...qk.accuracy.all(), 'run', runId] as const,
    history: (imageId: Uuid) => [...qk.accuracy.state(imageId), 'history'] as const,
  },

  heatmap: {
    forImage: (imageId: Uuid) => [...qk.all, 'heatmap', imageId] as const,

    /** ★ ADDED — endpoint 49 takes `HeatmapParams` (`format` changes the body entirely). */
    forImageFiltered: (imageId: Uuid, p: HeatmapParams) =>
      [...qk.heatmap.forImage(imageId), p] as const,
  },

  batches: {
    all: () => [...qk.all, 'batches'] as const,
    detail: (id: Uuid) => [...qk.batches.all(), 'detail', id] as const,

    /** ★ ADDED — endpoint 55 `GET /batch` had no key. Mirrors the `projects`/`jobs` idiom. */
    lists: () => [...qk.batches.all(), 'list'] as const,
    list: (f: BatchFilters) => [...qk.batches.lists(), f] as const,
  },

  exports: {
    all: () => [...qk.all, 'exports'] as const,
    lists: () => [...qk.exports.all(), 'list'] as const,
    detail: (id: Uuid) => [...qk.exports.all(), 'detail', id] as const,

    /** ★ ADDED — endpoint 60 takes `ExportListParams`; §8.3 had `lists()` but no `list(f)`. */
    list: (f: ExportFilters) => [...qk.exports.lists(), f] as const,
  },
} as const;
