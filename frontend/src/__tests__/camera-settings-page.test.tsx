/**
 * The camera SETTINGS PIPELINE (2026-09-04) — `/cameras/new` and `/cameras/:id/settings`.
 *
 * ★ What these pin: the seven steps read in order and EVERY one is open from the
 *   start (owner ask — nothing locked, one button at the end); the connection
 *   picker offers every kind the field plugs in and asks only for what that kind
 *   needs; a new camera is a persisted DRAFT — its DEM step creates the backing
 *   project on demand, its frame step opens the editor with `?camera=new` — and
 *   "Add camera to the server" posts the whole draft as one row and clears it;
 *   an existing camera's lookup-table step builds and saves to its row.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

vi.mock('../api/cameras', async () => {
  const m = await import('./fakeCamerasApi');
  return { camerasApi: m.fakeCameras.api };
});
vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));

const gcpTotal = vi.fn(() => 0);
const demActive = vi.fn(() => false);
vi.mock('../api/hooks', () => ({
  useProviders: () => ({
    data: { items: [{ name: 'esri', configured: true, allowed: true, is_default: true }] },
  }),
  useGcps: () => ({ data: { total: gcpTotal(), items: [] } }),
  useProjectDem: (projectId: string | null) => ({
    isSuccess: true,
    data:
      demActive() && projectId !== null
        ? { active: true, provider_enabled: true, project_id: projectId }
        : { active: false, provider_enabled: true, project_id: null },
  }),
}));
const stationFx = vi.fn<() => number | null>(() => 1200);
const stationNoCal = vi.fn(() => false);
vi.mock('../api/hooks/useImageCamera', () => ({
  useImageCamera: (id: string | null) => ({
    isSuccess: id !== null,
    data:
      id === null
        ? undefined
        : {
            configured: true,
            fx: stationFx(),
            fy: stationFx(),
            cx: 640,
            cy: 360,
            auto_gcp_enabled: false,
            no_calibration: stationNoCal(),
            fov_h_deg: null,
            fov_v_deg: null,
          },
  }),
}));
vi.mock('../api/hooks/useImages', () => ({
  useImage: (id: string | null) => ({
    data: id === null ? undefined : { id, filename: 'frame.jpg', width: 1280, height: 720 },
  }),
}));
const PROJECT = '00000000-0000-4000-8000-000000000901';
const IMAGE = '00000000-0000-4000-8000-000000000801';
const IMAGE2 = '00000000-0000-4000-8000-000000000802';
const projectCreate = vi.fn(async (body: { name: string }) => ({ id: PROJECT, name: body.name }));
vi.mock('../api/projects', () => ({
  projectsApi: { create: (b: { name: string }) => projectCreate(b) },
}));
const lutCreate = vi.fn(async () => ({ build_id: 'b1', site_name: 'roof_pi', status: 'queued' }));
vi.mock('../api/lut', () => ({
  lutApi: {
    create: (...a: unknown[]) => lutCreate(...(a as [])),
    get: async () => ({
      build_id: 'b1',
      site_name: 'roof_pi',
      status: 'succeeded',
      progress_done: 1,
      progress_total: 1,
      error: null,
    }),
    library: async () => [
      {
        site_name: 'roof_pi',
        validation_passed: true,
        max_error_m: 1.2,
        built_utc: '2026-09-04T08:00:00Z',
      },
    ],
  },
}));
const stationPut = vi.fn(async (..._args: unknown[]) => ({}));
vi.mock('../api/imageCamera', () => ({
  imageCameraApi: { put: (...a: unknown[]) => stationPut(...(a as [])) },
}));
vi.mock('../api/images', () => ({
  imagesApi: { upload: vi.fn(), thumbnailUrl: () => 'thumb.jpg', fileUrl: () => 'file.jpg' },
  isUploadAccepted: () => false,
}));
vi.mock('../api/live', () => ({
  liveApi: {
    listDevices: vi.fn(async () => ({
      items: [{ id: '/dev/video0', label: 'USB capture (HDMI)' }],
    })),
    captureFrame: vi.fn(),
    captureDeviceFrame: vi.fn(),
  },
}));
vi.mock('../api/captureLibrary', () => ({
  captureLibraryApi: {
    importIntoProject: vi.fn(),
    fileUrl: (name: string) => `/api/v1/capture-library/${name}`,
  },
}));
// ★ The drift watch is the camera's (2026-09-08): the page reads references and
//   monitors to label the frame step — an empty library here, the freeze itself
//   goes through the fake cameras API.
const gcpCopy = vi.fn(async () => ({ copied: 6, items: [] }));
vi.mock('../api/gcps', () => ({ gcpsApi: { copyFrom: (...a: unknown[]) => gcpCopy(...(a as [])) } }));
const driftStop = vi.fn(async () => ({}));
vi.mock('../api/drift', () => ({ driftApi: { stopMonitor: (...a: unknown[]) => driftStop(...(a as [])) } }));
vi.mock('../api/hooks/useDrift', () => ({
  useDriftReferences: () => ({ data: [] }),
  useDriftMonitors: () => ({ data: [] }),
}));
vi.mock('../components/project/ProjectDemCard', () => ({
  ProjectDemCard: ({ projectId }: { projectId: string }) => (
    <div data-testid="dem-card">{projectId}</div>
  ),
}));
vi.mock('../components/image/ImportFromLibraryDialog', () => ({
  ImportFromLibraryDialog: () => null,
}));
vi.mock('../components/monitor/globe/PositionPickerMap', () => ({
  default: ({ onPick }: { onPick: (p: { lat: number; lon: number }) => void }) => (
    <button type="button" onClick={() => onPick({ lat: 34.104264, lon: 36.015782 })}>
      mock-map
    </button>
  ),
}));

import { captureLibraryApi } from '../api/captureLibrary';
import { liveApi } from '../api/live';
import { CameraSettingsPage } from '../pages/cameras/CameraSettingsPage';
import { setLanguage } from '../i18n';
import { EMPTY_DRAFT, useCameraDraftStore } from '../store/cameraDraftStore';
import { useCameraRegistryStore, type RegisteredCamera } from '../store/cameraRegistryStore';
import type { Uuid } from '../types/common';
import { fakeCameras as fake } from './fakeCamerasApi';

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mount(path: string): void {
  setLanguage('en');
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/cameras/new" element={<CameraSettingsPage />} />
          <Route path="/cameras/:id/settings" element={<CameraSettingsPage />} />
          <Route path="*" element={<div />} />
        </Routes>
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const STEP_TITLES = [
  'Name the camera',
  'How does it connect?',
  'Where does the camera stand?',
  'Camera DEM',
  'Optional data — camera calibration',
  'The frame, and its control points',
  'Lookup table',
];

/** ★ 2026-09-10: the table shows one row's form at a time, beside it — click the
 *  row to work in it (the panel opens on the next empty row by itself). */
function openStep(title: string): void {
  fireEvent.click(screen.getByRole('heading', { name: title }));
}

beforeEach(() => {
  fake.rows.clear();
  useCameraRegistryStore.setState({ cameras: [], statuses: {}, hydrated: true });
  useCameraDraftStore.setState({ draft: EMPTY_DRAFT, touchedAt: null });
  gcpTotal.mockReturnValue(0);
  demActive.mockReturnValue(false);
  gcpCopy.mockClear();
  driftStop.mockClear();
  projectCreate.mockClear();
  lutCreate.mockClear();
  stationFx.mockReturnValue(1200);
  stationNoCal.mockReturnValue(false);
});

describe('a NEW camera', () => {
  it('★ reads as seven steps, every one open, with ONE button at the end', () => {
    mount('/cameras/new');
    for (const title of STEP_TITLES) {
      expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
    }
    // nothing is locked behind a creation step…
    expect(screen.queryByText('After the camera is created')).toBeNull();
    openStep('Camera DEM');
    expect(screen.getByRole('button', { name: 'Attach the camera’s DEM' })).toBeEnabled();
    openStep('The frame, and its control points');
    expect(screen.getByRole('button', { name: 'Capture from the camera now' })).toBeEnabled();
    // …and the add button exists exactly once, at the end
    expect(screen.getAllByRole('button', { name: 'Add camera to the server' })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /Create camera/ })).toBeNull();
    // ★ THREE kinds, because there are three answers (2026-09-11): an address on
    //   the network, a capture device on this machine, a serial line.
    openStep('How does it connect?');
    const picker = screen.getByRole('group', { name: 'Connection type' });
    for (const kind of ['UTP / LAN', 'USB / capture card', 'Serial / UART']) {
      expect(within(picker).getByRole('button', { name: kind })).toBeInTheDocument();
    }
    expect(within(picker).getAllByRole('button')).toHaveLength(3);
    for (const gone of ['Stream URL', 'HDMI', 'BNC', 'UART', 'Embedded (Pi)']) {
      expect(within(picker).queryByRole('button', { name: gone })).toBeNull();
    }
  });

  it('★ each kind asks only for what it needs: an address, a device, or a serial port', () => {
    mount('/cameras/new');
    openStep('How does it connect?');
    const picker = screen.getByRole('group', { name: 'Connection type' });
    expect(screen.getByLabelText('Video address')).toBeVisible();
    fireEvent.click(within(picker).getByRole('button', { name: 'Serial / UART' }));
    expect(screen.getByLabelText('Serial port')).toBeVisible();
    expect(screen.queryByLabelText('Video address')).toBeNull();
    fireEvent.click(within(picker).getByRole('button', { name: 'USB / capture card' }));
    expect(screen.getByText(/Capture cards and cameras on this machine/)).toBeVisible();
  });

  it('★ the protocol is a picker, not something to type — and only what the server opens', () => {
    mount('/cameras/new');
    openStep('How does it connect?');
    // Video: the capture's own schemes. Data: the feed's four, ws and tcp included.
    const video = screen.getByLabelText('Video protocol');
    const data = screen.getByLabelText('Data feed protocol');
    expect(video).toHaveTextContent('rtsp://');
    expect(data).toHaveTextContent('http://');

    // Choosing a protocol before an address is typed leaves the address EMPTY —
    // "rtsp://" alone is not an address and must not raise its error.
    fireEvent.mouseDown(video);
    fireEvent.click(within(screen.getByRole('listbox')).getByText('https://'));
    expect(useCameraDraftStore.getState().draft.source).toBe('');

    // …and once a host is typed the two are one address again.
    fireEvent.change(screen.getByLabelText('Video address'), {
      target: { value: 'cam.local:554/live' },
    });
    expect(useCameraDraftStore.getState().draft.source).toBe('https://cam.local:554/live');

    fireEvent.mouseDown(data);
    const options = within(screen.getByRole('listbox'));
    for (const scheme of ['http://', 'https://', 'ws://', 'wss://', 'tcp://']) {
      expect(options.getByText(scheme)).toBeVisible();
    }
    fireEvent.click(options.getByText('ws://'));
    fireEvent.change(screen.getByLabelText('Data feed (optional)'), {
      target: { value: '10.0.0.4:9000/feed' },
    });
    expect(useCameraDraftStore.getState().draft.dataUrl).toBe('ws://10.0.0.4:9000/feed');
  });

  it('★ the DEM step creates the backing project on demand — the draft remembers it', async () => {
    mount('/cameras/new');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Roof Pi' } });
    openStep('Camera DEM');
    fireEvent.click(screen.getByRole('button', { name: 'Attach the camera’s DEM' }));
    await waitFor(() => expect(projectCreate).toHaveBeenCalled());
    expect(projectCreate.mock.calls[0][0]).toMatchObject({
      name: 'Camera: Roof Pi',
      tags: ['camera'],
    });
    expect(await screen.findByTestId('dem-card')).toHaveTextContent(PROJECT);
    expect(useCameraDraftStore.getState().draft.project_id).toBe(PROJECT);
    // no camera row yet — the server list is untouched until the last press
    expect(fake.rows.size).toBe(0);
  });

  it('★ the draft is what typing edits, and it survives leaving the page', () => {
    mount('/cameras/new');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Gate' } });
    fireEvent.click(screen.getByText('mock-map'));
    const d = useCameraDraftStore.getState().draft;
    expect(d.name).toBe('Gate');
    expect(d.lat).toBe('34.104264');
    expect(screen.getByRole('button', { name: 'Discard draft' })).toBeVisible();
  });

  it('★ "Place control points" opens the editor addressed by the DRAFT (/cameras/new/editor)', async () => {
    useCameraDraftStore.setState({
      draft: { ...EMPTY_DRAFT, name: 'Gate', project_id: PROJECT, frame_image_id: IMAGE },
      touchedAt: new Date().toISOString(),
    });
    mount('/cameras/new');
    openStep('The frame, and its control points');
    expect(screen.getByText('frame.jpg')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Place control points' }));
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/cameras/new/editor'));
  });

  it('★ Add camera posts the WHOLE draft as one row — project, frame, calibration, table — and clears it', async () => {
    useCameraDraftStore.setState({
      draft: {
        ...EMPTY_DRAFT,
        name: 'Roof Pi',
        connection: 'lan',
        source: 'rtsp://roof/stream',
        lat: '34.104264',
        lon: '36.015782',
        calibration: { fx: '1200', fy: '1200' },
        project_id: PROJECT,
        frame_image_id: IMAGE,
        lut_site: 'roof_pi',
      },
      touchedAt: new Date().toISOString(),
    });
    mount('/cameras/new');
    fireEvent.click(screen.getByRole('button', { name: 'Add camera to the server' }));
    await waitFor(() => expect(fake.rows.size).toBe(1));
    const row = [...fake.rows.values()][0];
    expect(row).toMatchObject({
      name: 'Roof Pi',
      connection: 'lan',
      provides: 'camera',
      source: 'rtsp://roof/stream',
      project_id: PROJECT,
      frame_image_id: IMAGE,
      lut_site: 'roof_pi',
    });
    expect(row.calibration).toMatchObject({ fx: 1200, fy: 1200 });
    expect(useCameraDraftStore.getState().draft).toEqual(EMPTY_DRAFT);
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/cameras'));
  });

  it('★ a UART line without a port is refused by name, and nothing is created', async () => {
    mount('/cameras/new');
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Board' } });
    const picker = screen.getByRole('group', { name: 'Connection type' });
    fireEvent.click(within(picker).getByRole('button', { name: 'Serial / UART' }));
    fireEvent.click(screen.getByText('mock-map'));
    fireEvent.click(screen.getByRole('button', { name: 'Add camera to the server' }));
    expect(await screen.findByText(/A data feed is required/)).toBeVisible();
    expect(fake.rows.size).toBe(0);
  });
});

describe('an EXISTING camera', () => {
  const ROOF: RegisteredCamera = {
    id: '00000000-0000-4000-8000-000000000102',
    name: 'Roof Pi',
    lat: 33.9,
    lon: 35.5,
    source: 'http://pi.local:8080/stream',
    connection: 'lan',
    project_id: PROJECT,
    frame_image_id: IMAGE,
    created_at: '2026-09-04T08:00:00Z',
  };

  beforeEach(async () => {
    await fake.api.import([
      { ...ROOF, project_id: PROJECT as Uuid, frame_image_id: IMAGE as Uuid, client_id: 'roof' },
    ]);
    const row = [...fake.rows.values()][0];
    useCameraRegistryStore.setState({ cameras: [{ ...ROOF, id: row.id }] });
  });
  const id = (): string => useCameraRegistryStore.getState().cameras[0].id;

  it('★ shows the DEM card for its backing project and the frame it already has', () => {
    demActive.mockReturnValue(true);
    mount(`/cameras/${id()}/settings`);
    expect(screen.getByRole('heading', { name: 'Roof Pi' })).toBeVisible();
    expect(screen.getByTestId('dem-card')).toHaveTextContent(PROJECT);
    openStep('The frame, and its control points');
    expect(screen.getByText('frame.jpg')).toBeVisible();
    expect(screen.getAllByRole('button', { name: 'Save camera' })).toHaveLength(1);
  });

  it('★ "Place control points" saves the draft and opens the camera’s own editor', async () => {
    const updateSpy = vi.spyOn(fake.api, 'update');
    mount(`/cameras/${id()}/settings`);
    openStep('The frame, and its control points');
    fireEvent.click(screen.getByRole('button', { name: 'Place control points' }));
    await waitFor(() => expect(updateSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId('loc')).toHaveTextContent(`/cameras/${id()}/editor`),
    );
  });

  it('★ the lookup-table step names what is still needed; four points unlock the build', () => {
    demActive.mockReturnValue(false);
    gcpTotal.mockReturnValue(2);
    stationFx.mockReturnValue(null);
    mount(`/cameras/${id()}/settings`);
    openStep('Lookup table');
    const note = screen.getByText(/Still needed/);
    expect(note).toHaveTextContent('2 more control point(s)');
    expect(note).toHaveTextContent('a DEM');
    expect(note).toHaveTextContent('calibration (fx, fy — or no-calibration mode');
    expect(screen.getByRole('button', { name: 'Build lookup table' })).toBeDisabled();
    // the frame's missing focal length is said plainly in step 5 too
    openStep('Optional data — camera calibration');
    expect(screen.getByText(/The frame has no focal length yet/)).toBeVisible();
  });

  it('★ with four points the build is enabled even while something else is named', () => {
    demActive.mockReturnValue(false);
    gcpTotal.mockReturnValue(4);
    mount(`/cameras/${id()}/settings`);
    openStep('Lookup table');
    expect(screen.getByText(/Still needed/)).toHaveTextContent('a DEM');
    expect(screen.getByRole('button', { name: 'Build lookup table' })).toBeEnabled();
  });

  it('★ GEO-DRIFT C3: "No calibration" solves the focal from the points — the station carries the mode and its seed', async () => {
    stationFx.mockReturnValue(null);
    stationPut.mockClear();
    useCameraRegistryStore.setState((st) => ({
      cameras: st.cameras.map((c) => ({ ...c, fov_deg: 72 })),
    }));
    mount(`/cameras/${id()}/settings`);
    openStep('Optional data — camera calibration');
    // the old fixed-focal estimate is gone; the mode is a switch
    expect(screen.queryByRole('button', { name: 'Estimate from the field of view' })).toBeNull();
    const toggle = screen.getByRole('checkbox', { name: 'No calibration' });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
    expect(screen.getByText(/Seeded by the field of view at step 3/)).toBeVisible();
    // the intrinsics boxes are ignored in this mode
    expect(screen.getByLabelText('fx')).toBeDisabled();
    // …and the station is rewritten with the mode and its seed, a moment after
    await waitFor(
      () =>
        expect(stationPut.mock.calls.at(-1)?.[1]).toMatchObject({
          no_calibration: true,
          fov_h_deg: 72,
          fx: null,
          fy: null,
        }),
      { timeout: 3000 },
    );
  });

  it('★ 2026-09-09: "No calibration" with a BLANK field of view is enough — the solve starts from the default seed', async () => {
    stationFx.mockReturnValue(null);
    stationNoCal.mockReturnValue(true); // the frame's station: mode on, no seed
    gcpTotal.mockReturnValue(4);
    demActive.mockReturnValue(true);
    mount(`/cameras/${id()}/settings`);
    openStep('Optional data — camera calibration');
    // the form mirrors the station: the switch is on, and the caption names the default
    expect(screen.getByRole('checkbox', { name: 'No calibration' })).toBeChecked();
    expect(screen.getByText(/default 60° seed/)).toBeVisible();
    // nothing is still needed — no "with a field of view" demand — and the build is open
    expect(screen.queryByText(/calibration \(fx, fy/)).toBeNull();
    openStep('Lookup table');
    expect(screen.getByText('Everything the build needs is in place.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Build lookup table' })).toBeEnabled();
  });

  it('★ 2026-09-09: switching the mode on with a blank field of view writes the station with NO seed', async () => {
    stationFx.mockReturnValue(null);
    stationPut.mockClear();
    mount(`/cameras/${id()}/settings`);
    openStep('Optional data — camera calibration');
    fireEvent.click(screen.getByRole('checkbox', { name: 'No calibration' }));
    await waitFor(
      () =>
        expect(stationPut.mock.calls.at(-1)?.[1]).toMatchObject({
          no_calibration: true,
          fov_h_deg: null,
          fx: null,
        }),
      { timeout: 3000 },
    );
  });

  it('★ with four points and a DEM, Build runs and the table becomes the camera’s own', async () => {
    demActive.mockReturnValue(true);
    gcpTotal.mockReturnValue(4);
    mount(`/cameras/${id()}/settings`);
    const build = screen.getByRole('button', { name: 'Build lookup table' });
    expect(build).toBeEnabled();
    fireEvent.click(build);
    await waitFor(() => expect(lutCreate).toHaveBeenCalled());
    await waitFor(() => expect(fake.rows.get(id())?.lut_site).toBe('roof_pi'));
    openStep('Lookup table'); // the panel moved on to row 8 (drift watch) once the table existed
    expect(await screen.findByRole('button', { name: 'Rebuild lookup table' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Watch this camera' })).toBeVisible();
  });

  it('★ 2026-09-08: the built table freezes the drift reference on the frame; a new frame re-freezes it', async () => {
    demActive.mockReturnValue(true);
    gcpTotal.mockReturnValue(4);
    mount(`/cameras/${id()}/settings`);
    // Before the table: the frame step says WHEN the watch starts and offers no freeze.
    expect(screen.getByTestId('camera-drift-status')).toHaveTextContent(
      'once the lookup table is built',
    );
    expect(screen.queryByRole('button', { name: /reeze on this frame/ })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Build lookup table' }));
    await waitFor(() => expect(fake.rows.get(id())?.lut_site).toBe('roof_pi'));
    // The freeze FOLLOWED the table — on the server, recorded as the row's watch,
    // mirrored into the registry so the monitor page reads it at once.
    await waitFor(() => expect(fake.rows.get(id())?.desired.watch?.ref_id).toBeTruthy());
    const first = fake.rows.get(id())?.desired.watch?.ref_id;
    await waitFor(() =>
      expect(useCameraRegistryStore.getState().cameras[0].desired?.watch?.ref_id).toBe(first),
    );
    openStep('The frame, and its control points');
    openStep('Drift watch');
    expect(await screen.findByText(/Drift reference frozen on this frame/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Re-freeze on this frame' })).toBeEnabled();

    // A NEW frame is the one way to re-freeze: capture → adopt → a fresh reference.
    const shot = { filename: 'shot.jpg', file_url: '/x', saved_to: null };
    vi.mocked(liveApi.captureFrame).mockResolvedValue(shot as never);
    vi.mocked(liveApi.captureDeviceFrame).mockResolvedValue(shot as never);
    vi.mocked(captureLibraryApi.importIntoProject).mockResolvedValue({
      id: IMAGE2,
      filename: 'shot.jpg',
      width: 1280,
      height: 720,
    } as never);
    openStep('The frame, and its control points');
    fireEvent.click(screen.getByRole('button', { name: 'Capture from the camera now' }));
    // ★ 2026-09-09: the button opens the LIVE picture; the frame is chosen there —
    //   and, over a frame with points, the camera is asked whether it moved.
    fireEvent.click(await screen.findByRole('button', { name: 'Capture this frame' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Use this frame' }));
    fireEvent.click(await screen.findByTestId('frame-change-same-aim'));
    await waitFor(() => expect(fake.rows.get(id())?.frame_image_id).toBe(IMAGE2));
    await waitFor(() => expect(fake.rows.get(id())?.desired.watch?.ref_id).not.toBe(first));
    expect(fake.rows.get(id())?.desired.watch?.ref_id).toBeTruthy();
  });

  async function captureNewFrame(): Promise<void> {
    const shot = { filename: 'shot.jpg', file_url: '/x', saved_to: null };
    vi.mocked(liveApi.captureFrame).mockResolvedValue(shot as never);
    vi.mocked(liveApi.captureDeviceFrame).mockResolvedValue(shot as never);
    vi.mocked(captureLibraryApi.importIntoProject).mockResolvedValue({
      id: IMAGE2,
      filename: 'shot.jpg',
      width: 1280,
      height: 720,
    } as never);
    openStep('The frame, and its control points');
    fireEvent.click(screen.getByRole('button', { name: 'Capture from the camera now' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Capture this frame' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Use this frame' }));
  }

  it('★ 2026-09-09: a new frame over one with points asks "Has the camera moved?" — same aim carries the points and keeps the table', async () => {
    gcpTotal.mockReturnValue(6);
    useCameraRegistryStore.setState((st) => ({ cameras: st.cameras.map((c) => ({ ...c, lut_site: 'roof_pi' })) }));
    await fake.api.update(id(), { lut_site: 'roof_pi' });
    mount(`/cameras/${id()}/settings`);
    await captureNewFrame();
    // nothing adopted yet — the question comes first
    expect(await screen.findByText('Has the camera moved?')).toBeVisible();
    expect(fake.rows.get(id())?.frame_image_id).toBe(IMAGE);
    fireEvent.click(screen.getByTestId('frame-change-same-aim'));
    await waitFor(() => expect(fake.rows.get(id())?.frame_image_id).toBe(IMAGE2));
    await waitFor(() => expect(gcpCopy).toHaveBeenCalledWith(IMAGE2, IMAGE));
    expect(fake.rows.get(id())?.lut_site).toBe('roof_pi');
    expect(driftStop).not.toHaveBeenCalled();
  });

  it('★ 2026-09-09: "it moved" starts the points afresh, detaches the table and stops its watch', async () => {
    gcpTotal.mockReturnValue(6);
    useCameraRegistryStore.setState((st) => ({
      cameras: st.cameras.map((c) => ({
        ...c,
        lut_site: 'roof_pi',
        desired: { watch: { ref_id: 'a'.repeat(32), interval_s: 10 }, detect: null, feed: false },
      })),
    }));
    await fake.api.update(id(), { lut_site: 'roof_pi' });
    mount(`/cameras/${id()}/settings`);
    await captureNewFrame();
    fireEvent.click(await screen.findByTestId('frame-change-moved'));
    await waitFor(() => expect(fake.rows.get(id())?.frame_image_id).toBe(IMAGE2));
    expect(fake.rows.get(id())?.lut_site).toBeNull();
    expect(gcpCopy).not.toHaveBeenCalled();
    await waitFor(() => expect(driftStop).toHaveBeenCalledWith('a'.repeat(32), id()));
  });

  it('a frame with NO points is adopted without the question', async () => {
    gcpTotal.mockReturnValue(0);
    mount(`/cameras/${id()}/settings`);
    await captureNewFrame();
    await waitFor(() => expect(fake.rows.get(id())?.frame_image_id).toBe(IMAGE2));
    expect(screen.queryByText('Has the camera moved?')).toBeNull();
  });

  it('★ Save camera patches the row and returns to the server', async () => {
    mount(`/cameras/${id()}/settings`);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Roof Pi 2' } });
    fireEvent.change(screen.getByLabelText('fx'), { target: { value: '1200' } });
    fireEvent.change(screen.getByLabelText('fy'), { target: { value: '1200' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save camera' }));
    await waitFor(() => expect(fake.rows.get(id())?.name).toBe('Roof Pi 2'));
    expect(fake.rows.get(id())?.calibration).toMatchObject({ fx: 1200, fy: 1200 });
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/cameras'));
  });
});
