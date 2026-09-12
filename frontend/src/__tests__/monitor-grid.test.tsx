/**
 * The monitor's GRID view and the integration model behind it (2026-09-02).
 *
 * ★ What these pin: the fleet renders as tiles (camera tiles stream, data-only
 *   tiles say so honestly), the tile is a PROBE feeding the registry's statuses,
 *   search narrows, a click opens the camera — and the registry's validator
 *   enforces the integration rules: serial is data (never video), a data
 *   integration needs a data feed, video+data derives 'both'.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));
vi.mock('../api/detection', async (importOriginal) => {
  // eslint-disable-next-line @typescript-eslint/consistent-type-imports -- vitest's partial-mock idiom
  const real = await importOriginal<typeof import('../api/detection')>();
  return {
    ...real,
    detectionApi: {
      ...real.detectionApi,
      list: vi.fn(async () => ({ items: [] })),
      start: vi.fn(async () => ({}) as never),
      stop: vi.fn(async () => undefined),
    },
  };
});

import { detectionApi } from '../api/detection';
import { CameraGridView } from '../components/monitor/globe/CameraGridView';
import { useMonitorSettingsStore } from '../store/monitorSettingsStore';

function grid(ui: React.ReactElement): ReturnType<typeof render> {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}
import { setLanguage } from '../i18n';
import {
  looksLikeDataSource,
  useCameraRegistryStore,
  validateCamera,
  type RegisteredCamera,
} from '../store/cameraRegistryStore';

const CAM = (over: Partial<RegisteredCamera>): RegisteredCamera => ({
  id: over.id ?? 'cam-1',
  name: over.name ?? 'Gate',
  lat: 34.1,
  lon: 36.0,
  source: 'http://cam/stream',
  created_at: new Date().toISOString(),
  ...over,
});

beforeEach(() => {
  setLanguage('en');
  useCameraRegistryStore.setState({ cameras: [], statuses: {} });
});

describe('the grid view', () => {
  it('★ camera tiles stream; a data-only tile says so instead of faking a picture', () => {
    grid(
      <CameraGridView
        cameras={[
          CAM({ id: 'a', name: 'North gate' }),
          CAM({
            id: 'b',
            name: 'Field sensor',
            source: '',
            connection: 'serial',
            provides: 'data',
            data_source: 'serial:///dev/ttyUSB0?baud=115200',
          }),
        ]}
        onOpen={() => undefined}
      />,
    );
    expect(screen.getByText('North gate')).toBeVisible();
    // The streaming tile carries an <img> on the proxy; the data tile carries none.
    expect(document.querySelectorAll('img')).toHaveLength(1);
    expect(screen.getByText('DATA FEED — NO PICTURE')).toBeVisible();
    expect(screen.getByText('Serial / UART')).toBeVisible();
    expect(screen.getByText('detection data')).toBeVisible();
    expect(screen.getByText('2 / 2 cameras')).toBeVisible();
  });

  it('★ the tile is a probe: a dead stream marks the camera LOST in the registry', () => {
    useCameraRegistryStore.setState({ cameras: [CAM({ id: 'a' })] });
    grid(<CameraGridView cameras={[CAM({ id: 'a' })]} onOpen={() => undefined} />);
    fireEvent.error(document.querySelector('img')!);
    expect(useCameraRegistryStore.getState().statuses.a?.state).toBe('lost');
    expect(screen.getByText('SIGNAL LOST')).toBeVisible();
    // …and load marks it live again after a retry remount.
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    fireEvent.load(document.querySelector('img')!);
    expect(useCameraRegistryStore.getState().statuses.a?.state).toBe('live');
  });

  it('★ a tile CANCELS its stream on unmount — a zombie <img> must not hold the device', () => {
    const { unmount } = grid(
      <CameraGridView cameras={[CAM({ id: 'a' })]} onOpen={() => undefined} />,
    );
    const img = document.querySelector('img')!;
    expect(img.getAttribute('src')).toBe('http://cam/stream');
    unmount();
    // Blanked, not merely detached: this is what actually aborts the download.
    expect(img.getAttribute('src')).toBe('');
  });

  it('★ one click starts detection WITH the camera’s saved setup; Stop stops it', async () => {
    useMonitorSettingsStore.setState({
      byCamera: {
        a: {
          model: 'yolo26s.pt',
          lutSite: 'MONODEMO',
          classes: [0, 2],
          conf: 0.4,
          imgszChoice: 640,
          trackerStart: 30,
          trackerType: 'kcf',
          centreMarks: false,
          steadyBoxes: true,
          savedAt: new Date().toISOString(),
        },
      },
    });
    grid(<CameraGridView cameras={[CAM({ id: 'a' })]} onOpen={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: 'Start detection' }));
    await waitFor(() =>
      expect(vi.mocked(detectionApi.start)).toHaveBeenCalledWith({
        source: 'http://cam/stream',
        lut_site: 'MONODEMO',
        conf: 0.4,
        imgsz: 640,
        model: 'yolo26s.pt',
        // ★ Never auto-lock (2026-09-03): a saved trackerStart of 30 is IGNORED —
        //   the monitoring workspace tracks only what the operator clicks.
        tracker_start_frame: 0,
        tracker_type: 'kcf',
        classes: [0, 2],
        steady_boxes: true,
      }),
    );
  });

  it('★ a detecting tile streams the SESSION (boxes burned in) and offers Stop', async () => {
    vi.mocked(detectionApi.list).mockResolvedValue({
      items: [
        {
          session_id: 'wall-1',
          source: 'http://cam/stream',
          status: 'running',
          marks_total: 12,
          fps: 9.6,
        } as never,
      ],
    });
    grid(<CameraGridView cameras={[CAM({ id: 'a' })]} onOpen={() => undefined} />);
    expect(await screen.findByText('DETECTING · 12 · 10 fps')).toBeVisible();
    const img = document.querySelector('img')!;
    expect(img.getAttribute('src')).toContain('/detection/sessions/wall-1/stream');
    fireEvent.click(screen.getByRole('button', { name: 'Stop detection' }));
    await waitFor(() => expect(vi.mocked(detectionApi.stop)).toHaveBeenCalledWith('wall-1'));
  });

  it('★ a detecting tile flashes an icon of what it is seeing', async () => {
    vi.mocked(detectionApi.list).mockResolvedValue({
      items: [
        {
          session_id: 'wall-e',
          source: 'http://cam/stream',
          status: 'running',
          marks_total: 3,
          fps: 8,
          counts: { person: 4, car: 2 },
        } as never,
      ],
    });
    grid(<CameraGridView cameras={[CAM({ id: 'a' })]} onOpen={() => undefined} />);
    // The classes whose count rose since the (empty) baseline alert now.
    expect(await screen.findByLabelText('detecting: person')).toBeVisible();
    expect(screen.getByLabelText('detecting: car')).toBeVisible();
  });

  it('★ the wall filters by what it is seeing: All · Live · Lost — and offers no Add', () => {
    useCameraRegistryStore.setState({
      cameras: [CAM({ id: 'a', name: 'gate' }), CAM({ id: 'b', name: 'roof' })],
      statuses: { a: { state: 'live', at: 1 }, b: { state: 'lost', at: 1 } },
    });
    grid(
      <CameraGridView
        cameras={[CAM({ id: 'a', name: 'gate' }), CAM({ id: 'b', name: 'roof' })]}
        onOpen={() => undefined}
      />,
    );
    // ★ Registering a camera is the camera workspace's pipeline (2026-09-07).
    expect(screen.queryByRole('button', { name: 'Add camera' })).toBeNull();
    expect(screen.getByText('2 / 2', { exact: false })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Live' }));
    expect(screen.getByText('gate')).toBeVisible();
    expect(screen.queryByText('roof')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Lost' }));
    expect(screen.getByText('roof')).toBeVisible();
    expect(screen.queryByText('gate')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    expect(screen.getByText('gate')).toBeVisible();
    expect(screen.getByText('roof')).toBeVisible();
  });

  it('search narrows; a click opens the camera', () => {
    const onOpen = vi.fn();
    grid(
      <CameraGridView
        cameras={[CAM({ id: 'a', name: 'North gate' }), CAM({ id: 'b', name: 'South field' })]}
        onOpen={onOpen}
      />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Search cameras' }), {
      target: { value: 'south' },
    });
    expect(screen.queryByText('North gate')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Open South field' }));
    expect(onOpen).toHaveBeenCalledWith('b');
  });
});

describe('the integration rules in the validator', () => {
  const BASE = { name: 'x', lat: 34, lon: 36 };

  it('★ serial is DATA — it needs a feed, never a video source', () => {
    const ok = validateCamera({
      ...BASE,
      connection: 'serial',
      provides: 'data',
      data_source: 'serial:///dev/ttyUSB0?baud=115200',
    });
    expect(ok.ok).toBe(true);
    if (ok.ok) {
      expect(ok.value.provides).toBe('data');
      expect(ok.value.source).toBe('');
    }
    // No feed → refused with the field named.
    const bad = validateCamera({ ...BASE, connection: 'serial' });
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.errors.some((e) => e.field === 'data_source')).toBe(true);
    // Claiming video over serial is refused — a promise nothing can keep.
    const lie = validateCamera({
      ...BASE,
      connection: 'serial',
      provides: 'camera',
      source: 'http://x/s',
    });
    expect(lie.ok).toBe(false);
  });

  it("'both' needs both; each half is checked for its own shape", () => {
    const ok = validateCamera({
      ...BASE,
      connection: 'embedded',
      provides: 'both',
      source: 'http://pi/stream',
      data_source: 'http://pi:9000/detections',
    });
    expect(ok.ok).toBe(true);
    const noData = validateCamera({ ...BASE, provides: 'both', source: 'http://pi/stream' });
    expect(noData.ok).toBe(false);
    const badFeed = validateCamera({
      ...BASE,
      provides: 'both',
      source: 'http://pi/stream',
      data_source: 'ftp://nope',
    });
    expect(badFeed.ok).toBe(false);
  });

  it('an old row without the new fields is still a plain LAN camera', () => {
    const ok = validateCamera({ ...BASE, source: 'http://cam/stream' });
    expect(ok.ok).toBe(true);
    if (ok.ok) {
      // Defaults stay OFF the row — old exports import byte-identical.
      expect('connection' in ok.value).toBe(false);
      expect('provides' in ok.value).toBe(false);
    }
  });

  it('looksLikeDataSource knows the three wire shapes', () => {
    expect(looksLikeDataSource('serial:///dev/ttyUSB0?baud=115200')).toBe(true);
    expect(looksLikeDataSource('/dev/ttyACM0')).toBe(true);
    expect(looksLikeDataSource('http://pi:9000/detections')).toBe(true);
    expect(looksLikeDataSource('/dev/video0')).toBe(false);
    expect(looksLikeDataSource('')).toBe(false);
  });
});
