/**
 * The app-status page — the ConnectionChip's popover in full, plus the log monitor.
 *
 * ★ What these pin: every component arrives with its job explained (the page's
 *   whole reason to exist over the popover), the log tail renders what the server
 *   sends and lets the reader open a traceback, the filters narrow without
 *   refetching, and the chip's button is a real door to `/status`.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { setLanguage } from '../i18n';
import { asIsoDateTime } from '../types/common';
import type { LogsResponse, ReadinessResponse } from '../types/capabilities';

vi.mock('../api/capabilities', () => ({
  capabilitiesApi: {
    get: vi.fn(),
    health: vi.fn(),
    readiness: vi.fn(),
    logs: vi.fn(),
  },
}));

import { capabilitiesApi } from '../api/capabilities';
import { StatusPage } from '../pages/StatusPage';
import { ConnectionChip } from '../components/shell/ConnectionChip';

const READINESS: ReadinessResponse = {
  status: 'degraded',
  checked_at: asIsoDateTime('2026-09-01T08:00:00Z'),
  components: [
    { name: 'postgres', status: 'up', latency_ms: 1.2, message: null },
    { name: 'redis', status: 'up', latency_ms: 0.4, message: null },
    { name: 'storage', status: 'up', latency_ms: 2.1, message: null },
    { name: 'celery', status: 'degraded', latency_ms: 0.1, message: 'no worker configured' },
    { name: 'imagery', status: 'up', latency_ms: 0.2, message: null },
    { name: 'models', status: 'up', latency_ms: 0.1, message: null },
    { name: 'raster', status: 'up', latency_ms: 0.3, message: 'backend=rasterio' },
  ],
};

const LOGS: LogsResponse = {
  entries: [
    {
      seq: 1,
      timestamp: '2026-09-01T08:00:01Z',
      level: 'info',
      logger: 'app.main',
      event: 'api.started',
      request_id: null,
      exception: null,
      fields: {},
    },
    {
      seq: 2,
      timestamp: '2026-09-01T08:00:02Z',
      level: 'warning',
      logger: 'app.services.imagery_service',
      event: 'slow tile fetch',
      request_id: null,
      exception: null,
      fields: { provider: 'esri' },
    },
    {
      seq: 3,
      timestamp: '2026-09-01T08:00:03Z',
      level: 'error',
      logger: 'app.tasks',
      event: 'job.failed',
      request_id: '01JREQUESTID',
      exception: 'Traceback (most recent call last):\n  RuntimeError: boom',
      fields: { job_id: 'j-1' },
    },
  ],
  last_seq: 3,
  dropped_before: 0,
  capacity: 2000,
  checked_at: asIsoDateTime('2026-09-01T08:00:05Z'),
};

const EMPTY_LOGS: LogsResponse = { ...LOGS, entries: [] };

function mountPage(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <StatusPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setLanguage('en');
  vi.mocked(capabilitiesApi.readiness).mockResolvedValue(READINESS);
  vi.mocked(capabilitiesApi.health).mockResolvedValue({
    status: 'ok',
    version: '1.0.0',
    uptime_s: 4000,
  });
  // First poll delivers the tail; every later poll is quiet.
  vi.mocked(capabilitiesApi.logs).mockResolvedValue(EMPTY_LOGS);
  vi.mocked(capabilitiesApi.logs).mockResolvedValueOnce(LOGS);
});

describe('the app-status page', () => {
  it('shows every component WITH its job explained — the point of the page', async () => {
    mountPage();
    for (const name of ['postgres', 'redis', 'storage', 'celery', 'imagery', 'models', 'raster']) {
      expect(await screen.findByText(name)).toBeVisible();
    }
    // The explanation, not just the dot:
    expect(
      screen.getByText('The main database — projects, images, GCPs, detections and jobs all live here.'),
    ).toBeVisible();
    expect(
      screen.getByText('Background workers that run long jobs — ingest, exports, processing.'),
    ).toBeVisible();
    // A component's own message survives to the card.
    expect(screen.getByText('no worker configured')).toBeVisible();
    // Liveness rides along.
    expect(screen.getByText(/v1\.0\.0/)).toBeVisible();
  });

  it('tails the log and opens a traceback on click', async () => {
    mountPage();
    expect(await screen.findByText('api.started')).toBeVisible();
    expect(screen.getByText('job.failed')).toBeVisible();
    // The traceback is folded until asked for…
    expect(screen.queryByText(/RuntimeError: boom/)).toBeNull();
    fireEvent.click(screen.getByText('job.failed'));
    // …then the whole story is there: exception, request id, structured fields.
    expect(screen.getByText(/RuntimeError: boom/)).toBeVisible();
    expect(screen.getByText(/01JREQUESTID/)).toBeVisible();
    expect(screen.getByText(/j-1/)).toBeVisible();
  });

  it('counts what went wrong', async () => {
    mountPage();
    expect(await screen.findByText('1 errors')).toBeVisible();
    expect(screen.getByText('1 warnings')).toBeVisible();
  });

  it('★ the level filter narrows WITHOUT refetching — the tail is local', async () => {
    mountPage();
    expect(await screen.findByText('api.started')).toBeVisible();
    const callsBefore = vi.mocked(capabilitiesApi.logs).mock.calls.length;

    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Minimum level' }));
    fireEvent.click(within(screen.getByRole('listbox')).getByText('Errors only'));

    expect(screen.queryByText('api.started')).toBeNull();
    expect(screen.queryByText('slow tile fetch')).toBeNull();
    expect(screen.getByText('job.failed')).toBeVisible();
    expect(vi.mocked(capabilitiesApi.logs).mock.calls.length).toBe(callsBefore);
  });

  it('search reaches every field, not just the message', async () => {
    mountPage();
    expect(await screen.findByText('api.started')).toBeVisible();
    // "esri" lives only in a structured field of the warning line.
    fireEvent.change(screen.getByRole('textbox', { name: 'Search logs' }), {
      target: { value: 'esri' },
    });
    expect(screen.getByText('slow tile fetch')).toBeVisible();
    expect(screen.queryByText('api.started')).toBeNull();
    expect(screen.queryByText('job.failed')).toBeNull();
  });

  it('Clear empties the view; the empty state stays honest', async () => {
    mountPage();
    expect(await screen.findByText('api.started')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: /Clear/ }));
    expect(screen.queryByText('api.started')).toBeNull();
    expect(screen.getByText('Waiting for log entries…')).toBeVisible();
  });
});

describe('the door from the ConnectionChip', () => {
  function LocationProbe(): React.JSX.Element {
    const loc = useLocation();
    return <div data-testid="loc">{loc.pathname}</div>;
  }

  it('★ the popover offers "Open app status & logs" and it lands on /status', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/']}>
          <ConnectionChip />
          <Routes>
            <Route path="*" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole('button', { name: /System status/ }));
    const door = await screen.findByRole('button', { name: 'Open app status & logs' });
    fireEvent.click(door);
    await waitFor(() => expect(screen.getByTestId('loc')).toHaveTextContent('/status'));
  });
});
