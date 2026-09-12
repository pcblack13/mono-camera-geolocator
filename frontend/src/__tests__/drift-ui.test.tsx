/**
 * The drift watch UI — the four verdicts on screen, honestly.
 *
 * ★ What these pin: the pill keeps colour AND shape per state (and refuses to
 *   paint DEGRADED as an alarm), the map banner fires only on a CONFIRMED
 *   MOVED/CHANGED and never steals a pointer, and the section offers the flow
 *   in the right order — blocked freeze names its blocker, a frozen reference
 *   gets Check now, and the monitor clock is a live-source privilege.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { DriftReference, DriftVerdict } from '../api/drift';
import { DriftMapBanner } from '../components/drift/DriftMapBanner';
import { DriftPill } from '../components/drift/DriftPill';
import { DriftSection } from '../components/drift/DriftSection';
import { setLanguage } from '../i18n';

const REF: DriftReference = {
  ref_id: 'a'.repeat(32),
  name: 'tower',
  source: 'cam0',
  source_label: 'cam0',
  lut_site: 'site',
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

/** A clip reference frozen at second 20 — the self-comparison guard's fixture. */
const REF_IMG: DriftReference = {
  ...REF,
  ref_id: 'd'.repeat(32),
  source: 'cam7',
  frozen_from: 'image',
  frozen_from_label: 'DJI_0124.JPG',
  intrinsics_mode: 'fov',
  fov: { fov_h_deg: 72, fov_v_deg: 44.1, square_pixels: true },
  intrinsics_warning: 'derived intrinsics disagree with the table by 2.1 px',
};
const REF_CLIP: DriftReference = {
  ...REF,
  ref_id: 'c'.repeat(32),
  source: 'video:clip1',
  frozen_at_s: 20,
};

const verdict = (over: Partial<DriftVerdict>): DriftVerdict => ({
  ref_id: REF.ref_id,
  checked_utc: '2026-08-24T10:00:00Z',
  via: 'capture',
  state: 'OK',
  status: 'OK',
  confirmed: false,
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

const lut = vi.hoisted(() => ({
  library: [] as Array<{ site_name: string; has_pose: boolean; pose_needs_fov?: boolean }>,
}));
vi.mock('../api/lut', () => ({
  lutApi: { library: vi.fn(async () => lut.library) },
}));

vi.mock('../api/drift', async (importOriginal) => {
  const mod = (await importOriginal()) as Record<string, unknown>;
  return {
    ...mod,
    driftApi: {
      references: vi.fn(async () => ({ items: [REF, REF_CLIP, REF_IMG] })),
      status: vi.fn(async () => ({ items: [] })),
      check: vi.fn(async () =>
        verdict({ state: 'MOVED', status: 'MOVED', confirmed: true, why: 'camera rotated' }),
      ),
      freeze: vi.fn(async () => REF),
      fieldUnitUrl: (refId: string) => `/api/v1/drift/references/${refId}/field-unit`,
      startMonitor: vi.fn(),
      stopMonitor: vi.fn(),
      remove: vi.fn(),
    },
  };
});

function wrap(ui: React.ReactElement): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  setLanguage('en');
});

describe('the drift pill', () => {
  it('gives each state its own border shape and its own words', () => {
    // ★ jsdom drops var() colours (the StatusPill test's precedent), so the
    //   assertable channels here are SHAPE and TEXT — which is the point: the
    //   pill must survive with colour subtracted.
    const { container } = render(
      <>
        <DriftPill state="OK" confirmed />
        <DriftPill state="MOVED" confirmed />
        <DriftPill state="CHANGED" confirmed />
        <DriftPill state="DEGRADED" confirmed />
      </>,
    );
    const styleOf = (state: string): CSSStyleDeclaration =>
      getComputedStyle(container.querySelector(`[data-drift-state="${state}"]`)!);
    expect(styleOf('OK').borderStyle).toContain('solid');
    expect(styleOf('MOVED').borderStyle).toContain('dashed');
    expect(styleOf('CHANGED').borderStyle).toContain('double');
    expect(styleOf('DEGRADED').borderStyle).toContain('solid');
    expect(screen.getByText('Camera steady')).toBeInTheDocument();
    expect(screen.getByText('Camera moved')).toBeInTheDocument();
    expect(screen.getByText('Optics changed')).toBeInTheDocument();
    // ★ "Cannot judge" is not an alarm — it gets calm words, not warning ones.
    expect(screen.getByText('Cannot judge')).toBeInTheDocument();
  });

  it('marks an unconfirmed reading with an ellipsis', () => {
    render(<DriftPill state="MOVED" />);
    expect(screen.getByText('…')).toBeInTheDocument();
  });
});

describe('the live overlay', () => {
  it('draws the frozen view’s box where the server put it, in the frame’s own space', async () => {
    const { DriftOverlay } = await import('../components/drift/DriftOverlay');
    render(
      <DriftOverlay
        verdict={verdict({
          state: 'MOVED',
          status: 'MOVED',
          frame_w: 1000,
          frame_h: 500,
          // slid down by 5 % of the height — a pitch
          outline: [
            [0, 0.05],
            [1, 0.05],
            [1, 1.05],
            [0, 1.05],
          ],
          landmarks: [{ u: 0.5, v: 0.5, x: 0.5, y: 0.55 }],
        })}
      />,
    );
    const svg = screen.getByTestId('drift-overlay');
    expect(svg).toHaveAttribute('viewBox', '0 0 1000 500');
    expect(svg.querySelector('polygon')).toHaveAttribute('points', '0,25 1000,25 1000,525 0,525');
    // dashed when MOVED — shape, not only colour
    expect(svg.querySelector('polygon')).toHaveAttribute('stroke-dasharray');
    // ★ GEO-DRIFT A1: the twelve dots became TWO RETICLES for one real landmark —
    //   frozen (u,v) and matched (x,y) — with the separation amplified by a FIXED
    //   factor per state (MOVED ×6) and the label carrying the TRUE pixel figure.
    const reticle = svg.querySelector('[data-testid="drift-reticle"]');
    expect(reticle).not.toBeNull();
    expect(reticle).toHaveAttribute('data-amplify', '6');
    expect(reticle).toHaveAttribute('data-lost', 'false');
    // a 5 % drop on a 500 px frame is 25 px — said as such, not ×6
    expect(reticle?.textContent).toContain('25.0 px ×6');
    expect(getComputedStyle(svg).pointerEvents).toBe('none');
  });

  it('★ a lost landmark is labelled at its frozen position, never given a position', async () => {
    const { DriftOverlay } = await import('../components/drift/DriftOverlay');
    render(
      <DriftOverlay
        verdict={verdict({
          state: 'OK',
          status: 'OK',
          frame_w: 1000,
          frame_h: 500,
          landmarks: [{ u: 0.8, v: 0.4, x: null, y: null }],
        })}
      />,
    );
    const reticle = screen
      .getByTestId('drift-overlay')
      .querySelector('[data-testid="drift-reticle"]');
    expect(reticle).toHaveAttribute('data-lost', 'true');
    expect(reticle?.textContent).toContain('lost');
  });

  it('★ the caption names which way the camera moved when the server says', async () => {
    const { DriftOverlay } = await import('../components/drift/DriftOverlay');
    render(
      <DriftOverlay
        verdict={verdict({
          state: 'MOVED',
          status: 'MOVED',
          frame_w: 1000,
          frame_h: 500,
          rot_deg: 0.5,
          angles: { pan_deg: 0.4, tilt_deg: -0.3, roll_deg: 0.01, axis_total_deg: 0.5 },
        })}
      />,
    );
    expect(screen.getByTestId('drift-overlay').textContent).toContain('pan 0.40°');
    expect(screen.getByTestId('drift-overlay').textContent).toContain('tilt -0.30°');
  });

  it('draws a dashed frame edge, never a box, when no rotation was solved', async () => {
    const { DriftOverlay } = await import('../components/drift/DriftOverlay');
    render(
      <DriftOverlay
        verdict={verdict({ state: 'DEGRADED', frame_w: 640, frame_h: 360, outline: null })}
      />,
    );
    const svg = screen.getByTestId('drift-overlay');
    expect(svg.querySelector('polygon')).toBeNull();
    expect(svg.querySelector('rect')).toHaveAttribute('stroke-dasharray');
  });

  it('renders nothing without a frame size to draw in', async () => {
    const { DriftOverlay } = await import('../components/drift/DriftOverlay');
    const { container } = render(<DriftOverlay verdict={verdict({ frame_w: null })} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('the map banner', () => {
  it('stays silent for null, unconfirmed, OK and DEGRADED', () => {
    for (const v of [
      null,
      verdict({ state: 'MOVED', status: null }), // raw reading, not confirmed
      verdict({ state: 'OK', status: 'OK' }),
      verdict({ state: 'DEGRADED', status: 'DEGRADED' }),
    ]) {
      const { container, unmount } = render(<DriftMapBanner verdict={v} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it('fires on confirmed MOVED — and never swallows a pointer', () => {
    render(<DriftMapBanner verdict={verdict({ state: 'MOVED', status: 'MOVED' })} />);
    const banner = screen.getByRole('alert');
    expect(banner).toHaveTextContent('Camera moved — coordinates are no longer trusted.');
    expect(getComputedStyle(banner).pointerEvents).toBe('none');
  });

  it('tells CHANGED apart — re-aiming will not fix it', () => {
    render(<DriftMapBanner verdict={verdict({ state: 'CHANGED', status: 'CHANGED' })} />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Camera optics changed — coordinates are no longer trusted.',
    );
  });
});

describe('the drift section', () => {
  it('★ blocks freezing on a lookup table with no pose — before the server has to', async () => {
    // ★ A table imported as bare lat/lon arrays places detections fine but carries
    //   no `pose.R/C/K`; the freeze would be refused. The refusal used to be the
    //   first the surveyor heard of it, after pressing the button.
    lut.library = [{ site_name: 'usb_site', has_pose: false }];
    // A source with no frozen reference yet, so the button reads "Freeze reference".
    wrap(<DriftSection source="cam9" lutSite="usb_site" live />);
    // Both the caption and the disabled button’s tooltip carry the sentence.
    expect((await screen.findAllByText(/carries no camera pose/)).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /Freeze reference/ })).toBeDisabled();
    lut.library = [];
  });

  it('★ GEO-DRIFT C1: a table with everything but intrinsics freezes once a field of view is given', async () => {
    const { driftApi } = await import('../api/drift');
    lut.library = [{ site_name: 'fov_site', has_pose: false, pose_needs_fov: true }];
    // the camera's own field of view seeds the box, so the button is live at once
    wrap(<DriftSection source="cam9" lutSite="fov_site" live cameraFovDeg={72} />);
    const box = await screen.findByLabelText('Field of view (°)');
    expect(box).toHaveValue('72');
    const button = screen.getByRole('button', { name: /Freeze reference/ });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(driftApi.freeze).toHaveBeenCalled());
    expect(vi.mocked(driftApi.freeze).mock.calls.at(-1)?.[0]).toMatchObject({
      lut_site: 'fov_site',
      use_lut_image: true,
      no_calibration: true,
      fov_h_deg: 72,
      square_pixels: true,
    });
    lut.library = [];
  });

  it('★ GEO-DRIFT D1/C1/B2: the reference says where it was frozen, how it got K, and offers the field unit', async () => {
    wrap(<DriftSection source="cam7" lutSite="site" live />);
    expect(await screen.findByText(/frozen on the photograph DJI_0124\.JPG/)).toBeInTheDocument();
    expect(screen.getByText(/intrinsics from a field of view \(72°\)/)).toBeInTheDocument();
    expect(screen.getByText(/disagree with the table/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Field unit bundle/ })).toHaveAttribute(
      'href',
      `/api/v1/drift/references/${'d'.repeat(32)}/field-unit`,
    );
  });

  it('★ GEO-DRIFT A3: the reading names pan, tilt and roll when the server sends them', async () => {
    wrap(
      <DriftSection
        source="cam0"
        lutSite="site"
        live
        liveVerdict={verdict({
          state: 'MOVED',
          status: 'MOVED',
          confirmed: true,
          rot_deg: 0.5,
          angles: { pan_deg: 0.41, tilt_deg: -0.28, roll_deg: 0.02, axis_total_deg: 0.5 },
        })}
      />,
    );
    expect(await screen.findByText(/pan 0\.41°/)).toBeInTheDocument();
    expect(screen.getByText(/tilt -0\.28°/)).toBeInTheDocument();
  });

  it('blocks freezing without a source, and says why', () => {
    wrap(<DriftSection source={null} lutSite="" live />);
    expect(screen.getByText('Choose and apply a source above first.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Freeze reference/ })).toBeDisabled();
  });

  it('checks a frozen reference and hands the verdict to the map', async () => {
    const onVerdict = vi.fn();
    wrap(<DriftSection source="cam0" lutSite="site" live onVerdict={onVerdict} />);
    const checkBtn = await screen.findByRole('button', { name: /Check now/ });
    fireEvent.click(checkBtn);
    await waitFor(() =>
      expect(onVerdict).toHaveBeenCalledWith(expect.objectContaining({ status: 'MOVED' })),
    );
    expect(screen.getByText('Camera moved')).toBeInTheDocument();
  });

  it('shows THIS frame’s reading even while the confirmed status still says OK', async () => {
    // ★ Review bug: the pill used to show `status ?? state`, so a raw MOVED
    //   reading hid behind a still-OK confirmed status — "steady" on a frame
    //   that had just measured a move.
    const { driftApi } = await import('../api/drift');
    vi.mocked(driftApi.check).mockResolvedValueOnce(
      verdict({ state: 'MOVED', status: 'OK', confirmed: false, why: 'camera rotated 0.9 deg' }),
    );
    wrap(<DriftSection source="cam0" lutSite="site" live />);
    fireEvent.click(await screen.findByRole('button', { name: /Check now/ }));
    expect(await screen.findByText('Camera moved')).toBeInTheDocument();
    expect(screen.getByText(/confirmed:/)).toHaveTextContent('Camera steady');
  });

  it('refuses to check a clip at the very second it was frozen from', async () => {
    // ★ The field-day trap: same second in, "perfectly steady" out — six times.
    wrap(<DriftSection source="video:clip1" lutSite="site" live={false} />);
    const field = await screen.findByLabelText('at second');
    expect(await screen.findByRole('button', { name: /Check now/ })).toBeEnabled();
    fireEvent.change(field, { target: { value: '20' } });
    expect(screen.getByRole('button', { name: /Check now/ })).toBeDisabled();
    expect(screen.getByText(/That is the frozen second/)).toBeInTheDocument();
    fireEvent.change(field, { target: { value: '30' } });
    expect(screen.getByRole('button', { name: /Check now/ })).toBeEnabled();
  });

  it('surfaces a running watch even when it guards an OLDER reference of this source', async () => {
    // ★ The reported bug: after a re-freeze the old watch kept running while the
    //   UI (following the newest reference) showed nothing. Nothing invisible
    //   may hold the camera — a running same-source watch must show as running.
    const { driftApi } = await import('../api/drift');
    vi.mocked(driftApi.status).mockResolvedValue({
      items: [
        {
          ref_id: 'b'.repeat(32), // NOT the current reference's id
          status: 'running',
          source: 'cam0',
          interval_s: 30,
          started_utc: '2026-08-24T09:30:00Z',
          checks_done: 4,
          capture_failures: 0,
          last_error: null,
          last: verdict({}),
          history: [],
        },
      ],
    });
    wrap(<DriftSection source="cam0" lutSite="site" live />);
    expect(await screen.findByRole('button', { name: 'Stop watching' })).toBeInTheDocument();
    vi.mocked(driftApi.status).mockResolvedValue({ items: [] });
  });

  it('offers the monitor clock only on live sources', async () => {
    wrap(<DriftSection source="cam0" lutSite="site" live />);
    expect(await screen.findByRole('button', { name: 'Watch' })).toBeInTheDocument();
    document.body.innerHTML = '';
    wrap(<DriftSection source="video:abc" lutSite="site" live={false} />);
    // the clip still gets Freeze (no ref matches `video:abc` in the mock)…
    expect(await screen.findByRole('button', { name: /Freeze reference/ })).toBeInTheDocument();
    // …but never a Watch button
    expect(screen.queryByRole('button', { name: 'Watch' })).toBeNull();
  });
});

describe('the map banner can be closed (2026-09-10)', () => {
  const MOVED = verdict({ state: 'MOVED', status: 'MOVED' });
  beforeEach(() => {
    localStorage.removeItem('landexplorer.driftBanner.closed');
  });

  it('★ the × offers "show later" and "don’t show again"; the × itself takes the click', () => {
    render(<DriftMapBanner verdict={MOVED} />);
    const close = screen.getByRole('button', { name: 'Close this warning' });
    expect(getComputedStyle(close).pointerEvents).toBe('auto');
    fireEvent.click(close);
    expect(screen.getByRole('button', { name: 'Show later' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Don’t show again' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Keep it' }));
    expect(screen.getByRole('button', { name: 'Close this warning' })).toBeVisible();
  });

  it('★ "show later" hides it for 30 minutes, then it returns', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-10T11:30:00Z'));
    const { unmount } = render(<DriftMapBanner verdict={MOVED} />);
    fireEvent.click(screen.getByRole('button', { name: 'Close this warning' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show later' }));
    expect(screen.queryByRole('alert')).toBeNull();
    unmount();
    vi.setSystemTime(new Date('2026-09-10T11:50:00Z'));
    const again = render(<DriftMapBanner verdict={MOVED} />);
    expect(screen.queryByRole('alert')).toBeNull(); // still snoozed
    again.unmount();
    vi.setSystemTime(new Date('2026-09-10T12:01:00Z'));
    render(<DriftMapBanner verdict={MOVED} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    vi.useRealTimers();
  });

  it('★ "don’t show again" is remembered for THIS alarm — a new reference or verdict shows again', () => {
    const { unmount } = render(<DriftMapBanner verdict={MOVED} />);
    fireEvent.click(screen.getByRole('button', { name: 'Close this warning' }));
    fireEvent.click(screen.getByRole('button', { name: 'Don’t show again' }));
    expect(screen.queryByRole('alert')).toBeNull();
    unmount();
    render(<DriftMapBanner verdict={MOVED} />);
    expect(screen.queryByRole('alert')).toBeNull(); // remembered across a remount
    cleanup();
    render(<DriftMapBanner verdict={{ ...MOVED, status: 'CHANGED', state: 'CHANGED' }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('optics changed');
    cleanup();
    render(<DriftMapBanner verdict={{ ...MOVED, ref_id: 'b'.repeat(32) }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Camera moved');
  });
});
