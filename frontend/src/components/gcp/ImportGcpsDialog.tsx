/**
 * `gcp/ImportGcpsDialog.tsx` — deploy already-located GCPs onto this photograph.
 *
 * ★ THE REUSE FLOW, CLOSED. The same photograph serves several projects (capture
 *   library), and its points should too: export the GCPs once, import them here,
 *   and every correspondence lands on this copy of the photo — against whatever
 *   basemap this project uses. CSV and GeoJSON both work; this app's own exports
 *   round-trip losslessly, and foreign files are accepted when they carry both
 *   halves of each pair (image pixels + world coordinates). See `lib/gcpImport`.
 *
 * ★ PREVIEW, THEN CONFIRM — the same shape as the KML dialog: picking a file only
 *   parses it; nothing is created until the Import button. Skipped rows are listed
 *   with reasons, never silently dropped.
 *
 * ★ Created points record a surveyor confidence of 3 (middle) and a close-zoom
 *   accuracy basis: the app cannot verify a file's provenance, so it claims the
 *   midpoint rather than inheriting a confidence it cannot check.
 */

import { useRef, useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import LinearProgress from '@mui/material/LinearProgress';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined';

import { useCreateGcp } from '../../api/hooks/useGcps';
import { parseGcpFile, type GcpImportResult } from '../../lib/gcpImport';
import { useNotify } from '../common/Notifications';
import type { Uuid } from '../../types/common';
import { browseNativeOrInput, filtersFromAccept } from '../../lib/nativeFilePicker';
import { t } from '../../i18n';

export interface ImportGcpsDialogProps {
  open: boolean;
  onClose: () => void;
  imageId: Uuid;
  /** Open the KML/KMZ refinement dialog instead (the other kind of import). */
  onSwitchToKml: () => void;
}

/**
 * ★ Imported points are treated as CLOSE-ZOOM placements for the accuracy model
 * (the server derives CE90 from imagery GSD at this zoom). 18 ≈ sub-metre GSD —
 * consistent with coordinates precise enough to be worth importing.
 */
const IMPORT_MAP_ZOOM = 18;

export function ImportGcpsDialog({
  open,
  onClose,
  imageId,
  onSwitchToKml,
}: ImportGcpsDialogProps): JSX.Element {
  const notify = useNotify();
  const createGcp = useCreateGcp(imageId);
  const fileRef = useRef<HTMLInputElement>(null);

  const [filename, setFilename] = useState<string | null>(null);
  const [parsed, setParsed] = useState<GcpImportResult | null>(null);
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState(0);

  const reset = (): void => {
    setFilename(null);
    setParsed(null);
    setProgress(0);
  };

  const close = (): void => {
    if (importing) return;
    reset();
    onClose();
  };

  const onPickFile = async (file: File | undefined): Promise<void> => {
    if (!file) return;
    const text = await file.text();
    setFilename(file.name);
    setParsed(parseGcpFile(file.name, text));
    setProgress(0);
  };

  const runImport = async (): Promise<void> => {
    if (!parsed || parsed.points.length === 0) return;
    setImporting(true);
    let created = 0;
    let failed = 0;
    for (const p of parsed.points) {
      try {
        await createGcp.mutateAsync({
          lat: p.lat,
          lon: p.lon,
          image_px: { x: p.image_x, y: p.image_y },
          declared_confidence: 3,
          map_zoom: IMPORT_MAP_ZOOM,
          ...(p.name ? { name: p.name } : {}),
        });
        created += 1;
      } catch {
        failed += 1;
      }
      setProgress(created + failed);
    }
    setImporting(false);
    notify(
      failed === 0
        ? `Imported ${created} GCP${created === 1 ? '' : 's'} onto this photo.`
        : `Imported ${created} GCP${created === 1 ? '' : 's'} — ${failed} failed (see the table for what the server refused).`,
      { severity: failed === 0 ? 'success' : 'warning' },
    );
    if (failed === 0) {
      reset();
      onClose();
    }
  };

  const points = parsed?.points ?? [];
  const skipped = parsed?.skipped ?? [];

  return (
    <Dialog open={open} onClose={close} maxWidth="sm" fullWidth>
      <DialogTitle>{t('Import GCPs onto this photo')}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          A CSV or GeoJSON of already-located points — each row carrying its image pixel position
          and its latitude/longitude — is deployed onto this photograph as ready ground control
          points. Files exported by this app import exactly as they were; other files work when they
          name both halves of each pair.
        </Typography>

        <Button
          variant="outlined"
          size="small"
          startIcon={<UploadFileOutlinedIcon />}
          disabled={importing}
          onClick={() =>
            browseNativeOrInput(
              fileRef.current,
              filtersFromAccept('.csv,.geojson,.json', 'GCP tables'),
              (files) => {
                void onPickFile(files[0]);
              },
            )
          }
        >
          {filename ?? 'Choose file (.csv, .geojson)…'}
        </Button>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept=".csv,.geojson,.json,text/csv,application/geo+json,application/json"
          onChange={(e) => {
            void onPickFile(e.target.files?.[0]);
            e.target.value = '';
          }}
        />

        {parsed && (
          <Box sx={{ mt: 2 }}>
            {points.length > 0 ? (
              <>
                <Typography variant="caption" color="text.secondary">
                  {points.length} point{points.length === 1 ? '' : 's'} ready to import:
                </Typography>
                <Table size="small" sx={{ mt: 0.5 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>{t('Name')}</TableCell>
                      <TableCell align="right">{t('Image X')}</TableCell>
                      <TableCell align="right">{t('Image Y')}</TableCell>
                      <TableCell align="right">{t('Latitude')}</TableCell>
                      <TableCell align="right">{t('Longitude')}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {points.slice(0, 8).map((p, i) => (
                      <TableRow key={`${p.image_x},${p.image_y},${i}`}>
                        <TableCell>{p.name ?? '—'}</TableCell>
                        <TableCell align="right">{p.image_x.toFixed(1)}</TableCell>
                        <TableCell align="right">{p.image_y.toFixed(1)}</TableCell>
                        <TableCell align="right">{p.lat.toFixed(6)}</TableCell>
                        <TableCell align="right">{p.lon.toFixed(6)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {points.length > 8 && (
                  <Typography variant="caption" color="text.secondary">
                    …and {points.length - 8} more.
                  </Typography>
                )}
              </>
            ) : (
              <Alert severity="warning">{t('Nothing importable in this file.')}</Alert>
            )}

            {skipped.length > 0 && (
              <Alert severity="info" sx={{ mt: 1.5 }}>
                <Typography variant="caption" component="div" sx={{ fontWeight: 600 }}>
                  Skipped {skipped.length} row{skipped.length === 1 ? '' : 's'}:
                </Typography>
                {skipped.slice(0, 5).map((s) => (
                  <Typography key={s.row} variant="caption" component="div">
                    Row {s.row}: {s.reason}
                  </Typography>
                ))}
                {skipped.length > 5 && (
                  <Typography variant="caption" component="div">
                    …and {skipped.length - 5} more.
                  </Typography>
                )}
              </Alert>
            )}
          </Box>
        )}

        {importing && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress
              variant="determinate"
              value={points.length > 0 ? (progress / points.length) * 100 : 0}
            />
            <Typography variant="caption" color="text.secondary">
              {progress} / {points.length}
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions sx={{ justifyContent: 'space-between' }}>
        <Button
          size="small"
          onClick={() => {
            close();
            onSwitchToKml();
          }}
          disabled={importing}
        >
          {t('Refining positions? Import KML/KMZ…')}
        </Button>
        <Box>
          <Button onClick={close} disabled={importing} sx={{ mr: 1 }}>
            {t('Cancel')}
          </Button>
          <Button
            variant="contained"
            onClick={() => void runImport()}
            disabled={points.length === 0 || importing}
            startIcon={importing ? <CircularProgress size={14} color="inherit" /> : undefined}
          >
            {importing
              ? 'Importing…'
              : points.length > 0
                ? `Import ${points.length} point${points.length === 1 ? '' : 's'}`
                : 'Import'}
          </Button>
        </Box>
      </DialogActions>
    </Dialog>
  );
}

export default ImportGcpsDialog;
