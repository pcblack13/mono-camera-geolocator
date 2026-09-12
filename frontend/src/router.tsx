/**
 * The route table — `src/router.tsx` (§2.5), owned by IU-23.
 *
 * ★ Pages (`src/pages/**`) and `AppShell` (`src/components/shell/**`) are owned by
 *   IU-28 and are imported by NAMED export, matching 50-frontend §2's convention
 *   ("every props interface is exported from the component's own file").
 *
 * ★ THE WORKSPACE IS LAZY, and that is not a micro-optimisation. `WorkspacePage`
 *   pulls in Konva AND Leaflet — the two heaviest chunks in the bundle. A surveyor
 *   opening the projects list on a cellular connection must not download a canvas
 *   engine and a map engine to read a list of names.
 */

import { Suspense, lazy } from 'react';
import {
  Navigate,
  createBrowserRouter,
  isRouteErrorResponse,
  useParams,
  useRouteError,
} from 'react-router-dom';
import type { RouteObject } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { App } from './App';
import { CameraProjectGuard } from './components/cameras/CameraProjectGuard';
import { ApiError } from './types/common';

// Eager: small, and two of them are landing routes (Home is `/` itself).
import { HomePage } from './pages/HomePage';
import { NotFoundPage } from './pages/NotFoundPage';
import { LegacyTabForwarder, ToolFrame } from './pages/tools/ToolRoutes';
import { t } from './i18n';

// Lazy: heavy, or rarely the entry point.
const WorkspacePage = lazy(async () => ({
  default: (await import('./pages/WorkspacePage')).WorkspacePage,
}));
/**
 * ★ The dashboard is LAZY for the same reason the workspace is: its centrepiece is a
 *   satellite map, so it pulls in Leaflet. A surveyor who deep-links straight to
 *   `/projects` must not download a map engine to read a list of names.
 */
const DashboardPage = lazy(async () => ({
  default: (await import('./pages/DashboardPage')).DashboardPage,
}));
/**
 * ★ THE VIDEO PAGE — a video is a FRAME SOURCE. It is LAZY for the same reason as the
 *   workspace: nobody reading the project list should download an HTML5 video surface.
 *   Capturing a frame there navigates on to the image workspace to annotate.
 */
const VideoPage = lazy(async () => ({
  default: (await import('./pages/VideoPage')).VideoPage,
}));
/**
 * ★ A RECORDING, WATCHED (2026-09-07) — a camera's recording played beside its
 *   attribute table, the two on one clock, with a trim. Lazy like every player.
 */
const RecordingPage = lazy(async () => ({
  default: (await import('./pages/RecordingPage')).RecordingPage,
}));
/**
 * ★ IMAGE SETUP — every photograph gets its own: upload (or revisit) the photo, its
 *   camera intrinsics, position + tilt, and the project's DEM, on ONE page. Serves
 *   both the new-image route (a fresh project lands there; "Add image" starts there)
 *   and the per-photo edit route. Lazy: entered per photograph, not on every visit.
 */
const ImageSetupPage = lazy(async () => ({
  default: (await import('./pages/ImageSetupPage')).ImageSetupPage,
}));
/**
 * ★ THE WORKFLOW GUIDE — the whole method as a board: nine steps with arrows, each
 *   with a door into the page it happens on. Lazy: a guide is read occasionally,
 *   not on every launch.
 */
const GuidePage = lazy(async () => ({
  default: (await import('./pages/GuidePage')).GuidePage,
}));
/**
 * ★ THE MONITOR — a globe of registered cameras, and each camera's page. Both are
 *   LAZY and both pull in MapLibre; the projects list must never download a globe
 *   engine to read a list of names.
 */
const GlobePage = lazy(async () => ({
  default: (await import('./pages/monitor/GlobePage')).GlobePage,
}));
const CameraMonitorPage = lazy(async () => ({
  default: (await import('./pages/monitor/CameraMonitorPage')).CameraMonitorPage,
}));
/**
 * ★ THE CAMERA WORKSPACE (2026-09-04) — the registry as a page, and each camera's
 *   settings pipeline (name → connection → DEM → calibration → position → frame →
 *   control points → lookup table). Lazy: the settings page carries a Leaflet
 *   position picker.
 */
const CameraServerPage = lazy(async () => ({
  default: (await import('./pages/cameras/CameraServerPage')).CameraServerPage,
}));
const CameraSettingsPage = lazy(async () => ({
  default: (await import('./pages/cameras/CameraSettingsPage')).CameraSettingsPage,
}));
const CameraEditorPage = lazy(async () => ({
  default: (await import('./pages/cameras/CameraEditorPage')).CameraEditorPage,
}));
/**
 * ★ RECORDED VIDEOS AND THE TOOLS, each at its own address (2026-09-04): DEM
 *   processing, the recorded videos and the drift monitor. They were tabs of the
 *   Projects page; the Projects page is retired (the camera is the unit of work),
 *   and `LegacyTabForwarder` sends every old `/projects?tab=…` link on. Video
 *   detection was retired on 2026-09-07 — a clip is detected where a camera is
 *   watched. Lazy: none of them belongs in the landing chunk.
 */
const DemPage = lazy(async () => ({ default: (await import('./pages/DemPage')).DemPage }));
const VideoLibrary = lazy(async () => ({
  default: (await import('./components/video/VideoLibrary')).VideoLibrary,
}));
const DriftMonitorTab = lazy(async () => ({
  default: (await import('./components/drift/DriftMonitorTab')).DriftMonitorTab,
}));
/**
 * ★ THE MAP WINDOW — the camera monitor's satellite map alone, for a second
 *   screen. Mounted BESIDE the app layout (no shell, no nav): it is a panel that
 *   happens to be a window, not a page. Lazy, like every map.
 */
const MapWindowPage = lazy(async () => ({
  default: (await import('./pages/monitor/MapWindowPage')).MapWindowPage,
}));
/**
 * ★ APP STATUS — the ConnectionChip's popover in full: every component explained,
 *   plus a live tail of the server's own log. Lazy: a diagnostic page is entered
 *   when something is wrong, not on every launch.
 */
const StatusPage = lazy(async () => ({
  default: (await import('./pages/StatusPage')).StatusPage,
}));

/**
 * ★ ONE PAGE PER RECORD. React reuses a route element across `:projectId` /
 *   `:imageId` changes, and setup(A) → setup(B) can be one navigation.
 *   Both pages seed their forms once from the record, so without a key B showed A's
 *   values and Save wrote them onto B. The key remounts the page per record.
 */
function KeyedImageSetupPage(): JSX.Element {
  const { projectId, imageId } = useParams();
  return <ImageSetupPage key={`${projectId ?? ''}:${imageId ?? 'new'}`} />;
}
function KeyedCameraSettingsPage(): JSX.Element {
  const { id } = useParams();
  return <CameraSettingsPage key={id ?? 'new'} />;
}
function KeyedCameraEditorPage(): JSX.Element {
  const { id } = useParams();
  return <CameraEditorPage key={id ?? 'new'} />;
}

/**
 * The router's last resort — a render-time throw or a lazy-chunk load failure.
 *
 * ★ It is deliberately NOT `common/ErrorBoundary` (IU-28): that boundary wraps the
 *   app's CONTENT and can rely on the shell being mounted. This one must render
 *   when the shell itself failed, so it depends on nothing but MUI.
 *
 * ★ It shows `request_id` when there is one. That string is what a user pastes into
 *   a bug report, and it is the only thing that connects a screenshot to a log line
 *   (§6.2).
 */
function RouteErrorPage(): JSX.Element {
  const error = useRouteError();

  let title = 'Something went wrong';
  let detail = 'An unexpected error occurred while rendering this page.';
  let requestId: string | null = null;

  if (isRouteErrorResponse(error)) {
    title = `${error.status} ${error.statusText}`;
    detail = typeof error.data === 'string' ? error.data : detail;
  } else if (error instanceof ApiError) {
    title = error.body.code;
    detail = error.body.message;
    requestId = error.body.request_id;
  } else if (error instanceof Error) {
    detail = error.message;
  }

  return (
    <Box
      role="alert"
      sx={{
        minHeight: '100dvh',
        display: 'grid',
        placeItems: 'center',
        p: 3,
        bgcolor: 'background.default',
      }}
    >
      <Stack spacing={2} sx={{ maxWidth: 560, textAlign: 'center' }}>
        <Typography variant="h2">{title}</Typography>
        <Typography variant="body1" color="text.secondary">
          {detail}
        </Typography>
        {requestId !== null && (
          <Typography variant="mono" color="text.secondary">
            Request ID: {requestId}
          </Typography>
        )}
        <Box>
          <Button variant="contained" onClick={() => window.location.assign('/cameras')}>
            {t('Back to the camera workspace')}
          </Button>
        </Box>
      </Stack>
    </Box>
  );
}

/**
 * ★ Route params are LOCAL UI STATE, not wire fields, so they are camelCase. L9's
 *   casing law governs the API boundary (`src/types/**`, `src/api/**`); a URL
 *   segment is neither. `qk.images.list(projectId)` (§8.3) already spells them this
 *   way.
 */
export const routes: RouteObject[] = [
  {
    // The popped-out map: no shell around it (see the lazy note above).
    path: '/monitor/cameras/:id/map',
    element: (
      <Suspense fallback={null}>
        <MapWindowPage />
      </Suspense>
    ),
    errorElement: <RouteErrorPage />,
  },
  {
    path: '/',
    element: <App />,
    errorElement: <RouteErrorPage />,
    children: [
      /**
       * ★ `/` IS THE INTRODUCTION now. The landing page says what the product does
       *   and how a point comes to exist — and ships no map engine (the same budget
       *   rule the lazy notes state). The dashboard's every-GCP map moved to
       *   `/dashboard`, one click away in the nav.
       */
      { index: true, element: <HomePage /> },
      { path: 'dashboard', element: <DashboardPage /> },
      { path: 'guide', element: <GuidePage /> },

      // ★ App status — reached from the ConnectionChip's popover ("Open app
      //   status & logs"): the health components explained, and the log monitor.
      { path: 'status', element: <StatusPage /> },

      // ★ THE PROJECTS PAGE IS RETIRED (2026-09-04): its `?tab=` tools have their
      //   own addresses below, and the bare list forwards to the camera workspace.
      { path: 'projects', element: <LegacyTabForwarder /> },
      { path: 'dem', element: <DemPage /> },
      {
        path: 'videos',
        element: (
          <ToolFrame>
            <VideoLibrary />
          </ToolFrame>
        ),
      },
      {
        path: 'drift',
        element: (
          <ToolFrame>
            <DriftMonitorTab />
          </ToolFrame>
        ),
      },

      // ★ A camera's backing project has no project page and no project settings:
      //   the camera's settings page is both (the guard sends anything that still
      //   asks for them there). A plain project's page and settings are gone too.
      { path: 'projects/:projectId', element: <Navigate to="/cameras" replace /> },
      { path: 'projects/:projectId/settings', element: <Navigate to="/cameras" replace /> },

      // ★ Image setup — a photograph's own settings (photo, intrinsics, position,
      //   tilt, its optional DEM override). Reached by a clip's captured frame; a
      //   CAMERA's frame has no setup page of its own — the calibration, position
      //   and DEM are the camera's (the guard).
      {
        path: 'projects/:projectId/setup',
        element: (
          <CameraProjectGuard>
            <KeyedImageSetupPage />
          </CameraProjectGuard>
        ),
      },
      {
        path: 'projects/:projectId/images/:imageId/setup',
        element: (
          <CameraProjectGuard>
            <KeyedImageSetupPage />
          </CameraProjectGuard>
        ),
      },

      /**
       * ★ THE WORKSPACE — the mandated three-pane arrangement (§1.1): photo,
       *   satellite map, GCP dock. The image id is in the PATH, not a query param,
       *   because "which photograph am I surveying" is the identity of the screen —
       *   it must be linkable, bookmarkable, and survive a reload with the panes
       *   intact.
       */
      { path: 'projects/:projectId/images/:imageId', element: <WorkspacePage /> },

      /**
       * ★ THE VIDEO PAGE — scrub a field video to a second and capture that frame. The
       *   video id is in the PATH for the same reason the image id is: "which video am
       *   I sampling" is the identity of the screen, and it must be linkable.
       */
      { path: 'projects/:projectId/videos/:videoId', element: <VideoPage /> },
      // ★ A camera's recording, watched beside its table (2026-09-07). The
      //   static segment outranks `:videoId`, so the two never collide.
      { path: 'videos/recordings/:folder', element: <RecordingPage /> },
      // ★ A library-only clip (no project) has its own address (0018).
      { path: 'videos/:videoId', element: <VideoPage /> },

      // ★ The monitor: the globe is the Monitoring workspace's entry point; a marker
      //   opens its camera's page. The old Live stream tab forwards here (LegacyTabForwarder).
      { path: 'monitor', element: <GlobePage /> },
      { path: 'monitor/cameras/:id', element: <CameraMonitorPage /> },

      // ★ The camera workspace: the list, a new camera's pipeline and its editor,
      //   a camera's settings and its editor.
      { path: 'cameras', element: <CameraServerPage /> },
      { path: 'cameras/new', element: <KeyedCameraSettingsPage /> },
      { path: 'cameras/new/editor', element: <KeyedCameraEditorPage /> },
      { path: 'cameras/:id/settings', element: <KeyedCameraSettingsPage /> },
      { path: 'cameras/:id/editor', element: <KeyedCameraEditorPage /> },

      // ★ 404 is a route, not a redirect. A surveyor who mistypes a project id must
      //   be told the project is not there, not silently shown a different one.
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
