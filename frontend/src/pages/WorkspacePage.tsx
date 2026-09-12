/**
 * `pages/WorkspacePage.tsx` — the mandated workspace route (router.tsx, 50-frontend §1).
 *
 * ★ EVERY PHOTOGRAPH GOES THROUGH ITS SETUP ONCE. Opening the editor on a photo whose
 *   camera has NEVER been saved redirects to that photo's setup page — clicking a
 *   just-captured frame therefore lands on setup, not on an editor with no camera
 *   behind it. One Save there (even of an empty form) marks the photo configured and
 *   the editor opens directly ever after. A still-loading or failed probe is NOT
 *   treated as "unconfigured" — the editor must not be barred by a flaky request.
 *
 * ★ Renders the three-pane arrangement via `Workspace` (the layout arbiter), plus the
 *   version-history drawer wired to the annotation store (IU-25) and the revision
 *   restore mutation (IU-24). `VersionHistoryDrawer` itself is IU-26's — composed here
 *   by its contract interface (§2.15).
 *
 * ★ Lazy route (router.tsx): `Workspace` pulls in Konva AND Leaflet, the two heaviest
 *   chunks. A surveyor opening the project list on cellular must not download a canvas
 *   engine and a map engine to read a list of names.
 */

import type { JSX } from 'react';
import { Navigate, useParams, useSearchParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';

import { VersionHistoryDrawer } from '../components/annotation/VersionHistoryDrawer';
import { CameraSetupBanner } from '../components/cameras/CameraSetupBanner';
import { cameraParam, useCameraRefForProject } from '../lib/cameras/projectCamera';
import { Workspace } from '../components/workspace/Workspace';
import { ErrorBoundary } from '../components/common/ErrorBoundary';
import { EmptyState } from '../components/common/EmptyState';
import { useAccuracyAutopilot } from '../api/hooks/useAccuracyAutopilot';
import { useGcps } from '../api/hooks/useGcps';
import { useImageCamera } from '../api/hooks/useImageCamera';
import { useRestoreRevision } from '../api/hooks/useRevisions';
import { useAnnotationStore } from '../store/annotationStore';
import { useWorkspaceStore } from '../store/workspaceStore';
import { asUuid, type Uuid } from '../types/common';
import { t } from '../i18n';

function WorkspaceErrorFallback(error: Error, reset: () => void): JSX.Element {
  return (
    <EmptyState
      title={t('This editor hit a problem')}
      description={error.message || 'A pane failed to render.'}
      primaryAction={{ label: 'Reload editor', onClick: reset }}
    />
  );
}

/** The legacy address: `/projects/:projectId/images/:imageId` (a clip's captured frame). */
export function WorkspacePage(): JSX.Element {
  const params = useParams();
  const projectId = params.projectId ? asUuid(params.projectId) : null;
  const imageId = params.imageId ? asUuid(params.imageId) : null;
  // ★ THE EDITOR IS A STEP OF THE CAMERA'S SETTINGS (2026-09-04): `?camera=<id>`
  //   (or `new` for the draft) keeps it inside that pipeline. A frame reached any
  //   other way is recognised by its PROJECT: a camera's backing project is that
  //   camera's, so the strip is there regardless. (`/cameras/:id/editor` is the
  //   camera-addressed spelling — `CameraEditorPage`.)
  const [search] = useSearchParams();
  const projectCamera = useCameraRefForProject(projectId);
  const setupCameraId = search.get('camera') ?? (projectCamera ? cameraParam(projectCamera) : null);
  if (projectId === null) {
    return (
      <EmptyState title={t('No project')} description="This editor has no project in its URL." />
    );
  }
  return <EditorView projectId={projectId} imageId={imageId} setupCameraId={setupCameraId} />;
}

export interface EditorViewProps {
  projectId: Uuid;
  imageId: Uuid | null;
  /** The camera whose pipeline this editor is a step of — its id, `new`, or null. */
  setupCameraId: string | null;
}

/** The editor itself: the setup gate, the accuracy autopilot, the strip, the panes. */
export function EditorView({ projectId, imageId, setupCameraId }: EditorViewProps): JSX.Element {
  const versionDrawerOpen = useWorkspaceStore((s) => s.versionDrawerOpen);
  const setVersionDrawerOpen = useWorkspaceStore((s) => s.setVersionDrawerOpen);
  const previewVersionId = useAnnotationStore((s) => s.previewVersionId);
  const setPreviewVersion = useAnnotationStore((s) => s.setPreviewVersion);
  const restoreRevision = useRestoreRevision();

  // ★ THE ERROR MEASURES ITSELF ONCE A POSE EXISTS. Four points is the moment the
  //   photograph becomes measurable, so the run starts then — in the background, while
  //   the surveyor carries on placing points — and the correction follows it. Driven
  //   from the PAGE so it runs whichever pane the surveyor is looking at.
  const gcpsQuery = useGcps(imageId);
  useAccuracyAutopilot(imageId, {
    gcpCount: gcpsQuery.data?.total ?? 0,
    enabled: imageId !== null,
  });

  // ★ The setup gate. Cheap (one small row, cached by React Query after the first
  //   visit), and it is what makes "click the photo" honour per-photo setup.
  const cameraQuery = useImageCamera(imageId);

  if (imageId !== null) {
    if (cameraQuery.isLoading) {
      return (
        <Box sx={{ flex: 1, display: 'grid', placeItems: 'center' }}>
          <CircularProgress />
        </Box>
      );
    }
    // Only a RESOLVED "never saved" redirects — an errored probe opens the editor.
    if (cameraQuery.data !== undefined && !cameraQuery.data.configured) {
      return <Navigate to={`/projects/${projectId}/images/${imageId}/setup`} replace />;
    }
  }

  return (
    <ErrorBoundary fallback={WorkspaceErrorFallback} resetKeys={[imageId]}>
      <Box sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {setupCameraId !== null && imageId !== null && (
          <CameraSetupBanner cameraId={setupCameraId} projectId={projectId} imageId={imageId} />
        )}
        <Workspace projectId={projectId} imageId={imageId} />
      </Box>

      {imageId !== null && (
        <VersionHistoryDrawer
          open={versionDrawerOpen}
          imageId={imageId}
          currentVersionId={previewVersionId}
          onClose={() => setVersionDrawerOpen(false)}
          onPreview={(versionId: number | null) => setPreviewVersion(versionId)}
          onRestore={(versionId: Uuid) =>
            restoreRevision.mutate({ revisionId: versionId, projectId, body: { confirm: true } })
          }
        />
      )}
    </ErrorBoundary>
  );
}

export default WorkspacePage;
