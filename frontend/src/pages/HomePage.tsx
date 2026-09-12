/**
 * `pages/HomePage.tsx` — the landing page: what this app IS, before where the work is.
 *
 * ★ THE ROOT ROUTE IS AN INTRODUCTION now, not the dashboard. A returning surveyor
 *   loses one click (the dashboard lives at /dashboard, still in the nav); a new one
 *   gains the thing software rarely offers — a page that says what the product does,
 *   how a point comes to exist, and what the numbers on it mean. The map stays off
 *   this page so the landing route ships no Leaflet (same budget rule as the router's
 *   lazy notes).
 *
 * ★ EVERYTHING HERE IS TRUE. The feature cards describe only what is BUILT (manual
 *   picking, auto estimation from four points, video frames, DEM + 3D, exports) —
 *   the deferred automatic matcher is deliberately not advertised.
 *
 * ★ THE HERO IS A LAUNCHER, NOT A POSTER: the claim and the three doors (the
 *   camera workspace, cameras monitoring, the guide) over a strip of REAL figures
 *   — how many cameras the server holds and how many of them are ready to place
 *   marks on the map.
 *
 * ★ THE TWO MAIN PAGES ARE TAUGHT ON THE WORKFLOW BOARD right under the hero
 *   (2026-09-07, owner ask): one interactive carousel per page walks its quick
 *   guide a step at a time (`home/WorkflowBoard.tsx`). The board replaced both the
 *   two hero cards (2026-09-04) and the rotating feature showcase. Under the board:
 *   how the method runs in four moves, and the product's promises. The nine-step
 *   guide teaser and the workspace launcher that used to follow were removed the
 *   same day — the board already teaches both pages, and every page stays one
 *   click away in the navbar.
 */

import type { JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { alpha, useTheme } from '@mui/material/styles';
import AddLocationAltOutlinedIcon from '@mui/icons-material/AddLocationAltOutlined';
import AutoFixHighOutlinedIcon from '@mui/icons-material/AutoFixHighOutlined';
import ExploreOutlinedIcon from '@mui/icons-material/ExploreOutlined';
import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded';
import WifiOffOutlinedIcon from '@mui/icons-material/WifiOffOutlined';

import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined';

import { WorkflowBoard } from '../components/home/WorkflowBoard';
import { t } from '../i18n';
import { useCameraRegistryStore } from '../store/cameraRegistryStore';

// ─────────────────────────────────────────────────────────────────────────────
// Content — one array per section, so the layout reads as layout
// ─────────────────────────────────────────────────────────────────────────────

const STEPS: readonly { title: string; body: string }[] = [
  {
    title: 'Register the camera',
    body: 'In the camera workspace: name it, say how it connects — UTP/LAN for an IP camera or a board, USB for a capture card, serial/UART for a data line — and click its spot on the map.',
  },
  {
    title: 'Give it ground truth',
    body: 'Attach the camera’s DEM — its only height source, honest Z, never a guess — and, if you have it, the calibration: intrinsics, mast height, tilt.',
  },
  {
    title: 'Frame and control points',
    body: 'Capture one frame from the camera, pair four of its pixels with map positions in the editor, and build the lookup table — it saves itself to the camera.',
  },
  {
    title: 'Watch and detect',
    body: 'On cameras monitoring: watch it live, run the detector, see every find land on the map through the table, and be told the moment the camera moves.',
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// The hero's parts
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Contour lines and a soft accent glow behind the hero — an instrument's ground,
 * not a marketing gradient. Pure decoration: hidden from assistive tech, drawn in
 * theme colours so it survives the light theme and never competes with content.
 */
function HeroBackdrop(): JSX.Element {
  const theme = useTheme();
  const line = alpha(theme.palette.primary.main, theme.palette.mode === 'dark' ? 0.16 : 0.2);
  const glow = alpha(theme.palette.primary.main, theme.palette.mode === 'dark' ? 0.18 : 0.14);
  return (
    <Box
      aria-hidden
      sx={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        background: `radial-gradient(60% 80% at 85% 20%, ${glow} 0%, transparent 60%)`,
      }}
    >
      <svg
        viewBox="0 0 1200 420"
        preserveAspectRatio="xMaxYMid slice"
        width="100%"
        height="100%"
        style={{ position: 'absolute', inset: 0 }}
      >
        <g fill="none" stroke={line} strokeWidth="1">
          <path d="M620 420 C 700 340, 760 330, 840 300 S 980 220, 1040 150 S 1120 40, 1200 20" />
          <path d="M700 420 C 780 360, 830 350, 900 320 S 1030 250, 1090 180 S 1160 80, 1200 60" />
          <path d="M780 420 C 850 380, 900 370, 960 340 S 1080 280, 1140 210 S 1190 120, 1200 100" />
          <path d="M860 420 C 920 400, 970 390, 1020 360 S 1130 310, 1180 250 S 1200 180, 1200 150" />
          <path d="M540 420 C 620 330, 690 300, 780 270 S 930 190, 990 110 S 1060 10, 1120 0" />
          <path d="M460 420 C 540 320, 620 270, 720 240 S 880 160, 940 80 S 1000 0, 1040 0" />
        </g>
        <g fill={theme.palette.confidence.high}>
          <circle cx="1002" cy="228" r="3.5" />
          <circle cx="905" cy="318" r="3.5" />
          <circle cx="1088" cy="132" r="3.5" />
        </g>
        <g fill="none" stroke={theme.palette.confidence.high} strokeWidth="1" opacity="0.45">
          <circle cx="1002" cy="228" r="8" />
          <circle cx="905" cy="318" r="8" />
          <circle cx="1088" cy="132" r="8" />
        </g>
      </svg>
    </Box>
  );
}

/** One figure, instrument-style: a mono value over a quiet label. */
function HeroFact({ label, value }: { label: string; value: string | null }): JSX.Element {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography
        component="div"
        className="le-mono"
        sx={{
          fontSize: 18,
          fontWeight: 600,
          lineHeight: 1.2,
          color: value === null ? 'text.disabled' : 'text.primary',
          whiteSpace: 'nowrap',
        }}
      >
        {value ?? '—'}
      </Typography>
      <Typography
        component="div"
        sx={{
          fontSize: 11,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: 'text.secondary',
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </Typography>
    </Box>
  );
}

/**
 * The facts strip under the buttons — REAL numbers, never a slogan: how many
 * cameras the server holds, and how many of them can already place marks on the
 * map. A missing value shows an em-dash, not a zero (the readout rule,
 * `ui/StatReadout`).
 */
function HeroFacts(): JSX.Element {
  const cameras = useCameraRegistryStore((s) => s.cameras);
  const cameraCount = cameras.length;
  // ★ Ready = its lookup table exists — the same rule the camera workspace's
  //   cards draw (`setupProgress`), read here from the registry directly.
  const readyCount = cameras.filter((c) => Boolean(c.lut_site)).length;

  return (
    <Stack
      direction="row"
      spacing={0}
      useFlexGap
      flexWrap="wrap"
      alignItems="center"
      sx={{
        mt: 1,
        pt: 2.5,
        borderTop: '1px solid var(--hairline)',
        alignSelf: 'stretch',
        columnGap: 4,
        rowGap: 2,
      }}
    >
      <HeroFact label={t('Cameras')} value={cameraCount === 0 ? null : String(cameraCount)} />
      <HeroFact label={t('Ready')} value={cameraCount === 0 ? null : String(readyCount)} />
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The page
// ─────────────────────────────────────────────────────────────────────────────

export function HomePage(): JSX.Element {
  const navigate = useNavigate();

  return (
    <Box sx={{ flex: 1, overflow: 'auto' }}>
      {/* ── hero ─────────────────────────────────────────────────────────── */}
      <Box
        component="section"
        aria-labelledby="home-hero-title"
        sx={{
          position: 'relative',
          overflow: 'hidden',
          borderBottom: '1px solid var(--hairline)',
          bgcolor: 'var(--bg-elevated)',
        }}
      >
        <HeroBackdrop />
        <Container maxWidth="lg" sx={{ position: 'relative', py: { xs: 5, md: 7 } }}>
          {/* the claim, the doors, the facts — the two pages themselves are taught on the board below */}
          <Stack spacing={2.5} alignItems="flex-start" sx={{ maxWidth: 760 }}>
            <Typography
              className="le-mono"
              sx={{ fontSize: 11, letterSpacing: '0.12em', color: 'var(--accent)' }}
            >
              {t('FIELD PHOTOGRAMMETRY · OFFLINE-FIRST')}
            </Typography>
            <Stack direction="row" spacing={1.75} alignItems="center">
              <Box
                aria-hidden
                sx={{
                  width: 56,
                  height: 56,
                  display: 'grid',
                  placeItems: 'center',
                  borderRadius: 'var(--radius-md)',
                  bgcolor: 'var(--accent-quiet)',
                  color: 'var(--accent)',
                  border: '1px solid var(--hairline-strong)',
                  flexShrink: 0,
                }}
              >
                <ExploreOutlinedIcon sx={{ fontSize: 34 }} />
              </Box>
              <Typography
                id="home-hero-title"
                variant="h3"
                component="h1"
                sx={{ fontWeight: 800, letterSpacing: -0.8, lineHeight: 1.05 }}
              >
                Mono Camera Geolocator
              </Typography>
            </Stack>
            <Typography
              variant="h6"
              color="text.secondary"
              sx={{ fontWeight: 400, maxWidth: 560, lineHeight: 1.5 }}
            >
              {t(
                'Fixed cameras, geolocated: register a camera once on the server — its connection, DEM, calibration, frame and lookup table — then watch it, and every detection lands on the map with real coordinates. Runs locally, works offline.',
              )}
            </Typography>
            <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
              <Button
                size="large"
                variant="contained"
                startIcon={<DnsOutlinedIcon />}
                onClick={() => navigate('/cameras')}
              >
                {t('Camera workspace')}
              </Button>
              <Button
                size="large"
                variant="outlined"
                startIcon={<SensorsOutlinedIcon />}
                onClick={() => navigate('/monitor')}
              >
                {t('Cameras Monitoring')}
              </Button>
              <Button
                size="large"
                variant="text"
                endIcon={<ArrowForwardRoundedIcon />}
                onClick={() => navigate('/guide')}
              >
                {t('Workflow guide')}
              </Button>
            </Stack>

            <HeroFacts />
          </Stack>
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ py: 6 }}>
        {/* ── the workflow board: the two main pages, one step at a time ──── */}
        <WorkflowBoard />

        {/* ── how it works ─────────────────────────────────────────────────── */}
        <Typography variant="h5" sx={{ fontWeight: 700, mt: 6, mb: 3 }}>
          {t('How it works')}
        </Typography>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr)' },
            gap: 2,
          }}
        >
          {STEPS.map((step, index) => (
            <Box
              key={step.title}
              sx={{
                'p': 1.5,
                'm': -1.5,
                'borderRadius': 2,
                'transition': (t) => t.transitions.create('background-color'),
                '&:hover': { bgcolor: 'action.hover' },
                '&:hover .home-step-badge': { transform: 'scale(1.12)' },
              }}
            >
              <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1 }}>
                <Box
                  className="home-step-badge"
                  sx={{
                    width: 32,
                    height: 32,
                    borderRadius: '50%',
                    bgcolor: 'primary.main',
                    color: 'primary.contrastText',
                    display: 'grid',
                    placeItems: 'center',
                    fontWeight: 700,
                    flexShrink: 0,
                    transition: (t) => t.transitions.create('transform'),
                  }}
                >
                  {index + 1}
                </Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  {t(step.title)}
                </Typography>
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ pl: 5.5 }}>
                {t(step.body)}
              </Typography>
            </Box>
          ))}
        </Box>

        <Divider sx={{ my: 5 }} />

        {/* ── the promises — this product's actual character ───────────────── */}
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={3}
          justifyContent="center"
          alignItems={{ xs: 'flex-start', sm: 'center' }}
        >
          <Stack direction="row" spacing={1} alignItems="center">
            <WifiOffOutlinedIcon fontSize="small" color="action" />
            <Typography variant="body2" color="text.secondary">
              {t('Fully offline-capable — your own imagery and DEMs')}
            </Typography>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <AddLocationAltOutlinedIcon fontSize="small" color="action" />
            <Typography variant="body2" color="text.secondary">
              {t('Accuracy is derived (CE90) — never invented')}
            </Typography>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <AutoFixHighOutlinedIcon fontSize="small" color="action" />
            <Typography variant="body2" color="text.secondary">
              {t('Estimates are labelled as estimates, with their diagnostics')}
            </Typography>
          </Stack>
        </Stack>
      </Container>
    </Box>
  );
}

export default HomePage;
