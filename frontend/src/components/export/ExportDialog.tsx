/**
 * `export/ExportDialog.tsx` — export options + the export JOB (50-frontend §2.23, SCOPE.md §3).
 *
 * ★ Export is a JOB, not a download (§2.23): the mutation returns a `JobRead`, the
 *   dialog shows `JobProgress`, and completion yields a signed artifact URL. Shapefile
 *   and PDF generation are slow and server-side; treating export as a job stops a
 *   30-second PDF from looking like a hang.
 *
 * ★ EVERY committed GCP is exported. There is no reliability-threshold filter and no
 *   low-confidence acknowledgement gate — the export ships exactly the points the table
 *   shows. (A GCP's declared confidence is still visible per-row; it just no longer gates
 *   the export.)
 *
 * ★ Full precision is ALWAYS in the file — §8.7's truncation is a DISPLAY policy, not
 *   a data policy. Nothing is lost by exporting.
 *
 * ★ SCOPE.md §5: uncommitted correspondences can never reach here — the server reads
 *   `gcps`, which only holds committed rows; there is no client-supplied GCP payload.
 */

import { useMemo, useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';

import { isExportDownloadable, useExport, useStartExport } from '../../api/hooks/useExport';
import { useJob } from '../../api/hooks/useJob';
import type { CoordinateFormat, Uuid } from '../../types/common';
import type { ExportFormat, ExportRequest } from '../../types/export';
import { asUuid } from '../../types/common';
import { JobProgress } from '../job/JobProgress';
import { useNotify } from '../common/Notifications';
import { t } from '../../i18n';

export interface ExportDialogProps {
  open: boolean;
  imageId: Uuid;
  format: ExportFormat;
  gcpCount: number;
  onClose: () => void;
}

const FORMAT_LABEL: Partial<Record<ExportFormat, string>> = {
  csv: 'CSV',
  geojson: 'GeoJSON',
  shapefile: 'Shapefile',
  kml: 'KML',
  kmz: 'KMZ',
  pdf: 'PDF report',
  gpkg: 'GeoPackage',
  dxf: 'DXF',
};

const SRID_OPTIONS: { value: number; label: string }[] = [
  { value: 4326, label: 'WGS 84 (EPSG:4326)' },
  { value: 3857, label: 'Web Mercator (EPSG:3857)' },
];

export function ExportDialog({
  open,
  imageId,
  format,
  gcpCount,
  onClose,
}: ExportDialogProps): JSX.Element {
  const notify = useNotify();
  const startExport = useStartExport();

  const [jobId, setJobId] = useState<Uuid | null>(null);
  const [coordinateFormat, setCoordinateFormat] = useState<CoordinateFormat>('dd');
  const [targetSrid, setTargetSrid] = useState<number>(4326);
  const [pdfTitle, setPdfTitle] = useState('');
  const [pdfNotes, setPdfNotes] = useState('');
  const [includePhoto, setIncludePhoto] = useState(true);
  const [includeMap, setIncludeMap] = useState(true);

  const jobQuery = useJob(jobId);
  const job = jobQuery.data?.data;

  // ★ The export id lives on the finished job's result_ref (§8.2).
  const exportId = useMemo<Uuid | null>(() => {
    if (job?.status === 'succeeded' && job.result_ref?.kind === 'export') {
      return asUuid(job.result_ref.id);
    }
    return null;
  }, [job]);
  const exportQuery = useExport(exportId);
  const exportRead = exportQuery.data;

  const isPdf = format === 'pdf';
  const canSubmit = gcpCount > 0 && !startExport.isPending && jobId === null;

  const submit = (): void => {
    const request: ExportRequest = {
      format,
      image_id: imageId,
      // Every committed GCP is exported — no reliability-threshold filtering.
      filter: {},
      options: {
        target_srid: targetSrid,
        csv: { coordinate_format: coordinateFormat },
        pdf: isPdf
          ? {
              title: pdfTitle.trim() === '' ? null : pdfTitle.trim(),
              notes: pdfNotes.trim() === '' ? null : pdfNotes.trim(),
              include_photo: includePhoto,
              include_map: includeMap,
              include_accuracy_table: true,
            }
          : undefined,
      },
    };

    startExport.mutate(
      { imageId, body: request },
      {
        onSuccess: (createdJob) => setJobId(createdJob.id),
        onError: () => notify('Could not start the export.', { severity: 'error' }),
      },
    );
  };

  const handleClose = (): void => {
    setJobId(null);
    startExport.reset();
    onClose();
  };

  // ★ The finished job carries the download link directly as `result_url`. The
  //   result_ref → exportId → useExport(download_url) chain is DEAD for exports: the backend
  //   returns `result_ref: null` on a succeeded export job (it puts the link in `result_url`
  //   instead), so `exportId` stayed null, `useExport` never ran, and the download button
  //   never appeared even though the file was ready. Prefer `result_url`; keep `exportRead`
  //   as a fallback so a filename is used when we have one.
  const downloadUrl =
    (job?.status === 'succeeded' ? job.result_url : null) ?? exportRead?.download_url ?? null;
  const downloadName = exportRead?.filename ?? undefined;
  const downloadable = downloadUrl !== null || isExportDownloadable(exportRead);

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Export {FORMAT_LABEL[format] ?? format}</DialogTitle>
      <DialogContent dividers>
        {jobId === null ? (
          <Stack spacing={2.5}>
            {gcpCount === 0 && (
              <Alert severity="info">
                {t('There are no ground control points to export yet. Place GCPs manually first.')}
              </Alert>
            )}

            <FormControl fullWidth size="small">
              <InputLabel id="export-srid-label">{t('Coordinate reference system')}</InputLabel>
              <Select
                labelId="export-srid-label"
                label={t('Coordinate reference system')}
                value={targetSrid}
                onChange={(e) => setTargetSrid(Number(e.target.value))}
              >
                {SRID_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {(format === 'csv' || format === 'pdf') && (
              <FormControl fullWidth size="small">
                <InputLabel id="export-coordfmt-label">{t('Coordinate format')}</InputLabel>
                <Select
                  labelId="export-coordfmt-label"
                  label={t('Coordinate format')}
                  value={coordinateFormat}
                  onChange={(e) => setCoordinateFormat(e.target.value as CoordinateFormat)}
                >
                  <MenuItem value="dd">{t('Decimal degrees')}</MenuItem>
                  <MenuItem value="dms">{t('Degrees / minutes / seconds')}</MenuItem>
                  <MenuItem value="utm">UTM</MenuItem>
                  <MenuItem value="ddutmz">{t('DD + UTM + Z')}</MenuItem>
                </Select>
              </FormControl>
            )}

            {isPdf && (
              <>
                <TextField
                  size="small"
                  label={t('Report title')}
                  value={pdfTitle}
                  onChange={(e) => setPdfTitle(e.target.value)}
                  fullWidth
                />
                <TextField
                  size="small"
                  label={t('Notes')}
                  value={pdfNotes}
                  onChange={(e) => setPdfNotes(e.target.value)}
                  fullWidth
                  multiline
                  minRows={2}
                />
                <Stack direction="row" spacing={2}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={includePhoto}
                        onChange={(e) => setIncludePhoto(e.target.checked)}
                      />
                    }
                    label={t('Include photo')}
                  />
                  <FormControlLabel
                    control={
                      <Switch
                        checked={includeMap}
                        onChange={(e) => setIncludeMap(e.target.checked)}
                      />
                    }
                    label={t('Include map')}
                  />
                </Stack>
              </>
            )}
          </Stack>
        ) : (
          <Stack spacing={2}>
            {job ? (
              <JobProgress job={job} variant="panel" />
            ) : (
              <Alert severity="info">{t('Starting export…')}</Alert>
            )}
            {downloadUrl !== null && (
              <Button variant="contained" href={downloadUrl} component="a" download={downloadName}>
                Download {downloadName ?? `${FORMAT_LABEL[format]} file`}
              </Button>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} color="inherit">
          {downloadable ? 'Close' : 'Cancel'}
        </Button>
        {jobId === null && (
          <Button variant="contained" onClick={submit} disabled={!canSubmit}>
            {t('Export')}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}

export default ExportDialog;
