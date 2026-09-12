/**
 * `live/DetectionOverlay.tsx` — the detector's boxes, over the live picture.
 *
 * ★ THE GEOMETRY IS THE WHOLE COMPONENT. Boxes arrive in SOURCE-MEDIA pixels; the
 *   player renders the stream contain-fit (letterboxed). An SVG with the media's
 *   own viewBox and `preserveAspectRatio="xMidYMid meet"` performs EXACTLY the same
 *   fit, so a box drawn in media coordinates lands on the object at any window size
 *   — no measuring, no resize observer, no drift.
 *
 * ★ Colours are the standalone tool's own words: yellow = the detector saw it this
 *   frame; orange = the tracker's estimate. The score rides on the label because a
 *   box with no number invites more trust than the detector claimed.
 */

import type { JSX } from 'react';
import Box from '@mui/material/Box';

import type { DetectionLatest } from '../../api/detection';
import { DETECTION_BOX, DETECTION_BOX_PREDICTED } from '../../theme/dataColors';

export function DetectionOverlay({ latest }: { latest: DetectionLatest }): JSX.Element | null {
  if (latest.width <= 0 || latest.height <= 0) return null;
  const stroke = Math.max(2, latest.width / 640);
  const font = Math.max(12, latest.width / 60);
  return (
    <Box
      component="svg"
      viewBox={`0 0 ${latest.width} ${latest.height}`}
      preserveAspectRatio="xMidYMid meet"
      sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
    >
      {latest.boxes.map((b, i) => {
        // ★ Orange = the visual tracker's estimate (has a track id); steady-boxes
        //   coasting is `predicted` but untracked and stays yellow (2026-09-03 fix).
        const colour =
          b.predicted && b.track_id !== null ? DETECTION_BOX_PREDICTED : DETECTION_BOX;
        return (
          <g key={i}>
            <rect
              x={b.x1}
              y={b.y1}
              width={b.x2 - b.x1}
              height={b.y2 - b.y1}
              fill="none"
              stroke={colour}
              strokeWidth={stroke}
            />
            <text
              x={b.x1}
              y={Math.max(font, b.y1 - stroke * 2)}
              fill={colour}
              fontSize={font}
              fontFamily="monospace"
              paintOrder="stroke"
              stroke="rgba(0,0,0,0.7)"
              strokeWidth={font / 6}
            >
              {b.cls_name} {(100 * b.score).toFixed(0)}%{b.placed ? ' ⌖' : ''}
            </text>
          </g>
        );
      })}
    </Box>
  );
}
