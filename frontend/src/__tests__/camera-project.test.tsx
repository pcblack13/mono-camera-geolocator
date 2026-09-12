/**
 * THE CAMERA IS THE UNIT OF WORK (2026-09-04) — a project that belongs to a camera
 * (a registered one's backing project, or the draft's) resolves to that camera.
 *
 * ★ What these pin: the lookup (registered → draft → none); the route guard sends
 *   the project page, project settings and a photo's setup page to the camera's
 *   settings; the editor's structural parent is the camera, named by `?camera=`
 *   or by its backing project.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { render, screen } from '@testing-library/react';

import { CameraProjectGuard } from '../components/cameras/CameraProjectGuard';
import { resolvePageNav } from '../components/shell/pageNav';
import {
  cameraParam,
  cameraRefForParam,
  cameraRefForProject,
  cameraSettingsPath,
} from '../lib/cameras/projectCamera';
import { EMPTY_DRAFT, useCameraDraftStore } from '../store/cameraDraftStore';
import { useCameraRegistryStore, type RegisteredCamera } from '../store/cameraRegistryStore';

const P_CAM = '00000000-0000-4000-8000-000000000901';
const P_DRAFT = '00000000-0000-4000-8000-000000000902';
const P_PLAIN = '00000000-0000-4000-8000-000000000903';
const GATE: RegisteredCamera = {
  id: '00000000-0000-4000-8000-000000000101',
  name: 'North gate',
  lat: 34.1,
  lon: 36.0,
  source: 'rtsp://cam/1',
  connection: 'lan',
  project_id: P_CAM,
  created_at: '2026-09-04T08:00:00Z',
};

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mountAt(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/projects/:projectId/settings"
          element={
            <CameraProjectGuard>
              <div>project settings page</div>
            </CameraProjectGuard>
          }
        />
        <Route
          path="/projects/:projectId/images/:imageId/setup"
          element={
            <CameraProjectGuard>
              <div>image setup page</div>
            </CameraProjectGuard>
          }
        />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useCameraRegistryStore.setState({ cameras: [GATE], statuses: {}, hydrated: true });
  useCameraDraftStore.setState({
    draft: { ...EMPTY_DRAFT, name: 'Draft cam', project_id: P_DRAFT },
    touchedAt: new Date().toISOString(),
  });
});

describe('which camera a project belongs to', () => {
  it('resolves a registered camera, the draft, or nothing', () => {
    expect(cameraRefForProject(P_CAM)).toEqual({ kind: 'camera', id: GATE.id, name: 'North gate' });
    expect(cameraRefForProject(P_DRAFT)).toEqual({ kind: 'draft', name: 'Draft cam' });
    expect(cameraRefForProject(P_PLAIN)).toBeNull();
    expect(cameraRefForProject(null)).toBeNull();
    expect(cameraRefForParam('new')?.kind).toBe('draft');
    expect(cameraRefForParam(GATE.id)?.kind).toBe('camera');
    expect(cameraRefForParam('nobody')).toBeNull();
  });

  it('names where each one lives, and how the editor reopens inside it', () => {
    const cam = cameraRefForProject(P_CAM)!;
    const draft = cameraRefForProject(P_DRAFT)!;
    expect(cameraSettingsPath(cam)).toBe(`/cameras/${GATE.id}/settings`);
    expect(cameraSettingsPath(draft)).toBe('/cameras/new');
    expect(cameraParam(cam)).toBe(GATE.id);
    expect(cameraParam(draft)).toBe('new');
  });
});

describe('the project-scoped pages of a camera', () => {
  it('★ project settings of a registered camera’s project go to the camera’s settings', () => {
    mountAt(`/projects/${P_CAM}/settings`);
    expect(screen.getByTestId('loc')).toHaveTextContent(`/cameras/${GATE.id}/settings`);
    expect(screen.queryByText('project settings page')).toBeNull();
  });

  it('★ a photo’s setup page inside the draft’s project goes to /cameras/new', () => {
    mountAt(`/projects/${P_DRAFT}/images/i1/setup`);
    expect(screen.getByTestId('loc')).toHaveTextContent('/cameras/new');
  });

  it('a plain project keeps its own pages', () => {
    mountAt(`/projects/${P_PLAIN}/settings`);
    expect(screen.getByText('project settings page')).toBeVisible();
  });
});

describe('the editor’s parent', () => {
  it('★ is the camera’s settings when the frame is a camera’s — by ?camera= or by its project', () => {
    const byParam = resolvePageNav(`/projects/${P_PLAIN}/images/i1`, `?camera=${GATE.id}`);
    expect(byParam.parent).toBe(`/cameras/${GATE.id}/settings`);
    expect(byParam.parentTitle).toBe('Camera settings');
    const byProject = resolvePageNav(`/projects/${P_CAM}/images/i1`);
    expect(byProject.parent).toBe(`/cameras/${GATE.id}/settings`);
    const draft = resolvePageNav(`/projects/${P_DRAFT}/images/i1`);
    expect(draft.parent).toBe('/cameras/new');
    expect(draft.parentTitle).toBe('New camera');
    // a frame with no camera behind it goes up to the server of cameras — there is
    // no project page any more
    expect(resolvePageNav(`/projects/${P_PLAIN}/images/i1`).parent).toBe('/cameras');
  });
});
