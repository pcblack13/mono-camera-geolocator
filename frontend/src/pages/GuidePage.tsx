/**
 * `pages/GuidePage.tsx` — the WORKFLOW GUIDE: the whole method, and the whole app.
 *
 * ★ TWO VIEWS OF ONE PRODUCT (2026-09-12, owner ask). A manual has to answer two
 *   different questions and the old one only answered the first:
 *
 *     ROUTE — "what do I do next?"  Ten steps from an empty server to a handed-over
 *             folder, in the order the method actually runs.
 *     PAGES — "what is this page FOR?"  Every page the app has, grouped by where it
 *             lives, each saying what it is responsible for and what it holds.
 *
 * ★ THE TWO VIEWS ARE WIRED TO EACH OTHER, which is what makes this a map rather
 *   than two lists. A step names the pages it happens on; clicking one crosses to
 *   that page's card and lights it. A page names the numbered steps that run on it;
 *   clicking one crosses back to that step. Neither view is a dead end.
 *
 * ★ THE PAGE NAMES ARE NOT RE-TYPED HERE. The three pages of the navbar and the two
 *   tools come from `shell/workspaces` — the app's own registry, the same list the
 *   navbar, the drawer and the command palette render from. Re-authoring their
 *   labels here would let the guide drift from the product by a copy-paste; the
 *   pages that have no entry there (a camera's settings, the editor, a record, the
 *   dashboard, this guide, app status) are declared below and marked as such.
 *
 * ★ EVERY STEP IS A DOOR, NOT JUST A PARAGRAPH. Where a step lives on a page of
 *   its own, the pane carries an "Open" button that navigates straight there.
 *   Where it lives INSIDE another page (the camera's settings, the editor's strip),
 *   the pane says so honestly instead of faking a destination.
 *
 * ★ FORKS ARE DRAWN AS FORKS. "Choose the frame" shows two option cards side by
 *   side under one number — two doors, one destination.
 *
 * ★ PROGRESS IS THE READER'S. "Mark as done" is a personal tick, persisted in the
 *   browser (`guideProgressStore`); it claims nothing about the project.
 *
 * ★ Strings are translated AT THE RENDER SITE (`t(step.title)`), the same rule
 *   the home workflow board follows — module-level data is authored in English and
 *   resolved per render, so the language toggle reaches it.
 *
 * ★ Lazy route: a guide is read occasionally, not on every launch.
 */

import { useEffect, useMemo, useRef, useState, type JSX, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import InputAdornment from '@mui/material/InputAdornment';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined';
import AddPhotoAlternateOutlinedIcon from '@mui/icons-material/AddPhotoAlternateOutlined';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined';
import EditLocationOutlinedIcon from '@mui/icons-material/EditLocationOutlined';
import GridOnOutlinedIcon from '@mui/icons-material/GridOnOutlined';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import LaunchIcon from '@mui/icons-material/Launch';
import MenuBookOutlinedIcon from '@mui/icons-material/MenuBookOutlined';
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined';
import MovieOutlinedIcon from '@mui/icons-material/MovieOutlined';
import RadarOutlinedIcon from '@mui/icons-material/RadarOutlined';
import RadioButtonCheckedOutlinedIcon from '@mui/icons-material/RadioButtonCheckedOutlined';
import RestartAltOutlinedIcon from '@mui/icons-material/RestartAltOutlined';
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import SpaceDashboardOutlinedIcon from '@mui/icons-material/SpaceDashboardOutlined';
import TerrainOutlinedIcon from '@mui/icons-material/TerrainOutlined';
import TuneOutlinedIcon from '@mui/icons-material/TuneOutlined';
import VideocamOutlinedIcon from '@mui/icons-material/VideocamOutlined';

import { pageByKey } from '../components/shell/workspaces';
import { useGuideProgressStore } from '../store/guideProgressStore';
import { t, useT } from '../i18n';

// ─────────────────────────────────────────────────────────────────────────────
// THE PAGES — every page the app has, and what each one is responsible for
// ─────────────────────────────────────────────────────────────────────────────

/** Where a page lives, which is how the Pages view groups them. */
type PageGroup = 'In the navbar' | 'Inside a camera' | 'Tools' | 'Records' | 'Elsewhere';

interface GuidePageEntry {
  key: string;
  /** The page's name, as the app itself names it. */
  name: string;
  /** Its address, or null when it only exists for a specific record. */
  path: string | null;
  /** How to reach it when it has no address of its own. */
  reach?: string;
  group: PageGroup;
  icon: JSX.Element;
  /** ★ ONE SENTENCE: what this page is RESPONSIBLE FOR. Not what it looks like. */
  owns: string;
  /** The things that live here — what you would lose if the page went away. */
  holds: readonly string[];
  /** The route steps that run on this page, by number. */
  steps: readonly number[];
}

const PAGES: readonly GuidePageEntry[] = [
  // ── the three pages of the bar ───────────────────────────────────────────
  {
    key: 'cameras',
    name: pageByKey('cameras').label,
    path: pageByKey('cameras').path,
    group: 'In the navbar',
    icon: <DnsOutlinedIcon />,
    owns: 'The registry: which cameras exist at all. Every other page reads this list.',
    holds: [
      'One card per camera, with how far its setup has got',
      'Add camera — the door into a new camera’s settings',
      'Download the camera settings: the whole camera as one file',
    ],
    steps: [1],
  },
  {
    key: 'live',
    name: pageByKey('live').label,
    path: pageByKey('live').path,
    group: 'In the navbar',
    icon: <SensorsOutlinedIcon />,
    owns: 'Watching the fleet: where every registered camera is, and which are live right now.',
    holds: [
      'GLOBE — every camera on the Earth, and GRID — the wall of live tiles',
      'The instrument strip: the Zulu clock, the camera / live / lost counts, the place search',
      'The door into any one camera’s monitoring page',
    ],
    steps: [8],
  },
  {
    key: 'videos',
    name: pageByKey('videos').label,
    path: pageByKey('videos').path,
    group: 'In the navbar',
    icon: <MovieOutlinedIcon />,
    owns: 'Keeping what the cameras recorded, and the clips you uploaded by hand.',
    holds: [
      'Every recorded session, newest first',
      'Package — the session’s video, satellite map and attribute table in one folder',
      'Uploaded clips, to scrub to a moment and keep that frame as a photograph',
    ],
    steps: [5, 9],
  },

  // ── the pages a camera opens ─────────────────────────────────────────────
  {
    key: 'camera-settings',
    name: 'A camera’s settings',
    path: null,
    reach: 'Open a camera from the camera workspace, or press Add camera.',
    group: 'Inside a camera',
    icon: <TuneOutlinedIcon />,
    owns: 'The whole setup pipeline for one camera — the eight steps that make it measurable.',
    holds: [
      'Name, connection and position (steps 1–3)',
      'Its DEM, its calibration and its frame (steps 4–6)',
      'The lookup-table build and the drift watch (steps 7–8)',
      'Download the settings — everything above, in one file',
    ],
    steps: [1, 3, 4, 5, 7],
  },
  {
    key: 'editor',
    name: 'The control-point editor',
    path: null,
    reach: 'Press “Place control points” on the camera’s settings (step 6).',
    group: 'Inside a camera',
    icon: <EditLocationOutlinedIcon />,
    owns: 'Pairing pixels in the frame with positions on the satellite map.',
    holds: [
      'The frame beside the map, and every control point placed on both',
      'Auto GCP, which estimates the map point once four are placed',
      'The strip that counts the points against four and builds the lookup table',
      'The control-point table, exportable in the formats a GIS reads',
    ],
    steps: [6, 7, 10],
  },
  {
    key: 'camera-monitor',
    name: 'A camera’s monitoring page',
    path: null,
    reach: 'Open a camera from the globe or the grid.',
    group: 'Inside a camera',
    icon: <VideocamOutlinedIcon />,
    owns: 'One camera, watched: its picture, its detections, and where each one landed.',
    holds: [
      'The live picture with the detector’s boxes burned in',
      'The map deck — every mark placed through the lookup table',
      'Record, Capture, and the detector’s own dials',
      'The detections export: CSV, GeoJSON or Shapefile',
    ],
    steps: [8, 9, 10],
  },

  // ── the tools a camera’s settings open ───────────────────────────────────
  {
    key: 'dem',
    name: pageByKey('dem').label,
    path: pageByKey('dem').path,
    group: 'Tools',
    icon: <TerrainOutlinedIcon />,
    owns: 'Turning a raw elevation raster into the terrain a camera can measure against.',
    holds: [
      'Upload, crop to the working area, reproject to a metric CRS',
      'The statistics and the preview that say whether the tile is usable',
      'The processed tile, ready for a camera’s DEM step',
    ],
    steps: [2],
  },
  {
    key: 'drift',
    name: pageByKey('drift').label,
    path: pageByKey('drift').path,
    group: 'Tools',
    icon: <RadarOutlinedIcon />,
    owns: 'Knowing the moment a camera stops pointing where it was solved for.',
    holds: [
      'The frozen reference: the trusted picture and the pose it was frozen on',
      'The running watch and its verdict — OK, or MOVED by this many metres',
      'The soak report, and the log of every check',
    ],
    steps: [8],
  },

  // ── the records ──────────────────────────────────────────────────────────
  {
    key: 'recording',
    name: 'A recording',
    path: null,
    reach: 'Press Watch on any recording in Recorded videos.',
    group: 'Records',
    icon: <RadioButtonCheckedOutlinedIcon />,
    owns: 'One recorded session, watched beside the attribute table it produced.',
    holds: [
      'The video on its own clock, with the table following the playhead',
      'Trim — cutting a window into a new recording, leaving the original alone',
      'Download the package: video, satellite map and table in one folder',
    ],
    steps: [9],
  },
  {
    key: 'clip',
    name: 'A clip',
    path: null,
    reach: 'Open any uploaded clip from Recorded videos.',
    group: 'Records',
    icon: <MovieOutlinedIcon />,
    owns: 'Scrubbing an uploaded video to one moment and keeping that frame as a photograph.',
    holds: [
      'The scrubber and the frame grab',
      'The captured frame, which becomes a camera’s frame',
    ],
    steps: [5],
  },

  // ── the rest ─────────────────────────────────────────────────────────────
  {
    key: 'dashboard',
    name: 'Dashboard',
    path: '/dashboard',
    group: 'Elsewhere',
    icon: <SpaceDashboardOutlinedIcon />,
    owns: 'The state of the whole system at a glance — what is running and what needs attention.',
    holds: [
      'The map of everything placed so far',
      'Counts, recent activity and the health summary',
    ],
    steps: [],
  },
  {
    key: 'guide',
    name: 'Workflow guide',
    path: '/guide',
    group: 'Elsewhere',
    icon: <MenuBookOutlinedIcon />,
    owns: 'This page: the method in order, and every page in the app explained.',
    holds: [
      'The route — ten steps, each with a door',
      'The pages — what each one is responsible for',
    ],
    steps: [],
  },
  {
    key: 'status',
    name: 'App status & logs',
    path: '/status',
    group: 'Elsewhere',
    icon: <MonitorHeartOutlinedIcon />,
    owns: 'Saying which part of the system is unhappy, and showing the log that proves it.',
    holds: ['Every health component, explained', 'The live log monitor'],
    steps: [],
  },
];

const PAGE_GROUPS: readonly PageGroup[] = [
  'In the navbar',
  'Inside a camera',
  'Tools',
  'Records',
  'Elsewhere',
];

const pageOf = (key: string): GuidePageEntry => {
  const found = PAGES.find((p) => p.key === key);
  if (found === undefined) throw new Error(`Unknown guide page: ${key}`);
  return found;
};

// ─────────────────────────────────────────────────────────────────────────────
// THE ROUTE — the method, authored once, in order
// ─────────────────────────────────────────────────────────────────────────────

interface GuideDoor {
  label: string;
  to: string;
}

interface GuideForkOption {
  title: string;
  blurb: string;
  door: GuideDoor;
}

type GuidePhase = 'Set up' | 'Model the camera' | 'Survey' | 'Automate' | 'Deliver';

interface GuideStep {
  title: string;
  phase: GuidePhase;
  icon: JSX.Element;
  /** One sentence: why this step exists. */
  blurb: string;
  /** The expanded how-to, in order. Empty when `fork` carries the detail. */
  substeps: readonly string[];
  /** The way in, when the step has a page of its own. */
  door?: GuideDoor;
  /** The honest alternative to a door — where the step actually lives. */
  note?: string;
  /** Two parallel doors under one number. */
  fork?: readonly [GuideForkOption, GuideForkOption];
  /** ★ The pages this step happens on — the cross-link into the Pages view. */
  on: readonly string[];
  /** Steps the method does not require. */
  optional?: boolean;
}

export const STEPS: readonly GuideStep[] = [
  {
    title: 'Register the camera',
    phase: 'Set up',
    icon: <DnsOutlinedIcon />,
    blurb:
      'A camera is the unit of work: registered once on the server, it holds its connection, its position, its DEM, its calibration, its frame and its lookup table.',
    substeps: [
      'Open the camera workspace — with no cameras yet, it asks you to add the first.',
      'Press Add camera: name it, choose how it connects (LAN for an IP camera or a board, USB for a capture card, serial for a data line) and click its spot on the map.',
      'Every step of its settings page is open from the start; the camera joins the server when you press Add camera at the end.',
    ],
    door: { label: 'Open the camera workspace', to: '/cameras' },
    on: ['cameras', 'camera-settings'],
  },
  {
    title: 'Prepare the elevation model (DEM)',
    phase: 'Set up',
    icon: <TerrainOutlinedIcon />,
    blurb:
      'The DEM is the terrain the geolocation stands on — every ray from the camera ends where it meets this surface.',
    substeps: [
      'Bring a raster (GeoTIFF or similar) into DEM processing.',
      'Crop it to the camera’s working area and reproject it to a metric CRS — the page suggests the UTM zone.',
      'Check the statistics and the preview; export the processed tile or adopt it from the camera’s DEM step.',
    ],
    door: { label: 'Open DEM processing', to: '/dem' },
    on: ['dem'],
  },
  {
    title: 'Attach the camera’s DEM',
    phase: 'Set up',
    icon: <TerrainOutlinedIcon />,
    blurb:
      'Each camera reads its heights from its own DEM, and only from it — honest Z, never a guess.',
    substeps: [
      'On the camera’s settings page, step 4: upload a preprocessed DEM, process a new one, or pick one from the library.',
      'A point outside the DEM’s extent records no elevation — the page says so rather than inventing one.',
    ],
    note: 'Lives on the camera’s settings page (step 4) — open the camera from the camera workspace.',
    on: ['camera-settings', 'dem'],
  },
  {
    title: 'Describe the camera',
    phase: 'Model the camera',
    icon: <TuneOutlinedIcon />,
    blurb:
      'The intrinsics and the station turn a pixel into a ray: focal length and principal point, the mast height above the DEM, the tilt below horizontal.',
    substeps: [
      'Step 5 of the camera’s settings: enter fx, fy, cx, cy and, if known, the distortion coefficients.',
      'No measured focal length? Switch on “No calibration” and the focal is solved from the control points instead — labelled as the estimate it is.',
      'Without fx and fy the camera can still be watched and detections counted, but nothing can be placed on the map.',
    ],
    note: 'Lives on the camera’s settings page (step 5) — optional data, but the lookup table needs it.',
    on: ['camera-settings'],
  },
  {
    title: 'Choose the frame',
    phase: 'Model the camera',
    icon: <AddPhotoAlternateOutlinedIcon />,
    blurb:
      'One photograph from the camera is the surface the control points sit on and the lookup table is solved from.',
    substeps: [],
    fork: [
      {
        title: 'From the camera itself',
        blurb:
          'Step 6 of the camera’s settings captures a frame from the live source now, or takes one from the capture library.',
        door: { label: 'Open the camera workspace', to: '/cameras' },
      },
      {
        title: 'From a field video',
        blurb:
          'Scrub a recording or an uploaded clip to the moment in Recorded videos and keep that frame as a photograph.',
        door: { label: 'Open Recorded videos', to: '/videos' },
      },
    ],
    on: ['camera-settings', 'videos', 'clip'],
  },
  {
    title: 'Place control points in the Editor',
    phase: 'Survey',
    icon: <EditLocationOutlinedIcon />,
    blurb:
      'Pair pixels in the frame with positions on the satellite map — four make the camera measurable.',
    substeps: [
      'From the camera’s settings press “Place control points”: the editor opens on its frame with the camera’s strip on top.',
      'Click a landmark in the photo, then the same spot on the map; commit. After four, Auto GCP estimates the map point for each new photo click.',
      'The strip counts the points against four and names anything still missing.',
    ],
    note: 'The editor is a step of the camera’s settings — “Back to camera settings” brings you back.',
    on: ['editor', 'camera-settings'],
  },
  {
    title: 'Build the lookup table',
    phase: 'Survey',
    icon: <GridOnOutlinedIcon />,
    blurb:
      'One ground coordinate per pixel, solved from the frame, its control points, the calibration and the DEM — what every detection is placed through.',
    substeps: [
      'Press “Build lookup table” on the editor’s strip or on step 7 of the camera’s settings once four points are placed.',
      'The build validates itself and reports its maximum error; a refusal names the exact missing prerequisite.',
      'The finished bundle is saved to the camera and preselected on its monitoring page.',
    ],
    note: 'Built from the editor’s strip or the camera’s settings page (step 7).',
    on: ['editor', 'camera-settings'],
  },
  {
    title: 'Watch and detect',
    phase: 'Automate',
    icon: <SmartToyOutlinedIcon />,
    blurb: 'Once a camera has its table, every detection lands on the map with real coordinates.',
    substeps: [
      'The monitoring page shows the fleet two ways: GLOBE puts every camera on the Earth, GRID is the wall of live tiles.',
      'Open one camera, apply the detector’s dials, and watch marks land on the map deck beside the picture.',
      'Freeze a drift reference from the camera’s settings (step 8) so the watch tells you if the camera moves.',
    ],
    door: { label: 'Open cameras monitoring', to: '/monitor' },
    on: ['live', 'camera-monitor', 'drift'],
  },
  {
    title: 'Record the scene',
    phase: 'Automate',
    icon: <RadioButtonCheckedOutlinedIcon />,
    blurb:
      'A run is evidence that evaporates. Record turns a watch into a keepsake — the picture, the ground it happened on, and the table, kept together.',
    substeps: [
      'Press Record on the camera’s monitoring page while its stream is live; press it again to stop.',
      'Stopping saves three things at once: the video as watched, the attribute table for that window, and a satellite map of the scene with the camera and every placed mark drawn on it.',
      'The recording lands on the Recorded videos page. Press Package and the whole session downloads as one folder — video/, map/ and table/ — with a world file so the map opens in a GIS.',
      'A run with no lookup table places nothing, so it gets no map: the package says so rather than drawing a map of nowhere.',
    ],
    door: { label: 'Open Recorded videos', to: '/videos' },
    on: ['camera-monitor', 'videos', 'recording'],
  },
  {
    title: 'Export and hand over',
    phase: 'Deliver',
    icon: <DownloadOutlinedIcon />,
    blurb:
      'Take the work with you — the coordinates, the sessions, and the cameras themselves, each with the accuracy figure that says how far to trust it.',
    substeps: [
      'Detections export as CSV, GeoJSON or Shapefile from the camera’s monitoring page, each row carrying the camera’s drift verdict at the moment it was placed.',
      'Control points export from the editor’s table in the formats your GIS reads.',
      'A recorded session exports as one package — video, satellite map and attribute table in one folder.',
      'A whole camera exports too: “Download the camera settings” takes its name, connection, position, DEM, calibration, frame, control points, lookup table and drift reference to another machine in one file. A half-configured camera exports as well, naming what it still lacks.',
    ],
    door: { label: 'Open the camera workspace', to: '/cameras' },
    on: ['cameras', 'camera-settings', 'camera-monitor', 'editor', 'recording'],
  },
];

const PHASES: readonly GuidePhase[] = [
  'Set up',
  'Model the camera',
  'Survey',
  'Automate',
  'Deliver',
];
// ─────────────────────────────────────────────────────────────────────────────
// The rail — the route, one node per step
// ─────────────────────────────────────────────────────────────────────────────

interface StepNodeProps {
  step: GuideStep;
  n: number;
  selected: boolean;
  done: boolean;
  last: boolean;
  onSelect: () => void;
  onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void;
}

function StepNode({
  step,
  n,
  selected,
  done,
  last,
  onSelect,
  onKeyDown,
}: StepNodeProps): JSX.Element {
  const t = useT();
  return (
    <Box
      role="tab"
      id={`guide-step-${n}`}
      aria-selected={selected}
      aria-controls="guide-step-panel"
      tabIndex={selected ? 0 : -1}
      onClick={onSelect}
      onKeyDown={onKeyDown}
      sx={{
        'position': 'relative',
        'display': 'flex',
        'alignItems': 'center',
        'gap': 1.5,
        'px': 1.25,
        'py': 1,
        'borderRadius': 'var(--radius-md)',
        'cursor': 'pointer',
        'outline': 'none',
        'minWidth': { xs: 200, md: 0 },
        'bgcolor': selected ? 'var(--accent-quiet)' : 'transparent',
        'transition': 'background-color var(--dur-fast) var(--ease-standard)',
        '&:hover': { bgcolor: selected ? 'var(--accent-quiet)' : 'action.hover' },
        '&:focus-visible': { boxShadow: 'var(--focus-ring)' },
        // ★ The route line: from this node down to the next. Done stretches paint
        //   in the accent, so the line itself shows how far the reader has come.
        '&::after': last
          ? undefined
          : {
              content: '""',
              position: 'absolute',
              left: 25,
              top: 'calc(50% + 16px)',
              bottom: -10,
              width: 2,
              bgcolor: done ? 'var(--accent)' : 'var(--hairline-strong)',
              display: { xs: 'none', md: 'block' },
            },
      }}
    >
      <Box
        className="le-mono"
        aria-hidden
        sx={{
          width: 28,
          height: 28,
          flexShrink: 0,
          display: 'grid',
          placeItems: 'center',
          borderRadius: '50%',
          fontSize: 12,
          fontWeight: 600,
          border: '2px solid',
          borderColor: done || selected ? 'var(--accent)' : 'var(--hairline-strong)',
          bgcolor: done ? 'var(--accent)' : 'var(--bg-elevated)',
          color: done ? 'var(--accent-contrast)' : selected ? 'var(--accent)' : 'text.secondary',
          transition:
            'background-color var(--dur-fast) var(--ease-standard), border-color var(--dur-fast) var(--ease-standard)',
        }}
      >
        {done ? <CheckRoundedIcon sx={{ fontSize: 16 }} /> : n}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography
          noWrap
          sx={{
            fontSize: 13,
            fontWeight: selected ? 600 : 500,
            color: selected ? 'text.primary' : done ? 'text.secondary' : 'text.primary',
            lineHeight: 1.3,
          }}
        >
          {t(step.title)}
        </Typography>
        <Typography sx={{ fontSize: 11, color: 'text.secondary', lineHeight: 1.3 }} noWrap>
          {step.fork !== undefined
            ? t('Two doors')
            : step.door !== undefined
              ? t('Opens a page')
              : t('Inside another page')}
          {step.optional && ` · ${t('optional')}`}
        </Typography>
      </Box>
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The pane — the step in focus
// ─────────────────────────────────────────────────────────────────────────────

function DoorButton({
  door,
  variant = 'outlined',
}: {
  door: GuideDoor;
  variant?: 'outlined' | 'contained';
}): JSX.Element {
  const navigate = useNavigate();
  return (
    <Button
      size="small"
      variant={variant}
      endIcon={<LaunchIcon sx={{ fontSize: 14 }} />}
      onClick={() => navigate(door.to)}
      sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
    >
      {t(door.label)}
    </Button>
  );
}

function ForkOptionCard({
  option,
  index,
}: {
  option: GuideForkOption;
  index: number;
}): JSX.Element {
  return (
    <Stack
      spacing={1}
      sx={{
        'flex': 1,
        'minWidth': 0,
        'p': 2,
        'borderRadius': 'var(--radius-lg)',
        'border': '1px solid var(--hairline)',
        'bgcolor': 'var(--bg-inset)',
        'alignItems': 'flex-start',
        'transition': 'border-color var(--dur-fast) var(--ease-standard)',
        '&:hover': { borderColor: 'var(--accent)' },
      }}
    >
      <Typography
        className="le-mono"
        sx={{ fontSize: 10, letterSpacing: '0.08em', color: 'text.secondary' }}
      >
        {t('OPTION')} {String.fromCharCode(65 + index)}
      </Typography>
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        {t(option.title)}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
        {t(option.blurb)}
      </Typography>
      <DoorButton door={option.door} />
    </Stack>
  );
}

interface StepPaneProps {
  step: GuideStep;
  n: number;
  total: number;
  done: boolean;
  onToggleDone: () => void;
  onPrev: (() => void) | null;
  onNext: (() => void) | null;
  /** Cross into the Pages view, landing on this page's card. */
  onOpenPage: (key: string) => void;
}

function StepPane({
  step,
  n,
  total,
  done,
  onToggleDone,
  onPrev,
  onNext,
  onOpenPage,
}: StepPaneProps): JSX.Element {
  const t = useT();
  return (
    <Box
      id="guide-step-panel"
      role="tabpanel"
      aria-labelledby={`guide-step-${n}`}
      sx={{
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--hairline)',
        bgcolor: 'var(--bg-elevated)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        minHeight: { md: 520 },
      }}
    >
      {/* header */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'flex-start', sm: 'flex-start' }}
        sx={{ p: { xs: 2, md: 3 }, pb: { xs: 2, md: 2.5 } }}
      >
        <Box
          aria-hidden
          sx={{
            width: 48,
            height: 48,
            flexShrink: 0,
            display: 'grid',
            placeItems: 'center',
            borderRadius: 'var(--radius-md)',
            bgcolor: done ? 'var(--accent)' : 'var(--accent-quiet)',
            color: done ? 'var(--accent-contrast)' : 'var(--accent)',
            transition: 'background-color var(--dur-normal) var(--ease-standard)',
          }}
        >
          {step.icon}
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
            <Typography
              className="le-mono"
              sx={{ fontSize: 11, letterSpacing: '0.08em', color: 'text.secondary' }}
            >
              {t('STEP')} {n} / {total} · {t(step.phase).toUpperCase()}
            </Typography>
            {step.optional && <Chip size="small" variant="outlined" label={t('Optional')} />}
            {done && (
              <Chip
                size="small"
                icon={<CheckRoundedIcon />}
                label={t('Done')}
                sx={{ borderColor: 'var(--status-ok)', color: 'var(--status-ok)' }}
                variant="outlined"
              />
            )}
          </Stack>
          <Typography variant="h5" sx={{ fontWeight: 700, lineHeight: 1.2, mb: 0.75 }}>
            {t(step.title)}
          </Typography>
          <Typography variant="body1" color="text.secondary">
            {t(step.blurb)}
          </Typography>
        </Box>
        {step.door !== undefined && <DoorButton door={step.door} variant="contained" />}
      </Stack>

      <Divider />

      {/* body */}
      <Box sx={{ p: { xs: 2, md: 3 }, flex: 1 }}>
        {step.substeps.length > 0 && (
          <>
            <Typography
              className="le-mono"
              sx={{ fontSize: 11, letterSpacing: '0.08em', color: 'text.secondary', mb: 1.5 }}
            >
              {t('HOW')}
            </Typography>
            <Stack component="ol" spacing={1} sx={{ m: 0, p: 0, listStyle: 'none' }}>
              {step.substeps.map((s, i) => (
                <Stack
                  key={s}
                  component="li"
                  direction="row"
                  spacing={1.5}
                  alignItems="flex-start"
                  sx={{
                    p: 1.25,
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--hairline)',
                    bgcolor: 'var(--bg-inset)',
                  }}
                >
                  <Box
                    className="le-mono"
                    aria-hidden
                    sx={{
                      width: 22,
                      height: 22,
                      flexShrink: 0,
                      display: 'grid',
                      placeItems: 'center',
                      borderRadius: '50%',
                      fontSize: 11,
                      bgcolor: 'var(--accent-quiet)',
                      color: 'var(--accent)',
                    }}
                  >
                    {i + 1}
                  </Box>
                  <Typography variant="body2" sx={{ pt: '2px' }}>
                    {t(s)}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </>
        )}

        {step.fork !== undefined && (
          <>
            <Typography
              className="le-mono"
              sx={{ fontSize: 11, letterSpacing: '0.08em', color: 'text.secondary', mb: 1.5 }}
            >
              {t('TWO WAYS IN')}
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems="stretch">
              <ForkOptionCard option={step.fork[0]} index={0} />
              <Box
                aria-hidden
                className="le-mono"
                sx={{ alignSelf: 'center', color: 'text.secondary', fontSize: 12, px: 0.5 }}
              >
                {t('or')}
              </Box>
              <ForkOptionCard option={step.fork[1]} index={1} />
            </Stack>
          </>
        )}

        {/* ★ WHERE IT HAPPENS. The step names the pages it runs on, and each name
            is a way into that page's card — the reader who asks "but what IS the
            editor for?" mid-step gets an answer without losing their place. */}
        {step.on.length > 0 && (
          <Box sx={{ mt: 2.5 }}>
            <Typography
              className="le-mono"
              sx={{ fontSize: 11, letterSpacing: '0.08em', color: 'text.secondary', mb: 1 }}
            >
              {t('WHERE IT HAPPENS')}
            </Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
              {step.on.map((key) => {
                const target = pageOf(key);
                return (
                  <Chip
                    key={key}
                    size="small"
                    variant="outlined"
                    clickable
                    icon={<AccountTreeOutlinedIcon />}
                    label={t(target.name)}
                    onClick={() => onOpenPage(key)}
                    aria-label={`${t('What is')} ${t(target.name)} ${t('for?')}`}
                  />
                );
              })}
            </Stack>
          </Box>
        )}

        {step.note !== undefined && (
          <Stack
            direction="row"
            spacing={1.25}
            alignItems="flex-start"
            sx={{
              mt: step.substeps.length > 0 ? 2 : 0,
              p: 1.5,
              borderRadius: 'var(--radius-md)',
              borderLeft: '3px solid var(--accent)',
              bgcolor: 'var(--accent-quiet)',
            }}
          >
            <InfoOutlinedIcon sx={{ fontSize: 18, color: 'var(--accent)', mt: '1px' }} />
            <Box>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, lineHeight: 1.3 }}>
                {t('Where it lives')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t(step.note)}
              </Typography>
            </Box>
          </Stack>
        )}
      </Box>

      <Divider />

      {/* footer */}
      <Stack
        direction="row"
        spacing={1}
        alignItems="center"
        sx={{ px: { xs: 2, md: 3 }, py: 1.5, flexWrap: 'wrap', rowGap: 1 }}
      >
        <Button
          size="small"
          variant={done ? 'contained' : 'outlined'}
          color={done ? 'success' : 'primary'}
          startIcon={<CheckRoundedIcon />}
          onClick={onToggleDone}
          aria-pressed={done}
        >
          {done ? t('Done') : t('Mark as done')}
        </Button>
        <Box sx={{ flex: 1 }} />
        <Button
          size="small"
          color="inherit"
          startIcon={<ArrowBackRoundedIcon />}
          onClick={onPrev ?? undefined}
          disabled={onPrev === null}
        >
          {t('Previous')}
        </Button>
        <Button
          size="small"
          variant="outlined"
          endIcon={<ArrowForwardRoundedIcon />}
          onClick={onNext ?? undefined}
          disabled={onNext === null}
        >
          {t('Next step')}
        </Button>
      </Stack>
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The Pages view — every page, and what it is responsible for
// ─────────────────────────────────────────────────────────────────────────────

interface PageCardProps {
  page: GuidePageEntry;
  lit: boolean;
  /** Cross back into the Route view, landing on that step. */
  onOpenStep: (index: number) => void;
}

function PageCard({ page, lit, onOpenStep }: PageCardProps): JSX.Element {
  const t = useT();
  const navigate = useNavigate();
  return (
    <Box
      component="article"
      id={`guide-page-${page.key}`}
      aria-labelledby={`guide-page-${page.key}-title`}
      sx={{
        'display': 'flex',
        'flexDirection': 'column',
        'gap': 1.25,
        'p': 2,
        'borderRadius': 'var(--radius-lg)',
        'border': '1px solid',
        // ★ Arriving from a step's chip LIGHTS the card. Without it the reader
        //   lands in a grid of twelve and has to hunt for the one they asked for.
        'borderColor': lit ? 'var(--accent)' : 'var(--hairline)',
        'bgcolor': lit ? 'var(--accent-quiet)' : 'var(--bg-elevated)',
        'transition':
          'border-color var(--dur-fast) var(--ease-standard), background-color var(--dur-fast) var(--ease-standard)',
        '&:hover': { borderColor: 'var(--accent)' },
      }}
    >
      <Stack direction="row" spacing={1.5} alignItems="flex-start">
        <Box
          aria-hidden
          sx={{
            width: 36,
            height: 36,
            flexShrink: 0,
            display: 'grid',
            placeItems: 'center',
            borderRadius: 'var(--radius-md)',
            bgcolor: 'var(--accent-quiet)',
            color: 'var(--accent)',
          }}
        >
          {page.icon}
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            id={`guide-page-${page.key}-title`}
            variant="subtitle1"
            sx={{ fontWeight: 700, lineHeight: 1.25 }}
          >
            {t(page.name)}
          </Typography>
          <Typography
            className="le-mono"
            sx={{ fontSize: 11, color: 'text.disabled' }}
            dir="ltr"
            noWrap
            title={page.path ?? undefined}
          >
            {page.path ?? t('no address of its own')}
          </Typography>
        </Box>
      </Stack>

      {/* ★ THE ONE SENTENCE THAT MATTERS: what this page is RESPONSIBLE for. */}
      <Typography variant="body2">{t(page.owns)}</Typography>

      <Box>
        <Typography
          className="le-mono"
          sx={{ fontSize: 10, letterSpacing: '0.08em', color: 'text.secondary', mb: 0.75 }}
        >
          {t('WHAT LIVES HERE')}
        </Typography>
        <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 2 }}>
          {page.holds.map((h) => (
            <Typography key={h} component="li" variant="body2" color="text.secondary">
              {t(h)}
            </Typography>
          ))}
        </Stack>
      </Box>

      {page.reach !== undefined && (
        <Typography variant="caption" color="text.secondary">
          {t('How to get here')}: {t(page.reach)}
        </Typography>
      )}

      <Box sx={{ flex: 1 }} />

      <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap', gap: 1 }}>
        {/* ★ The steps that run here — the way back into the Route view. */}
        {page.steps.map((n) => (
          <Tooltip key={n} describeChild title={t(STEPS[n - 1].title)}>
            <Chip
              size="small"
              variant="outlined"
              clickable
              label={`${t('Step')} ${n}`}
              onClick={() => onOpenStep(n - 1)}
            />
          </Tooltip>
        ))}
        {page.steps.length === 0 && (
          <Typography variant="caption" color="text.disabled">
            {t('Not part of the route — read it when you need it.')}
          </Typography>
        )}
        <Box sx={{ flex: 1 }} />
        {page.path !== null && (
          <Button
            size="small"
            variant="outlined"
            endIcon={<LaunchIcon sx={{ fontSize: 14 }} />}
            onClick={() => navigate(page.path as string)}
            sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
          >
            {t('Open')}
          </Button>
        )}
      </Stack>
    </Box>
  );
}

interface PagesViewProps {
  lit: string | null;
  onOpenStep: (index: number) => void;
}

function PagesView({ lit, onOpenStep }: PagesViewProps): JSX.Element {
  const t = useT();
  const [query, setQuery] = useState('');

  // ★ Searched over the TRANSLATED text, so the Arabic reader can search in Arabic.
  const needle = query.trim().toLowerCase();
  const matches = useMemo(
    () =>
      PAGES.filter((p) => {
        if (needle === '') return true;
        const hay = [t(p.name), t(p.owns), p.path ?? '', ...p.holds.map((h) => t(h))]
          .join(' ')
          .toLowerCase();
        return hay.includes(needle);
      }),
    [needle, t],
  );

  return (
    <Box>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1.5}
        alignItems={{ sm: 'center' }}
        sx={{ mb: 2.5 }}
      >
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          {t(
            'Every page the app has, and what each one is responsible for. The step numbers on a card take you back to that point in the route.',
          )}
        </Typography>
        <TextField
          size="small"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('Search the pages')}
          sx={{ width: { xs: '100%', sm: 260 } }}
          // ★ lowercase inputProps: an aria-label on the TextField itself lands on
          //   the wrapper div, where no screen reader reads it for the field.
          inputProps={{ 'aria-label': t('Search the pages') }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchOutlinedIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
      </Stack>

      {matches.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
          {t('No page matches.')}
        </Typography>
      ) : (
        <Stack spacing={3}>
          {PAGE_GROUPS.map((group) => {
            const inGroup = matches.filter((p) => p.group === group);
            if (inGroup.length === 0) return null;
            return (
              <Box key={group} component="section" aria-label={t(group)}>
                <Typography
                  className="le-mono"
                  sx={{
                    fontSize: 11,
                    letterSpacing: '0.1em',
                    color: 'text.secondary',
                    mb: 1.25,
                  }}
                >
                  {t(group).toUpperCase()}
                </Typography>
                <Box
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: {
                      xs: '1fr',
                      sm: 'repeat(2, minmax(0, 1fr))',
                      lg: 'repeat(3, minmax(0, 1fr))',
                    },
                    gap: 1.5,
                  }}
                >
                  {inGroup.map((p) => (
                    <PageCard key={p.key} page={p} lit={lit === p.key} onOpenStep={onOpenStep} />
                  ))}
                </Box>
              </Box>
            );
          })}
        </Stack>
      )}
    </Box>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

type GuideView = 'route' | 'pages';

export function GuidePage(): JSX.Element {
  const t = useT();
  const [view, setView] = useState<GuideView>('route');
  const [selected, setSelected] = useState(0);
  /** The page card to light on arrival from a step's chip. */
  const [litPage, setLitPage] = useState<string | null>(null);
  const railRef = useRef<HTMLDivElement>(null);
  const doneTitles = useGuideProgressStore((s) => s.done);
  const toggleDone = useGuideProgressStore((s) => s.toggle);
  const resetDone = useGuideProgressStore((s) => s.reset);
  // ★ DEMO PROGRESS, BY DESIGN. The ticks are the reader's own notes while they
  //   walk the method — never derived from the project, so nothing here claims a
  //   fact about the survey. Reset clears every tick.
  const isDone = (i: number): boolean => doneTitles.includes(STEPS[i].title);
  const doneCount = STEPS.filter((_, i) => isDone(i)).length;

  // ★ Keep the focused node in view when the selection moves by keyboard.
  useEffect(() => {
    if (view !== 'route') return;
    const el = railRef.current?.querySelector<HTMLElement>(`#guide-step-${selected + 1}`);
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  }, [selected, view]);

  // ★ Crossing from a step to a page scrolls its card into view; the light stays
  //   until the reader crosses again, so the answer does not vanish as they read.
  useEffect(() => {
    if (view !== 'pages' || litPage === null) return;
    const el = document.getElementById(`guide-page-${litPage}`);
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [view, litPage]);

  const select = (i: number): void => setSelected(Math.max(0, Math.min(STEPS.length - 1, i)));

  /** A step's chip → that page's card. */
  const crossToPage = (key: string): void => {
    setLitPage(key);
    setView('pages');
  };

  /** A page's step chip → that step of the route. */
  const crossToStep = (index: number): void => {
    select(index);
    setView('route');
  };

  const onRailKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    const move = (i: number): void => {
      e.preventDefault();
      select(i);
      railRef.current?.querySelector<HTMLElement>(`#guide-step-${i + 1}`)?.focus();
    };
    switch (e.key) {
      case 'ArrowDown':
      case 'ArrowRight':
        move(Math.min(STEPS.length - 1, selected + 1));
        break;
      case 'ArrowUp':
      case 'ArrowLeft':
        move(Math.max(0, selected - 1));
        break;
      case 'Home':
        move(0);
        break;
      case 'End':
        move(STEPS.length - 1);
        break;
      default:
        break;
    }
  };

  const step = STEPS[selected];

  return (
    <Box sx={{ flex: 1, overflow: 'auto', scrollbarGutter: 'stable' }}>
      <Box sx={{ maxWidth: 1180, mx: 'auto', py: { xs: 2, md: 4 }, px: { xs: 2, md: 3 } }}>
        {/* ── header ─────────────────────────────────────────────────────────── */}
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={2}
          alignItems={{ xs: 'stretch', md: 'center' }}
          sx={{ mb: 2.5 }}
        >
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
            <Box
              aria-hidden
              sx={{
                width: 40,
                height: 40,
                display: 'grid',
                placeItems: 'center',
                borderRadius: 'var(--radius-md)',
                bgcolor: 'var(--accent-quiet)',
                color: 'var(--accent)',
                flexShrink: 0,
              }}
            >
              <MenuBookOutlinedIcon />
            </Box>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="h5" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
                {t('Workflow guide')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t(
                  'The method in order, and every page in the app explained. The two are wired together: a step names the pages it runs on, and a page names the steps that run on it.',
                )}
              </Typography>
            </Box>
          </Stack>

          {view === 'route' && (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                px: 2,
                py: 1.25,
                borderRadius: 'var(--radius-lg)',
                border: '1px solid var(--hairline)',
                bgcolor: 'var(--bg-elevated)',
                minWidth: { md: 300 },
              }}
            >
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="baseline">
                  <Typography variant="caption" color="text.secondary">
                    {t('Your progress')}
                  </Typography>
                  <Typography className="le-mono" sx={{ fontSize: 12 }} aria-live="polite">
                    {doneCount} / {STEPS.length} {t('done')}
                  </Typography>
                </Stack>
                <LinearProgress
                  variant="determinate"
                  value={(100 * doneCount) / STEPS.length}
                  aria-label={t('Your progress')}
                  sx={{ mt: 0.75 }}
                />
              </Box>
              <Tooltip describeChild title={t('Reset progress')}>
                <span>
                  <Button
                    size="small"
                    color="inherit"
                    onClick={() => {
                      resetDone();
                      select(0);
                    }}
                    aria-label={t('Reset progress')}
                    startIcon={<RestartAltOutlinedIcon fontSize="small" />}
                    sx={{ whiteSpace: 'nowrap' }}
                  >
                    {t('Reset')}
                  </Button>
                </span>
              </Tooltip>
            </Box>
          )}
        </Stack>

        {/* ── the two views ──────────────────────────────────────────────────── */}
        <ToggleButtonGroup
          exclusive
          size="small"
          value={view}
          onChange={(_e, v: GuideView | null) => {
            if (v !== null) setView(v);
          }}
          aria-label={t('View')}
          sx={{ mb: 2.5 }}
        >
          <ToggleButton value="route" sx={{ px: 2 }}>
            <AccountTreeOutlinedIcon sx={{ fontSize: 16, mr: 0.75 }} />
            {t('Route')}
          </ToggleButton>
          <ToggleButton value="pages" sx={{ px: 2 }}>
            <SpaceDashboardOutlinedIcon sx={{ fontSize: 16, mr: 0.75 }} />
            {t('Pages')}
          </ToggleButton>
        </ToggleButtonGroup>

        {view === 'pages' ? (
          <PagesView lit={litPage} onOpenStep={crossToStep} />
        ) : (
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: '300px minmax(0, 1fr)' },
              gap: 3,
              alignItems: 'start',
            }}
          >
            <Box
              ref={railRef}
              role="tablist"
              aria-label={t('Steps')}
              aria-orientation="vertical"
              className="le-chrome"
              onKeyDown={onRailKey}
              sx={{
                display: 'flex',
                flexDirection: { xs: 'row', md: 'column' },
                gap: { xs: 1, md: 0.5 },
                overflowX: { xs: 'auto', md: 'visible' },
                pb: { xs: 1, md: 0 },
                position: { md: 'sticky' },
                top: { md: 16 },
              }}
            >
              {PHASES.map((phase) => {
                const indices = STEPS.map((s, i) => (s.phase === phase ? i : -1)).filter(
                  (i) => i >= 0,
                );
                return (
                  <Box key={phase} sx={{ display: 'contents' }}>
                    <Typography
                      className="le-mono"
                      sx={{
                        display: { xs: 'none', md: 'block' },
                        fontSize: 10,
                        letterSpacing: '0.1em',
                        color: 'text.secondary',
                        px: 1.25,
                        pt: indices[0] === 0 ? 0 : 1.5,
                        pb: 0.5,
                      }}
                    >
                      {t(phase).toUpperCase()}
                    </Typography>
                    {indices.map((i) => (
                      <StepNode
                        key={STEPS[i].title}
                        step={STEPS[i]}
                        n={i + 1}
                        selected={selected === i}
                        done={isDone(i)}
                        last={i === STEPS.length - 1}
                        onSelect={() => select(i)}
                        onKeyDown={() => undefined}
                      />
                    ))}
                  </Box>
                );
              })}
            </Box>

            <StepPane
              key={step.title}
              step={step}
              n={selected + 1}
              total={STEPS.length}
              done={isDone(selected)}
              onToggleDone={() => {
                const wasDone = isDone(selected);
                toggleDone(step.title);
                // ★ Ticking a step moves on — that is what "done" means on a route.
                if (!wasDone && selected < STEPS.length - 1) select(selected + 1);
              }}
              onPrev={selected > 0 ? () => select(selected - 1) : null}
              onNext={selected < STEPS.length - 1 ? () => select(selected + 1) : null}
              onOpenPage={crossToPage}
            />
          </Box>
        )}
      </Box>
    </Box>
  );
}

export default GuidePage;
