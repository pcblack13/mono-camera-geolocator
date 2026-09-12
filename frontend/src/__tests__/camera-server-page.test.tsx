/**
 * The CAMERA WORKSPACE page (2026-09-04; redesigned 2026-09-07) — one of the main pages.
 *
 * ★ What these pin: with no cameras the page IS the ask (add the first one);
 *   with cameras it shows them as cards beside an "Add camera"; a card's note
 *   says how far the setup is and what comes next, its primary button is the one
 *   thing the camera needs (watch, or continue the setup), the other page is a
 *   secondary button and the menu; search and the Ready / In setup toggle filter
 *   the cards; removing goes through the menu, a confirmation, and the server.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

vi.mock('../api/cameras', async () => {
  const m = await import('./fakeCamerasApi');
  return { camerasApi: m.fakeCameras.api };
});
vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));

import { CameraServerPage } from '../pages/cameras/CameraServerPage';
import { setLanguage } from '../i18n';
import { useCameraRegistryStore, type RegisteredCamera } from '../store/cameraRegistryStore';
import { fakeCameras as fake } from './fakeCamerasApi';

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mount(): void {
  setLanguage('en');
  render(
    <MemoryRouter initialEntries={['/cameras']}>
      <CameraServerPage />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

const GATE: RegisteredCamera = {
  id: '00000000-0000-4000-8000-000000000101',
  name: 'North gate',
  lat: 34.1,
  lon: 36.0,
  source: 'rtsp://cam/1',
  connection: 'lan',
  created_at: '2026-09-04T08:00:00Z',
};
const ROOF: RegisteredCamera = {
  id: '00000000-0000-4000-8000-000000000102',
  name: 'Roof Pi',
  lat: 33.9,
  lon: 35.5,
  source: 'http://pi.local:8080/stream',
  connection: 'lan',
  project_id: '00000000-0000-4000-8000-000000000901',
  frame_image_id: '00000000-0000-4000-8000-000000000801',
  calibration: {
    fx: 1000,
    fy: 1000,
    cx: 640,
    cy: 360,
    k1: null,
    k2: null,
    p1: null,
    p2: null,
    k3: null,
    mast_offset_m: null,
    tilt_deg: null,
  },
  lut_site: 'roof_pi',
  created_at: '2026-09-04T08:00:00Z',
};

beforeEach(() => {
  fake.rows.clear();
  useCameraRegistryStore.setState({ cameras: [], statuses: {}, hydrated: true });
});

describe('the camera workspace', () => {
  it('★ with no cameras, the page asks for the first one — and that is the whole page', () => {
    mount();
    expect(screen.getByText('No cameras on the server yet')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Add camera' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Add your first camera' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/cameras/new');
  });

  it('★ with cameras, it lists them beside an Add button and says what each setup has', () => {
    useCameraRegistryStore.setState({ cameras: [GATE, ROOF] });
    mount();
    expect(screen.getByRole('heading', { name: 'Camera workspace' })).toBeVisible();
    expect(screen.getByText(/2 cameras registered/)).toBeVisible();
    const list = screen.getByRole('list', { name: 'Registered cameras' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);

    expect(screen.getByText(/1 ready · 1 in setup/)).toBeVisible();

    // the unfinished camera's note names what its setup still lacks (2026-09-10:
    // no meter); its primary button continues the setup — and its cover opens
    // the same place
    const gate = within(list).getByRole('listitem', { name: 'North gate' });
    expect(within(gate).queryByRole('img', { name: /Setup/ })).toBeNull();
    expect(within(gate).getByTestId('setup-note')).toHaveTextContent(
      'Missing: Calibration · Frame · Lookup table',
    );
    expect(within(gate).getByText('In setup')).toBeVisible();
    expect(within(gate).getByText('UTP / LAN')).toBeVisible();
    // ★ 2026-09-10: no frame chosen yet → nothing to review
    expect(within(gate).queryByRole('button', { name: 'Review control points' })).toBeNull();
    // the address is no longer printed on the card — it is the caption's tooltip
    expect(within(gate).queryByText('rtsp://cam/1')).toBeNull();
    fireEvent.click(within(gate).getByRole('button', { name: 'Continue setup' }));
    expect(screen.getByTestId('loc')).toHaveTextContent(`/cameras/${GATE.id}/settings`);
    fireEvent.click(within(gate).getByRole('button', { name: 'Watch' }));
    expect(screen.getByTestId('loc')).toHaveTextContent(`/monitor/cameras/${GATE.id}`);
    fireEvent.click(within(gate).getByRole('button', { name: 'Open North gate' }));
    expect(screen.getByTestId('loc')).toHaveTextContent(`/cameras/${GATE.id}/settings`);

    // the finished one is READY: its primary button watches, its cover too;
    // the settings are the secondary button
    const roof = within(list).getByRole('listitem', { name: 'Roof Pi' });
    expect(within(roof).getByText('Ready')).toBeVisible();
    expect(within(roof).getByText(/Ready — marks land on the map/)).toBeVisible();
    fireEvent.click(within(roof).getByRole('button', { name: 'Watch' }));
    expect(screen.getByTestId('loc')).toHaveTextContent(`/monitor/cameras/${ROOF.id}`);
    fireEvent.click(within(roof).getByRole('button', { name: 'Open Roof Pi' }));
    expect(screen.getByTestId('loc')).toHaveTextContent(`/monitor/cameras/${ROOF.id}`);
    fireEvent.click(within(roof).getByRole('button', { name: 'Settings' }));
    expect(screen.getByTestId('loc')).toHaveTextContent(`/cameras/${ROOF.id}/settings`);

    // ★ 2026-09-10: a frame is chosen, so its points can be reviewed — straight
    //   to the editor, without going through the settings first.
    fireEvent.click(within(roof).getByRole('button', { name: 'Review control points' }));
    expect(screen.getByTestId('loc')).toHaveTextContent(`/cameras/${ROOF.id}/editor`);

    fireEvent.click(screen.getByRole('button', { name: 'Add camera' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/cameras/new');
  });

  it('★ search and the Ready / In setup toggle narrow the cards; clearing brings them back', () => {
    useCameraRegistryStore.setState({ cameras: [GATE, ROOF] });
    mount();
    const list = (): HTMLElement => screen.getByRole('list', { name: 'Registered cameras' });
    fireEvent.click(screen.getByRole('button', { name: 'Ready' }));
    expect(
      within(list())
        .getAllByRole('listitem')
        .map((li) => li.getAttribute('aria-label')),
    ).toEqual(['Roof Pi']);
    fireEvent.click(screen.getByRole('button', { name: 'In setup' }));
    expect(
      within(list())
        .getAllByRole('listitem')
        .map((li) => li.getAttribute('aria-label')),
    ).toEqual(['North gate']);
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    // the search matches the name or the address
    fireEvent.change(screen.getByRole('textbox', { name: 'Search cameras' }), {
      target: { value: 'pi.local' },
    });
    expect(within(list()).getAllByRole('listitem')).toHaveLength(1);
    fireEvent.change(screen.getByRole('textbox', { name: 'Search cameras' }), {
      target: { value: 'nothing like this' },
    });
    expect(screen.queryByRole('list', { name: 'Registered cameras' })).toBeNull();
    expect(screen.getByText('No camera matches.')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(within(list()).getAllByRole('listitem')).toHaveLength(2);
  });

  it('★ removing lives in the card menu, asks first, then goes to the server and drops the card', async () => {
    const removeSpy = vi.spyOn(fake.api, 'remove');
    useCameraRegistryStore.setState({ cameras: [GATE] });
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'More actions for North gate' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Remove from the server' }));
    expect(screen.getByText('Remove this camera?')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(removeSpy).toHaveBeenCalledWith(GATE.id));
    await waitFor(() => expect(screen.getByText('No cameras on the server yet')).toBeVisible());
  });
});
