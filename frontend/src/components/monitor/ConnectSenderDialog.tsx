/**
 * `monitor/ConnectSenderDialog.tsx` — what the camera announced, and what it fills in.
 *
 * ★ CONNECT IS A REVIEW, SAVE IS THE ACTION (2026-09-09, owner ask). A camera that
 *   detects on its own hardware announces itself with everything needed to register
 *   it. The first version of this flow used that to register the camera the moment
 *   Connect was pressed — which meant the operator never saw what had been decided
 *   on their behalf. This dialog shows the packet as it arrived, shows exactly which
 *   camera settings each field fills, lets the operator correct any of them, and
 *   registers nothing until Save. Cancel leaves no trace.
 *
 * ★ THE PACKET IS SHOWN, NOT SUMMARISED. The left column is the sender's own words
 *   — field names as they travel on the wire — because an operator debugging a
 *   wrong position needs to know whether the camera SAID the wrong thing or the app
 *   MISREAD it. The right column says where each one lands. A field the sender did
 *   not send is shown as "not sent", never silently defaulted out of sight.
 *
 * ★ THE POSITION DESERVES A WARNING WHEN IT CANNOT BE TRUSTED. A sender on a
 *   placeholder lookup table reports a position that is believable and wrong; it
 *   is still offered (it may be a fine starting point) but flagged, and the
 *   operator is expected to correct it or accept it knowingly.
 */

import { useEffect, useState, type JSX } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';

import { liveApi, type SenderRead } from '../../api/live';
import { t } from '../../i18n';
import { useCameraRegistryStore } from '../../store/cameraRegistryStore';

export interface ConnectSenderDialogProps {
  /** The sender under review, or null to close. */
  sender: SenderRead | null;
  onClose: () => void;
  /** Called with the registered camera's id after Save succeeds. */
  onSaved: (cameraId: string) => void;
}

/** One row of the packet table: the wire field, its value, and where it lands. */
interface PacketRow {
  field: string;
  value: string;
  fills: string;
  warn?: boolean;
}

function describePacket(s: SenderRead): PacketRow[] {
  const notSent = t('not sent');
  return [
    { field: 'name', value: s.name, fills: t('Camera name') },
    { field: 'host', value: s.host, fills: t('Stream source (the app reads it directly)') },
    { field: 'port', value: String(s.port), fills: t('Stream source') },
    { field: 'control_port', value: String(s.control_port), fills: t('Click-to-track commands') },
    {
      field: 'w × h',
      value: s.width !== null && s.height !== null ? `${s.width} × ${s.height}` : notSent,
      fills: t('Picture size (used to place boxes on the picture)'),
    },
    {
      field: 'lat, lon',
      value:
        s.lat !== null && s.lon !== null ? `${s.lat.toFixed(6)}, ${s.lon.toFixed(6)}` : notSent,
      fills: t('Camera position on the map'),
      warn: s.lut_placeholder,
    },
    {
      field: 'manual',
      value:
        s.manual === null
          ? notSent
          : s.manual
            ? t('true — follows nothing until you click an object')
            : t('false — follows every confirmed detection'),
      fills: t('How tracking behaves (set on the camera, shown here)'),
    },
    {
      field: 'classes',
      value: s.classes === null ? t('all 80 classes') : s.classes.join(', '),
      fills: t('What the camera detects (set on the camera, shown here)'),
    },
    {
      field: 'lut',
      value: (s.lut ?? notSent) + (s.lut_placeholder ? ` — ${t('PLACEHOLDER')}` : ''),
      fills: t('Whether its coordinates can be trusted'),
      warn: s.lut_placeholder,
    },
    {
      // Not in the beacon — it rides with every frame instead — but the
      // operator asked where drift fits, so the review says so plainly.
      field: 'drift',
      value: t('sent with every frame, not in this packet'),
      fills: t('The drift stamp on each mark this camera places (ok / moved / changed / degraded)'),
    },
  ];
}

export function ConnectSenderDialog({ sender, onClose, onSaved }: ConnectSenderDialogProps): JSX.Element {
  const addCamera = useCameraRegistryStore((s) => s.add);

  // The editable half. Seeded from the packet each time a sender is chosen, so
  // reopening the dialog for a different camera never carries stale edits over.
  const [name, setName] = useState('');
  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const [heading, setHeading] = useState('');
  const [fov, setFov] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (sender === null) return;
    setName(sender.name || sender.id);
    setLat(sender.lat !== null ? String(sender.lat) : '');
    setLon(sender.lon !== null ? String(sender.lon) : '');
    setHeading('');
    setFov('');
    setProblem(null);
  }, [sender]);

  const latNum = Number(lat);
  const lonNum = Number(lon);
  const latOk = lat.trim() !== '' && Number.isFinite(latNum) && Math.abs(latNum) <= 90;
  const lonOk = lon.trim() !== '' && Number.isFinite(lonNum) && Math.abs(lonNum) <= 180;
  const headingNum = heading.trim() === '' ? undefined : Number(heading);
  const fovNum = fov.trim() === '' ? undefined : Number(fov);
  const headingOk = headingNum === undefined || (Number.isFinite(headingNum) && headingNum >= 0 && headingNum <= 360);
  const fovOk = fovNum === undefined || (Number.isFinite(fovNum) && fovNum > 0 && fovNum <= 180);
  const canSave = sender !== null && name.trim() !== '' && latOk && lonOk && headingOk && fovOk && !busy;

  const save = async (): Promise<void> => {
    if (sender === null || !canSave) return;
    setBusy(true);
    setProblem(null);
    try {
      // 1. Start the app's own reader. Idempotent; harmless if already running.
      await liveApi.connectSender(sender.id);
      // 2. Register — THROUGH the registry store, so this browser knows the
      //    camera the moment the server does.
      // ★ PICTURE AND RECORD, BOTH FROM THE APP'S OWN READER (2026-09-09,
      //   owner decision: option 2). The stream is what the operator watches;
      //   the detections feed is what becomes marks, rows and points on the
      //   map — each stamped with the sender's own drift verdict, so the record
      //   says whether the coordinates were trustworthy when they were written.
      const camera = await addCamera({
        name: name.trim(),
        lat: latNum,
        lon: lonNum,
        source: liveApi.senderStreamUrl(sender.id),
        data_source: liveApi.senderDetectionsUrl(sender.id),
        // ★ A sender is reached at an ADDRESS on the network, like any IP camera
        //   (2026-09-11: the separate "embedded" kind folded into this one).
        connection: 'lan',
        provides: 'both',
        ...(headingNum !== undefined ? { heading_deg: headingNum } : {}),
        ...(fovNum !== undefined ? { fov_deg: fovNum } : {}),
      });
      onSaved(camera.id);
    } catch (exc) {
      setProblem(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const rows = sender === null ? [] : describePacket(sender);

  return (
    <Dialog open={sender !== null} onClose={busy ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        {t('Connect')} {sender?.name ?? ''}
        <Typography variant="body2" color="text.secondary">
          {t('What this camera announced, and the settings it fills in. Nothing is saved until you press Save.')}
        </Typography>
      </DialogTitle>

      <DialogContent dividers>
        <Stack spacing={3}>
          {/* ── the packet, as it arrived ── */}
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              {t('Received from the camera')}
              {sender !== null && (
                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                  {t('last heard')} {Math.max(0, Math.round(Date.now() / 1000 - sender.last_seen))} s {t('ago')}
                </Typography>
              )}
            </Typography>
            <Box sx={{ overflowX: 'auto' }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('Field')}</TableCell>
                    <TableCell>{t('Value')}</TableCell>
                    <TableCell>{t('Fills')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.field}>
                      <TableCell className="le-mono" sx={{ whiteSpace: 'nowrap' }}>
                        {row.field}
                      </TableCell>
                      <TableCell>
                        {row.value}
                        {row.warn === true && (
                          <Chip size="small" color="warning" label={t('placeholder')} sx={{ ml: 1 }} />
                        )}
                      </TableCell>
                      <TableCell sx={{ color: 'text.secondary' }}>{row.fills}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </Box>

          {sender?.lut_placeholder === true && (
            <Alert severity="warning">
              {t(
                'This camera is running on a placeholder lookup table, so the position it ' +
                  'announced is a guess. Correct it below if you know where the camera is.',
              )}
            </Alert>
          )}

          {/* ── the settings it becomes, editable ── */}
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              {t('Camera settings')}
            </Typography>
            <Stack spacing={2}>
              <TextField
                label={t('Name')}
                value={name}
                onChange={(e) => setName(e.target.value)}
                size="small"
                fullWidth
                error={name.trim() === ''}
              />
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField
                  label={t('Latitude')}
                  value={lat}
                  onChange={(e) => setLat(e.target.value)}
                  size="small"
                  fullWidth
                  error={!latOk}
                  helperText={latOk ? ' ' : t('−90 to 90')}
                  inputProps={{ inputMode: 'decimal' }}
                />
                <TextField
                  label={t('Longitude')}
                  value={lon}
                  onChange={(e) => setLon(e.target.value)}
                  size="small"
                  fullWidth
                  error={!lonOk}
                  helperText={lonOk ? ' ' : t('−180 to 180')}
                  inputProps={{ inputMode: 'decimal' }}
                />
              </Stack>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField
                  label={t('Heading (°)')}
                  value={heading}
                  onChange={(e) => setHeading(e.target.value)}
                  size="small"
                  fullWidth
                  error={!headingOk}
                  helperText={t('Optional — the camera did not send one')}
                  inputProps={{ inputMode: 'decimal' }}
                />
                <TextField
                  label={t('Field of view (°)')}
                  value={fov}
                  onChange={(e) => setFov(e.target.value)}
                  size="small"
                  fullWidth
                  error={!fovOk}
                  helperText={t('Optional — the camera did not send one')}
                  inputProps={{ inputMode: 'decimal' }}
                />
              </Stack>
              <TextField
                label={t('Stream source')}
                value={sender === null ? '' : liveApi.senderStreamUrl(sender.id)}
                size="small"
                fullWidth
                InputProps={{ readOnly: true }}
                helperText={t('The app reads this camera itself — there is nothing to type here.')}
              />
            </Stack>
          </Box>

          {problem !== null && <Alert severity="error">{problem}</Alert>}
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          {t('Cancel')}
        </Button>
        <Button variant="contained" onClick={() => void save()} disabled={!canSave}>
          {busy ? t('Saving…') : t('Save camera')}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
