/**
 * `home/WorkflowBoard.tsx` — the landing page's workflow guide: THE TWO MAIN PAGES,
 * each as an interactive carousel that walks its quick guide one step at a time.
 *
 * ★ ONE BOARD PER PAGE (2026-09-07, owner ask). The two cards that sat in the hero —
 *   "Camera workspace" and "Cameras Monitoring", each with an overview and a
 *   numbered quick guide — moved down here, and the guide's steps became the
 *   slides. The rotating feature showcase they replace is gone: the landing page
 *   teaches the two doors it opens instead of advertising twelve features.
 *
 * ★ DEPENDENCY-FREE by design, as the showcase was: a carousel library would be the
 *   only reason the landing route ships extra bytes. Each step's picture is an
 *   inline SVG *illustration* drawn in theme colours — not a screenshot — so it
 *   renders identically offline, in both modes, at every size.
 *
 * ★ INTERACTION RULES:
 *   - Auto-advances every 6 s, and STOPS while hovered, focused, or swiped — a
 *     guide that walks away from its reader is hostile, not lively.
 *   - `prefers-reduced-motion` disables autoplay entirely (the global CSS already
 *     collapses the slide transition to instant).
 *   - Swipe (pointer drag ≥ 40 px), the arrows, and the numbered step rail all
 *     work; each carousel is a labelled region and inactive steps are hidden from
 *     assistive tech.
 *   - In Arabic the TRACK stays left-to-right (its translateX maths and swipe
 *     deltas assume it — see LtrIsland), but everything a reader sees is mirrored
 *     inside it: the words run right-to-left, the text column swaps sides with the
 *     picture, and the rail reads 1 → n from the right with its arrows swapped.
 *
 * ★ COLOUR HONESTY even in decoration: control points, registered cameras and
 *   landed detections use the CONFIDENCE green — the one colour this product
 *   reserves for earned confidence — because that is exactly what they depict.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type JSX,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import useMediaQuery from '@mui/material/useMediaQuery';
import { alpha, useTheme, type Theme } from '@mui/material/styles';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';

import { t } from '../../i18n';
import { LtrIsland } from '../common/LtrIsland';

// ─────────────────────────────────────────────────────────────────────────────
// Illustrations — one small themed SVG per step
// ─────────────────────────────────────────────────────────────────────────────

interface IllustrationProps {
  theme: Theme;
}

/** The server page with nothing on it yet — an empty list, and the one thing it asks for. */
function EmptyServerIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      {/* the page and its top bar */}
      <rect
        x="10"
        y="16"
        width="300"
        height="148"
        rx="8"
        fill={alpha(p.primary.main, 0.05)}
        stroke={p.divider}
      />
      <rect x="10" y="16" width="300" height="26" rx="8" fill={alpha(p.text.secondary, 0.08)} />
      <rect x="10" y="30" width="300" height="12" fill={alpha(p.text.secondary, 0.08)} />
      <rect x="22" y="24" width="10" height="10" rx="2" fill={alpha(p.primary.main, 0.5)} />
      <text x="38" y="33" fontSize="9" fontFamily="monospace" fill={p.text.secondary}>
        {t('Camera workspace')}
      </text>
      {/* the list, still empty */}
      {[56, 84, 112].map((y) => (
        <rect
          key={y}
          x="22"
          y={y}
          width="104"
          height="20"
          rx="4"
          fill="none"
          stroke={alpha(p.text.secondary, 0.28)}
          strokeDasharray="4 3"
        />
      ))}
      {/* the ask: the first camera */}
      <rect
        x="146"
        y="54"
        width="150"
        height="94"
        rx="8"
        fill={alpha(p.primary.main, 0.08)}
        stroke={p.primary.main}
        strokeWidth="1.5"
        strokeDasharray="6 4"
      />
      <circle cx="221" cy="88" r="14" fill={p.primary.main} />
      <path
        d="M221 80 v16 M213 88 h16"
        stroke={p.primary.contrastText}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <text
        x="221"
        y="126"
        fontSize="11"
        fontFamily="monospace"
        textAnchor="middle"
        fill={p.primary.main}
      >
        {t('Add camera')}
      </text>
    </svg>
  );
}

/** The Add camera form — a name, a connection — beside the map waiting for its spot. */
function AddCameraIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  const cam = p.confidence.high;
  // ★ The three kinds the setup offers (2026-09-11) — an address, a capture
  //   device on this machine, a serial line.
  const chips: readonly [string, number, number, boolean][] = [
    ['LAN', 22, 88, true],
    ['USB', 62, 88, false],
    ['SERIAL', 102, 88, false],
  ];
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      {/* the form */}
      <rect
        x="10"
        y="16"
        width="146"
        height="148"
        rx="8"
        fill={alpha(p.primary.main, 0.05)}
        stroke={p.divider}
      />
      <text x="22" y="36" fontSize="9" fontFamily="monospace" fill={p.text.secondary}>
        {t('Name')}
      </text>
      <rect
        x="22"
        y="42"
        width="122"
        height="20"
        rx="4"
        fill={p.background.paper}
        stroke={p.primary.main}
        strokeWidth="1.5"
      />
      <rect x="30" y="48" width="56" height="8" rx="2" fill={alpha(p.text.primary, 0.55)} />
      <line x1="90" y1="46" x2="90" y2="58" stroke={p.primary.main} strokeWidth="1.5" />
      <text x="22" y="80" fontSize="9" fontFamily="monospace" fill={p.text.secondary}>
        {t('Connection')}
      </text>
      {chips.map(([label, x, y, chosen]) => (
        <g key={label}>
          <rect
            x={x}
            y={y}
            width="36"
            height="16"
            rx="8"
            fill={chosen ? p.primary.main : 'none'}
            stroke={chosen ? p.primary.main : alpha(p.text.secondary, 0.4)}
          />
          <text
            x={x + 18}
            y={y + 11}
            fontSize="8"
            fontFamily="monospace"
            textAnchor="middle"
            fill={chosen ? p.primary.contrastText : p.text.secondary}
          >
            {label}
          </text>
        </g>
      ))}
      {/* the map */}
      <rect
        x="170"
        y="16"
        width="140"
        height="148"
        rx="8"
        fill={alpha(p.success.main, 0.06)}
        stroke={p.divider}
      />
      {[46, 76, 106, 136].map((y) => (
        <line key={y} x1="176" y1={y} x2="304" y2={y} stroke={alpha(p.text.secondary, 0.18)} />
      ))}
      {[200, 230, 260, 290].map((x) => (
        <line key={x} x1={x} y1="22" x2={x} y2="158" stroke={alpha(p.text.secondary, 0.18)} />
      ))}
      {/* the click: a crosshair becoming the camera's spot, and where it looks */}
      <path
        d="M240 84 L300 50 L300 118 Z"
        fill={alpha(p.primary.main, 0.1)}
        stroke={alpha(p.primary.main, 0.45)}
        strokeDasharray="4 4"
      />
      <circle
        cx="240"
        cy="84"
        r="13"
        fill="none"
        stroke={p.primary.main}
        strokeWidth="1.5"
        strokeDasharray="3 3"
      />
      <path
        d="M240 66 v8 M240 94 v8 M222 84 h8 M250 84 h8"
        stroke={p.primary.main}
        strokeWidth="1.5"
      />
      <circle cx="240" cy="84" r="6" fill={cam} stroke={p.background.paper} strokeWidth="2.5" />
    </svg>
  );
}

/** Terrain ridges with a draped grid — the camera's DEM, its only height source. */
function TerrainIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      <rect
        x="10"
        y="16"
        width="300"
        height="148"
        rx="8"
        fill={alpha(p.info.main, 0.05)}
        stroke={p.divider}
      />
      {[0, 1, 2].map((i) => (
        <path
          key={i}
          d={`M14 ${146 - i * 26} q40 ${-30 - i * 8} 80 -6 q46 26 82 -12 q40 ${-38 + i * 10} 140 8`}
          fill="none"
          stroke={alpha(p.primary.main, 0.55 - i * 0.15)}
          strokeWidth={2.5 - i * 0.5}
        />
      ))}
      {[40, 90, 140, 190, 240, 290].map((x) => (
        <path
          key={x}
          d={`M${x} 160 q4 -60 ${x > 160 ? -8 : 8} -110`}
          fill="none"
          stroke={alpha(p.text.secondary, 0.16)}
        />
      ))}
      <circle
        cx="212"
        cy="84"
        r="6"
        fill={p.confidence.high}
        stroke={p.background.paper}
        strokeWidth="2"
      />
      <circle
        cx="118"
        cy="104"
        r="6"
        fill={p.confidence.high}
        stroke={p.background.paper}
        strokeWidth="2"
      />
    </svg>
  );
}

/** The frame and the map, four control points paired across them — the build unlocks. */
function ControlPointsIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  const gcp = p.confidence.high;
  const pairs: readonly [number, number, number, number][] = [
    [40, 62, 206, 54],
    [116, 56, 282, 50],
    [52, 128, 214, 130],
    [126, 112, 290, 116],
  ];
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      {/* the frame */}
      <rect
        x="10"
        y="16"
        width="140"
        height="148"
        rx="8"
        fill={alpha(p.primary.main, 0.08)}
        stroke={p.divider}
      />
      <path
        d="M20 120 q30 -44 60 -18 q34 28 60 -8"
        fill="none"
        stroke={alpha(p.text.secondary, 0.5)}
        strokeWidth="2"
      />
      <path
        d="M20 140 q40 -20 120 -6"
        fill="none"
        stroke={alpha(p.text.secondary, 0.3)}
        strokeWidth="2"
      />
      {/* the map */}
      <rect
        x="170"
        y="16"
        width="140"
        height="148"
        rx="8"
        fill={alpha(p.success.main, 0.06)}
        stroke={p.divider}
      />
      {[46, 76, 106, 136].map((y) => (
        <line key={y} x1="176" y1={y} x2="304" y2={y} stroke={alpha(p.text.secondary, 0.18)} />
      ))}
      {[200, 230, 260, 290].map((x) => (
        <line key={x} x1={x} y1="22" x2={x} y2="158" stroke={alpha(p.text.secondary, 0.18)} />
      ))}
      {/* the four pairs — the last one still being drawn */}
      {pairs.map(([u, v, x, y], i) => (
        <g key={`${u}:${v}`}>
          <path
            d={`M${u} ${v} Q160 ${Math.min(v, y) - 28} ${x} ${y}`}
            fill="none"
            stroke={alpha(p.primary.main, i === pairs.length - 1 ? 0.9 : 0.35)}
            strokeWidth="1.5"
            strokeDasharray="4 4"
          />
          <circle cx={u} cy={v} r="6" fill={gcp} stroke={p.background.paper} strokeWidth="2" />
          <circle cx={x} cy={y} r="6" fill={gcp} stroke={p.background.paper} strokeWidth="2" />
        </g>
      ))}
      {/* the count that unlocks the build */}
      <rect x="130" y="142" width="60" height="18" rx="9" fill={alpha(gcp, 0.14)} stroke={gcp} />
      <text x="160" y="155" fontSize="10" fontFamily="monospace" textAnchor="middle" fill={gcp}>
        4 / 4
      </text>
    </svg>
  );
}

/** A photo's pixel grid resolved onto the ground, packaged as two arrays. */
function LutIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      {/* the photograph, ruled into pixels */}
      <rect
        x="16"
        y="20"
        width="126"
        height="90"
        rx="6"
        fill={alpha(p.primary.main, 0.1)}
        stroke={p.divider}
      />
      {[38, 56, 74, 92].map((y) => (
        <line key={y} x1="16" y1={y} x2="142" y2={y} stroke={alpha(p.text.secondary, 0.22)} />
      ))}
      {[40, 64, 88, 112].map((x) => (
        <line key={x} x1={x} y1="20" x2={x} y2="110" stroke={alpha(p.text.secondary, 0.22)} />
      ))}
      {/* one pixel singled out, and the ray it resolves along */}
      <rect
        x="64"
        y="56"
        width="24"
        height="18"
        fill={alpha(p.primary.main, 0.5)}
        stroke={p.primary.main}
        strokeWidth="1.5"
      />
      <path d="M76 74 L76 122" stroke={p.primary.main} strokeWidth="2" strokeDasharray="5 4" />

      {/* the ground it lands on */}
      <path
        d="M16 138 q40 -16 76 -4 q34 12 66 -6"
        fill="none"
        stroke={alpha(p.text.secondary, 0.45)}
        strokeWidth="2"
      />
      <circle
        cx="76"
        cy="128"
        r="6"
        fill={p.confidence.high}
        stroke={p.background.paper}
        strokeWidth="2"
      />

      {/* the payload a field unit actually carries */}
      <rect
        x="184"
        y="42"
        width="112"
        height="30"
        rx="5"
        fill={alpha(p.success.main, 0.12)}
        stroke={alpha(p.success.main, 0.7)}
      />
      <text x="196" y="62" fontSize="13" fontFamily="monospace" fill={p.text.secondary}>
        lat.npy
      </text>
      <rect
        x="184"
        y="82"
        width="112"
        height="30"
        rx="5"
        fill={alpha(p.success.main, 0.12)}
        stroke={alpha(p.success.main, 0.7)}
      />
      <text x="196" y="102" fontSize="13" fontFamily="monospace" fill={p.text.secondary}>
        lon.npy
      </text>
      <path
        d="M150 65 L180 57 M150 65 L180 95"
        stroke={alpha(p.primary.main, 0.7)}
        strokeWidth="1.5"
        strokeDasharray="4 3"
      />
    </svg>
  );
}

/** Every camera on a globe — or on a wall of live tiles, one with its Start button. */
function PickCameraIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  const cam = p.confidence.high;
  const tiles: readonly [number, number][] = [
    [170, 30],
    [242, 30],
    [170, 98],
    [242, 98],
  ];
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      {/* the globe */}
      <circle
        cx="82"
        cy="90"
        r="60"
        fill={alpha(p.info.main, 0.07)}
        stroke={p.divider}
        strokeWidth="1.5"
      />
      <ellipse cx="82" cy="90" rx="24" ry="60" fill="none" stroke={alpha(p.text.secondary, 0.25)} />
      <ellipse cx="82" cy="90" rx="48" ry="60" fill="none" stroke={alpha(p.text.secondary, 0.18)} />
      <line x1="22" y1="90" x2="142" y2="90" stroke={alpha(p.text.secondary, 0.25)} />
      <path d="M28 62 Q82 44 136 62" fill="none" stroke={alpha(p.text.secondary, 0.18)} />
      <path d="M28 118 Q82 136 136 118" fill="none" stroke={alpha(p.text.secondary, 0.18)} />
      {/* the cameras on it — one picked */}
      <circle cx="62" cy="76" r="4.5" fill={cam} stroke={p.background.paper} strokeWidth="2" />
      <circle cx="108" cy="106" r="4.5" fill={cam} stroke={p.background.paper} strokeWidth="2" />
      <circle cx="92" cy="66" r="6" fill={cam} stroke={p.background.paper} strokeWidth="2" />
      <circle
        cx="92"
        cy="66"
        r="12"
        fill="none"
        stroke={p.primary.main}
        strokeWidth="1.5"
        strokeDasharray="3 3"
      />
      {/* the wall */}
      {tiles.map(([x, y], i) => (
        <g key={`${x}:${y}`}>
          <rect
            x={x}
            y={y}
            width="66"
            height="54"
            rx="5"
            fill={i === 0 ? alpha(p.primary.main, 0.14) : alpha(p.text.secondary, 0.08)}
            stroke={i === 0 ? p.primary.main : alpha(p.text.secondary, 0.3)}
            strokeWidth={i === 0 ? 1.5 : 1}
          />
          <path
            d={`M${x + 6} ${y + 36} q14 -14 26 -4 q12 10 28 -6`}
            fill="none"
            stroke={alpha(p.text.secondary, 0.4)}
            strokeWidth="1.5"
          />
          <circle cx={x + 10} cy={y + 9} r="2.5" fill={p.success.main} />
        </g>
      ))}
      {/* Start, on the picked tile */}
      <rect x="180" y="64" width="46" height="14" rx="7" fill={p.primary.main} />
      <path d="M188 67 l5 4 l-5 4 z" fill={p.primary.contrastText} />
      <text x="197" y="75" fontSize="8" fontFamily="monospace" fill={p.primary.contrastText}>
        {t('Start')}
      </text>
    </svg>
  );
}

/** The detector's dials beside the frame they act on — the lookup table already chosen. */
function DialsIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  const dials: readonly [number, number][] = [
    [44, 0.7],
    [72, 0.45],
    [100, 0.55],
  ];
  const boxes: readonly [number, number, number, number][] = [
    [186, 78, 30, 24],
    [244, 92, 26, 20],
  ];
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      {/* the dials */}
      <rect
        x="10"
        y="16"
        width="124"
        height="148"
        rx="8"
        fill={alpha(p.primary.main, 0.05)}
        stroke={p.divider}
      />
      {dials.map(([y, f]) => {
        const kx = 24 + 96 * f;
        return (
          <g key={y}>
            <line
              x1="24"
              y1={y}
              x2="120"
              y2={y}
              stroke={alpha(p.text.secondary, 0.3)}
              strokeWidth="3"
              strokeLinecap="round"
            />
            <line
              x1="24"
              y1={y}
              x2={kx}
              y2={y}
              stroke={p.primary.main}
              strokeWidth="3"
              strokeLinecap="round"
            />
            <circle
              cx={kx}
              cy={y}
              r="6"
              fill={p.background.paper}
              stroke={p.primary.main}
              strokeWidth="2"
            />
          </g>
        );
      })}
      {/* the lookup table, already selected */}
      <rect
        x="24"
        y="122"
        width="96"
        height="22"
        rx="11"
        fill={alpha(p.success.main, 0.12)}
        stroke={alpha(p.success.main, 0.7)}
      />
      <path
        d="M36 133 l4 4 l7 -8"
        fill="none"
        stroke={p.success.main}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <text x="54" y="137" fontSize="10" fontFamily="monospace" fill={p.text.secondary}>
        LUT
      </text>
      {/* the frame, with the boxes the dials produce */}
      <rect
        x="150"
        y="16"
        width="160"
        height="148"
        rx="8"
        fill={alpha(p.primary.main, 0.08)}
        stroke={p.divider}
      />
      <path
        d="M158 122 q40 -30 70 -10 q40 24 74 -8"
        fill="none"
        stroke={alpha(p.text.secondary, 0.45)}
        strokeWidth="2"
      />
      {boxes.map(([x, y, w, h]) => (
        <g key={`${x}:${y}`}>
          <rect
            x={x}
            y={y}
            width={w}
            height={h}
            fill={alpha(p.primary.main, 0.16)}
            stroke={p.primary.main}
            strokeWidth="1.5"
          />
          <rect x={x} y={y - 9} width="22" height="9" rx="2" fill={p.primary.main} />
        </g>
      ))}
      {/* the dials reach the frame */}
      <path d="M134 72 L150 72" stroke={p.primary.main} strokeWidth="2" strokeDasharray="4 3" />
    </svg>
  );
}

/** Detections landing on the map beside the frame — and the drift watch's verdict on the frame. */
function WatchIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  const gcp = p.confidence.high;
  const boxes: readonly [number, number, number, number][] = [
    [46, 80, 30, 24],
    [104, 94, 26, 20],
  ];
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      {/* the frame */}
      <rect
        x="10"
        y="20"
        width="160"
        height="140"
        rx="8"
        fill={alpha(p.primary.main, 0.08)}
        stroke={p.divider}
      />
      <path
        d="M18 118 q40 -30 70 -10 q40 24 74 -8"
        fill="none"
        stroke={alpha(p.text.secondary, 0.45)}
        strokeWidth="2"
      />
      {/* the frozen reference, lying exactly on the frame — steady */}
      <rect
        x="18"
        y="28"
        width="144"
        height="100"
        rx="5"
        fill="none"
        stroke={alpha(gcp, 0.7)}
        strokeWidth="1.5"
        strokeDasharray="6 4"
      />
      {/* the detections, and where each lands */}
      {boxes.map(([x, y, w, h]) => (
        <g key={`${x}:${y}`}>
          <rect
            x={x}
            y={y}
            width={w}
            height={h}
            fill={alpha(p.primary.main, 0.16)}
            stroke={p.primary.main}
            strokeWidth="1.5"
          />
          <rect x={x} y={y - 9} width="22" height="9" rx="2" fill={p.primary.main} />
        </g>
      ))}
      <path
        d="M92 92 Q160 60 226 86"
        fill="none"
        stroke={p.primary.main}
        strokeWidth="1.5"
        strokeDasharray="4 4"
      />
      <path
        d="M130 104 Q170 132 246 120"
        fill="none"
        stroke={p.primary.main}
        strokeWidth="1.5"
        strokeDasharray="4 4"
      />
      {/* the verdict */}
      <rect x="18" y="136" width="66" height="18" rx="9" fill={alpha(gcp, 0.14)} stroke={gcp} />
      <circle cx="29" cy="145" r="3" fill={gcp} />
      <text x="36" y="149" fontSize="9" fontFamily="monospace" fill={gcp}>
        {t('Steady')}
      </text>
      {/* the map */}
      <rect
        x="184"
        y="20"
        width="126"
        height="140"
        rx="8"
        fill={alpha(p.success.main, 0.06)}
        stroke={p.divider}
      />
      {[50, 80, 110, 140].map((y) => (
        <line key={y} x1="190" y1={y} x2="304" y2={y} stroke={alpha(p.text.secondary, 0.18)} />
      ))}
      {[214, 244, 274].map((x) => (
        <line key={x} x1={x} y1="26" x2={x} y2="154" stroke={alpha(p.text.secondary, 0.18)} />
      ))}
      <circle cx="230" cy="88" r="6" fill={gcp} stroke={p.background.paper} strokeWidth="2.5" />
      <circle cx="250" cy="122" r="6" fill={gcp} stroke={p.background.paper} strokeWidth="2.5" />
    </svg>
  );
}

/** The export: a document carrying its accuracy circle — or the recording kept for later. */
function ExportIllustration({ theme }: IllustrationProps): JSX.Element {
  const p = theme.palette;
  return (
    <svg viewBox="0 0 320 180" width="100%" height="100%" aria-hidden>
      {/* the recording, kept */}
      <rect
        x="18"
        y="66"
        width="62"
        height="44"
        rx="5"
        fill={alpha(p.text.secondary, 0.08)}
        stroke={alpha(p.text.secondary, 0.35)}
      />
      <path
        d="M24 98 q12 -12 22 -4 q10 8 28 -6"
        fill="none"
        stroke={alpha(p.text.secondary, 0.4)}
        strokeWidth="1.5"
      />
      <circle cx="28" cy="76" r="3" fill={p.text.secondary} />
      <text x="35" y="79" fontSize="8" fontFamily="monospace" fill={p.text.secondary}>
        REC
      </text>
      {/* the document */}
      <rect
        x="112"
        y="18"
        width="128"
        height="144"
        rx="8"
        fill={p.background.paper}
        stroke={p.divider}
        strokeWidth="1.5"
      />
      {[44, 60, 76].map((y) => (
        <line
          key={y}
          x1="128"
          y1={y}
          x2="224"
          y2={y}
          stroke={alpha(p.text.secondary, 0.35)}
          strokeWidth="3"
          strokeLinecap="round"
        />
      ))}
      {/* the CE90 ring — the number that travels with every point */}
      <circle
        cx="176"
        cy="116"
        r="26"
        fill="none"
        stroke={alpha(p.primary.main, 0.35)}
        strokeWidth="1.5"
        strokeDasharray="4 4"
      />
      <circle
        cx="176"
        cy="116"
        r="4.5"
        fill={p.confidence.high}
        stroke={p.background.paper}
        strokeWidth="2"
      />
      <line x1="176" y1="116" x2="202" y2="116" stroke={p.primary.main} strokeWidth="1.5" />
      <text x="208" y="112" fontSize="11" fontFamily="monospace" fill={p.text.secondary}>
        {t('CE90')}
      </text>
      {/* the formats it leaves as */}
      {[
        ['CSV', 254, 52],
        ['KML', 254, 78],
        ['PDF', 254, 104],
      ].map(([label, x, y]) => (
        <g key={String(label)}>
          <rect
            x={Number(x)}
            y={Number(y)}
            width="44"
            height="18"
            rx="4"
            fill={alpha(p.success.main, 0.12)}
            stroke={alpha(p.success.main, 0.7)}
          />
          <text
            x={Number(x) + 22}
            y={Number(y) + 13}
            fontSize="9"
            fontFamily="monospace"
            textAnchor="middle"
            fill={p.text.secondary}
          >
            {label}
          </text>
        </g>
      ))}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The two pages, and their steps
// ─────────────────────────────────────────────────────────────────────────────

interface WorkflowStep {
  /** The step in a few words — the slide's heading and the rail button's name. */
  title: string;
  /** The quick guide's sentence for this step, verbatim. */
  body: string;
  Illustration: (props: IllustrationProps) => JSX.Element;
}

/**
 * THE TWO MAIN PAGES — what each contains, and how it is used, in order. The
 * paths are the registry's (`shell/workspaces.tsx`); the words are the page's.
 */
interface WorkflowPage {
  key: 'cameras' | 'monitoring';
  title: string;
  path: string;
  door: string;
  icon: JSX.Element;
  /** What the page contains, in two or three sentences. */
  overview: string;
  /** The quick guide: one slide per step, in the order the page is used. */
  steps: readonly WorkflowStep[];
}

const WORKFLOW_PAGES: readonly WorkflowPage[] = [
  {
    key: 'cameras',
    title: 'Camera workspace',
    path: '/cameras',
    door: 'Open the camera workspace',
    icon: <DnsOutlinedIcon />,
    overview:
      'Every camera the app knows, registered once on the server: how it connects, where it stands, its DEM, its calibration, the frame its control points sit on, and its lookup table. Every machine sees the same list.',
    steps: [
      {
        title: 'Open the page',
        body: 'Open the page — with no cameras yet, it asks you to add the first one.',
        Illustration: EmptyServerIllustration,
      },
      {
        title: 'Add the camera',
        body: 'Press Add camera: name it, choose the connection (UTP/LAN for an IP camera or a board, USB for a capture card, serial/UART for a data line) and click its spot on the map.',
        Illustration: AddCameraIllustration,
      },
      {
        title: 'Attach its DEM and calibration',
        body: 'Attach the camera’s DEM and, if you have it, its calibration.',
        Illustration: TerrainIllustration,
      },
      {
        title: 'Frame and control points',
        body: 'Choose a frame from the camera and place four control points on it in the editor.',
        Illustration: ControlPointsIllustration,
      },
      {
        title: 'Build the lookup table',
        body: 'Build the lookup table — it comes back with you. Press Add camera, and it is on the server, ready to watch.',
        Illustration: LutIllustration,
      },
    ],
  },
  {
    key: 'monitoring',
    title: 'Cameras Monitoring',
    path: '/monitor',
    door: 'Open cameras monitoring',
    icon: <SensorsOutlinedIcon />,
    overview:
      'Every registered camera on a globe or a wall of live tiles. Open one to watch it, run detection, see each find land on the map through the camera’s lookup table, and be told when the camera itself has moved.',
    steps: [
      {
        title: 'Pick a camera',
        body: 'Pick a camera on the globe or the wall — or press Start on a tile to detect with its saved setup.',
        Illustration: PickCameraIllustration,
      },
      {
        title: 'Apply the detector’s dials',
        body: 'On the camera’s page, apply the detector’s dials; the camera’s lookup table is already selected.',
        Illustration: DialsIllustration,
      },
      {
        title: 'Watch, and know if it moves',
        body: 'Watch marks land on the map, freeze a reference and let the drift watch tell you if the camera moves.',
        Illustration: WatchIllustration,
      },
      {
        title: 'Export, or keep a recording',
        body: 'Export the detections, or keep a recording for later.',
        Illustration: ExportIllustration,
      },
    ],
  },
];

const ADVANCE_MS = 6000;
const SWIPE_PX = 40;

// ─────────────────────────────────────────────────────────────────────────────
// The carousel mechanics — shared by both boards
// ─────────────────────────────────────────────────────────────────────────────

interface CarouselControls {
  index: number;
  /** Go to a step by index; wraps at both ends. */
  go: (next: number) => void;
  /** Hold the autoplay — while hovered, focused, or being swiped. */
  setPaused: (paused: boolean) => void;
  onPointerDown: (e: ReactPointerEvent) => void;
  onPointerUp: (e: ReactPointerEvent) => void;
}

function useCarousel(count: number): CarouselControls {
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const dragStartX = useRef<number | null>(null);

  const go = useCallback((next: number) => setIndex(((next % count) + count) % count), [count]);

  // Autoplay — never against the user's motion preference, never under their pointer.
  useEffect(() => {
    if (reducedMotion || paused) return undefined;
    const id = window.setInterval(() => setIndex((i) => (i + 1) % count), ADVANCE_MS);
    return () => window.clearInterval(id);
  }, [reducedMotion, paused, count]);

  const onPointerDown = (e: ReactPointerEvent): void => {
    dragStartX.current = e.clientX;
  };
  const onPointerUp = (e: ReactPointerEvent): void => {
    const start = dragStartX.current;
    dragStartX.current = null;
    if (start === null) return;
    const dx = e.clientX - start;
    if (Math.abs(dx) >= SWIPE_PX) go(index + (dx < 0 ? 1 : -1));
  };

  return { index, go, setPaused, onPointerDown, onPointerUp };
}

// ─────────────────────────────────────────────────────────────────────────────
// One page's board
// ─────────────────────────────────────────────────────────────────────────────

/**
 * One main page as a board: its overview and door in the header, then its quick
 * guide as slides — one step at a time — and a rail of numbered doors into them.
 */
function PageCarousel({ page }: { page: WorkflowPage }): JSX.Element {
  const theme = useTheme();
  const navigate = useNavigate();
  const { index, go, setPaused, onPointerDown, onPointerUp } = useCarousel(page.steps.length);
  const count = page.steps.length;
  const titleId = `home-workflow-${page.key}`;
  // The document's direction, read OUTSIDE the island below (which swaps the theme).
  const rtl = theme.direction === 'rtl';

  return (
    <Box
      component="article"
      aria-labelledby={titleId}
      sx={{
        'borderRadius': 'var(--radius-lg)',
        'border': '1px solid var(--hairline)',
        'bgcolor': 'var(--bg-elevated)',
        'overflow': 'hidden',
        'transition':
          'border-color var(--dur-fast) var(--ease-standard), box-shadow var(--dur-fast) var(--ease-standard)',
        '&:hover': { borderColor: 'var(--accent)', boxShadow: 'var(--elev-popover)' },
      }}
    >
      {/* the header: what the page contains, and its door */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1.5}
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        sx={{ p: { xs: 2, md: 2.5 }, borderBottom: '1px solid var(--hairline)' }}
      >
        <Box
          aria-hidden
          sx={{
            width: 40,
            height: 40,
            display: 'grid',
            placeItems: 'center',
            borderRadius: 'var(--radius-md)',
            bgcolor: 'var(--accent)',
            color: 'var(--accent-contrast)',
            flexShrink: 0,
          }}
        >
          {page.icon}
        </Box>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography
            id={titleId}
            variant="subtitle1"
            component="h3"
            sx={{ fontWeight: 700, lineHeight: 1.2 }}
          >
            {t(page.title)}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {t(page.overview)}
          </Typography>
        </Box>
        <Button
          size="small"
          variant="contained"
          endIcon={<ArrowForwardRoundedIcon />}
          onClick={() => navigate(page.path)}
          sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
        >
          {t(page.door)}
        </Button>
      </Stack>

      {/* the guide, one step at a time */}
      {/* ★ The sliding track's translateX maths and the swipe deltas assume a
            left-to-right slide order — island it. See LtrIsland. */}
      <LtrIsland>
        <Box
          role="region"
          aria-roledescription="carousel"
          aria-label={`${t(page.title)}: ${t('Quick guide')}`}
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
          onFocus={() => setPaused(true)}
          onBlur={() => setPaused(false)}
          sx={{ overflow: 'hidden' }}
        >
          <Box
            onPointerDown={onPointerDown}
            onPointerUp={onPointerUp}
            sx={{
              'display': 'flex',
              'transform': `translateX(-${index * 100}%)`,
              'transition': (th) =>
                th.transitions.create('transform', {
                  duration: 420,
                  easing: th.transitions.easing.easeInOut,
                }),
              'touchAction': 'pan-y',
              'cursor': 'grab',
              '&:active': { cursor: 'grabbing' },
            }}
          >
            {page.steps.map((step, i) => (
              <Box
                key={step.title}
                aria-hidden={i !== index}
                sx={{
                  minWidth: '100%',
                  display: 'grid',
                  gridTemplateColumns: { xs: '1fr', md: rtl ? '4fr 5fr' : '5fr 4fr' },
                  gap: { xs: 2, md: 4 },
                  alignItems: 'center',
                  p: { xs: 2.5, md: 4 },
                }}
              >
                {/* the words keep the document's direction even inside the LTR track */}
                <Stack
                  spacing={1.25}
                  dir={rtl ? 'rtl' : undefined}
                  sx={{ order: { xs: 2, md: rtl ? 2 : 1 } }}
                >
                  <Typography
                    className="le-mono"
                    sx={{ fontSize: 11, letterSpacing: '0.12em', color: 'var(--accent)' }}
                  >
                    {`${t('STEP')} ${i + 1} / ${count}`}
                  </Typography>
                  <Typography
                    variant="h5"
                    component="h4"
                    sx={{ fontWeight: 700, lineHeight: 1.25 }}
                  >
                    {t(step.title)}
                  </Typography>
                  <Typography variant="body1" color="text.secondary">
                    {t(step.body)}
                  </Typography>
                </Stack>
                <Box sx={{ order: { xs: 1, md: rtl ? 1 : 2 }, height: { xs: 150, md: 200 } }}>
                  <step.Illustration theme={theme} />
                </Box>
              </Box>
            ))}
          </Box>

          {/* the rail: the arrows, and one numbered door per step — mirrored in Arabic,
              so step 1 sits where reading starts and each arrow points the way it moves */}
          <Stack
            direction="row"
            spacing={1}
            useFlexGap
            alignItems="center"
            justifyContent="center"
            dir={rtl ? 'rtl' : undefined}
            sx={{ px: 1.5, py: 1, borderTop: '1px solid var(--hairline)' }}
          >
            <IconButton size="small" aria-label={t('Previous step')} onClick={() => go(index - 1)}>
              {rtl ? <ChevronRightIcon /> : <ChevronLeftIcon />}
            </IconButton>
            <Stack direction="row" spacing={0.75} useFlexGap>
              {page.steps.map((step, i) => {
                const current = i === index;
                return (
                  <Box
                    key={step.title}
                    component="button"
                    type="button"
                    className="le-mono"
                    aria-label={`${t('Step')} ${i + 1}: ${t(step.title)}`}
                    aria-current={current}
                    onClick={() => go(i)}
                    sx={{
                      'width': 28,
                      'height': 28,
                      'p': 0,
                      'borderRadius': '50%',
                      'border': '1px solid',
                      'borderColor': current ? 'var(--accent)' : 'transparent',
                      'bgcolor': current ? 'var(--accent)' : 'var(--accent-quiet)',
                      'color': current ? 'var(--accent-contrast)' : 'var(--accent)',
                      'fontSize': 11,
                      'cursor': 'pointer',
                      'transition':
                        'background-color var(--dur-fast) var(--ease-standard), color var(--dur-fast) var(--ease-standard), border-color var(--dur-fast) var(--ease-standard)',
                      '&:hover': { borderColor: 'var(--accent)' },
                      '&:focus-visible': { outline: 'none', boxShadow: 'var(--focus-ring)' },
                    }}
                  >
                    {i + 1}
                  </Box>
                );
              })}
            </Stack>
            <IconButton size="small" aria-label={t('Next step')} onClick={() => go(index + 1)}>
              {rtl ? <ChevronLeftIcon /> : <ChevronRightIcon />}
            </IconButton>
          </Stack>
        </Box>
      </LtrIsland>
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The board
// ─────────────────────────────────────────────────────────────────────────────

/** The two main pages as boards, in the order the work runs: register, then watch. */
export function WorkflowBoard(): JSX.Element {
  return (
    <Box component="section" aria-labelledby="home-workflow-title">
      <Stack spacing={0.5} sx={{ mb: 2.5 }}>
        <Typography
          className="le-mono"
          sx={{ fontSize: 11, letterSpacing: '0.12em', color: 'var(--accent)' }}
        >
          {t('THE TWO MAIN PAGES')}
        </Typography>
        <Typography id="home-workflow-title" variant="h5" component="h2" sx={{ fontWeight: 700 }}>
          {t('Two pages, step by step')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 760 }}>
          {t(
            'Register a camera in the camera workspace, then watch it on cameras monitoring. Each board walks through its page one step at a time — swipe, use the arrows, or pick a step.',
          )}
        </Typography>
      </Stack>
      <Stack spacing={3}>
        {WORKFLOW_PAGES.map((page) => (
          <PageCarousel key={page.key} page={page} />
        ))}
      </Stack>
    </Box>
  );
}

export default WorkflowBoard;
