/**
 * `detection/DetectionSettingsBar.tsx` — every detection setting, in ONE BAR.
 *
 * ★ ONE BAR, BOTH PAGES. The live page used to hide these behind a popover: a
 *   cramped column where the Detail select, the tracker field and the confidence
 *   slider stacked on top of each other and the whole run had to be configured
 *   blind, over a player you could no longer see. Settings that decide what a run
 *   DOES belong in the open, above the panels they govern.
 *
 * ★ GROUPED, NOT A FLAT ROW. Eight controls in a wrapping line is a list, not an
 *   instrument panel — nothing tells you which knob belongs to which decision. The
 *   bar reads as four labelled groups instead, in the order the questions come:
 *   SOURCE (what to watch) → DETECTOR (what to look for) → PLACEMENT (where it
 *   lands on the ground) → TRACKING (who follows it once found).
 *
 * ★ While a run is live the same bar carries its state — phase, rate, tally — so
 *   the thing you configured and the thing it is doing are never two places apart.
 */

import { useState, type JSX, type ReactNode } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import FormControl from '@mui/material/FormControl';
import FormHelperText from '@mui/material/FormHelperText';
import InputLabel from '@mui/material/InputLabel';
import ListItemText from '@mui/material/ListItemText';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Select from '@mui/material/Select';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import ReplayOutlinedIcon from '@mui/icons-material/ReplayOutlined';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import StopCircleOutlinedIcon from '@mui/icons-material/StopCircleOutlined';
import CheckOutlinedIcon from '@mui/icons-material/CheckOutlined';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import DriveFolderUploadOutlinedIcon from '@mui/icons-material/DriveFolderUploadOutlined';

import { useQuery } from '@tanstack/react-query';
import { lutApi } from '../../api/lut';
import { qk } from '../../api/queryKeys';
import type { DetectionSession } from '../../api/detection';
import { useDetectionAvailability } from '../../api/hooks/useDetection';
import { LutImportDialog } from '../lut/LutImportDialog';
import { useT } from '../../i18n';

/** Everything a run is configured with, minus which source it runs on. */
export interface DetectionSettingsValue {
  /** '' = the first local weights file. */
  model: string;
  /** '' = no lookup table: boxes and counts, honestly unlocated. */
  lutSite: string;
  /** COCO ids to detect. EMPTY = all of them, which is what the server does too. */
  classes: number[];
  conf: number;
  imgsz: number;
  /** 0 = YOLO every frame; N = the tracker locks once N frames are detected. */
  trackerStart: number;
  trackerType: string;
}

export interface DetectionSettingsBarProps {
  value: DetectionSettingsValue;
  onChange: (patch: Partial<DetectionSettingsValue>) => void;
  running: boolean;
  starting: boolean;
  /** Non-null disables Start and says why — the caller knows about the source. */
  disabledReason: string | null;
  startError: string | null;
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
  /** File runs only — a live feed has no pause button. */
  paused?: boolean;
  onPause?: () => void;
  /** Controls that lead the bar (the video page's clip picker). */
  leading?: ReactNode;
  /**
   * Commit the settings to the panels WITHOUT running anything — the video page's
   * preview. Omitted on pages that have nothing to preview.
   */
  onApply?: () => void;
  /** True when the controls hold changes the panels have not been shown yet. */
  dirty?: boolean;
  /** The live run, for the status strip. */
  session?: DetectionSession | null;
}

/** One labelled group of controls — the bar's unit of meaning. */
function Group({ label, children }: { label: string; children: ReactNode }): JSX.Element {
  return (
    <Stack spacing={0.75}>
      <Typography
        variant="caption"
        sx={{
          color: 'text.secondary',
          letterSpacing: '0.08em',
          fontSize: 10,
          fontWeight: 600,
          textTransform: 'uppercase',
        }}
      >
        {label}
      </Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="flex-start">
        {children}
      </Stack>
    </Stack>
  );
}

export function DetectionSettingsBar({
  value,
  onChange,
  running,
  starting,
  disabledReason,
  startError,
  onStart,
  onStop,
  onRestart,
  paused,
  onPause,
  leading,
  session,
  onApply,
  dirty = false,
}: DetectionSettingsBarProps): JSX.Element {
  const t = useT();
  const availability = useDetectionAvailability();
  // ★ THE BAR'S SHAPE MUST NOT DEPEND ON AN ANSWER THAT TAKES TIME. Probing the
  //   runtime costs ~2 s the first time (it imports torch), and the Tracking group
  //   used to be mounted only once the answer said the tracker existed — so the bar
  //   built itself in two stages while the surveyor watched. Every control is now
  //   rendered from the first frame and simply DISABLED until its answer lands; the
  //   helper lines say which state they are in. (The backend also warms this probe
  //   at startup, so in practice the answer is usually already there.)
  const probing = availability.data === undefined;
  const models = availability.data?.models ?? [];
  const classes = availability.data?.classes ?? [];
  const trackerAvailable = availability.data?.tracker.available === true;
  const trackerReason = availability.data?.tracker.reason ?? null;
  const onCpu = availability.data?.device === 'cpu';
  const chosenModel = value.model !== '' ? value.model : (models[0] ?? '');
  // ★ WHY THE DETECTOR IS LOCKED, IN THE OPEN. The server's probe names the exact
  //   fix (a pip install, or where to copy the weights); it used to live only in
  //   a tooltip on a disabled button — a lock with the key hidden under it.
  const detectorLocked = availability.data !== undefined && !availability.data.detector.available;
  const detectorReason = availability.data?.detector.reason ?? null;
  const probeFailed = availability.isError;

  const lutLibrary = useQuery({
    queryKey: qk.lut.library(),
    queryFn: ({ signal }) => lutApi.library(signal),
  });
  // ★ A surveyor arriving with a LUT built on another machine can file it FROM
  //   HERE — the import lands in the same library this select reads, and the
  //   imported bundle is selected on the spot rather than sending them to the
  //   generator page and back. See LutImportDialog.
  const [importOpen, setImportOpen] = useState(false);

  // ★ NEVER an empty selection on screen. A MUI multi-select with `[]` does not
  //   shrink its label, so the rendered "All classes" would sit on top of the word
  //   "Detect"; and "detect nothing" is not a thing the pipeline can do anyway —
  //   the server reads an empty list as ALL. So empty state shows every class
  //   ticked, and unticking the last one snaps back to all rather than to nothing.
  const allClassIds = classes.map((c) => c.id);
  const shownClasses = value.classes.length > 0 ? value.classes : allClassIds;
  const classLabel =
    shownClasses.length === classes.length
      ? 'All classes'
      : classes
          .filter((c) => shownClasses.includes(c.id))
          .map((c) => c.name)
          .join(', ');

  return (
    <Paper
      variant="outlined"
      sx={{ borderRadius: 2, px: 2, py: 1.75, bgcolor: 'background.paper' }}
    >
      {(detectorLocked || probeFailed) && (
        <Alert
          severity="warning"
          icon={<LockOutlinedIcon fontSize="inherit" />}
          sx={{ mb: 2, alignItems: 'flex-start' }}
          action={
            detectorReason !== null ? (
              <Tooltip title={t('Copy the fix')}>
                <Button
                  size="small"
                  color="inherit"
                  startIcon={<ContentCopyIcon fontSize="small" />}
                  onClick={() => {
                    void navigator.clipboard?.writeText(detectorReason).catch(() => undefined);
                  }}
                >
                  {t('Copy')}
                </Button>
              </Tooltip>
            ) : undefined
          }
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {probeFailed
              ? t('Could not ask the server what this machine can run.')
              : t('The detector is locked on this machine')}
          </Typography>
          <Typography
            className="le-mono"
            component="div"
            sx={{ fontSize: 12, mt: 0.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
          >
            {probeFailed
              ? t('Check that the API is running, then reload this page.')
              : detectorReason}
          </Typography>
          {!probeFailed && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              {t(
                'Two things make it available: the runtime (`ultralytics`) in the app’s own Python, and a YOLO weights file in the models folder. Restart the API afterwards — it probes once at start.',
              )}
            </Typography>
          )}
        </Alert>
      )}
      <Stack
        direction="row"
        spacing={2}
        useFlexGap
        flexWrap="wrap"
        alignItems="flex-start"
        divider={
          <Divider orientation="vertical" flexItem sx={{ display: { xs: 'none', xl: 'block' } }} />
        }
      >
        {leading !== undefined && <Group label={t('Source')}>{leading}</Group>}

        <Group label={t('Detector')}>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel id="det-model">{t('Model')}</InputLabel>
            <Select
              labelId="det-model"
              label={t('Model')}
              value={chosenModel}
              onChange={(e) => onChange({ model: e.target.value })}
              disabled={running || models.length === 0}
            >
              {models.map((m) => (
                <MenuItem key={m} value={m}>
                  {m}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {/* ★ The picker is built from the SERVER's allow-list (id + name), so it
              can never offer a class the detector would silently drop. Empty means
              all of them — the same rule the pipeline itself applies. */}
          <FormControl size="small" sx={{ minWidth: 170, maxWidth: 260 }}>
            <InputLabel id="det-classes">{t('Detect')}</InputLabel>
            <Select
              multiple
              labelId="det-classes"
              label={t('Detect')}
              value={shownClasses}
              onChange={(e) => {
                const next = e.target.value;
                const picked = (typeof next === 'string' ? [] : next).map(Number);
                onChange({ classes: picked.length > 0 ? picked : allClassIds });
              }}
              renderValue={() => classLabel}
              disabled={running || classes.length === 0}
            >
              {classes.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  <Checkbox size="small" checked={shownClasses.includes(c.id)} />
                  <ListItemText primary={c.name} />
                </MenuItem>
              ))}
            </Select>
            <FormHelperText>
              {shownClasses.length === classes.length ? 'everything it can find' : 'only these'}
            </FormHelperText>
          </FormControl>

          <Box sx={{ width: 132, px: 0.5 }}>
            <Typography variant="caption" color="text.secondary">
              {t('Confidence')} <b>{value.conf.toFixed(2)}</b>
            </Typography>
            <Slider
              size="small"
              min={0.05}
              max={0.9}
              step={0.05}
              value={value.conf}
              onChange={(_e, v) => onChange({ conf: v as number })}
              disabled={running}
              aria-label={t('Confidence floor')}
              sx={{ py: 0.5 }}
            />
          </Box>

          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel id="det-imgsz">{t('Detail')}</InputLabel>
            <Select
              labelId="det-imgsz"
              label={t('Detail')}
              value={value.imgsz}
              onChange={(e) => onChange({ imgsz: Number(e.target.value) })}
              disabled={running}
            >
              <MenuItem value={640}>{t('Full (640 px)')}</MenuItem>
              <MenuItem value={480}>{t('Balanced (480 px)')}</MenuItem>
              <MenuItem value={320}>{t('Fast (320 px)')}</MenuItem>
            </Select>
            <FormHelperText>
              {probing ? 'checking this machine…' : onCpu ? 'CPU — Balanced by default' : 'GPU'}
            </FormHelperText>
          </FormControl>
        </Group>

        <Group label={t('Placement')}>
          <Stack direction="row" alignItems="flex-start" spacing={0.5}>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel id="det-lut">{t('Lookup table')}</InputLabel>
              <Select
                labelId="det-lut"
                label={t('Lookup table')}
                value={value.lutSite}
                onChange={(e) => onChange({ lutSite: e.target.value })}
                disabled={running}
              >
                <MenuItem value="">
                  <em>{t('None')}</em>
                </MenuItem>
                {(lutLibrary.data ?? []).map((entry) => (
                  <MenuItem key={entry.site_name} value={entry.site_name}>
                    {entry.site_name}
                    {entry.validation_passed === false && ' (validation failed)'}
                    {/* ★ An imported bundle is usable for placement whether or not it
                        carries a pose — but the surveyor should know which table on
                        this camera came from somewhere else. */}
                    {entry.imported && ` (${t('imported')})`}
                  </MenuItem>
                ))}
              </Select>
              <FormHelperText>
                {value.lutSite === '' ? 'no marks on the map' : 'must match this camera'}
              </FormHelperText>
            </FormControl>
            <Tooltip title={t('Import a lookup table built elsewhere')}>
              <span>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setImportOpen(true)}
                  disabled={running}
                  aria-label={t('Import a lookup table')}
                  sx={{ minWidth: 0, px: 1, py: 0.75 }}
                >
                  <DriveFolderUploadOutlinedIcon fontSize="small" />
                </Button>
              </span>
            </Tooltip>
          </Stack>
          <LutImportDialog
            open={importOpen}
            onClose={() => setImportOpen(false)}
            // ★ Straight into use: importing from this bar is how someone says
            //   "run THIS run on MY table", so the pick follows the import.
            onImported={(entry) => onChange({ lutSite: entry.site_name })}
          />
        </Group>

        <Group label={t('Tracking')}>
          <TextField
            size="small"
            // ★ NOT type="number". React skips the DOM sync when the typed text
            //   and the bound number are loosely equal, so a field holding "0"
            //   that you type 60 into stays "060" on screen (seen 2026-08-20).
            //   Digits-only text has no such ambiguity.
            type="text"
            inputMode="numeric"
            label={t('Start at frame')}
            value={String(value.trackerStart)}
            onChange={(e) => {
              const digits = e.target.value.replace(/\D/g, '');
              onChange({ trackerStart: Math.min(100000, Number(digits || '0')) });
            }}
            disabled={running || !trackerAvailable}
            sx={{ width: 130 }}
            helperText={
              probing
                ? 'checking…'
                : !trackerAvailable
                  ? 'unavailable'
                  : value.trackerStart === 0
                    ? 'off — YOLO only'
                    : 'locks there'
            }
          />
          {/* ★ ALWAYS VISIBLE. This select was gated on `trackerStart > 0` for one
                afternoon and the result was a setting nobody could find: the field
                defaults to 0, so the choice simply was not on the page. */}
          <Tooltip title={!probing && !trackerAvailable ? (trackerReason ?? '') : ''}>
            <FormControl size="small" sx={{ minWidth: 190 }}>
              <InputLabel id="det-tracker-type">{t('Tracker')}</InputLabel>
              <Select
                labelId="det-tracker-type"
                label={t('Tracker')}
                value={value.trackerType}
                onChange={(e) => onChange({ trackerType: e.target.value })}
                disabled={running || !trackerAvailable}
              >
                <MenuItem value="vit">{t('ViT — learned, steadiest')}</MenuItem>
                <MenuItem value="csrt">{t('CSRT — accurate')}</MenuItem>
                <MenuItem value="kcf">{t('KCF — fast')}</MenuItem>
                <MenuItem value="mil">{t('MIL — occlusion-tolerant')}</MenuItem>
              </Select>
              <FormHelperText>
                {probing
                  ? 'checking…'
                  : !trackerAvailable
                    ? 'needs opencv-contrib'
                    : value.trackerStart === 0
                      ? 'set a frame to use it'
                      : 'takes over there'}
              </FormHelperText>
            </FormControl>
          </Tooltip>
        </Group>

        {/* ★ `ml: auto`, not a spacer Box. A flex spacer only pushes on the line it
            shares; once the bar wrapped, the spacer ate the first line and dropped
            the actions to the LEFT of the next one — the primary button in the least
            expected corner. Auto margin keeps them right on whichever line they land. */}
        <Stack direction="row" spacing={1} sx={{ pt: 2.25, ml: 'auto' }}>
          {running ? (
            <>
              {onPause !== undefined && (
                <Button
                  variant="outlined"
                  startIcon={
                    paused === true ? <PlayCircleOutlineIcon /> : <PauseCircleOutlineIcon />
                  }
                  onClick={onPause}
                >
                  {paused === true ? t('Resume') : t('Pause')}
                </Button>
              )}
              <Button variant="outlined" startIcon={<ReplayOutlinedIcon />} onClick={onRestart}>
                {t('Restart')}
              </Button>
              <Button
                variant="outlined"
                color="warning"
                startIcon={<StopCircleOutlinedIcon />}
                onClick={onStop}
              >
                {t('Stop')}
              </Button>
            </>
          ) : (
            <>
              {onApply !== undefined && (
                <Tooltip
                  title={
                    dirty
                      ? 'Show these settings in the panels below — nothing is detected yet'
                      : 'The panels already show these settings'
                  }
                >
                  <span>
                    <Button
                      variant="outlined"
                      size="large"
                      startIcon={<CheckOutlinedIcon />}
                      disabled={!dirty}
                      onClick={onApply}
                    >
                      {t('Apply')}
                    </Button>
                  </span>
                </Tooltip>
              )}
              <Tooltip title={disabledReason ?? 'Detect people and road vehicles'}>
                <span>
                  <Button
                    variant="contained"
                    size="large"
                    startIcon={<SmartToyOutlinedIcon />}
                    disabled={disabledReason !== null || starting}
                    onClick={onStart}
                  >
                    {starting ? t('Starting…') : t('Start detection')}
                  </Button>
                </span>
              </Tooltip>
            </>
          )}
        </Stack>
      </Stack>

      {/* ── the run, in the same frame as the settings that made it ─────────── */}
      {running && session != null && (
        <>
          <Divider sx={{ my: 1.5 }} />
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
            <Chip
              size="small"
              color={paused === true ? 'default' : 'success'}
              label={paused === true ? t('Paused') : t('Running')}
            />
            <Chip
              size="small"
              variant="outlined"
              label={
                session.phase === 'tracker'
                  ? `${value.trackerType.toUpperCase()} tracking`
                  : 'YOLO detecting'
              }
            />
            <Chip size="small" variant="outlined" label={`${session.fps.toFixed(1)} fps`} />
            <Chip size="small" variant="outlined" label={`${session.frames_done} frames`} />
            <Chip size="small" variant="outlined" label={`${session.marks_total} marks`} />
            {Object.entries(session.counts).map(([name, n]) => (
              <Chip key={name} size="small" label={`${name}: ${n}`} />
            ))}
          </Stack>
        </>
      )}

      {dirty && !running && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.25 }}>
          {t('The panels below still show the last applied settings. Press')} <b>{t('Apply')}</b>{' '}
          {t('to see these — or')} <b>{t('Start detection')}</b>
          {t(', which applies them and runs.')}
        </Typography>
      )}
      {value.trackerStart > 0 && !running && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.25 }}>
          {t('The tracker locks the moment')} <b>{value.trackerStart}</b> frames have been detected
          — or on the first later frame with objects, if that frame happens to be empty. After the
          lock only the objects already found are followed; a lost one is rescued by YOLO on that
          same frame.
        </Typography>
      )}
      {value.lutSite !== '' && !running && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
          {t('The lookup table must have been built for')} <b>this camera&rsquo;s exact view</b>{' '}
          {t('— it answers for one frozen pose, and marks are only as right as that match.')}
        </Typography>
      )}
      {startError !== null && (
        <Alert severity="error" variant="outlined" sx={{ mt: 1.5, wordBreak: 'break-word' }}>
          {startError}
        </Alert>
      )}
    </Paper>
  );
}
