/**
 * The Live stream page — sources, player, fullscreen, stats, and the honest
 * detections placeholder.
 *
 * ★ jsdom cannot decode MJPEG: `fetch` is stubbed to reject, which exercises the
 *   real fallback path (plain <img>, FPS "not measurable") — the same path a
 *   CORS-blocking camera takes in production.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const captureFrame = vi.fn().mockResolvedValue({
  filename: 'live_pi_20260810_120000.jpg',
  width: 1920,
  height: 1080,
  size_bytes: 250000,
  file_url: '/api/v1/capture-library/live_pi_20260810_120000.jpg',
});
const listDevices = vi.fn().mockResolvedValue({ items: [] });
vi.mock('../api/live', () => ({
  liveApi: {
    captureFrame: (...a: unknown[]) => captureFrame(...a),
    captureDeviceFrame: (...a: unknown[]) => captureFrame(...a),
    listDevices: (...a: unknown[]) => listDevices(...a),
    proxyStreamUrl: (src: string) => `/api/v1/live/stream?src=${encodeURIComponent(src)}`,
  },
}));
const listCaptures = vi.fn().mockResolvedValue({ folder: null, items: [] });
vi.mock('../api/captureLibrary', () => ({
  captureLibraryApi: {
    list: (...a: unknown[]) => listCaptures(...a),
    fileUrl: (f: string) => `/api/v1/capture-library/${f}`,
  },
}));
vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));
vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network in tests')));

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import {
  LiveStreamTab,
  LiveStatsPanel,
  canPreviewInBrowser,
  looksLikeStreamUrl,
} from '../components/live/LiveStreamTab';
import { useLiveSourcesStore } from '../store/liveSourcesStore';

function mount(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <LiveStreamTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useLiveSourcesStore.setState({ sources: [] });
  // ★ vitest.config sets `restoreMocks: true`, which STRIPS each mock's implementation
  //   before every test (clearMocks already wipes call history). Re-establish the
  //   resolved values here — otherwise `captureLibraryApi.list()` returns undefined and
  //   the recent-captures strip's `.then(...)` throws on mount, taking the whole tab
  //   down (the same pattern the workspace-setup smoke test uses for its demApi mock).
  captureFrame.mockResolvedValue({
    filename: 'live_pi_20260810_120000.jpg',
    width: 1920,
    height: 1080,
    size_bytes: 250000,
    file_url: '/api/v1/capture-library/live_pi_20260810_120000.jpg',
  });
  listDevices.mockResolvedValue({ items: [] });
  listCaptures.mockResolvedValue({ folder: null, items: [] });
});

describe('url rules', () => {
  it('previews http(s) only — rtsp is server-side capture', () => {
    expect(canPreviewInBrowser('http://pi:8080/?action=stream')).toBe(true);
    expect(canPreviewInBrowser('rtsp://cam:554/s1')).toBe(false);
  });

  it('accepts only camera-shaped urls', () => {
    expect(looksLikeStreamUrl('rtsp://cam:554/s1')).toBe(true);
    expect(looksLikeStreamUrl('file:///etc/passwd')).toBe(false);
  });
});

describe('LiveStreamTab', () => {
  // ★ 1.2.6: the player panel is MOUNTED FROM PAGE OPEN, showing an idle frame that
  //   says what it is waiting for. Before, the whole panel was absent until a source
  //   was picked, which read as a missing player rather than an idle one. The
  //   ENABLEMENT rule is unchanged — capture stays disabled until a source is live.
  it('★ the player frame is present but idle before any source is chosen', () => {
    mount();
    expect(screen.getByText(/No device scanned yet/)).toBeTruthy();
    // Present, so the page looks complete — but not usable, because nothing is live.
    const capture = screen.getByRole('button', { name: /Capture frame/ });
    expect(capture).toBeTruthy();
    expect((capture as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Add a stream URL above, or scan for local devices/)).toBeTruthy();
  });

  it('adds a source and enables the player with a fullscreen button', async () => {
    mount();
    fireEvent.change(screen.getByLabelText(/Stream URL/), {
      target: { value: 'http://raspberrypi.local:8080/?action=stream' },
    });
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Roof Pi' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    fireEvent.click(screen.getByText('Roof Pi'));

    const capture = screen.getByRole('button', { name: /Capture frame/ });
    expect(capture).toBeTruthy();
    expect((capture as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByRole('button', { name: 'Fullscreen' })).toBeTruthy();
    expect(screen.queryByText(/No device scanned yet/)).toBeNull();
  });

  it('★ the stats panel shows FPS and the honest no-detector placeholder', () => {
    useLiveSourcesStore.setState({
      sources: [{ id: 's1', name: 'Roof Pi', url: 'http://pi:8080/?action=stream' }],
    });
    mount();
    fireEvent.click(screen.getByText('Roof Pi'));
    expect(screen.getByText('Stream statistics')).toBeTruthy();
    expect(screen.getByText('FPS')).toBeTruthy();
    expect(screen.getByText('Detected objects')).toBeTruthy();
    expect(screen.getByText(/No detector connected/)).toBeTruthy();
  });

  it('★ Capture frame opens the name dialog, then calls the server with a name', async () => {
    useLiveSourcesStore.setState({
      sources: [{ id: 's1', name: 'Roof Pi', url: 'http://pi:8080/?action=stream' }],
    });
    mount();
    fireEvent.click(screen.getByText('Roof Pi'));
    // Clicking the toolbar button now opens the capture dialog (name + folder)…
    fireEvent.click(screen.getByRole('button', { name: /Capture frame/ }));
    // …and the dialog's own Capture button is what sends the request.
    const dialogCapture = await screen.findByRole('button', { name: /^Capture$/ });
    fireEvent.click(dialogCapture);
    await waitFor(() =>
      expect(captureFrame).toHaveBeenCalledWith(
        'http://pi:8080/?action=stream',
        expect.objectContaining({ name: 'Roof Pi' }),
      ),
    );
  });

  it('★ rtsp sources preview through the server re-stream — player, not an excuse', () => {
    useLiveSourcesStore.setState({
      sources: [{ id: 's1', name: 'Gate cam', url: 'rtsp://cam:554/s1' }],
    });
    mount();
    fireEvent.click(screen.getByText('Gate cam'));
    // The old "RTSP cannot be watched" alert is gone — the panel now plays rtsp
    // via GET /live/stream, so the player chrome (capture + fullscreen) renders.
    expect(screen.queryByText(/cannot be watched/)).toBeNull();
    expect(screen.getByRole('button', { name: /Capture frame/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Fullscreen' })).toBeTruthy();
  });

  it('★ scanning lists local devices only on the explicit button', async () => {
    listDevices.mockResolvedValueOnce({
      items: [{ id: '/dev/video0', label: 'USB Capture HDMI' }],
    });
    mount();
    expect(listDevices).not.toHaveBeenCalled(); // never probes hardware on mount
    fireEvent.click(screen.getByRole('button', { name: /Scan local devices/ }));
    await waitFor(() => expect(screen.getByText('USB Capture HDMI')).toBeTruthy());
    // Selecting the device enables the same player + capture flow.
    fireEvent.click(screen.getByText('USB Capture HDMI'));
    expect(screen.getByRole('button', { name: /Capture frame/ })).toBeTruthy();
  });

  it('★ the detection settings sit in a BAR, not a popover, and gate on the runtime', () => {
    // ★ The popover went away 2026-08-20: settings that decide what a run does
    //   belong above the panels they govern, not covering the player. The Start
    //   button is still gated — without the runtime there is nothing to start.
    useLiveSourcesStore.setState({
      sources: [{ id: 's1', name: 'Roof Pi', url: 'http://pi:8080/?action=stream' }],
    });
    mount();
    fireEvent.click(screen.getByText('Roof Pi'));
    // The bar's controls are on the page directly — no click needed to reach them.
    expect(screen.getByLabelText('Confidence floor')).toBeTruthy();
    const start = screen.getByRole('button', { name: /Start detection/ });
    expect(start.hasAttribute('disabled')).toBe(true);
  });
});

describe('LiveStatsPanel', () => {
  it('★ renders one labeled entity per detected class, busiest first', () => {
    render(
      <LiveStatsPanel
        stats={{
          fps: 24.9,
          width: 1920,
          height: 1080,
          frames: 500,
          startedAt: Date.now(),
          encoding: 'MJPEG (re-encoded from H264)',
        }}
        fpsMeasurable
        detections={{ person: 3, car: 7, dog: 1 }}
      />,
    );
    expect(screen.getByText('car: 7')).toBeTruthy();
    expect(screen.getByText('person: 3')).toBeTruthy();
    expect(screen.getByText('dog: 1')).toBeTruthy();
    expect(screen.getByText('24.9')).toBeTruthy();
    expect(screen.getByText('1920×1080')).toBeTruthy();
    expect(screen.getByText('MJPEG (re-encoded from H264)')).toBeTruthy();
  });

  it('says "not measurable" instead of a fake number when FPS cannot be measured', () => {
    render(
      <LiveStatsPanel
        stats={{ fps: null, width: null, height: null, frames: 0, startedAt: null, encoding: null }}
        fpsMeasurable={false}
        detections={{}}
      />,
    );
    expect(screen.getByText('not measurable')).toBeTruthy();
    // Encoding is likewise honest in <img> fallback mode: unknown, not a guess.
    expect(screen.getByText('unknown')).toBeTruthy();
  });
});
