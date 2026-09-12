/**
 * `pages/cameras/CameraEditorPage.tsx` — `/cameras/:id/editor` and `/cameras/new/editor`:
 * the GCP editor, addressed by the CAMERA whose frame it edits.
 *
 * ★ THE EDITOR IS A STEP OF THE CAMERA'S SETTINGS (2026-09-04). A camera — a
 *   registered one, or the draft on `/cameras/new` — owns a backing project and a
 *   frame; this route resolves both from the camera and opens the editor on
 *   them, with the pipeline strip on top. A camera without a frame yet is sent
 *   back to its settings, where the frame is chosen. The old
 *   `/projects/:pid/images/:iid` spelling still works for a frame reached
 *   another way (a clip's captured frame).
 */

import type { JSX } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';

import { DRAFT_CAMERA_ID } from '../../lib/cameras/projectCamera';
import { useCameraDraftStore } from '../../store/cameraDraftStore';
import { selectCameraById, useCameraRegistryStore } from '../../store/cameraRegistryStore';
import { asUuid } from '../../types/common';
import { EditorView } from '../WorkspacePage';

export function CameraEditorPage(): JSX.Element {
  const { id } = useParams();
  const isDraft = id === undefined || id === DRAFT_CAMERA_ID;
  const cameraId = isDraft ? DRAFT_CAMERA_ID : id;
  const registered = useCameraRegistryStore(selectCameraById(isDraft ? '' : id));
  const hydrated = useCameraRegistryStore((s) => s.hydrated);
  const draft = useCameraDraftStore((s) => s.draft);

  const projectId = isDraft ? draft.project_id : (registered?.project_id ?? null);
  const frameId = isDraft ? draft.frame_image_id : (registered?.frame_image_id ?? null);
  const settings = isDraft ? '/cameras/new' : `/cameras/${id}/settings`;

  if (!isDraft && registered === undefined) {
    if (!hydrated) {
      return (
        <Box sx={{ flex: 1, display: 'grid', placeItems: 'center' }}>
          <CircularProgress />
        </Box>
      );
    }
    return <Navigate to="/cameras" replace />;
  }
  // ★ No frame yet: the settings page is where one is chosen.
  if (!projectId || !frameId) return <Navigate to={settings} replace />;

  return (
    <EditorView
      key={`${cameraId}:${frameId}`}
      projectId={asUuid(projectId)}
      imageId={asUuid(frameId)}
      setupCameraId={cameraId}
    />
  );
}

export default CameraEditorPage;
