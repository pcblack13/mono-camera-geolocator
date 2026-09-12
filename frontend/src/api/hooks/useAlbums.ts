/**
 * Albums — collections of projects (§7).
 *
 * ★★ THE INVALIDATION RULE, and it is not optional: **every album write invalidates
 *    BOTH `qk.albums.*` AND `qk.projects.lists()`.** `ProjectSummary` embeds
 *    `albums: AlbumRef[]`, so a membership toggle changes rows in a cache the album
 *    endpoints never touched. Invalidate only the album side and the chips on the
 *    projects page keep advertising a membership that no longer exists — the exact
 *    class of silently-stale render `queryKeys.ts`'s header exists to prevent.
 *
 * ★ Membership calls are IDEMPOTENT server-side, which is what makes the multi-toggle
 *   menu safe: it asserts a desired state rather than diffing the current one.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type {
  Album,
  AlbumCreate,
  AlbumFilters,
  AlbumSummary,
  AlbumUpdate,
} from '../../types/album';
import type { ProjectFilters, ProjectSummary } from '../../types/project';
import { albumsApi } from '../albums';
import { qk } from '../queryKeys';

/**
 * ★ ONE place, so no write site can forget half of it. See the module header for why
 *   the project lists are in here.
 */
function invalidateAlbumSurface(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: qk.albums.all() });
  void queryClient.invalidateQueries({ queryKey: qk.projects.lists() });
}

// ─────────────────────────────────────────────────────────────────────────────
// Reads
// ─────────────────────────────────────────────────────────────────────────────

export function useAlbums(f: AlbumFilters = {}): UseQueryResult<Page<AlbumSummary>> {
  return useQuery({
    queryKey: qk.albums.list(f),
    queryFn: ({ signal }) => albumsApi.list(f, signal),
  });
}

export function useAlbum(albumId: Uuid | null): UseQueryResult<Album> {
  return useQuery({
    queryKey: qk.albums.detail(albumId!),
    queryFn: ({ signal }) => albumsApi.get(albumId!, signal),
    enabled: albumId !== null,
  });
}

/** `GET /albums/{id}/projects` — the album's members, same shape as the projects list. */
export function useAlbumProjects(
  albumId: Uuid | null,
  f: ProjectFilters = {},
): UseQueryResult<Page<ProjectSummary>> {
  return useQuery({
    queryKey: qk.albums.projectsFiltered(albumId!, f),
    queryFn: ({ signal }) => albumsApi.projects(albumId!, f, signal),
    enabled: albumId !== null,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Writes
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ★ Rejects with `ApiError` `409 ALBUM_NAME_CONFLICT` when the name collides
 *   case-insensitively with a live album. The caller renders that on the name FIELD,
 *   not as a toast — it is a correctable input problem, not a system failure.
 */
export function useCreateAlbum(): UseMutationResult<Album, unknown, AlbumCreate> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AlbumCreate) => albumsApi.create(body),
    onSuccess: (album) => {
      queryClient.setQueryData(qk.albums.detail(album.id), album);
      invalidateAlbumSurface(queryClient);
    },
  });
}

export interface UpdateAlbumVariables {
  albumId: Uuid;
  /** ★ CHANGED FIELDS ONLY — an empty body is a `400 EMPTY_PATCH`. */
  body: AlbumUpdate;
}

export function useUpdateAlbum(): UseMutationResult<Album, unknown, UpdateAlbumVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ albumId, body }: UpdateAlbumVariables) => albumsApi.update(albumId, body),
    onSuccess: (album) => {
      queryClient.setQueryData(qk.albums.detail(album.id), album);
      invalidateAlbumSurface(queryClient);
    },
  });
}

export interface DeleteAlbumVariables {
  albumId: Uuid;
}

/** ★ Deletes the COLLECTION only. Its projects survive — see `albums.ts`. */
export function useDeleteAlbum(): UseMutationResult<void, unknown, DeleteAlbumVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ albumId }: DeleteAlbumVariables) => albumsApi.remove(albumId),
    onSuccess: (_void, { albumId }) => {
      queryClient.removeQueries({ queryKey: qk.albums.detail(albumId) });
      invalidateAlbumSurface(queryClient);
    },
  });
}

export interface AlbumMembershipVariables {
  albumId: Uuid;
  projectId: Uuid;
}

/** `POST /albums/{id}/projects/{project_id}` — idempotent; adding twice is fine. */
export function useAddProjectToAlbum(): UseMutationResult<void, unknown, AlbumMembershipVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ albumId, projectId }: AlbumMembershipVariables) =>
      albumsApi.addProject(albumId, projectId),
    onSuccess: () => invalidateAlbumSurface(queryClient),
  });
}

/**
 * `DELETE /albums/{id}/projects/{project_id}` — idempotent.
 *
 * ★ REMOVES A MEMBERSHIP, NOT A PROJECT. The wording and the icon at every call site
 *   must say "remove from album"; a bin icon here would be a lie about consequences.
 */
export function useRemoveProjectFromAlbum(): UseMutationResult<
  void,
  unknown,
  AlbumMembershipVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ albumId, projectId }: AlbumMembershipVariables) =>
      albumsApi.removeProject(albumId, projectId),
    onSuccess: () => invalidateAlbumSurface(queryClient),
  });
}
