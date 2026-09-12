/**
 * The inspector's gates — ① to ⑤ — and the overlay's fit.
 *
 * ★ A gated stage says WHY and links to the fix; a satisfied one shows a check and
 *   a one-line summary. The rules are pure (`computeStages`), so every gate is
 *   pinned without a stream; the rendered `InspectorStage` is checked once for the
 *   check / fix-link contract.
 */

import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';

import { containRect, cssToMedia, mediaToCss } from '../lib/monitor/fit';
import {
  computeStages,
  runAverageFps,
  startBlocker,
  type StageInputs,
} from '../lib/monitor/stages';
import { InspectorStage } from '../components/monitor/camera/InspectorStage';

const base: StageInputs = {
  feedStatus: 'idle',
  stats: { fps: null, width: null, height: null, encoding: null },
  detectorAvailable: true,
  detectorReason: null,
  detecting: false,
  lutSite: '',
  appliedLut: '',
  lutHasPose: null,
  trackerStart: 0,
  trackerType: 'csrt',
  driftFrozen: false,
  driftWatching: false,
  driftState: null,
  driftStatus: null,
  driftError: null,
  modelName: 'yolo26s.pt',
  classesLabel: 'all classes',
  conf: 0.25,
  imgsz: 640,
};

describe('computeStages', () => {
  it('★ nothing live: ① and ② gated, Start blocked on ①', () => {
    const stages = computeStages(base);
    // ④ Tracking is always ready now (operator-chosen, not a gate); the rest gate.
    expect(stages.map((s) => s.satisfied)).toEqual([false, false, false, true, false]);
    expect(stages[1].summary).toContain('needs the source live');
    expect(startBlocker(stages, false)).toContain('①');
  });

  it('★ live: ① summarises the measured stream, ② opens, ③ links to the camera’s settings', () => {
    const stages = computeStages({
      ...base,
      feedStatus: 'live',
      stats: { fps: 30, width: 1280, height: 720, encoding: 'MJPEG' },
    });
    expect(stages[0].satisfied).toBe(true);
    expect(stages[0].summary).toBe('● live 30 fps 1280×720 MJPEG');
    expect(stages[1].satisfied).toBe(true);
    expect(stages[2].satisfied).toBe(false);
    expect(stages[2].fix?.to).toBe('/cameras');
    expect(startBlocker(stages, false)).toBeNull();
  });

  it('★ lost and refused name themselves and offer Reconnect', () => {
    expect(computeStages({ ...base, feedStatus: 'lost' })[0].summary).toContain('stalled 6 s');
    expect(computeStages({ ...base, feedStatus: 'refused' })[0].fix?.action).toBe('reconnect');
  });

  it('★ a chosen-but-unapplied table offers Apply; ④ is armed with the run; ⑤ reads the camera’s watch', () => {
    const s = computeStages({ ...base, feedStatus: 'live', lutSite: 'site', appliedLut: '' });
    expect(s[2].satisfied).toBe(true);
    expect(s[2].fix?.action).toBe('apply');
    // ★ Tracking is ARMED WITH THE RUN (2026-09-08): no button, no frame gate —
    //   the stage is always ready, says to click an object, and offers no fix.
    expect(s[3].satisfied).toBe(true);
    expect(s[3].summary).toContain('armed with the run');
    expect(s[3].summary).toContain('click a detected object');
    expect(s[3].summary).not.toContain('Start tracking');
    expect(s[3].fix).toBeUndefined();
    // ★ ⑤ is the CAMERA'S background watch, frozen on its frame in the settings —
    //   this page never freezes. Unfrozen: say where it is made, link there.
    expect(s[4].satisfied).toBe(false);
    expect(s[4].summary).toContain('not frozen yet');
    expect(s[4].summary).toContain('camera settings');
    expect(s[4].fix?.to).toBe('/cameras');
    expect(s[4].fix?.action).toBeUndefined();
    const none = computeStages({ ...base, lutSite: '', appliedLut: '', settingsTo: '/cameras/c1/settings' });
    expect(none[4].summary).toContain('build the lookup table');
    expect(none[4].fix?.to).toBe('/cameras/c1/settings');

    // frozen but the watch is down: not satisfied, the settings are the remedy
    const stalled = computeStages({ ...base, lutSite: 'site', driftFrozen: true, driftWatching: false });
    expect(stalled[4].satisfied).toBe(false);
    expect(stalled[4].summary).toContain('watch is not running');
    const failed = computeStages({
      ...base,
      driftFrozen: true,
      driftWatching: false,
      driftError: 'frames no longer fit the reference',
    });
    expect(failed[4].summary).toContain('the watch stopped: frames no longer fit');

    // watching: satisfied, no fix, the reading in the line
    const fresh = computeStages({ ...base, driftFrozen: true, driftWatching: true });
    expect(fresh[4].satisfied).toBe(true);
    expect(fresh[4].summary).toContain('no look has run yet');
    expect(fresh[4].fix).toBeUndefined();
    const ok = computeStages({
      ...base,
      driftFrozen: true,
      driftWatching: true,
      driftState: 'OK',
      driftStatus: 'OK',
    });
    expect(ok[4].summary).toBe('watching live · OK (confirmed)');
    const moving = computeStages({
      ...base,
      driftFrozen: true,
      driftWatching: true,
      driftState: 'MOVED',
      driftStatus: 'OK',
    });
    expect(moving[4].summary).toBe('watching live · MOVED (confirmed OK)');
  });

  it('★ while a run holds the source, ① reports the RUN’s own rate, size and phase', () => {
    const s = computeStages({
      ...base,
      detecting: true,
      run: { fps: 13.6, phase: 'tracker', width: 1920, height: 1080 },
    });
    expect(s[0].satisfied).toBe(true);
    expect(s[0].summary).toBe('detecting · 13.6 fps · 1920×1080 · tracker');
    // before the first frame there is nothing to report but the fact of the run
    const early = computeStages({
      ...base,
      detecting: true,
      run: { fps: 0, phase: 'detector', width: 0, height: 0 },
    });
    expect(early[0].summary).toBe('detecting · detector');
  });

  it('a missing runtime shows the server’s reason in ② and blocks Start on ②', () => {
    const s = computeStages({
      ...base,
      feedStatus: 'live',
      detectorAvailable: false,
      detectorReason: 'pip install ultralytics',
    });
    expect(s[1].summary).toBe('pip install ultralytics');
    expect(startBlocker(s, false)).toContain('②');
  });
});

describe('InspectorStage', () => {
  it('★ a gated stage renders its line and a link to the fix; a satisfied one a check', () => {
    const stages = computeStages({
      ...base,
      feedStatus: 'live',
      stats: { fps: 30, width: 1280, height: 720, encoding: 'MJPEG' },
    });
    render(
      <MemoryRouter>
        <InspectorStage stage={stages[0]}>
          <div>body</div>
        </InspectorStage>
        <InspectorStage stage={stages[2]}>
          <div>body</div>
        </InspectorStage>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('stage-source').getAttribute('data-satisfied')).toBe('true');
    expect(screen.getByTestId('stage-placement').getAttribute('data-satisfied')).toBe('false');
    expect(screen.getByRole('link', { name: /Set up the lookup table/ }).getAttribute('href')).toBe(
      '/cameras',
    );
  });
});

describe('containRect — the overlay’s fit', () => {
  it('letterboxes a 16:9 picture in a square box and maps points through it', () => {
    const fit = containRect(1000, 1000, 1920, 1080);
    expect(fit.width).toBeCloseTo(1000);
    expect(fit.height).toBeCloseTo(562.5);
    expect(fit.x).toBeCloseTo(0);
    expect(fit.y).toBeCloseTo(218.75);
    // the media's centre lands at the box's centre
    const [cx, cy] = mediaToCss(fit, 960, 540);
    expect(cx).toBeCloseTo(500);
    expect(cy).toBeCloseTo(500);
    const back = cssToMedia(fit, 500, 500);
    expect(back?.[0]).toBeCloseTo(960);
    expect(back?.[1]).toBeCloseTo(540);
    // a click in the letterbox band is outside the picture
    expect(cssToMedia(fit, 500, 10)).toBeNull();
  });

  it('pillarboxes a tall picture and answers zero for an empty box', () => {
    const fit = containRect(800, 400, 1080, 1920);
    expect(fit.height).toBeCloseTo(400);
    expect(fit.x).toBeCloseTo(287.5);
    expect(containRect(0, 0, 1, 1).scale).toBe(0);
  });
});

describe('runAverageFps — frames over the clock', () => {
  it('★ is a count over time, never a smoothed guess — and nothing under a second', () => {
    const started = '2026-08-30T10:00:00.000Z';
    const t0 = Date.parse(started);
    expect(runAverageFps(150, started, t0 + 10_000)).toBeCloseTo(15, 5);
    expect(runAverageFps(0, started, t0 + 10_000)).toBeNull();
    expect(runAverageFps(5, started, t0 + 500)).toBeNull();
    expect(runAverageFps(5, 'not a date', t0)).toBeNull();
  });
});
