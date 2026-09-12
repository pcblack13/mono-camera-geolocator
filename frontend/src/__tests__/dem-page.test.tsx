/**
 * The DEM processing page — the stage strip tells the truth, the form reads well.
 *
 * ★ What these pin: the four stages are DERIVED from real state (a file, a run, a
 *   result) rather than a click counter; the AOI mode is a segmented choice whose
 *   fields follow it; Process is disabled until there is a file; the CRS picker
 *   only appears when the camera is not fixing the zone.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

vi.mock('../api/hooks/useProjects', () => ({
  useProjects: () => ({ data: { items: [{ id: 'p1', name: 'Yammouneh' }] } }),
  useProject: () => ({ data: { id: 'p1', name: 'Yammouneh' } }),
}));
vi.mock('../api/hooks/useImages', () => ({
  useImages: () => ({ data: { items: [] } }),
}));
vi.mock('../api/demLibrary', () => ({
  demLibraryApi: {
    list: vi.fn().mockResolvedValue({ folder: '/data/dem', items: [] }),
    adoptIntoProject: vi.fn(),
    adoptIntoImage: vi.fn(),
    remove: vi.fn(),
  },
}));
const dem = vi.hoisted(() => ({ process: vi.fn(), download: vi.fn() }));
vi.mock('../api/dem', () => ({ demApi: dem }));

import { DemPage, deriveStages } from '../pages/DemPage';
import { NotificationsProvider } from '../components/common/Notifications';
import { DEFAULT_PARAMS, useDemFormStore } from '../store/demFormStore';
import { setLanguage } from '../i18n';

function mount(at = '/dem'): void {
  setLanguage('en');
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MemoryRouter initialEntries={[at]}>
      <QueryClientProvider client={qc}>
        <NotificationsProvider>
          <DemPage embedded />
        </NotificationsProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useDemFormStore.setState({
    file: null,
    stage: 'idle',
    uploadPct: 0,
    result: null,
    errorMessage: null,
    params: DEFAULT_PARAMS,
  });
});

describe('deriveStages', () => {
  it('★ follows the real state: nothing → upload now; file → configure now; run → process running', () => {
    const states = (s: ReturnType<typeof deriveStages>) => s.map((x) => x.state);
    expect(states(deriveStages(false, 'idle', false))).toEqual([
      'current',
      'waiting',
      'waiting',
      'waiting',
    ]);
    expect(states(deriveStages(true, 'ready', false))).toEqual([
      'done',
      'current',
      'waiting',
      'waiting',
    ]);
    expect(states(deriveStages(true, 'processing', false))).toEqual([
      'done',
      'done',
      'running',
      'waiting',
    ]);
    expect(states(deriveStages(true, 'error', false))).toEqual([
      'done',
      'current',
      'failed',
      'waiting',
    ]);
    expect(states(deriveStages(true, 'done', false))).toEqual(['done', 'done', 'done', 'current']);
    expect(states(deriveStages(true, 'done', true))).toEqual(['done', 'done', 'done', 'done']);
  });
});

describe('DemPage', () => {
  it('mounts with the stage strip on Upload and Process disabled until a file is chosen', () => {
    mount();
    const strip = screen.getByRole('list', { name: 'Stages' });
    const items = within(strip).getAllByRole('listitem');
    expect(items.map((x) => x.textContent)).toEqual([
      expect.stringContaining('Upload'),
      expect.stringContaining('Configure'),
      expect.stringContaining('Process'),
      expect.stringContaining('Export'),
    ]);
    expect(items[0]).toHaveAttribute('aria-current', 'step');
    expect(screen.getByRole('button', { name: /Process DEM/ })).toBeDisabled();
    // no project chosen: the target card says what that costs, and offers the choice
    expect(
      screen.getByText(/No project — Auto GCP there would keep reporting/),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('Target project', { selector: 'div[role="combobox"]' }),
    ).toBeInTheDocument();
  });

  it('★ the AOI mode is a segmented choice — the fields follow it, and the CRS picker appears only without a camera', () => {
    mount();
    const group = screen.getByRole('group', { name: 'Area of interest' });
    // camera mode by default: the position fields, no CRS picker
    expect(screen.getByLabelText('Camera latitude')).toBeInTheDocument();
    expect(
      screen.queryByLabelText('Output coordinate reference system', {
        selector: 'div[role="combobox"]',
      }),
    ).toBeNull();

    fireEvent.click(within(group).getByRole('button', { name: 'Four corners' }));
    expect(screen.getByText('CORNER 1')).toBeInTheDocument();
    expect(screen.getAllByLabelText('Latitude')).toHaveLength(4);
    expect(useDemFormStore.getState().params.aoiMode).toBe('corners');
    expect(
      screen.getByLabelText('Output coordinate reference system', {
        selector: 'div[role="combobox"]',
      }),
    ).toBeInTheDocument();

    fireEvent.click(within(group).getByRole('button', { name: 'Whole DEM (no crop)' }));
    expect(screen.queryByText('CORNER 1')).toBeNull();
    // no crop → no tolerance
    expect(screen.queryByRole('slider')).toBeNull();
  });

  it('shows the derived UTM zone as the camera position is typed', () => {
    mount();
    fireEvent.change(screen.getByLabelText('Camera latitude'), { target: { value: '34.11' } });
    fireEvent.change(screen.getByLabelText('Camera longitude'), { target: { value: '36.02' } });
    expect(screen.getByText('UTM zone 37N · EPSG:32637')).toBeInTheDocument();
  });

  it('★ processing sends the project chosen AFTER the file was picked (no stale closure)', async () => {
    dem.process.mockResolvedValue({
      run_id: 'r1',
      camera: null,
      source_name: 'tile.tif',
      source_crs: 'EPSG:4326',
      output_crs: 'EPSG:32637',
      output_size: [10, 10],
      output_pixel_size_m: [30, 30],
      output_bytes: 1000,
      crop: null,
      reproject: null,
      statistics: { min_m: 1, max_m: 2, mean_m: 1.5, valid_cells: 100, void_cells: 0 },
      aoi_geojson: null,
      warnings: [],
      download_url: '/x',
      is_elevation_source: true,
    });
    // the file is already chosen (the closure was built with no project)…
    useDemFormStore.setState({
      file: { kind: 'path', name: 'tile.tif', size: 10, path: '/tmp/tile.tif' },
      stage: 'ready',
      params: { ...DEFAULT_PARAMS, aoiMode: 'none' },
    });
    mount();
    // …then the project is chosen in the header card
    fireEvent.mouseDown(
      screen.getByLabelText('Target project', { selector: 'div[role="combobox"]' }),
    );
    fireEvent.click(await screen.findByRole('option', { name: 'Yammouneh' }));
    expect(await screen.findByText('Yammouneh')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Process DEM/ }));
    await waitFor(() => expect(dem.process).toHaveBeenCalled());
    expect(dem.process.mock.calls[0][0]).toMatchObject({
      project_id: 'p1',
      set_as_elevation_source: true,
    });
  });

  it('names the target project in the header once one is chosen', () => {
    mount('/dem?project=p1');
    expect(screen.getByText('Yammouneh')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unselect project' })).toBeInTheDocument();
  });
});
