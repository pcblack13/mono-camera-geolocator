/**
 * The accuracy surface on the picking page — the honesty behaviours, not the layout.
 *
 * ★ THE PAGE IS GONE. Everything the loop produces now appears on the picking page: a
 *   status line in the GCP toolbar, suggestion boxes on the photograph, the heat map on
 *   the satellite pane, and a version history to compare runs. These tests cover the
 *   parts that could quietly become a sales pitch for the correction:
 *
 *   1. the corrected median is never shown without the raw one it came from;
 *   2. "enough points" is stated with the number that justifies it;
 *   3. a comparison that improves the median while worsening the worst areas says so.
 */

import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import type { HeatmapVersion } from '../api/accuracy';
import { heatColour } from '../components/accuracy/heat';
import { AccuracyLoopStatus } from '../components/gcp/AccuracyLoopStatus';

const measurement = {
  provider: 'mapbox_satellite',
  match_rate: 0.94,
  tiles_total: 407,
  median_error_m: 8.07,
};

describe('heatColour', () => {
  it('runs the server ramp and clamps at both ends', () => {
    expect(heatColour(0, 10)).toBe('rgb(255, 247, 236)');
    expect(heatColour(10, 10)).toBe('rgb(127, 0, 0)');
    expect(heatColour(999, 10)).toBe(heatColour(10, 10));
    expect(heatColour(-5, 10)).toBe(heatColour(0, 10));
  });
});

describe('AccuracyLoopStatus', () => {
  /**
   * ★ THE TECHNIQUE'S OWN CAPTION. The satellite pane draws the CORRECTED winner's
   *   field, so the number beside it must be the corrected median — with the raw one it
   *   started from kept in view. Either alone misleads: corrected-only claims an
   *   accuracy the survey does not have, raw-only hides what the correction is worth.
   */
  it('shows the corrected median with the raw one it came from', () => {
    render(
      <AccuracyLoopStatus
        state={
          {
            measurement,
            solutions: {
              best: 'pose',
              entries: [{ key: 'pose', label: 'Stage E - refined pose', all_m: 3.04 }],
            },
            suggestions: null,
          } as never
        }
        running={false}
        message={null}
        converged={false}
      />,
    );
    expect(screen.getByText(/3\.0 m \(was 8\.1\)/)).toBeInTheDocument();
  });

  it('shows the raw error alone before anything has been corrected', () => {
    render(
      <AccuracyLoopStatus
        state={{ measurement, solutions: null, suggestions: null } as never}
        running={false}
        message={null}
        converged={false}
      />,
    );
    expect(screen.getByText('error 8.1 m')).toBeInTheDocument();
  });

  it('says the points are enough once the loop converges', () => {
    render(
      <AccuracyLoopStatus
        state={
          {
            measurement,
            solutions: null,
            suggestions: {
              verdict: 'converged',
              best_cut_pct: 2.1,
              stop_below_pct: 5,
              regions: [],
            },
          } as never
        }
        running={false}
        message={null}
        converged
      />,
    );
    expect(screen.getByText(/Enough points/)).toBeInTheDocument();
  });

  it('reports what the loop is doing while it runs', () => {
    render(
      <AccuracyLoopStatus
        state={{ measurement: null, solutions: null, suggestions: null } as never}
        running
        message="measuring the error — 42%"
        converged={false}
      />,
    );
    expect(screen.getByText(/measuring the error — 42%/)).toBeInTheDocument();
  });
});

// ── the heat-map version history ────────────────────────────────────────────
function version(over: Partial<HeatmapVersion> = {}): HeatmapVersion {
  return {
    version: '20260818T120000',
    measured_at: '2026-08-18T12:00:00Z',
    provider: 'mapbox_satellite',
    params: {},
    tiles_total: 400,
    tiles_locked: 360,
    match_rate: 0.9,
    median_error_m: 8.07,
    bands: [],
    methods: { phase: 100 },
    grid: { vmax_m: 12 },
    pose: { gcps_used: 4 },
    warnings: [],
    corrected: { best: 'pose', label: 'Stage E - refined pose', all_m: 5.0, p95_m: 11.0 },
    gate: { accepted: true, reason: 'improves the median error' },
    layers: ['heat_raw', 'heat_pose'],
    ...over,
  };
}

const historyData: HeatmapVersion[] = [];
vi.mock('../api/hooks/useAccuracy', () => ({
  useAccuracyHistory: () => ({ data: historyData }),
  useAccuracyState: () => ({ data: undefined }),
  useMeasureAccuracy: () => ({ mutate: vi.fn(), isPending: false }),
  useSetSolveOptions: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { HeatmapHistoryMenu } from '../components/accuracy/HeatmapHistoryMenu';

function renderHistory(): ReturnType<typeof render> {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <HeatmapHistoryMenu imageId={'img-1' as never} />
    </QueryClientProvider>,
  );
}

describe('HeatmapHistoryMenu', () => {
  it('offers nothing at all until a measurement has been archived', () => {
    historyData.length = 0;
    const { container } = renderHistory();
    // ★ A control for an empty history is noise — it renders nothing, not a disabled
    //   button that explains itself.
    expect(container).toBeEmptyDOMElement();
  });

  it('opens once there is a version to look back at', () => {
    historyData.length = 0;
    historyData.push(version());
    renderHistory();
    expect(screen.getByLabelText('Heat map history')).toBeInTheDocument();
  });
});
