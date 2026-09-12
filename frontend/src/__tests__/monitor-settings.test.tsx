/**
 * Each camera's live-detection setup, remembered — the monitor settings store and
 * the header affordances built on it.
 *
 * ★ What these pin: the setup is keyed BY CAMERA and survives a reload (the whole
 *   point — no re-setup on every visit), a corrupt persisted entry is dropped
 *   rather than fed into a slider, a removed camera takes its setup with it, and
 *   the header offers "Edit settings" plus an honest "setup saved" that yields to
 *   "unsaved changes" while a draft is open.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen } from '@testing-library/react';

import { fakeCameras as fake } from './fakeCamerasApi';

vi.mock('../api/cameras', async () => {
  const m = await import('./fakeCamerasApi');
  return { camerasApi: m.fakeCameras.api };
});

import { MonitorHeader, type MonitorHeaderProps } from '../components/monitor/camera/MonitorHeader';
import { setLanguage } from '../i18n';
import { useCameraRegistryStore } from '../store/cameraRegistryStore';
import {
  reviveSettings,
  selectSettingsFor,
  useMonitorSettingsStore,
  type SavedMonitorSettings,
} from '../store/monitorSettingsStore';

const SETUP = {
  model: 'yolo26s.pt',
  lutSite: 'MONODEMO',
  classes: [0, 2],
  conf: 0.35,
  imgszChoice: 640,
  trackerStart: 30,
  trackerType: 'csrt',
  centreMarks: false,
  steadyBoxes: true,
};

beforeEach(() => {
  fake.rows.clear();
  useMonitorSettingsStore.setState({ byCamera: {} });
  localStorage.removeItem('le.monitorSettings.v1');
});

describe('the monitor settings store', () => {
  it('★ saves BY CAMERA — camera B never inherits camera A’s setup', () => {
    const s = useMonitorSettingsStore.getState();
    s.save('cam-a', SETUP);
    s.save('cam-b', { ...SETUP, lutSite: 'OTHER', conf: 0.6 });
    expect(selectSettingsFor('cam-a')(useMonitorSettingsStore.getState())?.lutSite).toBe(
      'MONODEMO',
    );
    expect(selectSettingsFor('cam-b')(useMonitorSettingsStore.getState())?.conf).toBe(0.6);
    expect(selectSettingsFor('cam-c')(useMonitorSettingsStore.getState())).toBeUndefined();
    // savedAt is stamped by the store, not trusted from the caller.
    expect(
      Date.parse(selectSettingsFor('cam-a')(useMonitorSettingsStore.getState())!.savedAt),
    ).toBeGreaterThan(0);
  });

  it('★ survives a reload — the persisted entry rehydrates intact', async () => {
    useMonitorSettingsStore.getState().save('cam-a', SETUP);
    // What the last session wrote to disk…
    const written = localStorage.getItem('le.monitorSettings.v1');
    expect(written).toContain('MONODEMO');
    // …is what a fresh boot reads. (Clearing state also persists the clear, so
    // the snapshot is put back first — that IS the reload being simulated.)
    useMonitorSettingsStore.setState({ byCamera: {} });
    localStorage.setItem('le.monitorSettings.v1', written!);
    await useMonitorSettingsStore.persist.rehydrate();
    const back = selectSettingsFor('cam-a')(useMonitorSettingsStore.getState());
    expect(back).toMatchObject(SETUP);
  });

  it('drops a corrupt persisted entry, keeps its neighbours', async () => {
    const good: SavedMonitorSettings = { ...SETUP, savedAt: new Date().toISOString() };
    localStorage.setItem(
      'le.monitorSettings.v1',
      JSON.stringify({
        state: {
          byCamera: {
            'cam-good': good,
            'cam-conf': { ...good, conf: 7 }, // out of range
            'cam-classes': { ...good, classes: ['person'] }, // not numbers
            'cam-imgsz': { ...good, imgszChoice: 'big' }, // not a number/null
          },
        },
        version: 1,
      }),
    );
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    await useMonitorSettingsStore.persist.rehydrate();
    const byCamera = useMonitorSettingsStore.getState().byCamera;
    expect(Object.keys(byCamera)).toEqual(['cam-good']);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('dropped 3'));
    warn.mockRestore();
  });

  it('reviveSettings accepts the null imgsz choice ("device default") as itself', () => {
    const revived = reviveSettings({ ...SETUP, imgszChoice: null, savedAt: 'nonsense' });
    expect(revived?.imgszChoice).toBeNull();
    // An unparseable savedAt degrades to the epoch, never to a crash.
    expect(revived?.savedAt).toBe(new Date(0).toISOString());
  });

  it('★ removing a camera from the registry forgets its setup too', async () => {
    const cam = await useCameraRegistryStore.getState().add({
      name: 'gate',
      lat: 34.1,
      lon: 36.0,
      source: 'http://cam/stream',
    });
    useMonitorSettingsStore.getState().save(cam.id, SETUP);
    await useCameraRegistryStore.getState().remove(cam.id);
    expect(selectSettingsFor(cam.id)(useMonitorSettingsStore.getState())).toBeUndefined();
    expect(fake.rows.has(cam.id)).toBe(false);
  });

  it('★ an old persisted entry without steadyBoxes revives with it ON', () => {
    const { steadyBoxes: _dropped, ...legacy } = SETUP;
    expect(reviveSettings(legacy)?.steadyBoxes).toBe(true);
    // ...but an operator's explicit OFF survives the round trip.
    expect(reviveSettings({ ...SETUP, steadyBoxes: false })?.steadyBoxes).toBe(false);
  });

  it('★ an old persisted entry without centreMarks revives with it OFF', () => {
    const { centreMarks: _dropped, ...legacy } = SETUP;
    const revived = reviveSettings({ ...legacy, savedAt: new Date().toISOString() });
    expect(revived?.centreMarks).toBe(false);
  });

  it('★ rekey moves a setup from the browser id to the server id', () => {
    useMonitorSettingsStore.getState().save('01J8OLDULID', SETUP);
    useMonitorSettingsStore.getState().rekey('01J8OLDULID', 'uuid-new');
    expect(selectSettingsFor('01J8OLDULID')(useMonitorSettingsStore.getState())).toBeUndefined();
    expect(selectSettingsFor('uuid-new')(useMonitorSettingsStore.getState())?.lutSite).toBe(
      'MONODEMO',
    );
  });
});

describe('the monitor header’s settings affordances', () => {
  const base: MonitorHeaderProps = {
    camera: {
      id: 'cam-a',
      name: 'gate',
      lat: 34.1,
      lon: 36.0,
      source: 'http://cam/stream',
      created_at: new Date().toISOString(),
    },
    status: 'live',
    dirty: false,
    detecting: false,
    starting: false,
    runStartedAt: null,
    startBlocker: null,
    startError: null,
    onDismissError: () => undefined,
    onApply: () => undefined,
    onStart: () => undefined,
    onStop: () => undefined,
    trackedCount: 0,
    onCapture: () => undefined,
    captureBusy: false,
    recordingStartedAt: null,
    recordBusy: false,
    onToggleRecord: () => undefined,
    onOpenLibrary: () => undefined,
  };

  const mount = (over: Partial<MonitorHeaderProps>): void => {
    setLanguage('en');
    render(
      <MemoryRouter>
        <MonitorHeader {...base} {...over} />
      </MemoryRouter>,
    );
  };

  it('★ "Edit settings" opens the editor — the door back into the setup', () => {
    const onEdit = vi.fn();
    mount({ onEditSettings: onEdit });
    fireEvent.click(screen.getByRole('button', { name: 'Edit settings' }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it('hides the Edit button when the editor is already on screen', () => {
    mount({});
    expect(screen.queryByRole('button', { name: 'Edit settings' })).toBeNull();
  });

  it('★ a draft says "unsaved changes" — the one saving state worth a word', () => {
    mount({ dirty: true });
    expect(screen.getByText('unsaved changes')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply changes' })).toBeInTheDocument();
  });

  // ★ 2026-09-10, owner ask: the header no longer badges the ordinary cases.
  //   "setup saved" is gone, and so is the live/lost status pill — the picture
  //   carries the feed's state in its own corner, a data-only camera in its panel.
  it('★ says nothing about saving, and does not repeat the feed status', () => {
    mount({});
    expect(screen.queryByText('setup saved')).toBeNull();
    expect(screen.queryByText('live')).toBeNull();
    mount({ status: 'lost' });
    expect(screen.queryByText(/stalled 6 s/)).toBeNull();
  });

  // ── the watch-time action: Capture ─────────────────────────────────────────
  // ★ The drift watch has no header button any more (2026-09-08): it is the
  //   camera's own, frozen on its frame in the settings; this page only reads.

  it('★ Capture stays live THROUGH a detection run (owner decision); no Drift watch door', () => {
    // The server taps the running session's own frames — Capture needs no stop.
    mount({ detecting: true, runStartedAt: Date.now() });
    expect(screen.getByRole('button', { name: 'Capture' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Stop' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Drift watch' })).toBeNull();
  });

  it('Capture needs the stream live', () => {
    mount({ status: 'connecting' });
    expect(screen.getByRole('button', { name: 'Capture' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Drift watch' })).toBeNull();
  });
});
