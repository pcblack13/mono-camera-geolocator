/**
 * The information dashboard (2026-09-10): the headline numbers come from the
 * registry and the server; a failed reading leaves the others standing.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';

import { DashboardPage, recordingsPerDay } from '../pages/DashboardPage';
import { useCameraRegistryStore, type RegisteredCamera } from '../store/cameraRegistryStore';
import { setLanguage } from '../i18n';

vi.mock('../api/capabilities', () => ({
  capabilitiesApi: {
    health: vi.fn(async () => ({ status: 'ok', version: '1.0.0', uptime_s: 3700 })),
    readiness: vi.fn(async () => ({
      status: 'ok',
      checked_at: '2026-09-10T00:00:00Z',
      components: [
        { name: 'postgres', status: 'up', latency_ms: 1, message: null },
        { name: 'celery', status: 'down', latency_ms: null, message: 'no worker' },
      ],
    })),
  },
}));
vi.mock('../api/lut', () => ({ lutApi: { library: vi.fn(async () => [{ site_name: 'a', validation_passed: true }, { site_name: 'b', validation_passed: false }]) } }));
vi.mock('../api/live', () => ({
  liveApi: {
    listRecordings: vi.fn(async () => ({
      root: '/r',
      items: [
        { folder: 'x', started_at: new Date().toISOString(), duration_s: 120, video_bytes: 5_000_000, marks: 7 },
        { folder: 'y', started_at: new Date().toISOString(), duration_s: 60, video_bytes: 1_000_000, marks: 0 },
      ],
    })),
  },
}));
vi.mock('../api/offline', () => ({ offlineApi: { listManifests: vi.fn(async () => [{ id: 'm', completed_tiles: 1200 }]) } }));
vi.mock('../api/hooks/useDetection', () => ({
  useDetectionAvailability: () => ({ data: { device: 'cuda:0', models: ['yolo26s.pt'] } }),
}));
vi.mock('../api/hooks/useDrift', () => ({
  useDriftMonitors: () => ({ data: [{ ref_id: '1', status: 'running', last: { status: 'ok' } }, { ref_id: '2', status: 'running', last: { status: 'moved' } }] }),
  useDriftReferences: () => ({ data: [{ ref_id: '1' }, { ref_id: '2' }, { ref_id: '3' }] }),
}));
vi.mock('../api/hooks/useProjects', () => ({ useProjects: () => ({ data: { total: 3, items: [{ image_count: 4 }, { image_count: 5 }] } }) }));
vi.mock('../api/hooks/useGcpOverview', () => ({ useGcpOverviewState: () => ({ status: 'ready', total: 41, items: [], refetch: () => undefined }) }));

const cam = (id: string, over: Partial<RegisteredCamera> = {}): RegisteredCamera =>
  ({ id, name: id, lat: 0, lon: 0, source: 'http://x', connection: 'stream', created_at: '2026-09-01T00:00:00Z', ...over }) as RegisteredCamera;

describe('DashboardPage', () => {
  beforeEach(() => {
    setLanguage('en');
    useCameraRegistryStore.setState({
      cameras: [cam('a', { lut_site: 'a', frame_image_id: 'f' as never, calibration: { fx: 1, fy: 1 } as never }), cam('b'), cam('c', { frame_image_id: 'f' as never })],
      statuses: { a: { state: 'live' }, b: { state: 'lost' } } as never,
      hydrated: true,
    });
  });

  it('★ the headline tiles and the readings', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const tiles = screen.getByTestId('dashboard-tiles');
    const tile = (label: string): HTMLElement => within(tiles).getByText(label).parentElement as HTMLElement;
    expect(tile('cameras')).toHaveTextContent('3');
    expect(tile('ready')).toHaveTextContent('1');
    expect(tile('in setup')).toHaveTextContent('2');
    expect(tile('live now')).toHaveTextContent('1');
    expect(tile('projects')).toHaveTextContent('3');
    expect(tile('photographs')).toHaveTextContent('9');
    expect(tile('control points')).toHaveTextContent('41');
    expect(await within(tiles).findByText('lookup tables')).toBeInTheDocument();
    expect(tile('lookup tables')).toHaveTextContent('2');
    // the setup pipeline counts what each camera has
    const pipeline = screen.getByRole('region', { name: 'Setup pipeline' });
    expect(within(pipeline).getByTitle('Frame: 2 / 3')).toBeInTheDocument();
    expect(within(pipeline).getByTitle('Lookup table: 1 / 3')).toBeInTheDocument();
    // the system panel names each component and its state
    const system = screen.getByRole('region', { name: 'System' });
    expect(await within(system).findByText('postgres')).toBeInTheDocument();
    expect(within(system).getByText(/Down/)).toBeInTheDocument();
    expect(within(system).getByText('Detection: GPU · cuda:0')).toBeInTheDocument();
    // recordings and cache
    expect(await screen.findByText('1,200')).toBeInTheDocument();
    expect(screen.getByText('3 min')).toBeInTheDocument();
    // the server header
    expect(await screen.findByText(/Server v1\.0\.0 · up for 1 h 1 min/)).toBeInTheDocument();
  });

  it('counts recordings per day over the last 14 days, oldest first', () => {
    const today = new Date('2026-09-10T12:00:00Z');
    const days = recordingsPerDay(['2026-09-10T05:00:00Z', '2026-09-10T06:00:00Z', '2026-09-01T00:00:00Z', '2026-08-01T00:00:00Z'], 14, today);
    expect(days).toHaveLength(14);
    expect(days[0]).toEqual({ day: '2026-08-28', count: 0 });
    expect(days[13]).toEqual({ day: '2026-09-10', count: 2 });
    expect(days.find((d) => d.day === '2026-09-01')?.count).toBe(1);
  });
});
