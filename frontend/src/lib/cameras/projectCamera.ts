/**
 * `lib/cameras/projectCamera.ts` — which CAMERA a project belongs to.
 *
 * ★ THE CAMERA IS THE UNIT OF WORK (2026-09-04, owner decision). A registered camera
 *   owns a backing project (`cameras.project_id`) — its DEM, its frame, its control
 *   points live there — and the draft on `/cameras/new` owns one from the moment
 *   its DEM or frame needed a home. Every project-scoped page the old architecture
 *   had (the project page, project settings, a photo's setup page) resolves to
 *   THAT camera's settings when the project is a camera's; the editor's strip and
 *   its "back" do the same. This is the one lookup they all share.
 */

import { useCameraDraftStore } from '../../store/cameraDraftStore';
import { useCameraRegistryStore } from '../../store/cameraRegistryStore';

export type CameraRef =
  | { kind: 'camera'; id: string; name: string }
  | { kind: 'draft'; name: string };

/** The `?camera=` value that means "the draft on /cameras/new". */
export const DRAFT_CAMERA_ID = 'new';

/** Non-hook: the camera (registered or draft) whose backing project this is, or null. */
export function cameraRefForProject(projectId: string | null | undefined): CameraRef | null {
  if (!projectId) return null;
  const registered = useCameraRegistryStore
    .getState()
    .cameras.find((c) => c.project_id === projectId);
  if (registered !== undefined) {
    return { kind: 'camera', id: registered.id, name: registered.name };
  }
  const draft = useCameraDraftStore.getState().draft;
  if (draft.project_id === projectId) return { kind: 'draft', name: draft.name.trim() };
  return null;
}

/** A `?camera=` value → the camera it names (an unknown id is null). */
export function cameraRefForParam(value: string | null): CameraRef | null {
  if (value === null || value === '') return null;
  if (value === DRAFT_CAMERA_ID) {
    return { kind: 'draft', name: useCameraDraftStore.getState().draft.name.trim() };
  }
  const c = useCameraRegistryStore.getState().cameras.find((x) => x.id === value);
  return c === undefined ? null : { kind: 'camera', id: c.id, name: c.name };
}

/** Where a camera's settings live. */
export function cameraSettingsPath(ref: CameraRef): string {
  return ref.kind === 'draft' ? '/cameras/new' : `/cameras/${ref.id}/settings`;
}

/** The `?camera=` value that reopens the editor inside this camera's pipeline. */
export function cameraParam(ref: CameraRef): string {
  return ref.kind === 'draft' ? DRAFT_CAMERA_ID : ref.id;
}

/** Hook: re-renders with the registry and the draft. */
export function useCameraRefForProject(projectId: string | null | undefined): CameraRef | null {
  const cameras = useCameraRegistryStore((s) => s.cameras);
  const draftProject = useCameraDraftStore((s) => s.draft.project_id);
  const draftName = useCameraDraftStore((s) => s.draft.name);
  if (!projectId) return null;
  const registered = cameras.find((c) => c.project_id === projectId);
  if (registered !== undefined) {
    return { kind: 'camera', id: registered.id, name: registered.name };
  }
  if (draftProject === projectId) return { kind: 'draft', name: draftName.trim() };
  return null;
}
