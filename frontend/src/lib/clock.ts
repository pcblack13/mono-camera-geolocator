/**
 * `lib/clock.ts` — `m:ss.s`, the clock a recording's viewer and page speak.
 *
 * Tenths, not frames: the recorder writes ten frames a second, so a tenth IS a
 * frame, and the same string reads the same on the timeline, the transport, the
 * table and the trim.
 */

export function fmtClock(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const m = Math.floor(safe / 60);
  const s = safe - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}
