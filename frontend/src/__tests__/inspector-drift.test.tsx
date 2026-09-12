/**
 * The inspector's drift stage READS the camera's background watch (2026-09-08):
 * the pill, the confirmed status when it differs, the server's own sentence,
 * the angles — and the settings door only while the watch is healthy.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

vi.mock('../api/lut', () => ({ lutApi: { library: async () => [] } }));

import type { DriftVerdict } from '../api/drift';
import { Inspector, type InspectorProps } from '../components/monitor/camera/Inspector';
import { computeStages, type StageInputs } from '../lib/monitor/stages';
import { setLanguage } from '../i18n';

const VERDICT: DriftVerdict = {
  ref_id: 'r'.repeat(32),
  checked_utc: '2026-09-09T10:00:00Z',
  via: 'capture',
  state: 'MOVED',
  status: 'OK',
  confirmed: false,
  why: 'camera rotated 0.150 deg = 0.42 m of ground error at 160 m (threshold 1.00 m); 12/12 landmarks agree, SNR 14.7',
  n_landmarks: 12,
  n_matched: 12,
  n_lost: 0,
  n_inliers: 12,
  rot_deg: 0.15,
  ground_err_at_ref: 0.42,
  resid_mean_px: 0.38,
  mean_conf: 0.91,
  snr: 14.7,
  angles: { pan_deg: 0.149, tilt_deg: 0.01, roll_deg: 0.002, axis_total_deg: 0.15 },
};

const INPUTS: StageInputs = {
  feedStatus: 'live',
  stats: { fps: 25, width: 1920, height: 1080, encoding: 'MJPEG' },
  detectorAvailable: true,
  detectorReason: null,
  detecting: false,
  lutSite: 'MONODEMO',
  appliedLut: 'MONODEMO',
  lutHasPose: true,
  trackerStart: 0,
  trackerType: 'csrt',
  driftFrozen: true,
  driftWatching: true,
  driftState: 'MOVED',
  driftStatus: 'OK',
  driftError: null,
  modelName: 'yolo26s.pt',
  classesLabel: 'all classes',
  conf: 0.25,
  imgsz: 640,
  settingsTo: '/cameras/c1/settings',
};

function mount(over: Partial<InspectorProps> = {}): void {
  setLanguage('en');
  const props: InspectorProps = {
    stages: computeStages(INPUTS),
    draft: { model: '', lutSite: 'MONODEMO', classes: [], conf: 0.25, imgsz: 640, trackerStart: 0, trackerType: 'csrt', centreMarks: false, steadyBoxes: true, markRateHz: 1 },
    onChange: () => undefined,
    availability: undefined,
    stats: INPUTS.stats as never,
    fpsMeasurable: true,
    running: false,
    run: null,
    onFix: () => undefined,
    drift: { verdict: VERDICT, frozen: true, watching: true, lastError: null, frozenFromLabel: 'live_yamouneh.jpg', refRangeM: 738, settingsTo: '/cameras/c1/settings' },
    ...over,
  };
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Inspector {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('the inspector drift stage', () => {
  beforeEach(() => setLanguage('en'));

  it('★ shows THIS frame’s state, names the confirmed status when it differs, and the server’s sentence verbatim', () => {
    mount();
    expect(screen.getByText('watching live · MOVED (confirmed OK)')).toBeInTheDocument();
    const pill = document.querySelector('[data-drift-state="MOVED"]');
    expect(pill).not.toBeNull();
    expect(screen.getByText(/confirmed:/)).toBeInTheDocument();
    expect(screen.getByText(VERDICT.why)).toBeInTheDocument();
    expect(screen.getByText(/pan 0.15°/)).toBeInTheDocument();
    expect(screen.getByTestId('drift-ground-shift')).toHaveTextContent('±0.42 m at 738 m');
    expect(screen.getByText(/frozen on the photograph/)).toHaveTextContent('live_yamouneh.jpg');
    // the door to re-freeze, only because the watch is healthy
    expect(screen.getByRole('link', { name: /Re-freeze from a new frame/ })).toHaveAttribute('href', '/cameras/c1/settings');
  });

  it('with no reference it says where the reference is made and offers ONE door', () => {
    mount({
      stages: computeStages({ ...INPUTS, driftFrozen: false, driftWatching: false, driftState: null, driftStatus: null }),
      drift: { verdict: null, frozen: false, watching: false, lastError: null, frozenFromLabel: null, refRangeM: null, settingsTo: '/cameras/c1/settings' },
    });
    expect(screen.getByText(/The drift reference is made in the camera settings/)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /camera settings/ })).toHaveLength(1);
  });

  it('a stopped watch shows its own trouble line', () => {
    mount({
      stages: computeStages({ ...INPUTS, driftWatching: false, driftError: 'frame is (720, 1280) but the reference was (1080, 1920)' }),
      drift: { verdict: null, frozen: true, watching: false, lastError: 'frame is (720, 1280) but the reference was (1080, 1920)', frozenFromLabel: null, refRangeM: null, settingsTo: '/cameras/c1/settings' },
    });
    // the stage summary AND the block both carry it — at least the block does
    expect(screen.getAllByText(/the reference was \(1080, 1920\)/).length).toBeGreaterThanOrEqual(1);
  });
});
