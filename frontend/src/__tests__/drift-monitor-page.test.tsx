/**
 * The Drift monitor PAGE — the camera console of the Monitoring workspace.
 *
 * ★ What these pin: the page lists every frozen reference with its watch state,
 *   "Use" points the drift watch at a reference in one press (the section then
 *   offers Check now), a running watch can be stopped from the table, and
 *   forgetting a reference is confirmed and names what goes.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import type { DriftMonitor, DriftReference, DriftVerdict } from '../api/drift';
import { DriftMonitorTab } from '../components/drift/DriftMonitorTab';
import { setLanguage } from '../i18n';

const REF: DriftReference = {
  ref_id: 'a'.repeat(32),
  name: 'tower',
  source: 'rtsp://cam.local/stream',
  source_label: 'cam.local',
  lut_site: 'north_site',
  created_utc: '2026-08-24T09:00:00Z',
  frame_width: 1920,
  frame_height: 1080,
  n_landmarks: 12,
  alert_ground_m: 1,
  ref_range_m: 200,
  confirm_n: 3,
  ref_reproj_mean_px: 0.4,
  range_min_m: 60,
  range_median_m: 200,
  range_max_m: 900,
};

const REF_CLIP: DriftReference = {
  ...REF,
  ref_id: 'c'.repeat(32),
  name: 'clip ref',
  source: 'video:clip1',
  source_label: 'field.mp4',
  frozen_at_s: 20,
};

const verdict = (over: Partial<DriftVerdict>): DriftVerdict => ({
  ref_id: REF.ref_id,
  checked_utc: '2026-08-24T10:00:00Z',
  via: 'capture',
  state: 'OK',
  status: 'OK',
  confirmed: true,
  why: 'drift 0.01 deg, below the threshold',
  n_landmarks: 12,
  n_matched: 12,
  n_lost: 0,
  n_inliers: 12,
  rot_deg: 0.01,
  ground_err_at_ref: 0.03,
  resid_mean_px: 0.3,
  mean_conf: 0.9,
  snr: 10,
  ...over,
});

const MONITOR: DriftMonitor = {
  ref_id: REF.ref_id,
  status: 'running',
  source: REF.source,
  interval_s: 30,
  started_utc: '2026-08-24T09:30:00Z',
  checks_done: 7,
  capture_failures: 1,
  last_error: null,
  last: verdict({ state: 'MOVED', status: 'MOVED', why: 'camera rotated 0.4 deg' }),
  history: [verdict({}), verdict({ state: 'MOVED', status: 'OK', confirmed: false })],
};

const api = vi.hoisted(() => ({
  references: vi.fn(),
  status: vi.fn(),
  check: vi.fn(),
  freeze: vi.fn(),
  startMonitor: vi.fn(),
  stopMonitor: vi.fn(),
  remove: vi.fn(),
}));

vi.mock('../api/drift', async (importOriginal) => {
  const mod = (await importOriginal()) as Record<string, unknown>;
  return { ...mod, driftApi: api };
});

const LUT_ROW = {
  site_name: 'north_site',
  built_utc: null,
  image: {},
  payload_mb: null,
  validation_passed: true,
  max_error_m: null,
  center: null,
  bundle_dir: '/x',
  archive_available: false,
  has_pose: true,
  imported: null,
};

vi.mock('../api/lut', () => ({
  lutApi: {
    library: vi.fn(async () => [
      LUT_ROW,
      // ★ An imported payload-only bundle: fine for placing detections, useless to
      //   this page, which re-solves geometry from the manifest's pose.
      {
        ...LUT_ROW,
        site_name: 'usb_site',
        has_pose: false,
        imported: { source: 'usb_site_lut.zip', manifest: 'synthesised' },
      },
    ]),
    import: vi.fn(),
  },
}));

vi.mock('../api/hooks/useVideos', () => ({
  useAllVideos: () => ({ data: { items: [{ id: 'clip1', filename: 'field.mp4' }] } }),
}));

function mount(): void {
  setLanguage('en');
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <DriftMonitorTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.references.mockResolvedValue({ items: [REF, REF_CLIP] });
  api.status.mockResolvedValue({ items: [MONITOR] });
  api.check.mockResolvedValue(verdict({ state: 'MOVED', status: 'MOVED', why: 'camera rotated' }));
  api.stopMonitor.mockResolvedValue({ ...MONITOR, status: 'stopped' });
  api.remove.mockResolvedValue(undefined);
});

describe('the drift monitor page', () => {
  it('★ lists every frozen reference with its watch state, verbatim', async () => {
    mount();
    expect(screen.getByRole('heading', { name: 'Drift monitor' })).toBeInTheDocument();
    const table = await screen.findByRole('table', { name: 'Frozen references' });
    expect(within(table).getByText('tower')).toBeInTheDocument();
    expect(within(table).getByText('clip ref')).toBeInTheDocument();
    // the running watch: its clock, its count, its confirmed verdict
    await waitFor(() =>
      expect(within(table).getByText(/every 30 s · 7 checks/)).toBeInTheDocument(),
    );
    expect(within(table).getByText('Camera moved')).toBeInTheDocument();
    expect(within(table).getByText(/1 looks failed/)).toBeInTheDocument();
    // a clip is judged on demand — no clock is offered or implied
    expect(within(table).getByText('on demand')).toBeInTheDocument();
    // and the page header counts the running watches
    expect(screen.getByText('1 watch running')).toBeInTheDocument();
  });

  it('★ "Use" points the watch at that reference — the section then offers Check now', async () => {
    mount();
    const table = await screen.findByRole('table', { name: 'Frozen references' });
    // nothing applied yet: the section asks for a source
    expect(screen.queryByRole('button', { name: 'Check now' })).toBeNull();
    // ★ The CLIP reference: it has no running watch, so the check's own verdict
    //   is what shows (a monitor's clock outranks a manual check by design).
    const useButtons = within(table).getAllByRole('button', { name: 'Use' });
    fireEvent.click(useButtons[1]);
    expect(await screen.findByRole('button', { name: 'Check now' })).toBeInTheDocument();
    // the row now says so, and cannot be pressed twice
    expect(within(table).getByRole('button', { name: 'In use' })).toBeDisabled();
    // a check surfaces the verdict card with the server's sentence, verbatim
    fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
    await waitFor(() => expect(screen.getAllByText('camera rotated').length).toBeGreaterThan(0));
    expect(screen.getByText('Rotation')).toBeInTheDocument();
  });

  it('★ applying a clip shows the clip itself, so a verdict has a picture to point at', async () => {
    mount();
    const table = await screen.findByRole('table', { name: 'Frozen references' });
    // nothing applied: no player
    expect(document.querySelector('video')).toBeNull();
    // the CLIP reference (video:clip1 → field.mp4)
    fireEvent.click(within(table).getAllByRole('button', { name: 'Use' })[1]);
    const player = await waitFor(() => {
      const v = document.querySelector('video');
      if (!v) throw new Error('no player yet');
      return v;
    });
    expect(player.getAttribute('src')).toContain('/videos/clip1/file');
    // once in the source picker, once as the player's title
    expect(screen.getAllByText('field.mp4').length).toBeGreaterThan(1);
    // a live camera reference gets no player here — the Live stream page owns that
    fireEvent.click(within(table).getAllByRole('button', { name: 'Use' })[0]);
    await waitFor(() => expect(document.querySelector('video')).toBeNull());
  });

  it('stops a running watch from the table', async () => {
    mount();
    const table = await screen.findByRole('table', { name: 'Frozen references' });
    const stop = await within(table).findByRole('button', { name: 'Stop' });
    fireEvent.click(stop);
    await waitFor(() => expect(api.stopMonitor).toHaveBeenCalledWith(REF.ref_id));
  });

  it('★ forgetting a reference is confirmed, and names what goes', async () => {
    mount();
    await screen.findByRole('table', { name: 'Frozen references' });
    fireEvent.click(screen.getByRole('button', { name: 'Forget tower' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('tower')).toBeInTheDocument();
    expect(api.remove).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Forget' }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith(REF.ref_id));
  });

  it('offers saved cameras, library clips and a free-form source', async () => {
    mount();
    await screen.findByRole('table', { name: 'Frozen references' });
    fireEvent.mouseDown(screen.getByLabelText('Source', { selector: 'div[role="combobox"]' }));
    const listbox = await screen.findByRole('listbox');
    expect(within(listbox).getByText('field.mp4')).toBeInTheDocument();
    expect(within(listbox).getByText('A camera URL or capture device…')).toBeInTheDocument();
  });

  it('★ a lookup table with no pose cannot be chosen here, and says why', async () => {
    // ★ Freezing a reference re-solves geometry from `pose.R/C/K` in the bundle's
    //   manifest. A table imported as bare lat/lon arrays has none — offering it
    //   would hand the surveyor a Freeze that fails seconds after they committed.
    mount();
    await screen.findByRole('table', { name: 'Frozen references' });
    fireEvent.mouseDown(
      screen.getByLabelText('Lookup table', { selector: 'div[role="combobox"]' }),
    );
    const listbox = await screen.findByRole('listbox');

    const usable = within(listbox).getByRole('option', { name: /north_site/ });
    expect(usable.getAttribute('aria-disabled')).not.toBe('true');

    const poseless = within(listbox).getByRole('option', { name: /usb_site/ });
    expect(poseless.getAttribute('aria-disabled')).toBe('true');
    expect(within(poseless).getByText('no pose in its manifest')).toBeInTheDocument();
  });
});
