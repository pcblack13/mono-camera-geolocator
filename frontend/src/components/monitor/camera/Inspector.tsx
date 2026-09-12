/**
 * `monitor/camera/Inspector.tsx` — the staged right-hand inspector, ① to ⑤.
 *
 * ★ THE SAME CONTROLS THE SETTINGS BAR CARRIED — model, classes, confidence,
 *   detail, lookup table, tracker — in the order the questions come, each behind
 *   its gate. The drift stage READS the camera's own background watch (frozen on
 *   its frame in the camera settings, 2026-09-08); nothing is frozen from here.
 */

import { type JSX } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import FormHelperText from '@mui/material/FormHelperText';
import InputLabel from '@mui/material/InputLabel';
import ListItemText from '@mui/material/ListItemText';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import type { DetectionAvailability, DetectionSession } from '../../../api/detection';
import type { DriftVerdict } from '../../../api/drift';
import { lutApi } from '../../../api/lut';
import { qk } from '../../../api/queryKeys';
import { runAverageFps, type StageState } from '../../../lib/monitor/stages';
import type { StreamStats } from '../../../hooks/useLiveFeed';
import { DRIFT_LABEL, DriftPill } from '../../drift/DriftPill';
import { StatReadout } from '../../ui';
import { t } from '../../../i18n';
import { InspectorStage } from './InspectorStage';

export interface DetectorDraft {
  model: string;
  lutSite: string;
  classes: number[];
  conf: number;
  imgsz: number;
  trackerStart: number;
  trackerType: string;
  /** Opt-in: push each mark from the object's near edge to its centre (1.3). */
  centreMarks: boolean;
  /** Steady boxes: smooth + debounce the overlay (on by default, 2026-09-03). */
  steadyBoxes: boolean;
  /** ★ Marks per second, per object (2026-09-11). 0 = one per frame. */
  markRateHz: number;
}

export interface InspectorProps {
  stages: StageState[];
  draft: DetectorDraft;
  onChange: (patch: Partial<DetectorDraft>) => void;
  availability: DetectionAvailability | undefined;
  stats: StreamStats;
  fpsMeasurable: boolean;
  running: boolean;
  /** The run, while one is on — the source stage reads ITS numbers then. */
  run: DetectionSession | null;
  onFix: (action: NonNullable<StageState['fix']>['action']) => void;
  /** The camera's background drift watch, as the page reads it (2026-09-08). */
  drift: InspectorDrift;
}

export interface InspectorDrift {
  /** The newest look, or null before the first one (or with no watch at all). */
  verdict: DriftVerdict | null;
  /** A reference exists — frozen on the camera's frame. */
  frozen: boolean;
  /** Its background watch is running now. */
  watching: boolean;
  /** The watch's own trouble line, verbatim (a stopped or failed run). */
  lastError: string | null;
  /** The frozen frame's name, when the reference says which one. */
  frozenFromLabel: string | null;
  /** The range the ground shift is stated at — the far end of the scene, metres. */
  refRangeM: number | null;
  /** The camera settings — where the reference is made and re-frozen. */
  settingsTo: string;
}

const TRACKERS: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'vit', label: 'ViT — learned, steadiest' },
  { id: 'csrt', label: 'CSRT — accurate' },
  { id: 'kcf', label: 'KCF — fast' },
  { id: 'mil', label: 'MIL — robust' },
];

export function Inspector(p: InspectorProps): JSX.Element {
  const models = p.availability?.models ?? [];
  const classes = p.availability?.classes ?? [];
  const allClassIds = classes.map((c) => c.id);
  const shownClasses = p.draft.classes.length > 0 ? p.draft.classes : allClassIds;
  const lutLibrary = useQuery({
    queryKey: qk.lut.library(),
    queryFn: ({ signal }) => lutApi.library(signal),
  });
  const by = (key: StageState['key']): StageState =>
    p.stages.find((s) => s.key === key) as StageState;

  return (
    <Box component="aside" aria-label={t('Inspector')} sx={{ overflowY: 'auto', height: '100%' }}>
      <InspectorStage stage={by('source')} onFix={p.onFix}>
        {/* ★ WHILE A RUN IS ON, THE RUN HOLDS THE SOURCE — the page's own preview
            reader is released to it, so the preview's counters would all read
            "not measurable". The run measures the same stream from the inside:
            its detect rate, the frame size, how many frames it saw and how many
            the camera produced that it never got to, and where it computes. */}
        {p.running && p.run !== null ? (
          <>
            {/* ★ TWO RATES, BOTH TRUE: "now" is the loop's moving average (it
                can read above the camera for a few seconds while frames arrive
                in bursts); "run average" is frames over the clock, which cannot. */}
            <StatReadout
              label={t('Rate now')}
              value={p.run.fps > 0 ? p.run.fps.toFixed(1) : null}
              unit="fps"
            />
            <StatReadout
              label={t('Rate, run average')}
              value={runAverageFps(p.run.frames_done, p.run.started_at, Date.now())?.toFixed(1)}
              unit="fps"
            />
            <StatReadout
              label={t('Phase')}
              value={p.run.phase === 'tracker' ? t('tracker') : t('detector')}
            />
            <StatReadout
              label={t('Resolution')}
              value={
                p.run.media_width > 0 && p.run.media_height > 0
                  ? `${p.run.media_width}×${p.run.media_height}`
                  : null
              }
            />
            <StatReadout
              label={t('Frames detected')}
              value={p.run.frames_done > 0 ? String(p.run.frames_done) : null}
            />
            <StatReadout
              label={t('Frames skipped')}
              value={p.run.frames_done > 0 ? String(p.run.frames_dropped) : null}
            />
            <StatReadout label={t('Device')} value={p.run.device_name || null} />
          </>
        ) : (
          <>
            <StatReadout
              label={t('FPS')}
              value={!p.fpsMeasurable ? t('not measurable') : p.stats.fps?.toFixed(1)}
            />
            <StatReadout
              label={t('Encoding')}
              value={p.stats.encoding ?? (p.fpsMeasurable ? null : 'unknown')}
            />
            <StatReadout
              label={t('Resolution')}
              value={p.stats.width && p.stats.height ? `${p.stats.width}×${p.stats.height}` : null}
            />
            <StatReadout
              label={t('Frames received')}
              value={p.stats.frames > 0 ? String(p.stats.frames) : null}
            />
          </>
        )}
      </InspectorStage>

      <InspectorStage stage={by('detector')} onFix={p.onFix}>
        <Stack spacing={1.5}>
          <FormControl size="small" fullWidth>
            <InputLabel id="insp-model">{t('Model')}</InputLabel>
            <Select
              labelId="insp-model"
              label={t('Model')}
              value={p.draft.model || (models[0] ?? '')}
              onChange={(e) => p.onChange({ model: String(e.target.value) })}
              disabled={p.running || models.length === 0}
            >
              {models.map((m) => (
                <MenuItem key={m} value={m}>
                  {m}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" fullWidth>
            <InputLabel id="insp-classes">{t('Detect')}</InputLabel>
            <Select
              labelId="insp-classes"
              label={t('Detect')}
              multiple
              value={shownClasses}
              onChange={(e) => {
                const next = (e.target.value as number[]).slice();
                p.onChange({
                  classes: next.length === 0 || next.length === classes.length ? [] : next,
                });
              }}
              renderValue={(v) =>
                (v as number[]).length === classes.length
                  ? t('All classes')
                  : classes
                      .filter((c) => (v as number[]).includes(c.id))
                      .map((c) => c.name)
                      .join(', ')
              }
              disabled={p.running || classes.length === 0}
            >
              {classes.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  <Checkbox size="small" checked={shownClasses.includes(c.id)} />
                  <ListItemText primary={c.name} />
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Box>
            <Typography variant="caption" color="text.secondary">
              {t('Confidence floor')}{' '}
              <Typography variant="mono" component="span" sx={{ fontSize: 12 }}>
                {p.draft.conf.toFixed(2)}
              </Typography>
            </Typography>
            <Slider
              size="small"
              min={0.05}
              max={0.95}
              step={0.05}
              value={p.draft.conf}
              onChange={(_e, v) => p.onChange({ conf: v as number })}
              disabled={p.running}
              aria-label={t('Confidence floor')}
            />
          </Box>
          <FormControl size="small" fullWidth>
            <InputLabel id="insp-imgsz">{t('Detail')}</InputLabel>
            <Select
              labelId="insp-imgsz"
              label={t('Detail')}
              value={p.draft.imgsz}
              onChange={(e) => p.onChange({ imgsz: Number(e.target.value) })}
              disabled={p.running}
            >
              <MenuItem value={640}>{t('Full (640 px)')}</MenuItem>
              <MenuItem value={480}>{t('Balanced (480 px)')}</MenuItem>
              <MenuItem value={320}>{t('Fast (320 px)')}</MenuItem>
            </Select>
            <FormHelperText>
              {p.availability?.device === 'cpu' ? 'CPU — Balanced by default' : 'GPU'}
            </FormHelperText>
          </FormControl>
          {/* ★ Steady boxes (2026-09-03, owner ask): the raw per-frame output
              flickers — boxes blink at the confidence floor and jitter on still
              objects. On, the overlay debounces new objects (one extra frame),
              smooths matched boxes, and briefly holds a missed one so it does not
              blink. It stays a plain (yellow) detection — orange is reserved for
              the tracker. Off = every frame exactly as YOLO saw it. */}
          <FormControlLabel
            control={
              <Checkbox
                size="small"
                checked={p.draft.steadyBoxes}
                onChange={(e) => p.onChange({ steadyBoxes: e.target.checked })}
                disabled={p.running}
              />
            }
            label={
              <Typography variant="body2">
                {t('Steady boxes (smooth and debounce the overlay)')}
              </Typography>
            }
          />
          {/* ★ HOW OFTEN AN OBJECT BECOMES A MARK (2026-09-11, owner: "the video
              is slow"). A run used to place one per detection per frame: a single
              tracked car at 25 fps put 605 points on the map in 24 seconds, and
              the browser — which is also drawing the video — stuttered under the
              weight of them. A ground fix does not change usefully that often.
              The choice is here because somebody may still want every frame. */}
          <FormControl size="small" fullWidth>
            <InputLabel id="det-mark-rate">{t('Marks per object')}</InputLabel>
            <Select
              labelId="det-mark-rate"
              label={t('Marks per object')}
              value={p.draft.markRateHz}
              onChange={(e) => p.onChange({ markRateHz: Number(e.target.value) })}
              disabled={p.running}
            >
              <MenuItem value={1}>{t('1 per second')}</MenuItem>
              <MenuItem value={2}>{t('2 per second')}</MenuItem>
              <MenuItem value={5}>{t('5 per second')}</MenuItem>
              <MenuItem value={0}>{t('Every frame')}</MenuItem>
            </Select>
            <FormHelperText>
              {t('Every detection is still counted and recorded — this thins the map.')}
            </FormHelperText>
          </FormControl>
        </Stack>
      </InspectorStage>

      <InspectorStage stage={by('placement')} onFix={p.onFix}>
        <FormControl size="small" fullWidth>
          <InputLabel id="insp-lut">{t('Lookup table')}</InputLabel>
          <Select
            labelId="insp-lut"
            label={t('Lookup table')}
            value={p.draft.lutSite}
            onChange={(e) => p.onChange({ lutSite: String(e.target.value) })}
            disabled={p.running}
          >
            <MenuItem value="">
              <em>{t('None')}</em>
            </MenuItem>
            {(lutLibrary.data ?? []).map((entry) => (
              <MenuItem key={entry.site_name} value={entry.site_name}>
                {entry.site_name}
                {entry.validation_passed === false && ' (validation failed)'}
                {entry.imported && ` (${t('imported')})`}
              </MenuItem>
            ))}
          </Select>
          <FormHelperText>
            {p.draft.lutSite === '' ? t('no marks on the map') : t('must match this camera')}
          </FormHelperText>
        </FormControl>
        {/* ★ OPT-IN, OFF BY DEFAULT (1.3). The mark is read from the box's bottom
            edge — the object's NEAR edge — so a long vehicle sits a few metres
            toward the camera. Ticking this pushes each mark to the object's centre
            by half its class's typical length, and every mark records the metres
            applied. It stays a choice because it assumes a length. */}
        <FormControlLabel
          sx={{ mt: 0.5 }}
          control={
            <Checkbox
              size="small"
              checked={p.draft.centreMarks}
              onChange={(e) => p.onChange({ centreMarks: e.target.checked })}
              disabled={p.running || p.draft.lutSite === ''}
            />
          }
          label={
            <Typography variant="body2">
              {t('Centre marks on the object (adds half a vehicle length away from the camera)')}
            </Typography>
          }
        />
      </InspectorStage>

      <InspectorStage stage={by('tracking')} onFix={p.onFix}>
        {/* ★ MANUAL TRACKING (2026-09-03), ARMED WITH THE RUN (2026-09-08). The
            tracker runs alongside detection from the first frame and follows
            nothing until the operator clicks a detected object (double-click
            locks one as the primary). This stage only picks WHICH tracker. */}
        <FormControl size="small" fullWidth>
          <InputLabel id="insp-tracker">{t('Tracker')}</InputLabel>
          <Select
            labelId="insp-tracker"
            label={t('Tracker')}
            value={p.draft.trackerType}
            onChange={(e) => p.onChange({ trackerType: String(e.target.value) })}
            disabled={p.running || p.availability?.tracker.available === false}
          >
            {TRACKERS.map((tr) => (
              <MenuItem key={tr.id} value={tr.id}>
                {t(tr.label)}
              </MenuItem>
            ))}
          </Select>
          {p.availability?.tracker.available === false ? (
            <FormHelperText>{p.availability.tracker.reason}</FormHelperText>
          ) : (
            <FormHelperText>
              {t('Runs with detection. Click a detected object to follow it; double-click to lock it.')}
            </FormHelperText>
          )}
        </FormControl>
      </InspectorStage>

      <InspectorStage stage={by('drift')} onFix={p.onFix}>
        {/* ★ READ-ONLY (2026-09-08, owner decision). The reference was frozen on
            the frame the control points sit on, in the camera settings, and the
            server watches it in the background. Re-freezing means choosing a new
            frame there — so this stage only says what the watch sees. */}
        <Stack spacing={0.75}>
          {p.drift.verdict !== null ? (
            <>
              <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                <DriftPill
                  state={p.drift.verdict.state}
                  confirmed={p.drift.verdict.status === p.drift.verdict.state}
                />
                {p.drift.verdict.status !== null &&
                  p.drift.verdict.status !== p.drift.verdict.state && (
                    <Typography variant="caption" color="text.secondary" noWrap>
                      {t('confirmed:')} {t(DRIFT_LABEL[p.drift.verdict.status])}
                    </Typography>
                  )}
                {p.drift.verdict.rot_deg !== null && (
                  <Typography variant="caption" className="le-mono" color="text.secondary">
                    {p.drift.verdict.rot_deg.toFixed(3)}°
                  </Typography>
                )}
              </Stack>
              {/* ★ THE SHIFT ON THE GROUND, in metres (2026-09-09, owner ask): what the
                  measured rotation moves a point by, at the far end of the scene. */}
              {p.drift.verdict.ground_err_at_ref !== null && (
                <Typography variant="body2" data-testid="drift-ground-shift">
                  {t('Shift on the ground')}: <b>±{p.drift.verdict.ground_err_at_ref.toFixed(2)} m</b>
                  {p.drift.refRangeM !== null && ` ${t('at')} ${p.drift.refRangeM.toFixed(0)} m`}
                </Typography>
              )}
              {p.drift.verdict.angles && (
                <Typography variant="caption" className="le-mono" color="text.secondary">
                  {t('pan')} {p.drift.verdict.angles.pan_deg.toFixed(2)}° · {t('tilt')}{' '}
                  {p.drift.verdict.angles.tilt_deg.toFixed(2)}° · {t('roll')}{' '}
                  {p.drift.verdict.angles.roll_deg.toFixed(2)}°
                </Typography>
              )}
              {/* the server's own sentence, verbatim — an honesty instrument */}
              <Typography variant="caption" color="text.secondary">
                {p.drift.verdict.why}
              </Typography>
            </>
          ) : (
            <Typography variant="caption" color="text.secondary">
              {!p.drift.frozen
                ? t(
                    'The drift reference is made in the camera settings: capture the frame, place its control points and build the lookup table — the watch starts on that frame.',
                  )
                : p.drift.watching
                  ? t('Watching live from the frozen frame — the first look has not run yet.')
                  : t('The reference is frozen but its watch is not running.')}
            </Typography>
          )}
          {p.drift.frozen && p.drift.frozenFromLabel !== null && (
            <Typography variant="caption" color="text.secondary">
              {t('frozen on the photograph')} {p.drift.frozenFromLabel}
            </Typography>
          )}
          {p.drift.lastError !== null && (
            <Typography variant="caption" sx={{ color: 'var(--status-warn)' }}>
              {p.drift.lastError}
            </Typography>
          )}
          {/* ★ Only while the watch is healthy: an unsatisfied stage already
              carries its own "Open the camera settings" fix above — two doors
              to one room read as a mistake. */}
          {p.drift.frozen && p.drift.watching && (
            <Box>
              <Button size="small" component={RouterLink} to={p.drift.settingsTo}>
                {t('Re-freeze from a new frame in the camera settings')} →
              </Button>
            </Box>
          )}
        </Stack>
      </InspectorStage>
    </Box>
  );
}
