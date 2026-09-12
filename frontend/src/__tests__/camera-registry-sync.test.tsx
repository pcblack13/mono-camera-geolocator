/**
 * `CameraRegistrySync` — the store becomes a cache of the server, and a browser
 * that ran 1.2.x is asked ONCE whether to move its cameras across.
 *
 * ★ What these pin: the server's list replaces the cached one on mount; a pre-1.3
 *   row triggers the offer exactly once (the answer is remembered either way);
 *   "Move to server" imports and re-keys; "Forget them" drops them without a
 *   server call.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { fakeCameras as fake } from './fakeCamerasApi';

vi.mock('../api/cameras', async () => {
  const m = await import('./fakeCamerasApi');
  return { camerasApi: m.fakeCameras.api };
});
vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));

import { CameraRegistrySync, MIGRATION_FLAG } from '../components/monitor/CameraRegistrySync';
import { setLanguage } from '../i18n';
import { isServerCameraId, useCameraRegistryStore } from '../store/cameraRegistryStore';
import { useMonitorSettingsStore } from '../store/monitorSettingsStore';

const LEGACY = {
  id: '01J8ULIDULIDULIDULIDULIDUL',
  name: 'Old gate',
  lat: 34.1,
  lon: 36.0,
  source: 'http://old/stream',
  created_at: '2026-08-01T00:00:00Z',
};

beforeEach(() => {
  setLanguage('en');
  fake.rows.clear();
  localStorage.removeItem(MIGRATION_FLAG);
  useCameraRegistryStore.setState({
    cameras: [],
    statuses: {},
    droppedOnLoad: 0,
    hydrated: false,
    legacy: [],
  });
  useMonitorSettingsStore.setState({ byCamera: {} });
});

describe('CameraRegistrySync', () => {
  it('replaces the cached list with the server’s on mount', async () => {
    await fake.api.create({ name: 'Server cam', lat: 1, lon: 2, source: 'rtsp://s/1' });
    render(<CameraRegistrySync />);
    await waitFor(() => {
      expect(useCameraRegistryStore.getState().hydrated).toBe(true);
    });
    expect(useCameraRegistryStore.getState().cameras.map((c) => c.name)).toEqual(['Server cam']);
    expect(screen.queryByText('Move your cameras to the server?')).toBeNull();
  });

  it('★ offers to move a pre-1.3 browser row, once, and re-keys its setup', async () => {
    useCameraRegistryStore.setState({ cameras: [LEGACY] });
    useMonitorSettingsStore.getState().save(LEGACY.id, {
      model: 'yolo26s.pt',
      lutSite: 'SITE',
      classes: [],
      conf: 0.3,
      imgszChoice: null,
      trackerStart: 0,
      trackerType: 'csrt',
      centreMarks: false,
      steadyBoxes: true,
    });
    render(<CameraRegistrySync />);
    expect(await screen.findByText('Move your cameras to the server?')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Move to server' }));
    await waitFor(() => {
      expect(useCameraRegistryStore.getState().legacy).toEqual([]);
    });
    const cams = useCameraRegistryStore.getState().cameras;
    expect(cams).toHaveLength(1);
    expect(cams[0].name).toBe('Old gate');
    expect(isServerCameraId(cams[0].id)).toBe(true);
    expect(useMonitorSettingsStore.getState().byCamera[cams[0].id]?.lutSite).toBe('SITE');
    expect(localStorage.getItem(MIGRATION_FLAG)).toBe('imported');
  });

  it('★ "Forget them" drops the rows, calls no server, and is not asked again', async () => {
    useCameraRegistryStore.setState({ cameras: [LEGACY] });
    render(<CameraRegistrySync />);
    fireEvent.click(await screen.findByRole('button', { name: 'Forget them' }));
    await waitFor(() => {
      expect(useCameraRegistryStore.getState().legacy).toEqual([]);
    });
    expect(fake.rows.size).toBe(0);
    expect(useCameraRegistryStore.getState().cameras).toEqual([]);
    expect(localStorage.getItem(MIGRATION_FLAG)).toBe('discarded');
    // a second mount with another stray row stays silent
    useCameraRegistryStore.setState({ cameras: [LEGACY], hydrated: false, legacy: [] });
    render(<CameraRegistrySync />);
    await waitFor(() => {
      expect(useCameraRegistryStore.getState().hydrated).toBe(true);
    });
    expect(screen.queryByText('Move your cameras to the server?')).toBeNull();
  });
});
