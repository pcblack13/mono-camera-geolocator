/**
 * `annotation/AnnotationInspector.tsx` — the middle region's contextual editor.
 * 50-frontend.md §2.12 / SCOPE.md §5.
 *
 * Two faces, mutually exclusive:
 *
 *  1. **The open-correspondence editor** (SCOPE.md §5, MANUAL GCP MODE). Whenever a
 *     correspondence is open this takes over the panel: it shows what endpoint is
 *     still needed, hosts the **surveyor-declared confidence** picker (a 1–5
 *     judgement, NEVER a computed number), the note, and the commit/cancel actions.
 *     Commit projects `correspondenceStore`'s committable state onto `useCreateGcp`
 *     (a new pairing) or `useAdjustGcp` (re-committing an edited one), following the
 *     store's prescribed protocol: `beginCommit → mutate → commitSucceeded/Failed`.
 *
 *  2. **The selection editor.** Every landmark field the client mandated is editable
 *     here — label, kind, marker certainty, and, for a point, its ORIGINAL-pixel X/Y
 *     (typed edits emit `move_annotation`, because a surveyor may key in a pixel from
 *     another tool). Each edit is an undoable command (§4); nothing mutates state
 *     directly.
 *
 * ★ There is no GCP confidence declaration in the commit flow — a fixed value is stored
 *   for the API only (`correspondenceStore`). The annotation's own 0–1 marker certainty is
 *   a separate thing and is unaffected.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import FormControl from '@mui/material/FormControl';
import IconButton from '@mui/material/IconButton';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import Select from '@mui/material/Select';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import AddLocationAltIcon from '@mui/icons-material/AddLocationAlt';

import type { AnnotationKind, AnnotationRead } from '../../types/annotation';
import { ApiError, type Uuid } from '../../types/common';
import type { GcpCreate } from '../../api/gcps';
import {
  createDeleteAnnotation,
  createMoveAnnotation,
  createSetConfidence,
  createSetKind,
  createSetLabel,
} from '../../lib/commands';
import { useAnnotationStore } from '../../store/annotationStore';
import { useCorrespondenceStore } from '../../store/correspondenceStore';
import { useSelectionStore } from '../../store/selectionStore';
import { useWorkspaceStore } from '../../store';
import { useColorMode } from '../../theme';
import { CONFIDENCE_COLORS, MANUAL_SOURCE_COLOR, NO_RESULT_COLOR } from '../../theme/confidence';
import { PointColorField } from './PointColorField';
import { useMapStore } from '../../store/mapStore';
import { useCreateGcp, useGcp, useGcps } from '../../api/hooks/useGcps';
import { linkedGcpId } from '../../lib/gcpLink';
import { useAdjustGcp } from '../../api/hooks/useAdjustGcp';
import {
  useEstimateFromPixel,
  useImageCamera,
  useProjectFromLatLon,
} from '../../api/hooks/useImageCamera';
import { AUTO_GCP_REQUIRED } from '../gcp/AutoGcpControl';
import { useNotify } from '../common/Notifications';
import { t } from '../../i18n';

export interface AnnotationInspectorProps {
  imageId: Uuid;
}

/** The kinds worth offering a GCP surveyor — the GCP-candidate landmarks plus escapes. */
const KIND_OPTIONS: { value: AnnotationKind; label: string }[] = [
  { value: 'generic', label: 'Generic' },
  { value: 'field_corner', label: 'Field corner' },
  { value: 'road_intersection', label: 'Road intersection' },
  { value: 'building_corner', label: 'Building corner' },
  { value: 'irrigation_canal', label: 'Irrigation canal' },
  { value: 'tree', label: 'Tree' },
  { value: 'water_body', label: 'Water body' },
  { value: 'other', label: 'Other' },
];

/**
 * ★ AUTOMATIC GCP NAMES (1.2.6) — `GCP-01`, `GCP-02`, … so committing a point needs
 *   no typing at all. Survey points are numbered, not christened; making the surveyor
 *   invent a name per point (or leave the column blank) was friction with no payoff.
 *
 * ★ IT CONTINUES THE SEQUENCE, IT DOES NOT COUNT THE ROWS. `count + 1` would collide
 *   the moment a point is deleted — delete GCP-03 of five and the next commit proposes
 *   GCP-05, which already exists. Reading the HIGHEST number actually present is the
 *   only rule that cannot produce a duplicate.
 *
 * ★ Names that do not match the pattern are ignored, not renumbered: a surveyor who
 *   typed "Field corner NE" or imported "pt-95" keeps it, and the automatic sequence
 *   simply runs alongside.
 */
const AUTO_NAME_RE = /^GCP-(\d+)$/i;

export function nextAutoGcpName(existing: readonly { name?: string | null }[]): string {
  let highest = 0;
  for (const g of existing) {
    const match = AUTO_NAME_RE.exec((g.name ?? '').trim());
    if (match) highest = Math.max(highest, Number.parseInt(match[1], 10));
  }
  // Two digits keeps the table's Name column aligned for the first 99 points and
  // simply grows past it — never truncated, never renumbered.
  return `GCP-${String(highest + 1).padStart(2, '0')}`;
}

function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError({
    code: 'INTERNAL_ERROR',
    message: e instanceof Error ? e.message : 'The correspondence could not be committed.',
    status: 500,
    details: null,
    request_id: '',
    timestamp: new Date().toISOString() as never,
    docs_url: null,
  });
}

export function AnnotationInspector({ imageId }: AnnotationInspectorProps): JSX.Element {
  const isCorrespondenceOpen = useCorrespondenceStore((s) => s.status !== 'idle');

  return (
    <Box sx={{ height: '100%', overflowY: 'auto', p: 1.5 }}>
      {isCorrespondenceOpen ? (
        <CorrespondencePanel imageId={imageId} />
      ) : (
        <SelectionPanel imageId={imageId} />
      )}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. The open-correspondence editor — MANUAL GCP MODE (SCOPE.md §5)
// ─────────────────────────────────────────────────────────────────────────────

function CorrespondencePanel({ imageId }: { imageId: Uuid }): JSX.Element {
  const mode = useCorrespondenceStore((s) => s.mode);
  const status = useCorrespondenceStore((s) => s.status);
  const imagePx = useCorrespondenceStore((s) => s.image_px);
  const latLon = useCorrespondenceStore((s) => s.lat_lon);
  const declared = useCorrespondenceStore((s) => s.declared_confidence);
  const note = useCorrespondenceStore((s) => s.note);
  const gcpName = useCorrespondenceStore((s) => s.gcp_name);
  const landmarkClientId = useCorrespondenceStore((s) => s.landmark_client_id);
  const editingGcpId = useCorrespondenceStore((s) => s.editing_gcp_id);
  const error = useCorrespondenceStore((s) => s.error);
  const setNote = useCorrespondenceStore((s) => s.setNote);
  const beginCommit = useCorrespondenceStore((s) => s.beginCommit);
  const commitSucceeded = useCorrespondenceStore((s) => s.commitSucceeded);
  const commitFailed = useCorrespondenceStore((s) => s.commitFailed);
  const cancel = useCorrespondenceStore((s) => s.cancel);
  const isCommittable = useCorrespondenceStore((s) => s.status === 'ready');
  // ★ Call `awaiting()` INSIDE the selector so Zustand subscribes to the derived
  //   value — selecting the method reference would never re-render on a status change.
  const awaiting = useCorrespondenceStore((s) => s.awaiting());

  const serverIdOf = useAnnotationStore((s) => s.serverIdOf);
  const mapZoom = useMapStore((s) => s.view.zoom);
  const flyToGcp = useMapStore((s) => s.flyToGcp);
  const providerId = useMapStore((s) => s.providerId);

  const createGcp = useCreateGcp(imageId);
  const adjustGcp = useAdjustGcp(imageId);
  // ★ Reading the GCP registers its ETag (client.ts), which `useAdjustGcp` needs to avoid a
  //   428 on the edit-mode commit. Only while editing.
  useGcp(mode === 'edit' ? editingGcpId : null);
  const committing = status === 'committing';

  // ★ The GCP's name — the table's "Name" column. Pre-filled from the existing name
  //   when editing, and from the automatic sequence when creating (see below).
  const [name, setName] = useState(gcpName ?? '');
  /** The surveyor opened the name for editing — the field replaces the readout. */
  const [nameEditing, setNameEditing] = useState(false);
  /**
   * ★ They TYPED a name. Once true the automatic sequence stops proposing, for the
   *   rest of this correspondence: a chosen name must never be silently replaced
   *   because the GCP list refetched a moment later.
   */
  const [nameChosen, setNameChosen] = useState(false);

  // ── AUTO GCP MODE ──────────────────────────────────────────────────────────
  // ★ When the tool is on and four points exist, the MAP CLICK IS REPLACED by the
  //   solver: the photo click is estimated into a lat/lon and the pair completes
  //   itself. The estimate is an INFERENCE — it lands as the usual draggable draft
  //   for the surveyor to review, refine and commit; it is never auto-committed.
  //   A failed estimate falls back to the manual map click, stated in the banner.
  const setMapPoint = useCorrespondenceStore((s) => s.setMapPoint);
  const setPhotoPoint = useCorrespondenceStore((s) => s.setPhotoPoint);
  const correspondenceId = useCorrespondenceStore((s) => s.correspondence_id);
  const camera = useImageCamera(imageId).data;
  const gcpsPage = useGcps(imageId).data;
  const gcpTotal = gcpsPage?.total ?? 0;

  // ★ The proposed name, recomputed as the list loads. In EDIT mode there is nothing
  //   to propose — the GCP already has a name, and renaming it is the surveyor's call.
  const autoName = useMemo(
    () => (mode === 'create' ? nextAutoGcpName(gcpsPage?.items ?? []) : null),
    [gcpsPage, mode],
  );
  useEffect(() => {
    if (autoName === null || nameChosen) return;
    setName(autoName);
  }, [autoName, nameChosen]);
  const estimate = useEstimateFromPixel();
  const project = useProjectFromLatLon();
  const notify = useNotify();
  const autoReady = camera?.auto_gcp_enabled === true && gcpTotal >= AUTO_GCP_REQUIRED;
  // Guarded per (correspondence, pixel): a drag re-place re-estimates, a re-render
  // does not, and a new correspondence starts fresh.
  const estimatedFor = useRef<string | null>(null);
  // Guarded per (correspondence, lat/lon) — the map→photo direction's twin guard.
  // ★ Each direction PRE-REGISTERS the other's key when it programmatically moves the
  //   other endpoint, so the two effects can never chase each other in a loop.
  const projectedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!autoReady || (mode !== 'create' && mode !== 'edit')) return;
    // ★ RE-ESTIMATE ON EVERY PHOTO-PIXEL CHANGE (1.2.6). The estimate must re-run not
    //   only on the first placement (awaiting_map_point) but on every later DRAG of the
    //   photo mark — the surveyor edits the image mark before committing and expects the
    //   predicted map point to follow (SCOPE.md §5: "either endpoint can be dragged").
    //   Keying on (correspondence, pixel) means a re-render never re-fires, and a manual
    //   drag of the MAP marker — which leaves image_px untouched — is preserved as the
    //   surveyor's override until they move the photo mark again.
    if (imagePx === null || status === 'committing') return;
    const key = `${correspondenceId}:${imagePx.x},${imagePx.y}`;
    if (estimatedFor.current === key) return;
    // ★ EDIT MODE OPENS PRE-FILLED (1.2.6): the STORED photo pixel must not fire an
    //   estimate that silently overwrites the STORED map point the surveyor came to
    //   inspect. Seed the guard with the opening pixel; only a later DRAG estimates.
    if (mode === 'edit' && !(estimatedFor.current ?? '').startsWith(`${correspondenceId}:`)) {
      estimatedFor.current = key;
      return;
    }
    // A "refine" is any estimate after the first for THIS correspondence: quieter, and it
    // must NOT fly the map away while the surveyor is nudging the photo mark. Every
    // edit-mode estimate is a refine by construction (the seed above came first).
    const isRefine =
      estimatedFor.current !== null && estimatedFor.current.startsWith(`${correspondenceId}:`);
    estimatedFor.current = key;
    estimate.mutate(
      { imageId, body: { u: imagePx.x, v: imagePx.y } },
      {
        onSuccess: (r) => {
          // ★ Pre-register the projection guard BEFORE moving the map point, so the
          //   map→photo effect recognises this move as ours and stays quiet.
          projectedFor.current = `${correspondenceId}:${r.lat},${r.lon}`;
          setMapPoint({ lat: r.lat, lon: r.lon });
          if (!isRefine) {
            // ★ FLY TO THE ESTIMATE, first time only — for two load-bearing reasons. The
            //   surveyor must SEE where the solver put the point before committing it; and
            //   the committed accuracy derives from the MAP ZOOM (imagery GSD), which in
            //   auto mode was whatever stale wide view the untouched map still held — a
            //   world-zoom commit recorded ±tens of kilometres. Revealing at close zoom
            //   makes the stored accuracy describe imagery actually inspected. On a refine
            //   drag the map stays put so it never yanks mid-adjustment.
            flyToGcp({ lat: r.lat, lon: r.lon });
            notify(
              `Estimated from ${r.gcps_used} points at ${r.distance_m.toFixed(0)} m range ` +
                `(reproj ${r.reproj_mean_px.toFixed(1)} px). Review the marker — drag the photo or map mark to refine — then commit.`,
              { severity: 'success' },
            );
            // ★ Pose diagnostics are NOT toasted (1.2.6) — see `useImageCamera`.
            //   They stay in the response and go to the console; the surveyor gets
            //   the estimate, not a lecture about it on every click.
          }
        },
        onError: (e) =>
          notify(toApiError(e).message || 'Estimation failed — click the map to place the point.', {
            severity: 'error',
          }),
      },
    );
  }, [
    autoReady,
    correspondenceId,
    estimate,
    flyToGcp,
    imageId,
    imagePx,
    mode,
    notify,
    setMapPoint,
    status,
  ]);

  // ── MAP → PHOTO, EDIT MODE ONLY (1.2.6) ────────────────────────────────────
  // ★ The OTHER direction of the same solve: dragging the MAP marker of an edited
  //   GCP re-projects the new coordinate through the solved pose and moves the photo
  //   mark to match — the two panels stay in lock-step in Auto mode. CREATE mode is
  //   deliberately untouched: there the photo pixel is the surveyor's direct
  //   observation and a map drag is their manual override of the estimate.
  useEffect(() => {
    if (!autoReady || mode !== 'edit') return;
    if (latLon === null || status === 'committing') return;
    const key = `${correspondenceId}:${latLon.lat},${latLon.lon}`;
    if (projectedFor.current === key) return;
    // Seed on reopen: the STORED map point must not immediately re-project and move
    // the STORED photo mark the surveyor came to inspect. Only a later drag projects.
    if (!(projectedFor.current ?? '').startsWith(`${correspondenceId}:`)) {
      projectedFor.current = key;
      return;
    }
    projectedFor.current = key;
    if (landmarkClientId !== null) {
      // ★ A landmark-backed GCP's photo mark IS the landmark — moving a mark the
      //   commit cannot persist would be a lie that reverts on save. Say so instead.
      notify(
        "This GCP's photo mark comes from its landmark, so the map move does not move it — drag the landmark on the photograph instead.",
        { severity: 'info' },
      );
      return;
    }
    project.mutate(
      { imageId, body: { lat: latLon.lat, lon: latLon.lon } },
      {
        onSuccess: (r) => {
          // Outside the frame (server-judged when img_w/img_h are on record; a
          // negative pixel is outside regardless) → warn, and DON'T move the mark.
          if (r.inside_image === false || r.u < 0 || r.v < 0) {
            notify(
              `That map position projects outside the photograph (${r.u.toFixed(0)}, ${r.v.toFixed(0)}) — the photo mark was left unchanged.`,
              { severity: 'warning' },
            );
            return;
          }
          // ★ Pre-register the estimate guard BEFORE moving the photo mark, so the
          //   photo→map effect recognises this move as ours and does not bounce back.
          estimatedFor.current = `${correspondenceId}:${r.u},${r.v}`;
          setPhotoPoint({ x: r.u, y: r.v });
        },
        onError: (e) =>
          notify(
            toApiError(e).message ||
              'Could not project the map point into the photograph — the photo mark was left unchanged.',
            { severity: 'warning' },
          ),
      },
    );
  }, [
    autoReady,
    correspondenceId,
    imageId,
    landmarkClientId,
    latLon,
    mode,
    notify,
    project,
    setPhotoPoint,
    status,
  ]);

  const onCommit = (): void => {
    if (!isCommittable || imagePx === null || latLon === null || declared === null) return;
    beginCommit();

    if (mode === 'edit' && editingGcpId) {
      adjustGcp.mutate(
        {
          gcpId: editingGcpId,
          body: {
            lat: latLon.lat,
            lon: latLon.lon,
            // ★ The PHOTO endpoint travels too (1.2.6) — for a BARE GCP, whose pixel
            //   lives on the gcps row. A landmark-backed GCP's photo mark is the
            //   annotation's; sending it here would be refused, so it is omitted
            //   (move the landmark on the photograph instead).
            ...(landmarkClientId === null && imagePx !== null ? { image_px: imagePx } : {}),
            declared_confidence: declared,
            adjustment_note: note,
            name: name.trim() || null,
          },
        },
        {
          onSuccess: (g) => {
            // ★ SAY WHAT HAPPENED, with the server's own row: the coordinate the DB
            //   now holds. The marker and the table refetch to the same values —
            //   "did my adjustment actually save?" gets an explicit answer.
            notify(
              `GCP moved to ${g.lat.toFixed(6)}, ${g.lon.toFixed(6)} — saved to the ` +
                'database; map and table updated.',
              { severity: 'success' },
            );
            commitSucceeded(g.id);
          },
          onError: (e) => commitFailed(toApiError(e)),
        },
      );
      return;
    }

    const landmarkId = landmarkClientId ? serverIdOf(landmarkClientId) : null;
    const body: GcpCreate = {
      lat: latLon.lat,
      lon: latLon.lon,
      declared_confidence: declared,
      provider: providerId,
      // ★ ROUNDED: the server takes an integer zoom, but the live view zoom is
      //   fractional whenever the 3D pane (or a pinch) set it — sending 20.7 made
      //   every commit a 422 "Request validation failed".
      map_zoom: Math.round(mapZoom),
      ...(name.trim() ? { name: name.trim() } : {}),
      ...(note ? { note } : {}),
      // ★ EXACTLY ONE of landmark_id / image_px — the server 422s on both.
      ...(landmarkId !== null ? { landmark_id: landmarkId } : { image_px: imagePx }),
    };
    createGcp.mutate(body, {
      onSuccess: (g) => commitSucceeded(g.id),
      onError: (e) => commitFailed(toApiError(e)),
    });
  };

  // ★ F1 COMMITS (1.2.6). A GCP run is two clicks and a commit, over and over —
  //   reaching for the button every time is the slow part. `onCommit` already refuses
  //   unless the pairing is committable, so the key needs no guard of its own beyond
  //   being inside an open correspondence.
  //
  //   The handler is held in a ref so the listener binds ONCE: `onCommit` is rebuilt
  //   every render, and re-registering per render would be churn for no gain.
  //   `preventDefault` stops the browser's own help panel from stealing the key.
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== 'F1') return;
      e.preventDefault();
      commitRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const stepText: Record<string, string> = {
    photo: 'Click the landmark in the photo.',
    map: !autoReady
      ? 'Now click the same physical spot on the satellite map →'
      : estimate.isPending
        ? 'Auto GCP: estimating the position from your located points…'
        : estimate.isError
          ? 'Estimation failed — click the same physical spot on the satellite map →'
          : 'Auto GCP: the position will be estimated for you.',
    confidence: 'Both points set. Declare how sure you are, then commit.',
  };

  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <AddLocationAltIcon color="primary" fontSize="small" />
        <Typography variant="subtitle2">
          {mode === 'edit' ? 'Adjust GCP' : 'New ground control point'}
        </Typography>
      </Stack>

      <Alert severity={awaiting ? 'info' : 'success'} variant="outlined" sx={{ py: 0.5 }}>
        {awaiting ? stepText[awaiting] : 'Ready to commit.'}
      </Alert>

      {/* The direct-observation endpoints, shown honestly as set / not-set. */}
      <Stack spacing={0.5}>
        <EndpointRow
          label={t('Photo pixel')}
          value={imagePx ? `${imagePx.x.toFixed(1)}, ${imagePx.y.toFixed(1)}` : '—'}
        />
        <EndpointRow
          label={t('Map (WGS84)')}
          value={latLon ? `${latLon.lat.toFixed(6)}, ${latLon.lon.toFixed(6)}` : '—'}
        />
      </Stack>

      <Divider />

      {/* ★ THE NAME IS AUTOMATIC, AND OVERRIDABLE (1.2.6). It shows as a readout with
          a pencil rather than an empty box: the common case (accept GCP-07 and
          commit) costs no interaction, and the uncommon one is one click away. Shown
          for a bare point; a landmark-linked GCP carries the landmark's name. */}
      {landmarkClientId === null &&
        (nameEditing ? (
          <TextField
            label={t('Name')}
            size="small"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setNameChosen(true);
            }}
            onBlur={() => setNameEditing(false)}
            disabled={committing}
            autoFocus
            placeholder={autoName ?? 'e.g. Field corner NE'}
            helperText="Leave it as it is to keep the automatic number."
          />
        ) : (
          <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="caption" color="text.secondary" display="block">
                {t('Name')}
              </Typography>
              <Typography variant="body2" noWrap title={name || autoName || ''}>
                {name || autoName || '—'}
              </Typography>
            </Box>
            <Tooltip title={t("Edit this point's name")}>
              <span>
                <IconButton
                  size="small"
                  aria-label={t('Edit the name')}
                  onClick={() => setNameEditing(true)}
                  disabled={committing}
                >
                  <EditOutlinedIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
          </Stack>
        ))}

      <TextField
        label={t('Note (optional)')}
        size="small"
        multiline
        minRows={2}
        value={note ?? ''}
        onChange={(e) => setNote(e.target.value || null)}
        disabled={committing}
      />

      {error && (
        <Alert severity="error" variant="outlined" sx={{ py: 0.5 }}>
          {error.message}
          {/* ★ NAME THE FIELD. A bare "Request validation failed" hides which of the
              nine body fields the server refused — the details carry `loc` + `msg`,
              and showing them turns a dead end into a fixable form. */}
          {error.body.details?.slice(0, 3).map((d) => (
            <Typography key={d.loc.join('.')} variant="caption" display="block">
              {d.loc.filter((part) => part !== 'body').join('.')}: {d.msg}
            </Typography>
          ))}
        </Alert>
      )}

      <Stack spacing={0.5}>
        <Stack direction="row" spacing={1}>
          <Button
            variant="contained"
            fullWidth
            disabled={!isCommittable || committing}
            onClick={onCommit}
          >
            {committing ? 'Committing…' : mode === 'edit' ? 'Save adjustment' : 'Commit GCP'}
          </Button>
          <Button variant="text" color="inherit" onClick={cancel} disabled={committing}>
            {t('Cancel')}
          </Button>
        </Stack>
        {/* ★ The shortcut is stated where the action is — a key nobody is told about
            is a key nobody uses. */}
        <Typography variant="caption" color="text.secondary">
          Press <strong>F1</strong> {t('to commit without reaching for the button.')}
        </Typography>
      </Stack>
    </Stack>
  );
}

function EndpointRow({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <Stack direction="row" justifyContent="space-between" alignItems="center">
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="mono" sx={{ fontSize: 12 }}>
        {value}
      </Typography>
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. The selection editor
// ─────────────────────────────────────────────────────────────────────────────

function SelectionPanel({ imageId }: { imageId: Uuid }): JSX.Element {
  const selected = useSelectionStore((s) => s.selected);
  const annotations = useAnnotationStore((s) => s.draft.annotations);
  const execute = useAnnotationStore((s) => s.execute);
  const openCorrespondence = useCorrespondenceStore((s) => s.open);

  const selectedAnnotations = useMemo(
    () =>
      selected
        .filter((r) => r.kind === 'annotation')
        .map((r) => annotations.find((a) => a.id === r.id))
        .filter((a): a is AnnotationRead => a != null && !a.is_deleted),
    [selected, annotations],
  );

  const startBareCorrespondence = (): void => openCorrespondence({ image_id: imageId });

  if (selectedAnnotations.length === 0) {
    return (
      <Stack spacing={2}>
        <Typography variant="subtitle2">{t('Landmarks')}</Typography>
        <Typography variant="body2" color="text.secondary">
          {t('Select the')} <strong>{t('Point')}</strong>{' '}
          {t(
            'tool and click a landmark in the photo, then link it to the satellite map to record a ground control point.',
          )}
        </Typography>
        <Button
          variant="outlined"
          startIcon={<AddLocationAltIcon />}
          onClick={startBareCorrespondence}
        >
          {t('New GCP correspondence')}
        </Button>
      </Stack>
    );
  }

  if (selectedAnnotations.length > 1) {
    return (
      <Stack spacing={2}>
        <Typography variant="subtitle2">{selectedAnnotations.length} landmarks selected</Typography>
        <Button
          variant="outlined"
          color="error"
          startIcon={<DeleteOutlineIcon />}
          onClick={() => {
            // Delete from the end so captured indices stay valid as the array shrinks.
            const ordered = selectedAnnotations
              .map((a) => ({ a, i: annotations.indexOf(a) }))
              .sort((x, y) => y.i - x.i);
            for (const { a, i } of ordered) execute(createDeleteAnnotation(a, i));
          }}
        >
          Delete {selectedAnnotations.length} landmarks
        </Button>
      </Stack>
    );
  }

  return (
    // ★ key = the selected annotation's id, so React REMOUNTS the editor when the
    //   selection changes to a different point. Without it, the editor's local
    //   useState (label/px/py, seeded once on mount) shows the PREVIOUS point's name —
    //   the "old mark" the surveyor sees when placing a new landmark. Remounting gives
    //   each point its own fresh Name/Kind/pixel fields.
    <SingleAnnotationEditor
      key={selectedAnnotations[0]!.id}
      imageId={imageId}
      annotation={selectedAnnotations[0]!}
      index={annotations.indexOf(selectedAnnotations[0]!)}
    />
  );
}

function SingleAnnotationEditor({
  imageId,
  annotation,
  index,
}: {
  imageId: Uuid;
  annotation: AnnotationRead;
  index: number;
}): JSX.Element {
  const execute = useAnnotationStore((s) => s.execute);
  const openCorrespondence = useCorrespondenceStore((s) => s.open);

  // What this point is drawn in when it has no colour of its own — so the field can
  // open on the real colour rather than an arbitrary one, and name where it came from.
  const { mode: themeMode } = useColorMode();
  const photoMarkColor = useWorkspaceStore((s) => s.photoMarkColor);
  // ★ The wire carries `gcp_ids`; `gcp_id` is always null (lib/gcpLink).
  const linkedGcp = linkedGcpId(annotation);
  const linkedGcpQuery = useGcp(linkedGcp);
  const inheritedColor =
    photoMarkColor ??
    (linkedGcp !== null
      ? CONFIDENCE_COLORS.high[themeMode]
      : annotation.is_gcp_candidate
        ? MANUAL_SOURCE_COLOR[themeMode]
        : NO_RESULT_COLOR[themeMode]);
  const inheritedFrom =
    photoMarkColor !== null
      ? 'in the workspace colour for the photograph'
      : linkedGcp !== null
        ? 'by its accuracy band'
        : 'in the landmark default';

  const [label, setLabel] = useState(annotation.label ?? '');
  const [px, setPx] = useState(String(annotation.pixel_x));
  const [py, setPy] = useState(String(annotation.pixel_y));
  // ★ The point moves on the photograph too (a drag): the fields follow it, or a
  //   later blur would snap the point back to where the field last saw it.
  useEffect(() => {
    setPx(String(annotation.pixel_x));
    setPy(String(annotation.pixel_y));
  }, [annotation.id, annotation.pixel_x, annotation.pixel_y]);

  const isPoint = annotation.geom_type === 'point';

  const commitLabel = (): void => {
    const next = label.trim() === '' ? null : label.trim();
    if (next !== annotation.label) execute(createSetLabel(annotation.id, annotation.label, next));
  };

  const commitPixel = (): void => {
    // A blank field is "leave it", never "move to 0".
    if (px.trim() === '' || py.trim() === '') {
      setPx(String(annotation.pixel_x));
      setPy(String(annotation.pixel_y));
      return;
    }
    const x = Number(px);
    const y = Number(py);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    if (x === annotation.pixel_x && y === annotation.pixel_y) return;
    execute(
      createMoveAnnotation(
        annotation.id,
        { x: annotation.pixel_x, y: annotation.pixel_y },
        { x, y },
        annotation.geometry,
        { type: 'Point', coordinates: [x, y] },
      ),
    );
  };

  const reopenCorrespondence = useCorrespondenceStore((s) => s.reopen);

  const linkToMap = (): void =>
    openCorrespondence({
      image_id: imageId,
      landmark_client_id: annotation.id,
      image_px: { x: annotation.pixel_x, y: annotation.pixel_y },
    });

  return (
    <Stack spacing={2}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="subtitle2">{annotation.label ?? 'Landmark'}</Typography>
        <Chip size="small" label={annotation.geom_type} variant="outlined" />
      </Stack>

      <TextField
        label={t('Name')}
        size="small"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onBlur={commitLabel}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commitLabel();
        }}
      />

      <FormControl size="small">
        <InputLabel id={`kind-${annotation.id}`}>{t('Kind')}</InputLabel>
        <Select
          labelId={`kind-${annotation.id}`}
          label={t('Kind')}
          value={annotation.kind}
          onChange={(e) =>
            execute(createSetKind(annotation.id, annotation.kind, e.target.value as AnnotationKind))
          }
        >
          {KIND_OPTIONS.map((k) => (
            <MenuItem key={k.value} value={k.value}>
              {k.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* ★ This point's own colour — keyed by GCP id when it has one, so the colour
          follows it onto the map as well as the photograph. */}
      <PointColorField
        pointKey={linkedGcp ?? annotation.id}
        inheritedColor={inheritedColor}
        inheritedFrom={inheritedFrom}
      />

      {isPoint && (
        <Stack direction="row" spacing={1}>
          <TextField
            label={t('Pixel X')}
            size="small"
            value={px}
            onChange={(e) => setPx(e.target.value)}
            onBlur={commitPixel}
            inputProps={{
              inputMode: 'decimal',
              style: { fontFamily: 'JetBrains Mono, monospace' },
            }}
          />
          <TextField
            label={t('Pixel Y')}
            size="small"
            value={py}
            onChange={(e) => setPy(e.target.value)}
            onBlur={commitPixel}
            inputProps={{
              inputMode: 'decimal',
              style: { fontFamily: 'JetBrains Mono, monospace' },
            }}
          />
        </Stack>
      )}

      <Box>
        <Typography variant="caption" color="text.secondary">
          Marker certainty ({annotation.confidence.toFixed(2)})
        </Typography>
        <Slider
          size="small"
          min={0}
          max={1}
          step={0.05}
          value={annotation.confidence}
          onChange={(_e, v) =>
            execute(createSetConfidence(annotation.id, annotation.confidence, v as number))
          }
          aria-label={t('Marker certainty')}
        />
      </Box>

      <Divider />

      {linkedGcp !== null ? (
        // ★ A linked landmark RE-OPENS its control point (SCOPE.md §5) — it must never
        //   start a second correspondence for the same landmark.
        <Button
          variant="contained"
          startIcon={<AddLocationAltIcon />}
          disabled={linkedGcpQuery.data === undefined}
          onClick={() => {
            const gcp = linkedGcpQuery.data;
            if (!gcp) return;
            reopenCorrespondence({
              image_id: imageId,
              gcp_id: gcp.id,
              image_px: { x: annotation.pixel_x, y: annotation.pixel_y },
              lat_lon: { lat: gcp.lat, lon: gcp.lon },
              declared_confidence: gcp.declared_confidence,
              landmark_client_id: annotation.id,
              note: null,
              gcp_name: null,
            });
          }}
        >
          {t('Re-open GCP to adjust')}
        </Button>
      ) : (
        <Button variant="contained" startIcon={<AddLocationAltIcon />} onClick={linkToMap}>
          {t('Link to satellite map')}
        </Button>
      )}

      <Stack direction="row" spacing={1}>
        <Button
          variant="outlined"
          color="error"
          startIcon={<DeleteOutlineIcon />}
          onClick={() => execute(createDeleteAnnotation(annotation, index))}
        >
          {t('Delete')}
        </Button>
      </Stack>
    </Stack>
  );
}
