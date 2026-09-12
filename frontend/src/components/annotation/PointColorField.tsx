/**
 * `annotation/PointColorField.tsx` — one point's own colour.
 *
 * ★ ON THE POINT, NOT IN A LIST. A surveyor wanting to mark ONE point ("this is the
 *   one I need to redo") finds it on the photograph, not by scrolling a palette of
 *   every point in the survey. So the control lives where the point is already
 *   selected and being edited, beside its name and kind.
 *
 * ★ KEYED BY GCP ID WHERE THERE IS ONE, so the colour follows the point onto the
 *   satellite map too: it is one physical thing seen from two sides, and someone who
 *   paints it red to find it again means both views.
 *
 * ★ It overrides the surface colours, and says so when one is in force — otherwise
 *   "why is this point still green" becomes a support question.
 */

import { type JSX } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { useWorkspaceStore } from '../../store';
import { t } from '../../i18n';

export interface PointColorFieldProps {
  /**
   * The point's key: its GCP id when it has one, else the annotation id. The caller
   * decides, because only it knows whether this mark is a control point yet.
   */
  pointKey: string;
  /** What the point is drawn in right now, when it has no colour of its own. */
  inheritedColor: string;
  /** Named in the "back to default" line so it says WHICH default. */
  inheritedFrom: string;
}

export function PointColorField({
  pointKey,
  inheritedColor,
  inheritedFrom,
}: PointColorFieldProps): JSX.Element {
  const own = useWorkspaceStore((s) => s.pointColors[pointKey]) ?? null;
  const setPointColor = useWorkspaceStore((s) => s.setPointColor);

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1.5}>
        <Box
          component="input"
          type="color"
          value={own ?? inheritedColor}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setPointColor(pointKey, e.target.value)
          }
          aria-label={t("This point's colour")}
          sx={{
            'width': 40,
            'height': 28,
            'p': 0,
            'border': 1,
            'borderColor': 'divider',
            'borderRadius': 1,
            'bgcolor': 'transparent',
            'cursor': 'pointer',
            '&::-webkit-color-swatch-wrapper': { p: '2px' },
            '&::-webkit-color-swatch': { border: 'none', borderRadius: '2px' },
          }}
        />
        <Typography variant="caption" sx={{ flex: 1 }}>
          {own === null ? 'Colour this point' : 'This point’s own colour'}
        </Typography>
        {own !== null && (
          <Button size="small" onClick={() => setPointColor(pointKey, null)}>
            {t('Clear')}
          </Button>
        )}
      </Stack>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        {own === null
          ? `Currently drawn ${inheritedFrom}.`
          : 'Overrides the workspace colours, on the photograph and the map.'}
      </Typography>
    </Box>
  );
}
