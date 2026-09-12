/**
 * `lib/monitor/stages.ts` — the inspector's five gates, as a pure function.
 *
 * ★ THE PIPELINE IS READABLE COLLAPSED. Each stage is either satisfied (a check and
 *   a one-line summary) or gated (one line saying WHY, and what fixes it). The
 *   rule set lives here, with no React in it, so the tests can pin every gate.
 *
 *   ① Source     — the stream is live.
 *   ② Detector   — the runtime exists here, and ① is live (or a run is on).
 *   ③ Placement  — a lookup table is chosen; the map needs it to say WHERE.
 *   ④ Tracking   — armed with the run: click a detected object to follow it.
 *   ⑤ Drift      — the camera's own background watch, frozen on the frame its
 *                  control points sit on (2026-09-08, owner decision). This page
 *                  only READS it: the reference is made in the camera settings
 *                  when the lookup table is built, and re-frozen there by
 *                  choosing a new frame. No freeze, no clock, no toggle here.
 */

import type { FeedStatus, StreamStats } from '../../hooks/useLiveFeed';

export type StageKey = 'source' | 'detector' | 'placement' | 'tracking' | 'drift';

export interface StageFix {
  label: string;
  /** A route to navigate to, or an action the page performs. */
  to?: string;
  action?: 'reconnect' | 'apply';
}

export interface StageState {
  key: StageKey;
  index: 1 | 2 | 3 | 4 | 5;
  title: string;
  satisfied: boolean;
  /** One line under the title, satisfied or not. */
  summary: string;
  fix?: StageFix;
}

export interface StageInputs {
  feedStatus: FeedStatus;
  stats: Pick<StreamStats, 'fps' | 'width' | 'height' | 'encoding'>;
  detectorAvailable: boolean | null;
  detectorReason: string | null;
  detecting: boolean;
  /** While a run holds the source: its own rate, size and phase (else null). */
  run?: { fps: number; phase: string; width: number; height: number } | null;
  lutSite: string;
  appliedLut: string;
  /** For the CHOSEN table: null = unknown (library not loaded); false = no pose. */
  lutHasPose: boolean | null;
  trackerStart: number;
  trackerType: string;
  /** A drift reference exists for this camera (frozen on its frame). */
  driftFrozen: boolean;
  /** The background watch on it is running right now. */
  driftWatching: boolean;
  /** The newest reading's raw state, and the confirmed status — null until a look ran. */
  driftState: 'OK' | 'MOVED' | 'CHANGED' | 'DEGRADED' | null;
  driftStatus: 'OK' | 'MOVED' | 'CHANGED' | 'DEGRADED' | null;
  /** The watch's own trouble line (a stopped or failed run), verbatim. */
  driftError: string | null;
  modelName: string;
  classesLabel: string;
  conf: number;
  imgsz: number;
  /** Where this camera's lookup table is set up — its settings page (2026-09-04). */
  settingsTo?: string;
}

export function computeStages(i: StageInputs): StageState[] {
  const live = i.feedStatus === 'live';
  const res = i.stats.width && i.stats.height ? `${i.stats.width}×${i.stats.height}` : '';
  const fps = i.stats.fps === null ? '' : `${i.stats.fps.toFixed(0)} fps`;
  const enc = i.stats.encoding ?? '';

  const source: StageState = {
    key: 'source',
    index: 1,
    title: 'Source',
    satisfied: live || i.detecting,
    summary: i.detecting
      ? i.run
        ? [
            'detecting',
            i.run.fps > 0 ? `${i.run.fps.toFixed(1)} fps` : '',
            i.run.width > 0 && i.run.height > 0 ? `${i.run.width}×${i.run.height}` : '',
            i.run.phase === 'tracker' ? 'tracker' : 'detector',
          ]
            .filter((x) => x !== '')
            .join(' · ')
        : 'detecting — the run holds the source'
      : live
        ? ['● live', fps, res, enc].filter((s) => s !== '').join(' ')
        : i.feedStatus === 'connecting'
          ? 'connecting…'
          : i.feedStatus === 'lost'
            ? 'lost — frames stopped arriving (stalled 6 s)'
            : i.feedStatus === 'refused'
              ? 'refused — the server would not open this source'
              : 'no stream yet',
    fix:
      live || i.detecting
        ? undefined
        : i.feedStatus === 'lost' || i.feedStatus === 'refused'
          ? { label: 'Reconnect', action: 'reconnect' }
          : undefined,
  };

  const detectorOk = i.detectorAvailable === true;
  const detector: StageState = {
    key: 'detector',
    index: 2,
    title: 'Detector',
    satisfied: detectorOk && source.satisfied,
    summary:
      i.detectorAvailable === null
        ? 'checking what this machine can run…'
        : !detectorOk
          ? (i.detectorReason ?? 'the detection runtime is not available.')
          : !source.satisfied
            ? 'needs the source live (①)'
            : `${i.modelName || 'default model'} · ${i.classesLabel} · conf ${i.conf.toFixed(2)} · ${i.imgsz} px`,
  };

  const placement: StageState = {
    key: 'placement',
    index: 3,
    title: 'Placement',
    satisfied: i.lutSite !== '',
    summary:
      i.lutSite === ''
        ? 'no lookup table — detections are counted, not placed on the map'
        : i.lutSite !== i.appliedLut
          ? `${i.lutSite} — applies when the run starts, or press Apply`
          : `${i.lutSite} · must match this camera`,
    fix:
      i.lutSite === ''
        ? { label: 'Set up the lookup table', to: i.settingsTo ?? '/cameras' }
        : i.lutSite !== i.appliedLut
          ? { label: 'Apply', action: 'apply' }
          : undefined,
  };

  // ★ Manual tracking (2026-09-03), ARMED WITH THE RUN (2026-09-08): the tracker
  //   runs alongside detection from the first frame, but follows nothing until
  //   the operator clicks a detected object. This stage only picks the tracker,
  //   so it is always "ready", never a gate.
  const tracking: StageState = {
    key: 'tracking',
    index: 4,
    title: 'Tracking',
    satisfied: true,
    summary: `${i.trackerType.toUpperCase()} armed with the run — click a detected object to follow it, double-click to lock it`,
    fix: undefined,
  };

  // ★ The drift watch is the CAMERA'S, not this page's (2026-09-08): it was
  //   frozen on the frame the control points sit on, in the camera settings, and
  //   runs in the background. Satisfied = a reference exists and its watch runs;
  //   every other case says what to do in the settings.
  const toSettings = { label: 'Open the camera settings', to: i.settingsTo ?? '/cameras' };
  const drift: StageState = {
    key: 'drift',
    index: 5,
    title: 'Drift watch',
    satisfied: i.driftFrozen && i.driftWatching,
    summary: !i.driftFrozen
      ? i.lutSite === ''
        ? 'not frozen yet — capture the frame, place its control points and build the lookup table in the camera settings'
        : 'not frozen yet — the reference is made from the frame in the camera settings'
      : !i.driftWatching
        ? i.driftError !== null
          ? `the watch stopped: ${i.driftError}`
          : 'reference frozen — the watch is not running; re-freeze from a new frame in the camera settings'
        : i.driftState === null
          ? 'watching live from the frozen frame — no look has run yet'
          : `watching live · ${i.driftState}${
              i.driftStatus !== null && i.driftStatus !== i.driftState
                ? ` (confirmed ${i.driftStatus})`
                : i.driftStatus === i.driftState
                  ? ' (confirmed)'
                  : ''
            }`,
    fix: i.driftFrozen && i.driftWatching ? undefined : toSettings,
  };

  return [source, detector, placement, tracking, drift];
}

/** Why Start is disabled, or null when it may run. */
export function startBlocker(stages: StageState[], detecting: boolean): string | null {
  if (detecting) return null;
  const s = stages.find((x) => x.key === 'source');
  const d = stages.find((x) => x.key === 'detector');
  if (s && !s.satisfied) return `Stage ① is not satisfied: ${s.summary}`;
  if (d && !d.satisfied) return `Stage ② is not satisfied: ${d.summary}`;
  return null;
}

/**
 * The run's AVERAGE detect rate — frames it finished over the time it has run.
 *
 * ★ The wire's `fps` is a moving average of loop timing, which reads high for a
 *   few seconds when frames arrive in bursts. This one cannot: it is a count over
 *   a clock. Null until at least a second and a frame have passed — a rate from
 *   less than that is noise dressed as a number.
 */
export function runAverageFps(
  framesDone: number,
  startedAtIso: string,
  nowMs: number,
): number | null {
  const started = Date.parse(startedAtIso);
  if (!Number.isFinite(started) || framesDone <= 0) return null;
  const seconds = (nowMs - started) / 1000;
  if (seconds < 1) return null;
  return framesDone / seconds;
}
