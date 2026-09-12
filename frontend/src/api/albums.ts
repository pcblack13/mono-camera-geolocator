/**
 * Albums — collections of projects (§7).
 *
 * ★ No `fetch` here or in any sibling: every call goes through `client.ts` (§2.5).
 *
 * ★ MEMBERSHIP IS IDEMPOTENT. `addProject`/`removeProject` both return `204` whether
 *   or not they changed anything, which is what lets the "Add to album" menu be a
 *   plain multi-toggle: the UI asserts the state it wants and never has to read the
 *   current one first, so a double-click cannot produce a 409 or a duplicate row.
 *
 * ★ AN ALBUM IS NOT AN OWNER. `remove()` deletes the collection; the projects in it
 *   are untouched. The confirm copy in `pages/AlbumsPage.tsx` says so out loud.
 */

import type { Page, Uuid } from '../types/common';
import type { Album, AlbumCreate, AlbumFilters, AlbumUpdate } from '../types/album';
import type { AlbumSummary } from '../types/album';
import type { ProjectFilters, ProjectSummary } from '../types/project';
import { fetchJson, forgetEtag, toQuery } from './client';

const path = (id: Uuid): string => `/albums/${id}`;
const memberPath = (albumId: Uuid, projectId: Uuid): string =>
  `/albums/${albumId}/projects/${projectId}`;

export const albumsApi = {
  /** `POST /albums` → `201 Album`. ★ `409 ALBUM_NAME_CONFLICT` on a duplicate name. */
  create: (body: AlbumCreate, signal?: AbortSignal): Promise<Album> =>
    fetchJson<Album>('/albums', { method: 'POST', body, signal }),

  /** `GET /albums` → `200 Page[AlbumSummary]`. */
  list: (f: AlbumFilters = {}, signal?: AbortSignal): Promise<Page<AlbumSummary>> =>
    fetchJson<Page<AlbumSummary>>('/albums', { query: toQuery(f), signal }),

  /** `GET /albums/{id}` → `200 Album`. */
  get: (id: Uuid, signal?: AbortSignal): Promise<Album> => fetchJson<Album>(path(id), { signal }),

  /**
   * `PATCH /albums/{id}` → `200 Album`.
   *
   * ★ Send ONLY the changed fields: an empty body is a `400 EMPTY_PATCH`, and
   *   `JSON.stringify` dropping `undefined` keys is what `AlbumUpdate`'s
   *   `T | null | undefined` typing buys — do not "normalise" the body.
   */
  update: (id: Uuid, body: AlbumUpdate, signal?: AbortSignal): Promise<Album> =>
    fetchJson<Album>(path(id), { method: 'PATCH', body, signal }),

  /** `DELETE /albums/{id}` → `204`. ★ The member projects SURVIVE. */
  remove: async (id: Uuid, signal?: AbortSignal): Promise<void> => {
    await fetchJson<void>(path(id), { method: 'DELETE', parse: 'none', signal });
    forgetEtag(path(id));
  },

  /** `GET /albums/{id}/projects` → `200 Page[ProjectSummary]`. */
  projects: (
    id: Uuid,
    f: ProjectFilters = {},
    signal?: AbortSignal,
  ): Promise<Page<ProjectSummary>> =>
    fetchJson<Page<ProjectSummary>>(`${path(id)}/projects`, { query: toQuery(f), signal }),

  /** `POST /albums/{id}/projects/{project_id}` → `204`, idempotent. */
  addProject: async (albumId: Uuid, projectId: Uuid, signal?: AbortSignal): Promise<void> => {
    await fetchJson<void>(memberPath(albumId, projectId), {
      method: 'POST',
      parse: 'none',
      signal,
    });
  },

  /** `DELETE /albums/{id}/projects/{project_id}` → `204`, idempotent. ★ Leaves the
   *  collection; does NOT delete the project. */
  removeProject: async (albumId: Uuid, projectId: Uuid, signal?: AbortSignal): Promise<void> => {
    await fetchJson<void>(memberPath(albumId, projectId), {
      method: 'DELETE',
      parse: 'none',
      signal,
    });
  },
};
