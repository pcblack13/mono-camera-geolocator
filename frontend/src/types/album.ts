/**
 * Albums — a user-named COLLECTION of projects (`backend/app/schemas/album.py`).
 *
 * ★ MANY-TO-MANY, and that is the whole point of the entity. A project belongs to as
 *   many albums as its owner likes — "Spring 2026", "Client: Northgate", "Coastal" —
 *   the way a track belongs to several playlists. An album is therefore NOT an owner
 *   and NOT a folder: deleting one detaches its projects and destroys nothing. Every
 *   membership call (`POST`/`DELETE /albums/{id}/projects/{project_id}`) is
 *   IDEMPOTENT for the same reason — a multi-toggle UI must be free to re-assert a
 *   state it already holds.
 *
 * ★ THE CASING LAW (§8.1 / L9): snake_case, mirroring the wire, no mapping layer.
 */

import type { IsoDateTime, Uuid } from './common';

/**
 * ★ The membership reference EMBEDDED IN `ProjectSummary.albums` — the reason a
 *   project card can render its album chips without a second request per row. It is
 *   deliberately thin: an id, a name and the accent colour are everything a chip
 *   needs, and inlining `project_count` here would make every project list pay for a
 *   rollup nothing on that screen reads.
 */
export interface AlbumRef {
  id: Uuid;
  name: string;
  color?: string | null;
}

/**
 * `GET /albums` row. ★ `project_count` is a server-side rollup — counting client-side
 * would need every album's membership list, i.e. one request per card.
 */
export interface AlbumSummary {
  id: Uuid;
  /** ★ CASE-INSENSITIVELY UNIQUE among live albums → `409 ALBUM_NAME_CONFLICT`. */
  name: string;
  description: string | null;
  /** A CSS hex colour (`#rrggbb`) used as the card's accent, or `null` for the default. */
  color: string | null;
  project_count: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

/** `GET /albums/{id}`, and the body of every album write. */
export interface Album extends AlbumSummary {
  /** Albums are soft-deleted, like projects; a live one is always `null`. */
  deleted_at?: IsoDateTime | null;
}

export interface AlbumCreate {
  name: string;
  description?: string | null;
  color?: string | null;
}

/**
 * PATCH — ★ UNSET-SENTINEL SEMANTICS (§6.1), and here it is load-bearing twice over:
 *   - an omitted key leaves the field untouched, `null` CLEARS it;
 *   - **an entirely empty body is a `400 EMPTY_PATCH`**, so callers must send only
 *     the fields that actually changed and must not submit an unchanged form.
 *
 * `JSON.stringify` drops `undefined` keys, so the `T | null | undefined` typing does
 * this for free — do not "normalise" the body.
 */
export interface AlbumUpdate {
  name?: string | undefined;
  description?: string | null | undefined;
  color?: string | null | undefined;
}

/** `GET /albums` query. `sort` accepts `name`, `created_at`, `project_count`, `-` prefixed. */
export interface AlbumFilters {
  q?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}
