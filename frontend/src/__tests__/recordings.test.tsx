/**
 * Recording a session into the library — the header control and the library UI.
 *
 * ★ What these pin: Record shows while watching and flips to a red REC while
 *   recording (and to Saving… while finalizing), the library lists one row per
 *   folder with video + CSV downloads pointing at the folder's OWN files, and
 *   delete removes the row.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { setLanguage } from '../i18n';

vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));
vi.mock('../api/live', async (importOriginal) => {
  // eslint-disable-next-line @typescript-eslint/consistent-type-imports -- vitest's own partial-mock idiom
  const real = await importOriginal<typeof import('../api/live')>();
  return {
    ...real,
    liveApi: {
      ...real.liveApi,
      listRecordings: vi.fn(async () => ({
        root: '/home/user/Pictures/LandExplorer/recordings',
        items: [
          {
            folder: 'Field-gate-20260902-120000',
            path: '/home/user/Pictures/LandExplorer/recordings/Field-gate-20260902-120000',
            camera_name: 'Field gate',
            source: 'http://cam/stream',
            started_at: '2026-09-02T12:00:00Z',
            ended_at: '2026-09-02T12:01:30Z',
            duration_s: 90,
            frames: 900,
            marks: 42,
            video_bytes: 12_000_000,
            has_video: true,
            has_csv: true,
          },
        ],
      })),
      deleteRecording: vi.fn(async () => undefined),
    },
  };
});

import { liveApi } from '../api/live';
import { GlobeHud } from '../components/monitor/globe/GlobeHud';
import { MonitorHeader, type MonitorHeaderProps } from '../components/monitor/camera/MonitorHeader';
import { RecordingsLibrary } from '../components/video/RecordingsLibrary';

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

const HEADER: MonitorHeaderProps = {
  camera: {
    id: 'cam-a',
    name: 'gate',
    lat: 34.1,
    lon: 36.0,
    source: 'http://cam/stream',
    created_at: new Date().toISOString(),
  },
  status: 'live',
  dirty: false,
  detecting: false,
  starting: false,
  runStartedAt: null,
  startBlocker: null,
  startError: null,
  onDismissError: () => undefined,
  onApply: () => undefined,
  onStart: () => undefined,
  onStop: () => undefined,
  trackedCount: 0,
  onCapture: () => undefined,
  captureBusy: false,
  recordingStartedAt: null,
  recordBusy: false,
  onToggleRecord: () => undefined,
  onOpenLibrary: () => undefined,
};

function mountHeader(over: Partial<MonitorHeaderProps>): void {
  setLanguage('en');
  render(
    <MemoryRouter>
      <MonitorHeader {...HEADER} {...over} />
    </MemoryRouter>,
  );
}

describe('the Record control', () => {
  it('★ offers Record while watching; a click reaches the handler', () => {
    const onToggle = vi.fn();
    mountHeader({ onToggleRecord: onToggle });
    fireEvent.click(screen.getByRole('button', { name: /Record$/ }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    // The library door sits beside it.
    expect(screen.getByRole('button', { name: 'Recorded videos' })).toBeVisible();
  });

  it('shows a red REC with elapsed time while recording, and Saving… while finalizing', () => {
    mountHeader({ recordingStartedAt: Date.now() - 65_000 });
    expect(screen.getByText(/REC/)).toBeVisible();
    expect(screen.getByText('01:05')).toBeVisible();
  });

  it('needs the stream live to START, but Stop stays reachable regardless', () => {
    mountHeader({ status: 'connecting' });
    expect(screen.getByRole('button', { name: /Record$/ })).toBeDisabled();
    // A recording in flight can always be stopped — even if the stream dropped.
    document.body.innerHTML = '';
    mountHeader({ status: 'lost', recordingStartedAt: Date.now() });
    expect(screen.getByText(/REC/).closest('button')).toBeEnabled();
  });
});

describe('the fleet HUD keeps only what is happening now', () => {
  it('★ no library door on the strip — Recorded videos is its own page (2026-09-12)', () => {
    setLanguage('en');
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter>
        <QueryClientProvider client={qc}>
          <GlobeHud
            view="grid"
            onView={() => undefined}
            cameras={2}
            live={1}
            lost={0}
            provider={undefined}
            hudOpen={false}
            onToggleHud={() => undefined}
            onHelp={() => undefined}
          />
        </QueryClientProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByRole('button', { name: 'Recorded videos' })).toBeNull();
  });
});

describe('the recordings on the Recorded videos page', () => {
  beforeEach(() => setLanguage('en'));

  function mountLibrary(): void {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/videos']}>
          <RecordingsLibrary />
          <Routes>
            <Route path="*" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('★ a row opens the recording’s own page — the video beside its table', async () => {
    mountLibrary();
    await screen.findByText('Field-gate-20260902-120000');
    fireEvent.click(
      screen.getByRole('button', { name: 'Open this recording Field-gate-20260902-120000' }),
    );
    expect(screen.getByTestId('loc')).toHaveTextContent(
      '/videos/recordings/Field-gate-20260902-120000',
    );
  });

  it('★ one card per folder; its menu holds downloads pointing at the folder’s own files', async () => {
    mountLibrary();
    expect(await screen.findByText('Field-gate-20260902-120000')).toBeVisible();
    expect(screen.getByText(/42 marks/)).toBeVisible();
    fireEvent.click(
      screen.getByRole('button', { name: 'More actions for Field-gate-20260902-120000' }),
    );
    const video = screen.getByRole('menuitem', { name: /Download the video/ });
    expect(video).toHaveAttribute(
      'href',
      expect.stringContaining('/live/recordings/files/Field-gate-20260902-120000/video.mp4'),
    );
    const csvLink = screen.getByRole('menuitem', { name: /Download the attribute table/ });
    expect(csvLink).toHaveAttribute(
      'href',
      expect.stringContaining('/live/recordings/files/Field-gate-20260902-120000/detections.csv'),
    );
    // The library's disk path is shown, copyable.
    expect(screen.getByText('/home/user/Pictures/LandExplorer/recordings')).toBeVisible();
  });

  it('delete asks first, then calls the API for that folder', async () => {
    mountLibrary();
    await screen.findByText('Field-gate-20260902-120000');
    fireEvent.click(
      screen.getByRole('button', { name: 'More actions for Field-gate-20260902-120000' }),
    );
    fireEvent.click(screen.getByRole('menuitem', { name: /Delete this recording/ }));
    expect(screen.getByText('Delete this recording?')).toBeVisible();
    expect(vi.mocked(liveApi.deleteRecording)).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() =>
      expect(vi.mocked(liveApi.deleteRecording)).toHaveBeenCalledWith('Field-gate-20260902-120000'),
    );
  });
});

describe('the session package — one button takes the whole scene (2026-09-12)', () => {
  function mountLibrary(): void {
    setLanguage('en');
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <RecordingsLibrary />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('★ the card offers the package, pointed at the one endpoint that builds it', async () => {
    mountLibrary();
    await screen.findByText('Field-gate-20260902-120000');

    const button = screen.getByRole('link', { name: /Package/ });
    expect(button).toHaveAttribute(
      'href',
      liveApi.recordingPackageUrl('Field-gate-20260902-120000'),
    );
    expect(button).toHaveAttribute('download');
  });

  it('★ the satellite map download is offered, and refused when the folder has none', async () => {
    mountLibrary();
    await screen.findByText('Field-gate-20260902-120000');
    fireEvent.click(
      screen.getByRole('button', { name: /More actions for Field-gate-20260902-120000/ }),
    );

    // The whole package first — it is what keeping a session means.
    expect(
      await screen.findByRole('menuitem', { name: /Download the whole package/ }),
    ).toHaveAttribute('href', liveApi.recordingPackageUrl('Field-gate-20260902-120000'));
    // ★ has_map is absent on this fixture: the map item must be disabled, not a
    //   link to a file the folder does not carry.
    const map = screen.getByRole('menuitem', { name: 'Download the satellite map' });
    expect(map).toHaveAttribute('aria-disabled', 'true');
  });
});
