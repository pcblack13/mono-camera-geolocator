/**
 * `gcp/ImportKmlDialog.tsx` — the KML/KMZ round trip: export, refine elsewhere, import.
 *
 * The inverse of `ExportDialog`. A surveyor exports the project's GCPs, opens the file in
 * whatever viewer they own, refines the positions against imagery this app never sees,
 * saves, and brings it back here.
 *
 * ★ **PREVIEW, THEN CONFIRM.** Picking a file only ever runs the preview, which writes
 *   nothing. The diff table below is the whole point of the dialog: an import edits
 *   coordinates in a survey deliverable, and the surveyor has to see *which* points move
 *   and *how far* before agreeing to it. `Apply` is a second, deliberate act.
 *
 * ★ **NOTHING IS HIDDEN.** Every placemark appears in exactly one of the three sections
 *   and every GCP the file did not mention is counted. A surveyor who exported 30 points
 *   and imports 28 must be able to see which two went missing and why — an import UI that
 *   silently drops rows has changed the deliverable without telling anyone.
 *
 * ★ **AN IMPORT CANNOT CREATE A GCP**, and the dialog says so rather than offering a
 *   greyed-out button. `gcps.pixel_x`/`pixel_y` are NOT NULL: a GCP pairs an image pixel
 *   with a ground coordinate, and a placemark carries only the ground half.
 *
 * ★ **The elevation switch defaults ON but is honest about what it writes**: an imported
 *   height is recorded as a *manual* source with **no** vertical error bar, because this
 *   system has no basis for one. That is stated in the UI, not just in the schema.
 */

import { useCallback, useRef, useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';

import { importsApi } from '../../api/imports';
import { queryClient } from '../../api/queryClient';
import { qk } from '../../api/queryKeys';
import type { Uuid } from '../../types/common';
import { ApiError } from '../../types/common';
import type { KmlImportMatch, KmlImportPreview } from '../../types/import';
import { useNotify } from '../common/Notifications';
import { browseNativeOrInput, filtersFromAccept } from '../../lib/nativeFilePicker';
import { t } from '../../i18n';

export interface ImportKmlDialogProps {
  open: boolean;
  projectId: Uuid;
  onClose: () => void;
}

/** Accepted extensions. The server sniffs the zip magic, so this is only a file picker hint. */
const ACCEPT = '.kml,.kmz,application/vnd.google-earth.kml+xml,application/vnd.google-earth.kmz';

/**
 * Metres shown to millimetre precision.
 *
 * ★ Not truncated to a "nice" figure. `offset_m` is the number the surveyor decides on,
 * and rounding 0.004 m to "0 m" would hide precisely the no-op case they need to see.
 */
function metres(value: number): string {
  return `${value.toFixed(3)} m`;
}

function coordinate(lat: number, lon: number): string {
  return `${lat.toFixed(7)}, ${lon.toFixed(7)}`;
}

/** One row of the diff: where the point is, where the file puts it, and how far that is. */
function MatchRow({ match }: { match: KmlImportMatch }): JSX.Element {
  const label = match.code ?? match.placemark_name ?? match.gcp_id.slice(0, 8);
  const moved = match.offset_m >= 0.001;

  return (
    <TableRow sx={{ opacity: moved ? 1 : 0.55 }}>
      <TableCell>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {label}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          matched by {match.matched_by}
        </Typography>
      </TableCell>

      <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
        {coordinate(match.current_lat, match.current_lon)}
      </TableCell>
      <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
        {moved ? coordinate(match.new_lat, match.new_lon) : '—'}
      </TableCell>

      <TableCell align="right">
        {moved ? (
          <Stack direction="row" spacing={0.5} alignItems="center" justifyContent="flex-end">
            {match.exceeds_accuracy && (
              <Tooltip
                title={
                  `This moves the point further than its own stated accuracy ` +
                  `(CE90 ${match.current_total_ce90_m?.toFixed(2) ?? '—'} m). That is a ` +
                  `legitimate refinement — it is flagged so you confirm it deliberately.`
                }
              >
                <WarningAmberIcon fontSize="small" color="warning" />
              </Tooltip>
            )}
            <Typography variant="body2">{metres(match.offset_m)}</Typography>
          </Stack>
        ) : (
          <Typography variant="caption" color="text.secondary">
            unchanged
          </Typography>
        )}
      </TableCell>

      <TableCell align="right">
        {match.elevation_note !== null ? (
          <Tooltip title={match.elevation_note}>
            <Typography variant="caption" color="warning.main">
              {t('altitude ignored')}
            </Typography>
          </Tooltip>
        ) : match.new_elevation_m !== null ? (
          <Typography variant="body2">
            {match.current_elevation_m !== null && `${match.current_elevation_m.toFixed(2)} → `}
            {match.new_elevation_m.toFixed(2)} m
          </Typography>
        ) : (
          <Typography variant="caption" color="text.secondary">
            —
          </Typography>
        )}
      </TableCell>
    </TableRow>
  );
}

export function ImportKmlDialog({ open, projectId, onClose }: ImportKmlDialogProps): JSX.Element {
  const notify = useNotify();
  const fileInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<KmlImportPreview | null>(null);
  const [busy, setBusy] = useState<'preview' | 'apply' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applyElevation, setApplyElevation] = useState(true);
  const [note, setNote] = useState('');

  const reset = useCallback(() => {
    setFile(null);
    setPreview(null);
    setError(null);
    setBusy(null);
    setNote('');
    if (fileInput.current) fileInput.current.value = '';
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  const applyPicked = useCallback(
    async (picked: File | null) => {
      setFile(picked);
      setPreview(null);
      setError(null);
      if (!picked) return;

      setBusy('preview');
      try {
        setPreview(await importsApi.previewKml(projectId, picked));
      } catch (err) {
        // ★ The parse failure message is the useful part — it names the actual defect
        //   ("longitude 999 outside [-180, 180]"), so it is surfaced verbatim rather
        //   than replaced with a generic "could not read file".
        setError(err instanceof ApiError ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [projectId],
  );

  const handleApply = useCallback(async () => {
    if (!file || !preview) return;
    setBusy('apply');
    setError(null);
    try {
      const result = await importsApi.applyKml(projectId, {
        file,
        // ★ Carries the surveyor's consent: if re-parsing at apply time disagrees, the
        //   file changed under them and the server refuses (409) rather than applying
        //   edits nobody looked at.
        expected_match_count: preview.matched.length,
        apply_elevation: applyElevation,
        note: note.trim().length > 0 ? note.trim() : undefined,
      });

      // Positions moved server-side, so every cached GCP view is stale.
      await queryClient.invalidateQueries({ queryKey: qk.gcps.all() });

      notify(
        `Imported: ${result.adjusted_gcp_ids.length} GCP(s) adjusted` +
          (result.elevation_written_count > 0
            ? `, ${result.elevation_written_count} with a new elevation`
            : '') +
          (result.unchanged_count > 0 ? `, ${result.unchanged_count} unchanged` : ''),
        { severity: 'success' },
      );
      handleClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [applyElevation, file, handleClose, note, notify, preview, projectId]);

  const nothingToApply =
    preview !== null && preview.moved_count === 0 && preview.matched.length === 0;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="lg" fullWidth>
      <DialogTitle>{t('Import GCP positions from KML/KMZ')}</DialogTitle>

      <DialogContent dividers>
        <Stack spacing={2}>
          <Alert severity="info">
            <AlertTitle>{t('How this works')}</AlertTitle>
            Export this project&apos;s GCPs as KML, open the file in your mapping or globe
            application, refine the marker positions there, and save. Importing the saved file moves
            the matching GCPs here.
            <br />
            <strong>{t('An import only moves points that already exist.')}</strong>{' '}
            {t(
              'A placemark carries a ground coordinate but no image pixel, and a GCP is a pairing of the two — so new placemarks are reported, never created. Pair those in the workspace against the photo they belong to.',
            )}
          </Alert>

          <Box>
            <input
              ref={fileInput}
              type="file"
              accept={ACCEPT}
              onChange={(e) => {
                void applyPicked(e.target.files?.[0] ?? null);
                e.target.value = '';
              }}
              style={{ display: 'none' }}
              id="kml-import-file"
            />
            <Stack direction="row" spacing={2} alignItems="center">
              <Button
                variant="outlined"
                onClick={() =>
                  browseNativeOrInput(
                    fileInput.current,
                    filtersFromAccept('.kml,.kmz', 'Google Earth files'),
                    (files) => {
                      void applyPicked(files[0]);
                    },
                  )
                }
                disabled={busy !== null}
              >
                {t('Choose .kml or .kmz')}
              </Button>
              {file && (
                <Typography variant="body2" color="text.secondary">
                  {file.name}
                </Typography>
              )}
              {busy === 'preview' && <CircularProgress size={20} />}
            </Stack>
          </Box>

          {error !== null && (
            <Alert severity="error" onClose={() => setError(null)}>
              {error}
            </Alert>
          )}

          {preview !== null && (
            <>
              <Divider />
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip size="small" color="primary" label={`${preview.moved_count} will move`} />
                <Chip
                  size="small"
                  label={`${preview.matched.length - preview.moved_count} unchanged`}
                />
                {preview.exceeds_accuracy_count > 0 && (
                  <Chip
                    size="small"
                    color="warning"
                    label={`${preview.exceeds_accuracy_count} beyond stated accuracy`}
                  />
                )}
                {preview.unmatched.length > 0 && (
                  <Chip size="small" label={`${preview.unmatched.length} unmatched`} />
                )}
                {preview.skipped.length > 0 && (
                  <Chip size="small" label={`${preview.skipped.length} skipped`} />
                )}
                <Chip
                  size="small"
                  variant="outlined"
                  label={`${preview.untouched_gcp_count} GCP(s) not in this file`}
                />
              </Stack>

              {preview.matched.length > 0 && (
                <Box sx={{ maxHeight: 320, overflow: 'auto' }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>{t('Point')}</TableCell>
                        <TableCell>{t('Current (lat, lon)')}</TableCell>
                        <TableCell>{t('From file')}</TableCell>
                        <TableCell align="right">Moves</TableCell>
                        <TableCell align="right">{t('Elevation')}</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {preview.matched.map((m) => (
                        <MatchRow key={m.gcp_id} match={m} />
                      ))}
                    </TableBody>
                  </Table>
                </Box>
              )}

              {preview.unmatched.length > 0 && (
                <Alert severity="warning">
                  <AlertTitle>
                    {preview.unmatched.length} placemark(s) matched no GCP — nothing will be created
                    for them
                  </AlertTitle>
                  <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                    {preview.unmatched.map((u, i) => (
                      <li key={`${u.placemark_name ?? 'unnamed'}-${i}`}>
                        <Typography variant="caption">
                          <strong>{u.placemark_name ?? '(unnamed)'}</strong> — {u.reason}
                        </Typography>
                      </li>
                    ))}
                  </Box>
                </Alert>
              )}

              {preview.skipped.length > 0 && (
                <Alert severity="warning">
                  <AlertTitle>{preview.skipped.length} placemark(s) could not be read</AlertTitle>
                  <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                    {preview.skipped.map((s, i) => (
                      <li key={`${s.placemark_name ?? 'unnamed'}-${i}`}>
                        <Typography variant="caption">
                          <strong>{s.placemark_name ?? '(unnamed)'}</strong> — {s.reason}
                        </Typography>
                      </li>
                    ))}
                  </Box>
                </Alert>
              )}

              <FormControlLabel
                control={
                  <Switch
                    checked={applyElevation}
                    onChange={(e) => setApplyElevation(e.target.checked)}
                  />
                }
                label={
                  <Typography variant="body2">
                    {t('Apply elevations from the file')}
                    <Typography variant="caption" color="text.secondary" display="block">
                      {t('Recorded as a')} <strong>manual</strong> source with{' '}
                      <strong>{t('no vertical accuracy figure')}</strong> — you asserted the height
                      and this system has no basis for an error bar on it. Turn this off to move
                      points horizontally and leave Z to the project&apos;s DEM.
                    </Typography>
                  </Typography>
                }
              />

              <TextField
                size="small"
                fullWidth
                label={t('Adjustment note (optional)')}
                placeholder={`Position imported from ${file?.name ?? 'a KML file'}`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                inputProps={{ maxLength: 500 }}
                helperText="Stored on every adjusted GCP, so the provenance of the move survives."
              />
            </>
          )}
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={handleClose} disabled={busy === 'apply'}>
          {t('Cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={handleApply}
          disabled={preview === null || busy !== null || nothingToApply}
        >
          {busy === 'apply' ? 'Applying…' : `Apply ${preview?.moved_count ?? 0} move(s)`}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
