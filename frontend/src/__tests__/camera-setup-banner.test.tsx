/**
 * The camera pipeline's strip over the GCP editor (2026-09-04).
 *
 * ★ What these pin: the strip counts the placed points against the four the
 *   solve needs and names what is still missing; the build button waits for
 *   them; a successful build writes the bundle's site name onto the camera on
 *   the server (the table "jumps back" with the operator); and "Back to camera
 *   settings" is always there.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/cameras', async () => {
  const m = await import('./fakeCamerasApi');
  return { camerasApi: m.fakeCameras.api };
});
vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));

const gcpTotal = vi.fn(() => 2);
const demActive = vi.fn(() => true);
vi.mock('../api/hooks', () => ({
  useGcps: () => ({ data: { total: gcpTotal(), items: [] } }),
  useProjectDem: (projectId: string) => ({
    isSuccess: true,
    data: demActive()
      ? { active: true, provider_enabled: true, project_id: projectId }
      : { active: false, provider_enabled: true, project_id: null },
  }),
  useProviders: () => ({ data: { items: [] } }),
}));

const stationFx = vi.fn<() => number | null>(() => 1200);
const stationNoCal = vi.fn<() => number | null>(() => null);
const stationNoCalOn = vi.fn(() => false);
vi.mock('../api/hooks/useImageCamera', () => ({
  useImageCamera: () => ({
    isSuccess: true,
    data: {
      configured: true,
      fx: stationFx(),
      fy: stationFx(),
      cx: 640,
      cy: 360,
      auto_gcp_enabled: true,
      no_calibration: stationNoCalOn() || stationNoCal() !== null,
      fov_h_deg: stationNoCal(),
      fov_v_deg: null,
    },
  }),
}));
const lutCreate = vi.fn(async () => ({
  build_id: 'b1',
  site_name: 'north_gate',
  status: 'queued',
}));
const lutGet = vi.fn(async () => ({
  build_id: 'b1',
  site_name: 'north_gate',
  status: 'succeeded',
  progress_done: 10,
  progress_total: 10,
  error: null,
}));
vi.mock('../api/lut', () => ({
  lutApi: {
    create: (...a: unknown[]) => lutCreate(...(a as [])),
    get: () => lutGet(),
    library: async () => [],
  },
}));

import { CameraSetupBanner, DRAFT_CAMERA_ID } from '../components/cameras/CameraSetupBanner';
import { EMPTY_DRAFT, useCameraDraftStore } from '../store/cameraDraftStore';
import { setLanguage } from '../i18n';
import { useCameraRegistryStore, type RegisteredCamera } from '../store/cameraRegistryStore';
import type { Uuid } from '../types/common';
import { fakeCameras as fake } from './fakeCamerasApi';

const PROJECT = '00000000-0000-4000-8000-000000000901' as Uuid;
const IMAGE = '00000000-0000-4000-8000-000000000801' as Uuid;
const GATE: RegisteredCamera = {
  id: '00000000-0000-4000-8000-000000000101',
  name: 'North gate',
  lat: 34.1,
  lon: 36.0,
  source: 'rtsp://cam/1',
  connection: 'lan',
  project_id: PROJECT,
  frame_image_id: IMAGE,
  created_at: '2026-09-04T08:00:00Z',
};

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mount(cameraId: string = GATE.id): void {
  setLanguage('en');
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/projects/${PROJECT}/images/${IMAGE}?camera=${cameraId}`]}>
        <CameraSetupBanner cameraId={cameraId} projectId={PROJECT} imageId={IMAGE} />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fake.rows.clear();
  stationNoCalOn.mockReturnValue(false);
  // The server row under the SAME id the strip is rendered with.
  fake.rows.set(GATE.id, {
    id: GATE.id as Uuid,
    name: GATE.name,
    lat: GATE.lat,
    lon: GATE.lon,
    source: GATE.source,
    connection: 'lan',
    provides: 'camera',
    data_source: null,
    heading_deg: null,
    fov_deg: null,
    fps: null,
    tags: [],
    lut_site: null,
    project_id: PROJECT,
    frame_image_id: IMAGE,
    calibration: null,
    desired: { watch: null, detect: null, feed: false },
    created_at: GATE.created_at,
    updated_at: GATE.created_at,
  });
  useCameraRegistryStore.setState({ cameras: [GATE], statuses: {}, hydrated: true });
  gcpTotal.mockReturnValue(2);
  demActive.mockReturnValue(true);
  stationFx.mockReturnValue(1200);
  stationNoCal.mockReturnValue(null);
  lutCreate.mockClear();
});

const cameraId = (): string => GATE.id;

describe('the camera setup strip in the editor', () => {
  it('★ counts the points against four, names what is missing, and always offers the way back', () => {
    mount();
    expect(screen.getByRole('region', { name: 'Camera setup' })).toBeVisible();
    expect(screen.getByText(/Setting up camera/)).toHaveTextContent('North gate');
    expect(screen.getByText('2/4')).toBeVisible();
    expect(screen.getByText(/still needed/)).toHaveTextContent('2 more control point(s)');
    expect(screen.getByRole('button', { name: 'Build lookup table' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Back to camera settings' }));
    expect(screen.getByTestId('loc')).toHaveTextContent(`/cameras/${cameraId()}/settings`);
  });

  it('★ with four points the build is enabled, and a missing DEM or calibration is still named', () => {
    gcpTotal.mockReturnValue(4);
    demActive.mockReturnValue(false);
    stationFx.mockReturnValue(null);
    mount();
    const note = screen.getByText(/still needed/);
    expect(note).toHaveTextContent('a DEM on the camera');
    expect(note).toHaveTextContent('calibration on the camera (fx, fy — or no-calibration mode');
    expect(screen.getByRole('button', { name: 'Build lookup table' })).toBeEnabled();
  });

  it('★ with four points and a DEM the build runs, and the table is saved to the camera', async () => {
    gcpTotal.mockReturnValue(4);
    mount();
    const build = screen.getByRole('button', { name: 'Build lookup table' });
    expect(build).toBeEnabled();
    fireEvent.click(build);
    await waitFor(() =>
      expect(lutCreate).toHaveBeenCalledWith(
        expect.objectContaining({ image_id: IMAGE, site_name: 'North gate' }),
      ),
    );
    // the bundle's site name lands on the camera row — on the server and in the cache
    await waitFor(() =>
      expect(useCameraRegistryStore.getState().cameras[0].lut_site).toBe('north_gate'),
    );
    expect(fake.rows.get(cameraId())?.lut_site).toBe('north_gate');
    expect(screen.getByRole('button', { name: 'Return with the lookup table' })).toBeVisible();
  });

  it('★ GEO-DRIFT C2: a station in no-calibration mode with a field of view needs no fx/fy', () => {
    gcpTotal.mockReturnValue(4);
    stationFx.mockReturnValue(null);
    stationNoCal.mockReturnValue(72);
    mount();
    expect(screen.queryByText(/calibration on the camera/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Build lookup table' })).toBeEnabled();
  });

  it('★ 2026-09-09: no-calibration mode with a BLANK field of view is enough too (default seed)', () => {
    gcpTotal.mockReturnValue(4);
    stationFx.mockReturnValue(null);
    stationNoCal.mockReturnValue(null);
    stationNoCalOn.mockReturnValue(true);
    mount();
    expect(screen.queryByText(/calibration on the camera/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Build lookup table' })).toBeEnabled();
  });

  it('★ a DRAFT camera (?camera=new) is served from the draft: the table lands on it, the way back is /cameras/new', async () => {
    gcpTotal.mockReturnValue(4);
    useCameraDraftStore.setState({
      draft: { ...EMPTY_DRAFT, name: 'Draft gate', project_id: PROJECT, frame_image_id: IMAGE },
      touchedAt: new Date().toISOString(),
    });
    mount(DRAFT_CAMERA_ID);
    expect(screen.getByText(/Setting up camera/)).toHaveTextContent('Draft gate');
    fireEvent.click(screen.getByRole('button', { name: 'Build lookup table' }));
    await waitFor(() => expect(useCameraDraftStore.getState().draft.lut_site).toBe('north_gate'));
    // no registry write for a draft
    expect(fake.rows.get(GATE.id)?.lut_site).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Return with the lookup table' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/cameras/new');
  });

  it('★ a stale draft (its frame is another image) shows no strip at all', () => {
    useCameraDraftStore.setState({
      draft: {
        ...EMPTY_DRAFT,
        name: 'Other',
        project_id: PROJECT,
        frame_image_id: 'ffffffff-0000-4000-8000-000000000000',
      },
      touchedAt: new Date().toISOString(),
    });
    mount(DRAFT_CAMERA_ID);
    expect(screen.queryByRole('region', { name: 'Camera setup' })).toBeNull();
  });
});
