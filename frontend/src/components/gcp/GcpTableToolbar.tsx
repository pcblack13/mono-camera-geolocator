/**
 * `gcp/GcpTableToolbar.tsx` — the GCP table's header. 50-frontend §2.22.
 *
 * Shows the point count and hosts the coordinate-format switch (`dd` / `dms` / `utm`),
 * which `workspaceStore` persists.
 */

import { useState, type JSX } from 'react';
import Badge from '@mui/material/Badge';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import type { CoordinateFormat, Uuid } from '../../types/common';
import { ExportMenu } from '../export/ExportMenu';
import { useAccuracyState, useMeasureAccuracy } from '../../api/hooks/useAccuracy';
import {
  AUTO_MEASURE_MIN_GCPS,
  resetAccuracyAutopilot,
  useAccuracyAutopilot,
} from '../../api/hooks/useAccuracyAutopilot';
import { useWorkspaceStore } from '../../store';
import StraightenIcon from '@mui/icons-material/Straighten';
import { AccuracyLoopStatus } from './AccuracyLoopStatus';
import { ImportGcpsDialog } from './ImportGcpsDialog';
import { ImportKmlDialog } from './ImportKmlDialog';
import { t } from '../../i18n';

export interface GcpTableToolbarProps {
  imageId: Uuid;
  /**
   * ★ Project-scoped, unlike the rest of this toolbar. A KML import matches placemarks
   * against every GCP in the project, not just this image's — the file a surveyor took
   * away and refined has no notion of which photo each point was paired against, and
   * scoping the match to one image would silently fail to find points that are plainly
   * in their project.
   */
  projectId: Uuid;
  total: number;
  coordinateFormat: CoordinateFormat;
  onCoordinateFormatChange: (f: CoordinateFormat) => void;
}

const FORMAT_LABEL: Record<CoordinateFormat, string> = {
  dd: 'DD',
  dms: 'DMS',
  utm: 'UTM',
  ddutmz: 'DD+UTM+Z',
};

export function GcpTableToolbar({
  imageId,
  projectId,
  total,
  coordinateFormat,
  onCoordinateFormatChange,
}: GcpTableToolbarProps): JSX.Element {
  const [importOpen, setImportOpen] = useState(false);
  const [kmlOpen, setKmlOpen] = useState(false);

  // ★ Read-only here: `WorkspacePage` drives the loop. React Query dedupes the state
  //   query, and the hook's own guards make a second caller harmless — but the page is
  //   the one that owns it, so the toolbar only reports.
  const accuracyState = useAccuracyState(imageId).data;
  const loop = useAccuracyAutopilot(imageId, { gcpCount: total });
  const autoMeasure = useWorkspaceStore((st) => st.autoMeasure);
  const measure = useMeasureAccuracy();

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 1,
        px: 1.5,
        py: 0.75,
        borderBottom: 1,
        borderColor: 'divider',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          {t('Ground Control Points')}
          <Badge color="default" badgeContent={total} showZero sx={{ ml: 1.5 }} />
        </Typography>
        {/* ★ Auto-GCP state lives beside the count it depends on: a progress chip
            while points are owed, a ready chip at four, an enable button (lit only
            at four) when the tool was never turned on. */}
        {/* ★ THE ACCURACY LOOP ACCOUNTS FOR ITSELF HERE — beside the count that
            drives it, including the verdict that the points are enough. */}
        <AccuracyLoopStatus
          state={accuracyState}
          running={loop.running}
          message={loop.message}
          converged={loop.converged}
        />
        {/* ★ THE MEASURE BUTTON. The loop is opt-in now (2026-08-20), so without a
            button in the open the whole accuracy feature would be reachable only
            through a popover behind a ruler icon — turning "stop doing this unasked"
            into "you can no longer do this". Hidden while a run is in flight, and
            while the automatic loop is on and would do it anyway. */}
        {!loop.running && !autoMeasure && total >= AUTO_MEASURE_MIN_GCPS && (
          <Tooltip
            title={
              accuracyState?.measurement == null
                ? 'Measure how far this photograph lands from the satellite imagery'
                : 'Measure again with the points as they stand now'
            }
          >
            <span>
              <Button
                size="small"
                variant={accuracyState?.measurement == null ? 'contained' : 'outlined'}
                startIcon={<StraightenIcon />}
                disabled={measure.isPending}
                onClick={() => {
                  resetAccuracyAutopilot(imageId);
                  measure.mutate({ image_id: imageId });
                }}
              >
                {measure.isPending
                  ? 'Measuring…'
                  : accuracyState?.measurement == null
                    ? 'Measure error'
                    : 'Re-measure'}
              </Button>
            </span>
          </Tooltip>
        )}
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={coordinateFormat}
          onChange={(_e, next: CoordinateFormat | null) => {
            if (next !== null) onCoordinateFormatChange(next);
          }}
          aria-label={t('Coordinate format')}
        >
          {(['dd', 'dms', 'utm', 'ddutmz'] as CoordinateFormat[]).map((f) => (
            <ToggleButton key={f} value={f} aria-label={FORMAT_LABEL[f]} sx={{ px: 1 }}>
              {FORMAT_LABEL[f]}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>

        {/* ★ Import CREATES now: a CSV/GeoJSON of already-located points (this
            app's own exports round-trip losslessly) deploys onto this photo —
            the reuse flow for a photograph serving several projects. The KML/KMZ
            refinement round-trip is reachable from inside the dialog. Always
            enabled: creation needs no existing points to match against. */}
        <Tooltip title="Import GCPs from a CSV or GeoJSON of already-located points">
          <Button
            size="small"
            variant="outlined"
            startIcon={<FileDownloadOutlinedIcon />}
            onClick={() => setImportOpen(true)}
          >
            {t('Import')}
          </Button>
        </Tooltip>

        {/* ★ Export the GCP table in the chosen format. Built (ExportMenu + ExportDialog +
            the backend writers) but never mounted — so the surveyor had no way to reach it.
            Disabled with an honest tooltip when there is nothing to export yet. */}
        <ExportMenu imageId={imageId} gcpCount={total} disabled={total === 0} />

        {/* ★ The lookup table is built from the camera's pipeline (the strip above the
            editor, or the camera's settings page) — no door to a generator here (2026-09-04). */}
      </Box>

      <ImportGcpsDialog
        open={importOpen}
        imageId={imageId}
        onClose={() => setImportOpen(false)}
        onSwitchToKml={() => setKmlOpen(true)}
      />
      <ImportKmlDialog open={kmlOpen} projectId={projectId} onClose={() => setKmlOpen(false)} />
    </Box>
  );
}
