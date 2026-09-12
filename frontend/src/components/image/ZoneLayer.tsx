/**
 * `image/ZoneLayer.tsx` — the nine range zones, drawn ON the photograph.
 *
 * ★ THE MEASUREMENT PUT BACK IN THE FRAME. Stage D measures on the ground and the
 *   satellite pane shows it there; the surveyor's question — "is the far left of
 *   what I see trustworthy?" — is asked at the photograph. Three range bands by
 *   three columns, each carrying the median error of the tiles inside it and how
 *   many tiles that number rests on.
 *
 * ★ A KONVA LAYER, NOT AN HTML OVERLAY, for the reason the suggestion layer gives:
 *   the stage owns the zoom and pan, so anything drawn inside it tracks the photo
 *   for free. It sits BELOW the annotations — it is context, never a target — and
 *   listens for nothing, so it cannot swallow a click.
 *
 * ★ "NO DATA" IS A WASH, NOT A COLOUR. Under the tile floor a zone has no number,
 *   and a confident colour over two tiles would be a lie.
 *
 * ★ Strokes and text divide by `stageScale` so they keep their screen size at every
 *   zoom — the rule every layer on this stage follows.
 *
 * ★ A LABEL FITS ITS ZONE OR SHRINKS. The far bands of a grazing view are a few
 *   dozen rows tall at fit zoom, and three two-line labels stacked there hide the
 *   very zones they name. A zone shorter on screen than its full label gets one
 *   line; shorter than that, none — zooming in brings the label back, because the
 *   zone's screen height grows with the zoom while the label's does not.
 */

import { useMemo, type JSX } from 'react';
import { Group, Label, Layer, Line, Tag, Text } from 'react-konva';

import type { AccuracyZones } from '../../api/accuracy';
import { withAlpha, zoneFill, zonePolygons } from '../../lib/accuracy/zones';
import { ZONE_EDGE, ZONE_LABEL_BG, ZONE_NO_DATA } from '../../theme/dataColors';
import { t } from '../../i18n';

export interface ZoneLayerProps {
  zones: AccuracyZones | null | undefined;
  /** Fill opacity, 0–100. At 0 the fills vanish and the edges and labels stay. */
  opacity: number;
  /** ORIGINAL px → DISPLAY px (`D`). The curves arrive in original photo pixels. */
  displayScale: number;
  /** The stage's live zoom (`s`). */
  stageScale: number;
}

export function ZoneLayer({
  zones,
  opacity,
  displayScale,
  stageScale,
}: ZoneLayerProps): JSX.Element | null {
  const polygons = useMemo(() => (zones ? zonePolygons(zones) : []), [zones]);
  if (!zones || polygons.length === 0) return null;
  const alpha = Math.max(0, Math.min(100, opacity)) / 100;
  const px = (n: number): number => n / Math.max(stageScale, 0.01);
  const D = displayScale;
  /** Screen pixels a zone stands, at this zoom. */
  const screenHeight = (heightPx: number): number => heightPx * D * stageScale;

  return (
    <Layer listening={false}>
      {polygons.map((z) => {
        const hasData = z.t !== null;
        const main = hasData ? `${(z.medianErrorM as number).toFixed(1)} m` : t('no data');
        const count = `${z.tiles} ${t(z.tiles === 1 ? 'tile' : 'tiles')}`;
        const room = screenHeight(z.heightPx);
        const label =
          room >= 48
            ? `${z.name}  ${main}\n${z.rangeLabel}   ${count}`
            : room >= 18
              ? `${z.name}  ${main}  ·  ${count}`
              : null;
        return (
          <Group key={z.key}>
            <Line
              points={z.points.map((n) => n * D)}
              closed
              fill={
                hasData
                  ? zoneFill(z.t as number, alpha)
                  : withAlpha(ZONE_NO_DATA, Math.max(0.08, alpha / 3))
              }
              stroke={withAlpha(ZONE_EDGE, hasData ? Math.min(1, alpha + 0.35) : 0.35)}
              strokeWidth={px(1)}
            />
            {label !== null && (
              <Label
                x={z.label.u * D}
                y={z.label.v * D}
                offsetX={px(label.includes('\n') ? 48 : 60)}
                offsetY={px(label.includes('\n') ? 18 : 10)}
              >
                <Tag fill={withAlpha(ZONE_LABEL_BG, 0.72)} cornerRadius={px(5)} />
                <Text
                  text={label}
                  fill={ZONE_EDGE}
                  fontSize={px(11)}
                  lineHeight={1.25}
                  padding={px(5)}
                  align="center"
                />
              </Label>
            )}
          </Group>
        );
      })}
    </Layer>
  );
}
