/**
 * `cameras/CameraProjectGuard.tsx` — a project that belongs to a camera has no page of its own.
 *
 * ★ THE CAMERA IS THE UNIT OF WORK (2026-09-04, owner decision). A registered
 *   camera's backing project — or the draft's — is reached through the camera's
 *   settings page: the project page, project settings and a photo's setup page all
 *   resolve there. Plain projects keep their pages; this wraps only the routes
 *   that used to speak for "a project with many photographs".
 */

import type { JSX } from 'react';
import { Navigate, useParams } from 'react-router-dom';

import { cameraRefForProject, cameraSettingsPath } from '../../lib/cameras/projectCamera';
import { useCameraDraftStore } from '../../store/cameraDraftStore';
import { useCameraRegistryStore } from '../../store/cameraRegistryStore';

export function CameraProjectGuard({ children }: { children: JSX.Element }): JSX.Element {
  const { projectId } = useParams();
  // Subscribe, so a registry that hydrates after the first render re-resolves.
  useCameraRegistryStore((s) => s.cameras);
  useCameraDraftStore((s) => s.draft.project_id);
  const ref = cameraRefForProject(projectId);
  if (ref !== null) return <Navigate to={cameraSettingsPath(ref)} replace />;
  return children;
}
