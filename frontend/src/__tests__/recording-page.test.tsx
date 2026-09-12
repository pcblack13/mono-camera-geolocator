/**
 * A recording watched in the app (2026-09-07): the player and the attribute table
 * on one clock.
 *
 * ★ What these pin: the page names the folder and lists the table's rows; picking
 *   a row seeks the video to its second and becomes the cursor; the video's own
 *   clock moving (a `timeupdate`) moves the cursor to the rows at that moment;
 *   the transport steps by a second and by a frame; the trim sends the selection
 *   and the page moves to the new recording it wrote.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import type { RecordingTable } from '../api/live';

const FOLDER = 'Field-gate-20260902-120000';
const TABLE: RecordingTable = {
  folder: FOLDER,
  camera_name: 'gate',
  source: 'http://cam/stream',
  started_at: '2026-09-02T12:00:00Z',
  ended_at: '2026-09-02T12:00:10Z',
  duration_s: 10,
  table: 'marks',
  columns: [],
  has_video: true,
  trimmed_from: null,
  rows: [
    {
      index: 0,
      t: 0.5,
      time_utc: '',
      class_name: 'car',
      score: 0.91,
      lat: 34.1,
      lon: 36.0,
      frame: 5,
      track_id: 1,
      predicted: false,
      drift: 'steady',
      centre_m: null,
      mark_id: 1,
    },
    {
      index: 1,
      t: 3,
      time_utc: '',
      class_name: 'person',
      score: 0.8,
      lat: 34.2,
      lon: 36.1,
      frame: 30,
      track_id: 2,
      predicted: false,
      drift: 'steady',
      centre_m: null,
      mark_id: 2,
    },
    {
      index: 2,
      t: 3.2,
      time_utc: '',
      class_name: 'van',
      score: 0.7,
      lat: 34.3,
      lon: 36.2,
      frame: 32,
      track_id: 3,
      predicted: true,
      drift: null,
      centre_m: null,
      mark_id: 3,
    },
  ],
};

vi.mock('../api/live', () => ({
  liveApi: {
    recordingTable: vi.fn(async () => TABLE),
    trimRecording: vi.fn(async (_folder: string, startS: number, endS: number) => ({
      folder: `${FOLDER}-trim`,
      path: '/x',
      camera_name: 'gate',
      source: '',
      started_at: '',
      ended_at: null,
      duration_s: endS - startS,
      frames: 0,
      marks: 0,
      video_bytes: 0,
      has_video: true,
      has_csv: true,
    })),
    recordingPlayUrl: (folder: string) => `/api/live/recordings/files/${folder}/preview.mp4`,
    recordingFileUrl: (folder: string, file: string) =>
      `/api/live/recordings/files/${folder}/${file}`,
    recordingPackageUrl: (folder: string) => `/api/live/recordings/package/${folder}`,
  },
}));
vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));

import { liveApi } from '../api/live';
import { RecordingPage } from '../pages/RecordingPage';
import { setLanguage } from '../i18n';

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mount(): void {
  setLanguage('en');
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/videos/recordings/${FOLDER}`]}>
        <Routes>
          <Route path="/videos/recordings/:folder" element={<RecordingPage />} />
          <Route path="*" element={null} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const video = (): HTMLVideoElement => {
  const el = document.querySelector('video');
  if (el === null) throw new Error('no video element');
  return el;
};
const rows = (): HTMLElement[] =>
  within(screen.getByRole('rowgroup', { name: 'Rows' })).getAllByRole('row');

beforeEach(() => {
  // jsdom has no media pipeline: play/pause are stubs, the clock is ours to set.
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: vi.fn().mockResolvedValue(undefined),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value: vi.fn(),
  });
});

describe('a recording watched in the app', () => {
  it('★ names the folder, lists the rows, and a picked row seeks the video and becomes the cursor', async () => {
    mount();
    expect(await screen.findByRole('heading', { name: FOLDER })).toBeVisible();
    // the header and the table both count the rows
    expect(screen.getAllByText(/3 rows/).length).toBeGreaterThanOrEqual(2);
    expect(video()).toHaveAttribute('src', expect.stringContaining(`${FOLDER}/preview.mp4`));
    expect(rows()).toHaveLength(3);
    expect(rows()[0]).toHaveTextContent('car');
    // the clock starts at zero: the first row is at hand, nothing selected yet
    expect(screen.getByText(/1 at this moment/)).toBeVisible();

    fireEvent.click(rows()[1]);
    expect(video().currentTime).toBe(3);
    // the rows within half a second of the moment light up; the cursor is the picked row
    expect(rows()[1]).toHaveAttribute('aria-selected', 'true');
    expect(rows()[1]).toHaveAttribute('data-moment', 'true');
    expect(rows()[2]).toHaveAttribute('data-moment', 'true');
    expect(rows()[0]).not.toHaveAttribute('data-moment');
    expect(screen.getByText(/2 at this moment/)).toBeVisible();
  });

  it('★ the video’s own clock moves the table: a timeupdate lands the cursor on that moment’s rows', async () => {
    mount();
    await screen.findByRole('heading', { name: FOLDER });
    const v = video();
    v.currentTime = 3.2;
    fireEvent.timeUpdate(v);
    expect(rows()[2]).toHaveAttribute('aria-selected', 'true');
    expect(rows()[1]).toHaveAttribute('data-moment', 'true');
    v.currentTime = 0.4;
    fireEvent.timeUpdate(v);
    expect(rows()[0]).toHaveAttribute('data-moment', 'true');
    expect(rows()[1]).not.toHaveAttribute('data-moment');
    expect(screen.getByText('0:00.4 / 0:10.0')).toBeVisible();
  });

  it('the transport steps by a second and by a frame, and play reaches the element', async () => {
    mount();
    await screen.findByRole('heading', { name: FOLDER });
    fireEvent.click(screen.getByRole('button', { name: 'Forward 1 s' }));
    expect(video().currentTime).toBe(1);
    fireEvent.click(screen.getByRole('button', { name: 'Forward one frame' }));
    expect(video().currentTime).toBeCloseTo(1.1, 5);
    fireEvent.click(screen.getByRole('button', { name: 'Back 1 s' }));
    expect(video().currentTime).toBeCloseTo(0.1, 5);
    fireEvent.click(screen.getByRole('button', { name: 'Back one frame' }));
    fireEvent.click(screen.getByRole('button', { name: 'Back one frame' }));
    expect(video().currentTime).toBe(0);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it('★ the trim sends the selection and moves to the recording it wrote', async () => {
    mount();
    await screen.findByRole('heading', { name: FOLDER });
    // a selection too short to cut cannot be sent
    fireEvent.click(screen.getByRole('button', { name: 'Forward 1 s' }));
    fireEvent.click(screen.getByRole('button', { name: 'Set start here' }));
    fireEvent.click(rows()[2]); // 3.2 s
    fireEvent.click(screen.getByRole('button', { name: 'Set end here' }));
    expect(screen.getByText('0:01.0 – 0:03.2 · 2.2 s')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Trim to selection' }));
    await waitFor(() =>
      expect(vi.mocked(liveApi.trimRecording)).toHaveBeenCalledWith(FOLDER, 1, 3.2),
    );
    await waitFor(() =>
      expect(screen.getByTestId('loc')).toHaveTextContent(`/videos/recordings/${FOLDER}-trim`),
    );
  });
});
