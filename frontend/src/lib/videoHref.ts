/**
 * `lib/videoHref.ts` — where a clip's page lives.
 *
 * ★ A clip with a project sits under it (`/projects/:id/videos/:id`); a library-only
 *   clip has its own address (`/videos/:id`). One function, so no component guesses.
 */

import type { Uuid } from '../types/common';

export function videoHref(video: { id: Uuid; project_id: Uuid | null }): string {
  return video.project_id !== null
    ? `/projects/${video.project_id}/videos/${video.id}`
    : `/videos/${video.id}`;
}
