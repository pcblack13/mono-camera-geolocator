/**
 * `image/SuggestionLayer.tsx` — where the next control point should go, drawn ON the
 * photograph the surveyor is working in.
 *
 * ★ WHY HERE AND NOT ONLY IN THE ACCURACY TAB. A suggestion is an instruction for the
 *   next click, and the next click happens on this canvas. Shown only in the accuracy
 *   view it would be advice the surveyor has to memorise and carry across a tab; shown
 *   here it is a target they place a point inside.
 *
 * ★ A KONVA LAYER, NOT AN HTML OVERLAY. The stage owns the zoom and pan transform, so
 *   anything drawn inside it tracks the photograph for free. An absolutely-positioned
 *   overlay would drift the moment the surveyor zoomed.
 *
 * ★ THE PERCENTAGE IS THE POINT, not the rank. "#1" only says which box is best; the
 *   percentage says whether ANY of them is still worth walking to — which is what tells
 *   a surveyor when to stop adding points. It is drawn on the box for that reason.
 *
 * ★ Strokes and text divide by `stageScale` so they stay the same size on screen at
 *   every zoom — the same rule the annotation layer follows.
 */

import type { JSX } from 'react';
import { Group, Label, Layer, Rect, Tag, Text } from 'react-konva';

import type { SuggestRegion } from '../../api/accuracy';
import { readableOn } from '../../lib/contrast';
import { SUGGESTION_DEFAULT } from '../../theme/dataColors';

/** Magenta — deliberately unlike any GCP confidence colour or correspondence marker. */
const SUGGESTION_COLOUR = SUGGESTION_DEFAULT;

export interface SuggestionLayerProps {
  regions: readonly SuggestRegion[];
  /** ORIGINAL px → DISPLAY px (`D`). Suggestions arrive in original photo pixels. */
  displayScale: number;
  /** The stage's live zoom (`s`) — screen-constant strokes divide by it. */
  stageScale: number;
  /** The surveyor's chosen box colour. Omitted = the magenta above. */
  color?: string;
}

export function SuggestionLayer({
  regions,
  displayScale,
  stageScale,
  color,
}: SuggestionLayerProps): JSX.Element | null {
  const colour = color ?? SUGGESTION_COLOUR;
  if (regions.length === 0) return null;
  const px = (n: number): number => n / Math.max(stageScale, 0.01);

  return (
    // `listening={false}`: the boxes are guidance, never a click target — they must not
    // swallow the very click they are asking for.
    <Layer listening={false}>
      {regions.map((region) => {
        const half = region.half_px * displayScale;
        const x = region.u * displayScale - half;
        const y = region.v * displayScale - half;
        return (
          <Group key={region.rank}>
            <Rect
              x={x}
              y={y}
              width={half * 2}
              height={half * 2}
              stroke={colour}
              strokeWidth={px(2)}
              dash={[px(8), px(6)]}
              cornerRadius={px(3)}
            />
            <Label x={x} y={y}>
              <Tag fill={colour} cornerRadius={px(2)} />
              <Text
                text={`#${region.rank}  ${region.cut_pct.toFixed(0)}%`}
                // ★ Not a fixed white: the label sits ON the chosen colour, and a
                //   pale pick would leave the rank unreadable on its own chip.
                fill={readableOn(colour)}
                fontSize={px(12)}
                padding={px(3)}
              />
            </Label>
          </Group>
        );
      })}
    </Layer>
  );
}
