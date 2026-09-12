/**
 * `drift/DriftOverlay.tsx` — the frozen view, drawn ON the moving picture.
 *
 * ★ ONE BIG BOX. The polygon is where the FROZEN frame's outline sits inside
 *   the frame being shown right now (the server maps it through the solved
 *   rotation). At zero drift it hugs the frame edge; as the camera turns, the
 *   scene slides out of the box — the drift, seen, not read off a number.
 *
 * ★ Rides over `<video>`, `<img>` or `<canvas>` alike: an SVG with the frame's
 *   own viewBox and `xMidYMid meet` letterboxes exactly like `object-fit:
 *   contain`, so the box lands on the pixels it names. Pointer-transparent —
 *   the player's controls underneath must keep working.
 *
 * ★ Colour by state, shape by state (dashed when MOVED), and the state's own
 *   words written on it — the pill's rules, on the picture.
 */

import type { JSX } from 'react';

import type { DriftState, DriftVerdict } from '../../api/drift';
import { t } from '../../i18n';
import { DRIFT_LABEL } from './DriftPill';

const STROKE: Record<DriftState, string> = {
  OK: 'var(--status-ok)',
  MOVED: 'var(--status-warn)',
  CHANGED: 'var(--status-error)',
  DEGRADED: 'var(--text-secondary)',
};

/** The fixed amplification per state — CHANGED is pushed hardest because it is the
 *  dangerous state whose rotation is SMALLEST (a zoom turns ≈0°). */
export const RETICLE_AMPLIFY: Record<DriftState, number> = {
  OK: 3,
  MOVED: 6,
  CHANGED: 9,
  DEGRADED: 3,
};

export interface Reticle {
  /** frozen position, frame px */
  ux: number;
  uy: number;
  /** live position AS DRAWN (amplified), frame px */
  lx: number;
  ly: number;
  /** the TRUE separation, frame px, and the amplification applied */
  truePx: number;
  k: number;
  /** drawn separation, frame px */
  gapPx: number;
  size: number;
  lost: boolean;
}

/**
 * ONE real landmark for the reticles: the matched one on the RIGHT of the frame
 * (the caption and the frozen-box label live on the left), else the first lost
 * one — a lost landmark is labelled, never given a position that was not measured.
 * The drawn gap is the true gap × the state's factor, capped at a tenth of the
 * frame so an amplified mark never leaves the picture.
 */
export function pickReticle(verdict: DriftVerdict, W: number, H: number): Reticle | null {
  const marks = verdict.landmarks ?? [];
  if (marks.length === 0) return null;
  const matched = marks.filter((m) => m.x !== null && m.y !== null);
  const chosen =
    matched.length > 0
      ? matched.reduce((best, m) => (m.u > best.u ? m : best), matched[0])
      : marks.reduce((best, m) => (m.u > best.u ? m : best), marks[0]);
  const size = Math.max(W, H) / 60;
  const ux = chosen.u * W;
  const uy = chosen.v * H;
  if (chosen.x === null || chosen.y === null) {
    return { ux, uy, lx: ux, ly: uy, truePx: 0, k: 1, gapPx: 0, size, lost: true };
  }
  const dx = chosen.x * W - ux;
  const dy = chosen.y * H - uy;
  const truePx = Math.hypot(dx, dy);
  const k = RETICLE_AMPLIFY[verdict.state];
  const cap = Math.max(W, H) / 10;
  const drawn = Math.min(truePx * k, cap);
  const scale = truePx > 0 ? drawn / truePx : 0;
  return {
    ux,
    uy,
    lx: ux + dx * scale,
    ly: uy + dy * scale,
    truePx,
    k,
    gapPx: drawn,
    size,
    lost: false,
  };
}

/** A halo under every stroke: this rides over arbitrary video, where a neutral
 *  line dies against bright terrain and a bright one against sky. */
function Halo({ children }: { children: JSX.Element | JSX.Element[] }): JSX.Element {
  return (
    <>
      <g
        stroke="var(--bg-base)"
        strokeOpacity={0.85}
        strokeWidth={6}
        strokeLinecap="round"
        fill="none"
      >
        {children}
      </g>
      <g strokeLinecap="round">{children}</g>
    </>
  );
}

export function DriftOverlay({ verdict }: { verdict: DriftVerdict | null }): JSX.Element | null {
  if (verdict == null || !verdict.frame_w || !verdict.frame_h) return null;
  const W = verdict.frame_w;
  const H = verdict.frame_h;
  const colour = STROKE[verdict.state];
  const outline = verdict.outline ?? null;
  const points = outline?.map(([x, y]) => `${x * W},${y * H}`).join(' ');
  const labelAt = outline?.[0] ?? [0, 0];
  const reticle = pickReticle(verdict, W, H);

  return (
    <svg
      data-testid="drift-overlay"
      data-drift-state={verdict.state}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        overflow: 'visible',
      }}
    >
      <defs>
        {(['OK', 'MOVED', 'CHANGED', 'DEGRADED'] as DriftState[]).map((st) => (
          <marker
            key={st}
            id={`drift-arrow-${st}`}
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill={STROKE[st]} />
          </marker>
        ))}
      </defs>
      {points !== undefined ? (
        <polygon
          points={points}
          fill="none"
          stroke={colour}
          strokeWidth={3}
          vectorEffect="non-scaling-stroke"
          strokeDasharray={verdict.state === 'MOVED' ? '10 6' : undefined}
        />
      ) : (
        // no rotation could be solved (DEGRADED): the frame edge, dashed, in
        // the neutral colour — "cannot judge", not "steady"
        <rect
          x={0}
          y={0}
          width={W}
          height={H}
          fill="none"
          stroke={colour}
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
          strokeDasharray="6 6"
        />
      )}
      {/* ★ GEO-DRIFT A1 — TWO RETICLES ON THE RIGHT, for ONE real landmark: where it
          was frozen (dashed, open centre) and where the template match found it
          in this frame (solid, heavier). Measured evidence, not the fitted
          rotation drawn back onto the picture. All landmarks are still computed —
          they separate MOVED from CHANGED — but one pair is what a person can read.
          The separation is AMPLIFIED by a FIXED factor per state (OK ×3, MOVED ×6,
          CHANGED ×9), capped, and the label says so with the TRUE pixel figure:
          a real drift is ~10 frame-pixels on a frame displayed scaled down, and an
          auto-scaled factor made a steady camera look as far apart as a drifted one. */}
      {reticle !== null && (
        <g data-testid="drift-reticle" data-amplify={reticle.k} data-lost={reticle.lost}>
          {/* the frozen datum — only once there is a gap to read it against, or when lost */}
          {(reticle.lost || reticle.gapPx >= reticle.size * 0.35) && (
            <g stroke="var(--text-secondary)" fill="none" strokeDasharray="6 5">
              <Halo>
                <circle cx={reticle.ux} cy={reticle.uy} r={reticle.size * 0.45} />
                <line
                  x1={reticle.ux - reticle.size}
                  y1={reticle.uy}
                  x2={reticle.ux - reticle.size * 0.55}
                  y2={reticle.uy}
                />
                <line
                  x1={reticle.ux + reticle.size * 0.55}
                  y1={reticle.uy}
                  x2={reticle.ux + reticle.size}
                  y2={reticle.uy}
                />
                <line
                  x1={reticle.ux}
                  y1={reticle.uy - reticle.size}
                  x2={reticle.ux}
                  y2={reticle.uy - reticle.size * 0.55}
                />
                <line
                  x1={reticle.ux}
                  y1={reticle.uy + reticle.size * 0.55}
                  x2={reticle.ux}
                  y2={reticle.uy + reticle.size}
                />
              </Halo>
            </g>
          )}
          {!reticle.lost && (
            <>
              {/* the travel between them, with an arrowhead so direction reads at once */}
              <Halo>
                <line
                  x1={reticle.ux}
                  y1={reticle.uy}
                  x2={reticle.lx}
                  y2={reticle.ly}
                  stroke={colour}
                  strokeWidth={2}
                  markerEnd={reticle.gapPx > 0 ? `url(#drift-arrow-${verdict.state})` : undefined}
                />
              </Halo>
              {/* the live mark — heavier, reaching further, open centre */}
              <g stroke={colour} fill="none" strokeWidth={2.5}>
                <Halo>
                  <line
                    x1={reticle.lx - reticle.size * 1.3}
                    y1={reticle.ly}
                    x2={reticle.lx - reticle.size * 0.45}
                    y2={reticle.ly}
                  />
                  <line
                    x1={reticle.lx + reticle.size * 0.45}
                    y1={reticle.ly}
                    x2={reticle.lx + reticle.size * 1.3}
                    y2={reticle.ly}
                  />
                  <line
                    x1={reticle.lx}
                    y1={reticle.ly - reticle.size * 1.3}
                    x2={reticle.lx}
                    y2={reticle.ly - reticle.size * 0.45}
                  />
                  <line
                    x1={reticle.lx}
                    y1={reticle.ly + reticle.size * 0.45}
                    x2={reticle.lx}
                    y2={reticle.ly + reticle.size * 1.3}
                  />
                </Halo>
              </g>
            </>
          )}
          <text
            x={reticle.ux}
            y={reticle.uy - reticle.size * 1.6}
            fill={reticle.lost ? 'var(--status-error)' : colour}
            fontSize={H / 40}
            fontFamily="var(--font-mono, monospace)"
            textAnchor="middle"
            style={{ paintOrder: 'stroke', stroke: 'var(--bg-base)', strokeWidth: H / 260 }}
          >
            {reticle.lost ? t('lost') : `${reticle.truePx.toFixed(1)} px ×${reticle.k}`}
          </text>
        </g>
      )}
      <text
        x={labelAt[0] * W + W * 0.012}
        y={labelAt[1] * H + H * 0.06}
        fill={colour}
        fontSize={H / 26}
        fontFamily="var(--font-mono, monospace)"
        style={{ paintOrder: 'stroke', stroke: 'var(--bg-base)', strokeWidth: H / 200 }}
      >
        {t(DRIFT_LABEL[verdict.state])}
        {verdict.rot_deg !== null ? ` · ${verdict.rot_deg.toFixed(2)}°` : ''}
        {verdict.angles
          ? ` · ${t('pan')} ${verdict.angles.pan_deg.toFixed(2)}° ${t('tilt')} ${verdict.angles.tilt_deg.toFixed(2)}° ${t('roll')} ${verdict.angles.roll_deg.toFixed(2)}°`
          : ''}
      </text>
    </svg>
  );
}
