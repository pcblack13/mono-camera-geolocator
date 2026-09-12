/**
 * The camera registry — validation that refuses rather than guesses, persistence
 * that drops what it cannot trust.
 *
 * ★ L12 in a store: a transposed lat/lon is REFUSED WITH A HINT, never swapped for
 *   the user; a corrupt persisted row is dropped and counted, never a boot crash.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeCameras as fake } from './fakeCamerasApi';

// ★ The store is a cache of the server (1.3): every add / import / remove goes
//   through `camerasApi`, played here by an in-memory server.
vi.mock('../api/cameras', async () => {
  const m = await import('./fakeCamerasApi');
  return { camerasApi: m.fakeCameras.api };
});

import {
  isServerCameraId,
  parseCameraCsv,
  selectIsLive,
  selectLiveCount,
  useCameraRegistryStore,
  validateCamera,
} from '../store/cameraRegistryStore';
import { useMonitorSettingsStore } from '../store/monitorSettingsStore';

beforeEach(() => {
  fake.rows.clear();
  useCameraRegistryStore.setState({
    cameras: [],
    statuses: {},
    droppedOnLoad: 0,
    hydrated: false,
    legacy: [],
  });
  useMonitorSettingsStore.setState({ byCamera: {} });
});

describe('validateCamera', () => {
  it('accepts a well-formed camera and normalises its numbers', () => {
    const r = validateCamera({
      name: ' Roof Pi ',
      lat: '33.8330',
      lon: '35.5410',
      source: 'http://pi.local:8080/stream',
      heading_deg: '120',
      fov_deg: '',
      fps: '25.4',
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.value).toEqual({
        name: 'Roof Pi',
        lat: 33.833,
        lon: 35.541,
        source: 'http://pi.local:8080/stream',
        heading_deg: 120,
        fps: 25,
      });
    }
  });

  it('★ refuses NaN, out-of-range and an empty source — every field named', () => {
    const r = validateCamera({ name: '', lat: 'abc', lon: 500, source: '' });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.errors.map((e) => e.field).sort()).toEqual(['lat', 'lon', 'name', 'source']);
    }
  });

  it('★ a transposed pair is refused WITH the swap hint — never swapped silently', () => {
    const r = validateCamera({ name: 'x', lat: 35.541, lon: 33.833, source: 'rtsp://c/s' });
    expect(r.ok).toBe(true); // both in range: nothing to say
    const swapped = validateCamera({ name: 'x', lat: 135.5, lon: 33.8, source: 'rtsp://c/s' });
    expect(swapped.ok).toBe(false);
    if (!swapped.ok) {
      expect(swapped.errors).toHaveLength(1);
      expect(swapped.errors[0].field).toBe('lat');
      expect(swapped.errors[0].hint).toBe('swap');
    }
  });

  it('accepts local device sources and refuses file:// and nonsense', () => {
    expect(validateCamera({ name: 'a', lat: 1, lon: 1, source: '/dev/video0' }).ok).toBe(true);
    expect(validateCamera({ name: 'a', lat: 1, lon: 1, source: '0' }).ok).toBe(true);
    expect(validateCamera({ name: 'a', lat: 1, lon: 1, source: 'file:///etc/passwd' }).ok).toBe(
      false,
    );
  });
});

describe('parseCameraCsv', () => {
  it('judges every row, skips a header and blank lines, and keeps line numbers', () => {
    const rows = parseCameraCsv(
      'name,lat,lon,source\nA,33.8,35.5,http://a/s,120,60\n\nB,999,35.5,http://b/s\nC,33.9\n',
    );
    expect(rows.map((r) => r.line)).toEqual([2, 4, 5]);
    expect(rows[0].result.ok).toBe(true);
    expect(rows[1].result.ok).toBe(false);
    expect(rows[2].result.ok).toBe(false);
    if (!rows[2].result.ok) expect(rows[2].result.errors[0].field).toBe('row');
  });
});

describe('the store', () => {
  it('adds through the server, keeps ITS id, tracks transient status, and answers boolean selectors', async () => {
    const cam = await useCameraRegistryStore
      .getState()
      .add({ name: 'A', lat: 33.833, lon: 35.541, source: 'http://a/s' });
    expect(isServerCameraId(cam.id)).toBe(true);
    expect(fake.rows.has(cam.id)).toBe(true);
    expect(selectIsLive(cam.id)(useCameraRegistryStore.getState())).toBe(false);
    useCameraRegistryStore.getState().setStatus(cam.id, 'live');
    expect(selectIsLive(cam.id)(useCameraRegistryStore.getState())).toBe(true);
    expect(selectLiveCount(useCameraRegistryStore.getState())).toBe(1);
  });

  it('★ exports JSON that imports back, and refuses a broken document without touching the registry', async () => {
    const s = useCameraRegistryStore.getState();
    const cam = await s.add({ name: 'A', lat: 1, lon: 2, source: 'http://a/s' });
    const text = s.exportJson();
    // A known server id is PATCHED, not duplicated…
    const r = await useCameraRegistryStore.getState().importJson(text);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value).toEqual({ added: 0, updated: 1 });
    expect(useCameraRegistryStore.getState().cameras).toHaveLength(1);
    expect(fake.rows.size).toBe(1);
    // …an unknown one is created, and a broken document changes nothing.
    const fresh = await useCameraRegistryStore
      .getState()
      .importJson(JSON.stringify({ cameras: [{ name: 'B', lat: 3, lon: 4, source: 'rtsp://b/s' }] }));
    expect(fresh.ok).toBe(true);
    expect(useCameraRegistryStore.getState().cameras).toHaveLength(2);
    const bad = await useCameraRegistryStore.getState().importJson('{"cameras":[{"name":"x"}]}');
    expect(bad.ok).toBe(false);
    expect(useCameraRegistryStore.getState().cameras).toHaveLength(2);
    expect(cam.id).not.toBe('');
  });

  it('★ hydrate replaces the cache with the server’s list and sets pre-1.3 rows aside', async () => {
    // a browser that ran 1.2.x: a ULID row nobody on the server knows about
    useCameraRegistryStore.setState({
      cameras: [
        { id: '01J8ULIDULIDULIDULIDULIDUL', name: 'Old', lat: 1, lon: 2, source: 'http://o/s', created_at: 'x' },
      ],
    });
    await fake.api.create({ name: 'Server', lat: 5, lon: 6, source: 'rtsp://s/1' });
    useCameraRegistryStore.getState().hydrate(await fake.api.all());
    const st = useCameraRegistryStore.getState();
    expect(st.hydrated).toBe(true);
    expect(st.cameras.map((c) => c.name)).toEqual(['Server']);
    expect(st.legacy.map((c) => c.name)).toEqual(['Old']);
  });

  it('★ migrateLegacy moves the rows across and re-keys their saved setups', async () => {
    const oldId = '01J8ULIDULIDULIDULIDULIDUL';
    useCameraRegistryStore.setState({
      cameras: [{ id: oldId, name: 'Old', lat: 1, lon: 2, source: 'http://o/s', created_at: 'x' }],
    });
    useMonitorSettingsStore.getState().save(oldId, {
      model: 'yolo26s.pt', lutSite: 'SITE', classes: [], conf: 0.3, imgszChoice: null,
      trackerStart: 0, trackerType: 'csrt', centreMarks: false, steadyBoxes: true,
    });
    useCameraRegistryStore.getState().hydrate([]);
    const moved = await useCameraRegistryStore.getState().migrateLegacy();
    expect(moved).toBe(1);
    const st = useCameraRegistryStore.getState();
    expect(st.legacy).toEqual([]);
    expect(st.cameras).toHaveLength(1);
    const newId = st.cameras[0].id;
    expect(isServerCameraId(newId)).toBe(true);
    const settings = useMonitorSettingsStore.getState().byCamera;
    expect(settings[oldId]).toBeUndefined();
    expect(settings[newId]?.lutSite).toBe('SITE');
  });

  it('★ rehydrates by re-validating: corrupt rows are dropped and counted, never a crash', () => {
    const persisted = {
      cameras: [
        { id: 'ok1', name: 'Good', lat: 33.8, lon: 35.5, source: 'http://a/s', created_at: 'x' },
        { id: 'bad', name: 'Bad', lat: 'nope', lon: 35.5, source: 'http://b/s' },
        'garbage',
        { id: 'ok1', name: 'Dup', lat: 1, lon: 1, source: 'http://c/s' },
      ],
    };
    const options = useCameraRegistryStore.persist.getOptions();
    const merged = options.merge!(persisted, useCameraRegistryStore.getState()) as ReturnType<
      typeof useCameraRegistryStore.getState
    >;
    expect(merged.cameras.map((c) => c.id)).toEqual(['ok1']);
    expect(merged.droppedOnLoad).toBe(3);
    expect(merged.statuses).toEqual({});
    expect(merged.hydrated).toBe(false);
  });
});
