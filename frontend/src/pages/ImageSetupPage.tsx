/**
 * `pages/ImageSetupPage.tsx` — EVERY photograph gets its own setup, on one page.
 *
 * ★ TWO ROUTES, ONE PAGE. `/projects/:projectId/setup` is NEW-IMAGE mode: the page a
 *   fresh project lands on, and where "Add image" starts — upload the photograph,
 *   then enter ITS camera. `/projects/:projectId/images/:imageId/setup` is EDIT mode:
 *   the same page for a photograph that already exists (each image card links here).
 *   The camera (intrinsics, position, tilt) is saved PER IMAGE — different photos may
 *   come from different stations — while the DEM card stays project-wide: the terrain
 *   under the survey is one surface however many photos look at it.
 *
 * ★ THE FORM HOLDS STRINGS. Calibration numbers carry more digits than a float64
 *   round-trip through a formatter preserves on screen (`2799.7344` must not become
 *   `2799.73` — the desktop tool's 6-significant-digit import bug is the cautionary
 *   tale). What the surveyor typed is what is parsed on save, once.
 *
 * ★ IMPORT MATCHES THE FIELD TOOL. "Import calibration CSV" reads the teammate
 *   tool's two-column `key,value` format verbatim (see `lib/calibrationCsv.ts`).
 *
 * ★ NOTHING IS FABRICATED. Every field may stay empty; empty saves as null. The one
 *   convenience: after an upload, blank `img_w`/`img_h` fill from the photo and blank
 *   `cx`/`cy` fill with its centre — the desktop tool's behaviour, only into BLANKS.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Container from '@mui/material/Container';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CameraAltOutlinedIcon from '@mui/icons-material/CameraAltOutlined';
import PhotoLibraryOutlinedIcon from '@mui/icons-material/PhotoLibraryOutlined';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import CollectionsOutlinedIcon from '@mui/icons-material/CollectionsOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import HeightOutlinedIcon from '@mui/icons-material/HeightOutlined';
import PlaceOutlinedIcon from '@mui/icons-material/PlaceOutlined';
import TerrainOutlinedIcon from '@mui/icons-material/TerrainOutlined';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';

import { isUploadAccepted, type ImageUploadForm } from '../api/images';
import { useImageUpload } from '../api/hooks/useImageUpload';
import { useDeleteImage, useImage, useImages } from '../api/hooks/useImages';
import { useProject } from '../api/hooks/useProjects';
import { useImageCamera, useSaveImageCamera } from '../api/hooks/useImageCamera';
import { ImageDemCard } from '../components/image/ImageDemCard';
import { UploadDropzone } from '../components/upload/UploadDropzone';
import { EmptyState } from '../components/common/EmptyState';
import { ImportFromLibraryDialog } from '../components/image/ImportFromLibraryDialog';
import { useNotify } from '../components/common/Notifications';
import { parseCalibrationCsv } from '../lib/calibrationCsv';
import { useImageSetupDraftStore } from '../store/imageSetupDraftStore';
import { asUuid, type ApiError, type Uuid } from '../types/common';
import type { ImageRead, ImageSummary } from '../types/image';
import type { ImageCameraPut, ImageCameraRead } from '../types/imageCamera';
import { browseNativeOrInput, filtersFromAccept } from '../lib/nativeFilePicker';
import { t } from '../i18n';

const IMAGE_ACCEPT = 'image/jpeg,image/png,image/tiff,image/tif';

// ─────────────────────────────────────────────────────────────────────────────
// The photograph this page is about — one shape for both sources
// ─────────────────────────────────────────────────────────────────────────────

/** What the page needs to know about its photograph, however it arrived. */
interface SetupImage {
  id: Uuid;
  filename: string;
  width: number;
  height: number;
  gcp_count: number;
  annotation_count: number;
}

function fromSummary(image: ImageSummary): SetupImage {
  return {
    id: image.id,
    filename: image.filename,
    width: image.width,
    height: image.height,
    gcp_count: image.gcp_count,
    annotation_count: image.annotation_count,
  };
}

/** A fresh upload has no work on it yet — the zeros are true, not defaults. */
function fromUpload(image: ImageRead): SetupImage {
  return {
    id: image.id,
    filename: image.filename,
    width: image.width,
    height: image.height,
    gcp_count: 0,
    annotation_count: 0,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// The form — strings in, numbers out (parsed once, on save)
// ─────────────────────────────────────────────────────────────────────────────

const FIELD_KEYS = [
  'fx',
  'fy',
  'cx',
  'cy',
  'k1',
  'k2',
  'p1',
  'p2',
  'k3',
  'img_w',
  'img_h',
  'lat',
  'lon',
  'mast_offset_m',
  'tilt_deg',
] as const;

type FieldKey = (typeof FIELD_KEYS)[number];
type FormState = Record<FieldKey, string>;
type FormErrors = Partial<Record<FieldKey, string>>;

/** What the inputs render while a saved camera is still loading. */
const EMPTY_FORM: FormState = Object.fromEntries(FIELD_KEYS.map((k) => [k, ''])) as FormState;

/** Server row → editable strings. Null → '' (blank), full precision via String(). */
function toForm(camera: ImageCameraRead): FormState {
  const form = {} as FormState;
  for (const key of FIELD_KEYS) {
    const value = camera[key];
    form[key] = value === null || value === undefined ? '' : String(value);
  }
  return form;
}

/**
 * Swap-aware autofill for a REPLACED photo: a field still blank, or still holding the
 * OLD photo's auto-filled value (its dimensions / centre), follows the new photo; a
 * value the surveyor typed themselves is never overwritten — the caller warns instead.
 */
function followReplacedImage(
  prev: FormState,
  old: { width: number; height: number },
  next: { width: number; height: number },
): FormState {
  const out = { ...prev };
  const follow = (key: FieldKey, oldValue: string, newValue: string): void => {
    if (out[key].trim() === '' || out[key].trim() === oldValue) out[key] = newValue;
  };
  follow('img_w', String(old.width), String(next.width));
  follow('img_h', String(old.height), String(next.height));
  follow('cx', String(old.width / 2), String(next.width / 2));
  follow('cy', String(old.height / 2), String(next.height / 2));
  return out;
}

/**
 * Strings → the PUT body, or field errors. ★ Validation mirrors the server's
 * (`fx/fy > 0`, dims ≥ 1, lat/lon bounds, tilt ±90, lat+lon as a pair) so the 422s
 * it would send are caught here with the field named.
 */
function toBody(form: FormState): { body: ImageCameraPut; errors: FormErrors } {
  const errors: FormErrors = {};
  const parsed: Partial<Record<FieldKey, number | null>> = {};

  for (const key of FIELD_KEYS) {
    const raw = form[key].trim();
    if (raw === '') {
      parsed[key] = null;
      continue;
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      errors[key] = 'Not a number';
      continue;
    }
    parsed[key] = value;
  }

  const positive = (key: FieldKey, label: string): void => {
    const v = parsed[key];
    if (v !== null && v !== undefined && v <= 0) errors[key] = `${label} must be > 0`;
  };
  positive('fx', 'fx');
  positive('fy', 'fy');
  positive('img_w', 'Width');
  positive('img_h', 'Height');

  const bounded = (key: FieldKey, min: number, max: number): void => {
    const v = parsed[key];
    if (v !== null && v !== undefined && (v < min || v > max)) {
      errors[key] = `Must be between ${min} and ${max}`;
    }
  };
  bounded('lat', -90, 90);
  bounded('lon', -180, 180);
  bounded('tilt_deg', -90, 90);

  const intField = (key: FieldKey): void => {
    const v = parsed[key];
    if (v !== null && v !== undefined && !Number.isInteger(v)) {
      errors[key] = 'Must be a whole number of pixels';
    }
  };
  intField('img_w');
  intField('img_h');

  if ((parsed.lat === null) !== (parsed.lon === null)) {
    const missing: FieldKey = parsed.lat === null ? 'lat' : 'lon';
    errors[missing] = 'Latitude and longitude go together';
  }

  const body: ImageCameraPut = {};
  for (const key of FIELD_KEYS) body[key] = parsed[key] ?? null;
  return { body, errors };
}

/**
 * The best SAVEABLE version of a form: the fields that validate, with the failing
 * ones nulled. Used when a replace must persist settings to the NEW photo — losing
 * the twelve good fields because one was mistyped would be the worse outcome; the
 * caller tells the surveyor exactly which fields were dropped.
 */
function toSaveableBody(form: FormState): { body: ImageCameraPut; dropped: FieldKey[] } {
  const { body, errors } = toBody(form);
  const dropped = Object.keys(errors) as FieldKey[];
  for (const key of dropped) body[key] = null;
  // A halved pair would 422 (lat and lon travel together) — drop both.
  if (body.lat === null || body.lon === null) {
    body.lat = null;
    body.lon = null;
  }
  return { body, dropped };
}

// ─────────────────────────────────────────────────────────────────────────────
// Small presentational pieces
// ─────────────────────────────────────────────────────────────────────────────

interface StepHeaderProps {
  index: number;
  title: string;
  icon: JSX.Element;
}

function StepHeader({ index, title, icon }: StepHeaderProps): JSX.Element {
  return (
    <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
      <Box
        sx={{
          width: 28,
          height: 28,
          borderRadius: '50%',
          bgcolor: 'primary.main',
          color: 'primary.contrastText',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 14,
          fontWeight: 600,
          flexShrink: 0,
        }}
      >
        {index}
      </Box>
      {icon}
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        {title}
      </Typography>
    </Stack>
  );
}

interface NumFieldProps {
  form: FormState;
  errors: FormErrors;
  onChange: (key: FieldKey, value: string) => void;
  disabled: boolean;
  field: FieldKey;
  label: string;
  width?: number;
}

/** One numeric text field. `type="text"` + mono, so long calibrations stay readable. */
function NumField({
  form,
  errors,
  onChange,
  disabled,
  field,
  label,
  width,
}: NumFieldProps): JSX.Element {
  return (
    <TextField
      size="small"
      label={label}
      value={form[field]}
      error={errors[field] !== undefined}
      helperText={errors[field]}
      onChange={(e) => onChange(field, e.target.value)}
      disabled={disabled}
      inputProps={{ inputMode: 'decimal', sx: { fontFamily: 'monospace' } }}
      sx={{ width: width ?? 130 }}
    />
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

export function ImageSetupPage(): JSX.Element {
  const params = useParams();
  const projectId = params.projectId ? asUuid(params.projectId) : null;
  /** Present ⇒ EDIT mode for that photograph; absent ⇒ NEW-IMAGE mode. */
  const paramImageId = params.imageId ? asUuid(params.imageId) : null;
  const navigate = useNavigate();
  const notify = useNotify();

  const { data: project } = useProject(projectId);
  const { data: imagesPage } = useImages(projectId);
  const cameraQuery = useImageCamera(paramImageId);
  const saveCamera = useSaveImageCamera();
  const upload = useImageUpload();
  const deleteImage = useDeleteImage();
  const csvRef = useRef<HTMLInputElement>(null);
  const replaceRef = useRef<HTMLInputElement>(null);

  // ★ THE DRAFT SURVIVES NAVIGATION. "Process new DEM…" (and any other excursion)
  //   unmounts this page; before 1.2.6 that discarded every hand-typed field. The
  //   session-scoped draft store re-seeds the form and the uploaded photo when the
  //   surveyor returns; a successful Save (or deleting the photo) clears it.
  const draftKey = `${projectId ?? 'none'}:${paramImageId ?? 'new'}`;
  const initialDraft = useImageSetupDraftStore.getState().byKey[draftKey];

  // ★ In NEW-IMAGE mode the uploaded photo lives here until the surveyor leaves —
  //   keeping it in state (not a route change) is what lets the form survive the
  //   upload without a remount.
  const [uploadedImage, setUploadedImage] = useState<SetupImage | null>(
    (initialDraft?.uploadedImage as SetupImage | null) ?? null,
  );
  const [libraryOpen, setLibraryOpen] = useState(false);

  /** A photo just arrived (upload OR library import): adopt it and autofill the
   *  blank frame-size / principal-point fields from its dimensions — only BLANK
   *  fields; an imported calibration is never overwritten. */
  const adoptFresh = useCallback((fresh: SetupImage): void => {
    setUploadedImage(fresh);
    setForm((prev) => {
      if (prev === null) return prev;
      const next = { ...prev };
      if (next.img_w.trim() === '') next.img_w = String(fresh.width);
      if (next.img_h.trim() === '') next.img_h = String(fresh.height);
      if (next.cx.trim() === '') next.cx = String(fresh.width / 2);
      if (next.cy.trim() === '') next.cy = String(fresh.height / 2);
      return next;
    });
  }, []);
  const [confirmReplace, setConfirmReplace] = useState<SetupImage | null>(null);
  const [pendingRemove, setPendingRemove] = useState<SetupImage | null>(null);
  const [uploadPct, setUploadPct] = useState<number | null>(null);

  // ★ The form materialises ONCE. A returning draft wins (it holds what the surveyor
  //   TYPED — the server copy cannot); otherwise edit mode waits for the saved camera
  //   and new-image mode starts blank — a new photograph has nothing saved yet.
  const [form, setForm] = useState<FormState | null>(
    initialDraft?.form
      ? ({ ...initialDraft.form } as FormState)
      : paramImageId === null
        ? { ...EMPTY_FORM }
        : null,
  );
  const [errors, setErrors] = useState<FormErrors>({});

  if (form === null && cameraQuery.data !== undefined) {
    setForm(toForm(cameraQuery.data));
  }

  // ★ VIEW/EDIT MODE (1.2.6, mirrors Project settings): revisiting a photo whose
  //   camera was SAVED BEFORE opens READ-ONLY — the fields unlock behind "Edit
  //   settings" on the camera card. A returning mid-edit draft re-opens unlocked
  //   (the surveyor WAS editing when they left for the DEM page). New-image mode
  //   and a never-configured photo have nothing to protect and start unlocked.
  const [editUnlocked, setEditUnlocked] = useState<boolean>(initialDraft?.form != null);
  const configured = cameraQuery.data?.configured === true;
  const locked = paramImageId !== null && configured && !editUnlocked;

  // Mirror every change into the draft store — cheap, and what makes the
  // DEM-page round trip lossless. ★ NOT while locked: a look-only visit must not
  // plant a draft that would unlock the next visit.
  useEffect(() => {
    if (!locked) useImageSetupDraftStore.getState().set(draftKey, { form, uploadedImage });
  }, [draftKey, form, uploadedImage, locked]);

  /** Cancel the edit: back to the saved camera's values, draft gone, page relocked. */
  const cancelEditing = useCallback((): void => {
    if (cameraQuery.data !== undefined) setForm(toForm(cameraQuery.data));
    setErrors({});
    useImageSetupDraftStore.getState().clear(draftKey);
    setEditUnlocked(false);
  }, [cameraQuery.data, draftKey]);

  const setField = useCallback((key: FieldKey, value: string): void => {
    setForm((prev) => (prev === null ? prev : { ...prev, [key]: value }));
    setErrors((prev) => {
      if (prev[key] === undefined) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const images = useMemo(() => imagesPage?.items ?? [], [imagesPage]);
  // ★ EDIT MODE READS THE PHOTO ITSELF. The project list is paginated (50 newest),
  //   so an older photograph was "not here" the moment a project grew past a page.
  //   The list row still wins when present — it carries the counts cheaply.
  const imageQuery = useImage(paramImageId);

  // The photograph this page is about: the route's (edit) or the uploaded one (new).
  const image: SetupImage | null = useMemo(() => {
    if (paramImageId !== null) {
      const row = images.find((i) => i.id === paramImageId);
      if (row) return fromSummary(row);
      const detail = imageQuery.data;
      if (detail && detail.id === paramImageId) {
        return {
          id: detail.id,
          filename: detail.filename,
          width: detail.width,
          height: detail.height,
          gcp_count: detail.counts.gcps,
          annotation_count: detail.counts.annotations,
        };
      }
      return null;
    }
    return uploadedImage;
  }, [images, imageQuery.data, paramImageId, uploadedImage]);
  const imageId = image?.id ?? null;

  // ★ Exits go to the PROJECT PAGE, empty or not (1.2.6): it no longer redirects an
  //   empty project back here, so the old bounce-loop guard (route empty projects to
  //   the Workspace list instead) is gone with it.
  const ready = form !== null;
  const busy = saveCamera.isPending;
  /** The strings the inputs show — blank until the saved camera arrives. */
  const f = form ?? EMPTY_FORM;
  const fieldProps = { form: f, errors, onChange: setField, disabled: !ready || busy || locked };

  // ── first upload (new-image mode) ─────────────────────────────────────────
  const onPickImage = useCallback(
    (files: File[]): void => {
      const file = files[0];
      if (!file || projectId === null || upload.isPending) return;
      const uploadForm: ImageUploadForm = { file, project_id: projectId };
      setUploadPct(0);
      upload.mutate(
        {
          form: uploadForm,
          onProgress: (sent, total) =>
            setUploadPct(total > 0 ? Math.round((sent / total) * 100) : 0),
        },
        {
          onSuccess: (response) => {
            const fresh = fromUpload(isUploadAccepted(response) ? response.image : response);
            notify(`Uploaded ${fresh.filename}.`, { severity: 'success' });
            setUploadPct(null);
            adoptFresh(fresh);
          },
          onError: (error) => {
            setUploadPct(null);
            notify((error as ApiError)?.message ?? 'Upload failed.', { severity: 'error' });
          },
        },
      );
    },
    [adoptFresh, notify, projectId, upload],
  );

  // ── replacing / removing a mistaken photo ─────────────────────────────────
  const onReplaceFile = useCallback(
    (file: File | undefined): void => {
      const old = image;
      if (!file || old === null || projectId === null || upload.isPending) return;
      const uploadForm: ImageUploadForm = { file, project_id: projectId };
      setUploadPct(0);
      upload.mutate(
        {
          form: uploadForm,
          onProgress: (sent, total) =>
            setUploadPct(total > 0 ? Math.round((sent / total) * 100) : 0),
        },
        {
          onSuccess: (response) => {
            const fresh = fromUpload(isUploadAccepted(response) ? response.image : response);
            setUploadPct(null);

            // ★ The camera follows the photograph. The (swap-adjusted) form is saved
            //   to the NEW image before anything else moves — fields that fail
            //   validation are dropped and NAMED, never silently kept as poison.
            const adjusted = form !== null ? followReplacedImage(form, old, fresh) : null;
            if (adjusted !== null) {
              const { body, dropped } = toSaveableBody(adjusted);
              // ★ Preserve the picking mode: it is set in the GCP panel now, and
              //   PUT is full-replace — omitting it would silently reset to manual.
              body.auto_gcp_enabled = cameraQuery.data?.auto_gcp_enabled ?? false;
              // ★ …and the no-calibration mode with its seed (2026-09-09): they are
              //   set on the camera's settings page, and this form has no box for them.
              body.no_calibration = cameraQuery.data?.no_calibration ?? false;
              body.fov_h_deg = cameraQuery.data?.fov_h_deg ?? null;
              body.fov_v_deg = cameraQuery.data?.fov_v_deg ?? null;
              saveCamera.mutate(
                { imageId: fresh.id, body },
                {
                  onError: () =>
                    notify(
                      'The camera settings could not be saved to the new photo — press Save to retry.',
                      {
                        severity: 'warning',
                      },
                    ),
                },
              );
              if (dropped.length > 0) {
                notify(`Not saved to the new photo (fix and Save): ${dropped.join(', ')}.`, {
                  severity: 'warning',
                });
              }
              if (
                adjusted.img_w.trim() !== String(fresh.width) ||
                adjusted.img_h.trim() !== String(fresh.height)
              ) {
                notify(
                  `The frame-size fields kept your typed values — check them against the new photograph (${fresh.width} × ${fresh.height}).`,
                  { severity: 'warning' },
                );
              }
            }

            // ★ ORDER MATTERS: the mistaken photo goes only AFTER the replacement is
            //   safely stored — a failed upload must not leave the project photo-less.
            deleteImage.mutate(
              { imageId: old.id, projectId },
              {
                onSuccess: () =>
                  notify(`Replaced ${old.filename} with ${fresh.filename}.`, {
                    severity: 'success',
                  }),
                onError: () =>
                  notify(
                    `Uploaded ${fresh.filename}, but ${old.filename} could not be removed — delete it from the project page.`,
                    { severity: 'warning' },
                  ),
              },
            );

            if (paramImageId !== null) {
              // Edit mode: the URL names the old photo — move to the new one's page.
              setForm(adjusted);
              navigate(`/projects/${projectId}/images/${fresh.id}/setup`, { replace: true });
            } else {
              setUploadedImage(fresh);
              if (adjusted !== null) setForm(adjusted);
            }
          },
          onError: (error) => {
            setUploadPct(null);
            notify((error as ApiError)?.message ?? 'Upload failed.', { severity: 'error' });
          },
        },
      );
    },
    [
      cameraQuery.data,
      deleteImage,
      form,
      image,
      navigate,
      notify,
      paramImageId,
      projectId,
      saveCamera,
      upload,
    ],
  );

  const browseReplacement = useCallback(() => {
    browseNativeOrInput(
      replaceRef.current,
      filtersFromAccept(IMAGE_ACCEPT, 'Photographs'),
      (files) => onReplaceFile(files[0]),
    );
  }, [onReplaceFile]);

  const startReplace = useCallback((): void => {
    if (image === null) return;
    // A photo already carrying work is confirmed first; a fresh mistake goes
    // straight to the file picker — "I want another photo" is explicit.
    if (image.gcp_count > 0 || image.annotation_count > 0) {
      setConfirmReplace(image);
      return;
    }
    browseReplacement();
  }, [image, browseReplacement]);

  const confirmRemove = useCallback((): void => {
    if (pendingRemove === null || projectId === null) return;
    const name = pendingRemove.filename;
    deleteImage.mutate(
      { imageId: pendingRemove.id, projectId },
      {
        onSuccess: () => {
          notify(`Deleted ${name}.`);
          // The draft described a photo that no longer exists.
          useImageSetupDraftStore.getState().clear(draftKey);
          if (paramImageId !== null) {
            // Edit mode: this page was about a photo that no longer exists.
            navigate(`/projects/${projectId}`, { replace: true });
          } else {
            setUploadedImage(null);
          }
        },
        onError: () => notify('Could not delete the photograph.', { severity: 'error' }),
        onSettled: () => setPendingRemove(null),
      },
    );
  }, [deleteImage, draftKey, navigate, notify, paramImageId, pendingRemove, projectId]);

  // ── calibration CSV import ────────────────────────────────────────────────
  const onImportCsv = useCallback(
    (file: File | undefined): void => {
      if (!file) return;
      void file.text().then((text) => {
        const result = parseCalibrationCsv(text);
        if (result.matched === 0) {
          notify(
            'No calibration keys found. Expected two columns, e.g. "fx,4123" — one per line.',
            { severity: 'error' },
          );
          return;
        }
        setForm((prev) => {
          if (prev === null) return prev;
          const next = { ...prev };
          for (const [key, value] of Object.entries(result.fields)) {
            next[key as FieldKey] = String(value);
          }
          return next;
        });
        setErrors({});
        notify(
          `Imported ${result.matched} value${result.matched === 1 ? '' : 's'} from ${file.name}.`,
        );
        result.badValues.forEach((k) =>
          notify(`Could not read a number for “${k}” — left unchanged.`, { severity: 'warning' }),
        );
      });
    },
    [notify],
  );

  // ── save ──────────────────────────────────────────────────────────────────
  // ★ Two ways out after a save: into the photo's EDITOR (the usual next step —
  //   clicking an un-set-up photo lands here first, and saving is what unlocks the
  //   editor's setup gate), or back to the project. Saving also marks the photo
  //   configured, so the editor opens directly from then on.
  const save = useCallback(
    (after: 'editor' | 'project'): void => {
      if (form === null || imageId === null || projectId === null) return;
      const { body, errors: found } = toBody(form);
      // ★ Preserve the picking mode chosen in the GCP panel (PUT is full-replace).
      body.auto_gcp_enabled = cameraQuery.data?.auto_gcp_enabled ?? false;
      // ★ …and the no-calibration mode with its seed (2026-09-09) — set on the
      //   camera's settings page; a save from here must not wipe them.
      body.no_calibration = cameraQuery.data?.no_calibration ?? false;
      body.fov_h_deg = cameraQuery.data?.fov_h_deg ?? null;
      body.fov_v_deg = cameraQuery.data?.fov_v_deg ?? null;
      setErrors(found);
      if (Object.keys(found).length > 0) {
        notify('Fix the highlighted fields first.', { severity: 'error' });
        return;
      }
      saveCamera.mutate(
        { imageId, body },
        {
          onSuccess: (camera) => {
            setForm(toForm(camera));
            // Saved = the server holds the truth now; the draft has done its job.
            useImageSetupDraftStore.getState().clear(draftKey);
            notify('Image settings saved.', { severity: 'success' });
            const dest =
              after === 'editor'
                ? `/projects/${projectId}/images/${imageId}`
                : `/projects/${projectId}`;
            navigate(dest);
          },
          onError: (error) =>
            notify((error as ApiError)?.message ?? 'Could not save the settings.', {
              severity: 'error',
            }),
        },
      );
    },
    [cameraQuery.data, draftKey, form, imageId, navigate, notify, projectId, saveCamera],
  );

  if (projectId === null) {
    return (
      <Box sx={{ flex: 1, display: 'grid', placeItems: 'center' }}>
        <Typography color="text.secondary">{t('This page needs a project in its URL.')}</Typography>
      </Box>
    );
  }

  // Edit mode pointing at a photograph that is gone (deleted elsewhere).
  if (
    paramImageId !== null &&
    (cameraQuery.isError ||
      imageQuery.isError ||
      (imageQuery.isSuccess && imagesPage !== undefined && image === null))
  ) {
    return (
      <Box sx={{ flex: 1, display: 'flex' }}>
        <EmptyState
          icon={<CameraAltOutlinedIcon />}
          title={t('This photograph isn’t here')}
          description="It may have been deleted. Open the project to see what it holds now."
          primaryAction={{
            label: 'Open project',
            onClick: () => navigate(`/projects/${projectId}`),
          }}
        />
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, overflow: 'auto' }}>
      {/* ★ The header hugs the page's top-left, outside the centred column — the
          same convention as the Workspace: titles anchor the page, forms centre. */}
      <Box sx={{ px: { xs: 2, md: 3 }, pt: 3 }}>
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 0.5 }}>
          <TuneOutlinedIcon color="primary" />
          <Typography variant="h4">{t('Image setup')}</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 860 }}>
          {project ? <strong>{project.name}</strong> : 'This project'}
          {image !== null && (
            <>
              {' · '}
              <strong>{image.filename}</strong>
            </>
          )}{' '}
          — every photograph carries its own settings: the camera’s calibration, where it stood and
          how it was aimed. The elevation model is shared by the whole project. Every field can be
          filled now or later; nothing is guessed for you.
        </Typography>
      </Box>

      <Container maxWidth="md" sx={{ py: 3 }}>
        <Stack spacing={2}>
          {/* ── 1 · The photograph ────────────────────────────────────────── */}
          <Card variant="outlined">
            <CardContent>
              <StepHeader
                index={1}
                title={t('Photograph')}
                icon={<CameraAltOutlinedIcon fontSize="small" color="action" />}
              />
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
                {t(
                  'The photograph these settings describe. Uploading it fills the blank frame-size and image-centre fields below from its dimensions.',
                )}
              </Typography>

              {image !== null && (
                <Alert
                  severity="success"
                  icon={<CheckCircleOutlineIcon fontSize="inherit" />}
                  sx={{ mb: 2 }}
                  action={
                    <Stack direction="row" spacing={0.5}>
                      {/* ★ The mistake-fixers: swap the photo for another, or remove
                          it. Both confirm first when work would go with it. */}
                      <Tooltip title={t('Replace with another photo')}>
                        <IconButton
                          size="small"
                          color="inherit"
                          aria-label={`Replace ${image.filename}`}
                          disabled={upload.isPending || deleteImage.isPending}
                          onClick={startReplace}
                        >
                          <SwapHorizIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title={t('Delete this photo')}>
                        <IconButton
                          size="small"
                          color="inherit"
                          aria-label={`Delete ${image.filename}`}
                          disabled={upload.isPending || deleteImage.isPending}
                          onClick={() => setPendingRemove(image)}
                          sx={{ '&:hover': { color: 'error.main' } }}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  }
                >
                  <strong>{image.filename}</strong> · {image.width} × {image.height}
                  {image.gcp_count > 0 && <> · {image.gcp_count} GCPs</>}
                </Alert>
              )}

              {uploadPct !== null && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="caption" color="text.secondary">
                    {uploadPct < 100 ? `Uploading… ${uploadPct}%` : 'Processing…'}
                  </Typography>
                  {uploadPct < 100 ? (
                    <LinearProgress variant="determinate" value={uploadPct} sx={{ mt: 0.5 }} />
                  ) : (
                    <LinearProgress sx={{ mt: 0.5 }} />
                  )}
                </Box>
              )}

              {image === null && (
                <>
                  <UploadDropzone
                    onFiles={onPickImage}
                    accept={IMAGE_ACCEPT}
                    multiple={false}
                    disabled={upload.isPending}
                    hint=""
                  />
                  {/* ★ The other way a photograph arrives: a frame already captured
                      from a video, waiting in the capture library. */}
                  <Button
                    size="small"
                    startIcon={<PhotoLibraryOutlinedIcon />}
                    onClick={() => setLibraryOpen(true)}
                    disabled={upload.isPending}
                    sx={{ mt: 1.5 }}
                  >
                    {t('Add from capture library')}
                  </Button>
                </>
              )}
              <input
                ref={replaceRef}
                type="file"
                hidden
                accept={IMAGE_ACCEPT}
                onChange={(e) => {
                  onReplaceFile(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
            </CardContent>
          </Card>

          {/* ── 2 · Camera intrinsics & position — one step: they describe ONE
              physical fact (this camera, standing here, aimed so) and the solver
              consumes them together. ── */}
          <Card variant="outlined">
            <CardContent>
              <Stack
                direction="row"
                alignItems="center"
                justifyContent="space-between"
                flexWrap="wrap"
                useFlexGap
                spacing={1}
              >
                <StepHeader
                  index={2}
                  title={t('Camera Intrinsics & Position')}
                  icon={<TuneOutlinedIcon fontSize="small" color="action" />}
                />
                {/* ★ Locked ⇒ the ONE way in is Edit settings; unlocked ⇒ the CSV
                    import returns to its place. */}
                {locked ? (
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<EditOutlinedIcon />}
                    onClick={() => setEditUnlocked(true)}
                  >
                    {t('Edit settings')}
                  </Button>
                ) : (
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<UploadFileOutlinedIcon />}
                    disabled={!ready || busy}
                    onClick={() =>
                      browseNativeOrInput(
                        csvRef.current,
                        filtersFromAccept('.csv', 'Calibration CSV'),
                        (files) => onImportCsv(files[0]),
                      )
                    }
                  >
                    {t('Import calibration CSV…')}
                  </Button>
                )}
                <input
                  ref={csvRef}
                  type="file"
                  hidden
                  accept=".csv,text/csv"
                  onChange={(e) => {
                    onImportCsv(e.target.files?.[0]);
                    e.target.value = '';
                  }}
                />
              </Stack>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
                {t('All in')} <strong>pixels</strong> (OpenCV pinhole model); distortion is
                Brown–Conrady, used in the order k1, k2, p1, p2, k3. The CSV import reads the field
                tool’s two-column <code>{t('key,value')}</code> format.
              </Typography>

              <Stack spacing={1.5}>
                <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                  <NumField {...fieldProps} field="fx" label="fx (px)" />
                  <NumField {...fieldProps} field="fy" label="fy (px)" />
                  <NumField {...fieldProps} field="cx" label="cx (px)" />
                  <NumField {...fieldProps} field="cy" label="cy (px)" />
                </Stack>
                <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                  {/* ★ Display order groups the radial ks together; the SOLVER order
                      is still OpenCV's (k1, k2, p1, p2, k3) — layout is not wire. */}
                  <NumField {...fieldProps} field="k1" label="k1" />
                  <NumField {...fieldProps} field="k2" label="k2" />
                  <NumField {...fieldProps} field="k3" label="k3" />
                  <NumField {...fieldProps} field="p1" label="p1" />
                  <NumField {...fieldProps} field="p2" label="p2" />
                </Stack>
                <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                  <NumField
                    {...fieldProps}
                    field="img_w"
                    label={t('Image width (px)')}
                    width={160}
                  />
                  <NumField
                    {...fieldProps}
                    field="img_h"
                    label={t('Image height (px)')}
                    width={160}
                  />
                </Stack>

                <Divider sx={{ my: 0.5 }} />

                {/* ── position & tilt, the same step's other half ──────────── */}
                <Stack direction="row" spacing={1} alignItems="center">
                  <PlaceOutlinedIcon fontSize="small" color="action" />
                  <Typography variant="subtitle2">Position &amp; tilt</Typography>
                </Stack>
                <Typography variant="caption" color="text.secondary" display="block">
                  {t(
                    'Where the camera stood for this photograph (WGS84 decimal degrees) and its height above the ground. Tilt is degrees',
                  )}{' '}
                  <strong>{t('below horizontal')}</strong> — positive means aimed down. Projected
                  X/Y/Z are derived from the DEM below; they are never typed here.
                </Typography>
                <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                  <NumField {...fieldProps} field="lat" label={t('Latitude (°)')} width={180} />
                  <NumField {...fieldProps} field="lon" label={t('Longitude (°)')} width={180} />
                </Stack>
                <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                  <NumField
                    {...fieldProps}
                    field="mast_offset_m"
                    label={t('Camera offset (m)')}
                    width={160}
                  />
                  <NumField
                    {...fieldProps}
                    field="tilt_deg"
                    label={t('Tilt below horizontal (°)')}
                    width={200}
                  />
                </Stack>
              </Stack>
            </CardContent>
          </Card>

          {/* ── Elevation (DEM) for THIS photograph (1.2.6) ─────────────────
              The project-wide DEM lives in Project settings now; here the surveyor
              only chooses whether this photo uses it or attaches its own. ★ The
              card is present from the VERY FIRST visit: before the photograph
              exists on the server it cannot own a DEM yet, so the same options
              show LOCKED with the reason stated — never an invisible feature. */}
          {projectId !== null && imageId !== null ? (
            <ImageDemCard
              projectId={projectId}
              imageId={imageId}
              title={t('Elevation source (DEM)')}
            />
          ) : (
            <Card variant="outlined">
              <CardContent>
                <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
                  <HeightOutlinedIcon fontSize="small" color="action" />
                  <Typography variant="subtitle2">{t('Elevation source (DEM)')}</Typography>
                </Stack>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
                  {t('By default this photo uses the')} <strong>{t('project DEM')}</strong> (managed
                  in Project settings). To replace it for THIS photograph only — its GCPs and
                  Auto&nbsp;GCP raycast then read the replacement — add the photograph above first;
                  these options unlock the moment it exists.
                </Typography>
                <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                  <Button variant="outlined" size="small" disabled>
                    {t('Upload DEM for this image…')}
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    disabled
                    startIcon={<TerrainOutlinedIcon />}
                  >
                    {t('Process new DEM…')}
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    disabled
                    startIcon={<CollectionsOutlinedIcon />}
                  >
                    {t('From DEM library…')}
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          )}
        </Stack>

        <Divider sx={{ my: 3 }} />

        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
          {locked ? (
            // ★ READ-ONLY visit: nothing to save, so the exits are plain navigation.
            <>
              <Button
                variant="contained"
                onClick={() => navigate(`/projects/${projectId}/images/${imageId}`)}
                disabled={imageId === null}
              >
                {t('Annotate')}
              </Button>
              <Button variant="outlined" onClick={() => navigate(`/projects/${projectId}`)}>
                {t('Open project')}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="contained"
                onClick={() => save('editor')}
                disabled={!ready || busy || imageId === null}
                startIcon={busy ? <CircularProgress size={16} color="inherit" /> : undefined}
              >
                {busy ? 'Saving…' : 'Save & annotate'}
              </Button>
              <Button
                variant="outlined"
                onClick={() => save('project')}
                disabled={!ready || busy || imageId === null}
              >
                {t('Save & open project')}
              </Button>
              {/* ★ Two different third buttons, honestly named: UNLOCKING an already-
                  saved setup offers CANCEL (discard the edits, relock); a FIRST setup
                  offers SKIP FOR NOW (leave without saving camera settings — the
                  uploaded photo itself stays). */}
              {paramImageId !== null && configured ? (
                <Button color="inherit" onClick={cancelEditing} disabled={busy}>
                  {t('Cancel')}
                </Button>
              ) : (
                <Button
                  color="inherit"
                  onClick={() => navigate(`/projects/${projectId}`)}
                  disabled={busy}
                >
                  {t('Skip for now')}
                </Button>
              )}
            </>
          )}
          {cameraQuery.data?.configured && (
            <Chip
              size="small"
              variant="outlined"
              color="success"
              label={t('Settings saved before')}
            />
          )}
        </Stack>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          {imageId === null
            ? 'Upload the photograph first — these settings are saved to it.'
            : locked
              ? 'These settings are locked — use “Edit settings” on the camera card to change them.'
              : 'You can return here any time from the photo’s setup button on the project page.'}
        </Typography>
      </Container>

      {/* ★ Replacing a photo that already carries work is destructive — confirmed,
          with the dialog NAMING what goes with it. A fresh mistake skips this. */}
      <Dialog open={confirmReplace !== null} onClose={() => setConfirmReplace(null)}>
        <DialogTitle>{t('Replace this photograph?')}</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">
            <Typography variant="body2" sx={{ mb: 1 }}>
              <strong>{confirmReplace?.filename}</strong> already carries{' '}
              {confirmReplace?.annotation_count ?? 0} annotation
              {confirmReplace?.annotation_count === 1 ? '' : 's'} and{' '}
              {confirmReplace?.gcp_count ?? 0} ground control point
              {confirmReplace?.gcp_count === 1 ? '' : 's'}. Replacing it deletes them with it.
            </Typography>
            <Typography variant="body2" color="warning.main">
              {t('Export those coordinates first if you still need them.')}
            </Typography>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmReplace(null)}>{t('Cancel')}</Button>
          <Button
            color="error"
            variant="contained"
            startIcon={<SwapHorizIcon />}
            onClick={() => {
              setConfirmReplace(null);
              browseReplacement();
            }}
          >
            {t('Choose replacement…')}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={pendingRemove !== null} onClose={() => setPendingRemove(null)}>
        <DialogTitle>{t('Delete this photograph?')}</DialogTitle>
        <DialogContent>
          <DialogContentText component="div">
            <Typography variant="body2" sx={{ mb: 1 }}>
              <strong>{pendingRemove?.filename}</strong> will be removed
              {(pendingRemove?.annotation_count ?? 0) > 0 || (pendingRemove?.gcp_count ?? 0) > 0 ? (
                <>
                  , along with its {pendingRemove?.annotation_count ?? 0} annotation
                  {pendingRemove?.annotation_count === 1 ? '' : 's'} and{' '}
                  {pendingRemove?.gcp_count ?? 0} ground control point
                  {pendingRemove?.gcp_count === 1 ? '' : 's'}.
                </>
              ) : (
                '.'
              )}
            </Typography>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingRemove(null)} disabled={deleteImage.isPending}>
            {t('Cancel')}
          </Button>
          <Button
            onClick={confirmRemove}
            color="error"
            variant="contained"
            disabled={deleteImage.isPending}
            startIcon={
              deleteImage.isPending ? (
                <CircularProgress size={16} color="inherit" />
              ) : (
                <DeleteOutlineIcon />
              )
            }
          >
            {deleteImage.isPending ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* ★ Single-select: a setup describes exactly ONE photograph. The imported
          image becomes this page's photo, exactly as if it had been uploaded. */}
      {projectId !== null && libraryOpen && (
        <ImportFromLibraryDialog
          open
          single
          projectId={projectId}
          onClose={() => setLibraryOpen(false)}
          onImported={(imported) => {
            if (imported.length > 0) adoptFresh(fromUpload(imported[0]));
          }}
        />
      )}
    </Box>
  );
}

export default ImageSetupPage;
