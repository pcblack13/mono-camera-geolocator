/**
 * `shell/TopBar.tsx` — the application bar (50-frontend §2.2, wireframe §1.2).
 *
 * ★ MUI `AppBar`, elevation 0 with a bottom divider. THE WHOLE NAVIGATION LIVES
 *   HERE — there is no side rail. Left: menu (below md) + wordmark (= Home), then
 *   the three PAGE TABS (`PageTabsBar`: Camera workspace, Cameras Monitoring,
 *   Recorded videos), then the shell's own links (`ShellLinks`: Dashboard,
 *   Workflow guide). Centre-left: `CameraSwitcher`. Centre-right:
 *   `GlobalJobIndicator`. Right: connection, language, theme, avatar. Below `sm`
 *   the wordmark collapses to a mark.
 *
 * ★ Compare, Settings and Help are NOT here. Compare acts on the editor's panes and
 *   now lives in them; Settings and Help were removed from the product.
 */

import type { JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import AppBar from '@mui/material/AppBar';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import useMediaQuery from '@mui/material/useMediaQuery';
import { alpha, useTheme } from '@mui/material/styles';
import TerrainIcon from '@mui/icons-material/Terrain';

import type { Uuid } from '../../types/common';
import { GlobalJobIndicator } from './GlobalJobIndicator';
import { MainNav } from './MainNav';
import { CameraSwitcher } from './CameraSwitcher';
import type { CameraRef } from '../../lib/cameras/projectCamera';
import { CommandPalette } from './CommandPalette';
import { ConnectionChip } from './ConnectionChip';
import { LanguageToggle } from './LanguageToggle';
import { ShortcutsDialog } from './ShortcutsDialog';
import { DisplaySizeMenu } from './DisplaySizeMenu';
import { ThemeModeToggle } from './ThemeModeToggle';
import { PageTabsBar, ShellLinks } from './PageTabs';
import { t } from '../../i18n';

export interface TopBarProps {
  /** The camera the current page belongs to (2026-09-04), or null outside any camera. */
  cameraRef: CameraRef | null;
  /** The active shell-level job, if any (export/ingest in this build). */
  jobId?: Uuid | null;
}

export function TopBar({ cameraRef, jobId = null }: TopBarProps): JSX.Element {
  const theme = useTheme();
  const navigate = useNavigate();
  const isSmUp = useMediaQuery(theme.breakpoints.up('sm'));

  return (
    <AppBar
      position="static"
      elevation={0}
      color="default"
      // ★ Translucent + blurred: the bar reads as the product's frame, not a slab —
      //   content scrolling beneath it stays faintly present, which is what makes
      //   the chrome feel layered. Falls back to solid paper where blur is absent.
      sx={{
        borderBottom: 1,
        borderColor: 'divider',
        bgcolor: (t) => alpha(t.palette.background.paper, 0.85),
        backdropFilter: 'saturate(1.4) blur(10px)',
        zIndex: (t) => t.zIndex.appBar,
      }}
    >
      <Toolbar variant="dense" sx={{ gap: 1, minHeight: 56 }}>
        <IconButton
          edge="start"
          color="inherit"
          aria-label="Mono Camera Geolocator home"
          onClick={() => navigate('/')}
        >
          {/* ★ The wordmark's icon carries the brand colour — one constant anchor. */}
          <TerrainIcon color="primary" />
        </IconButton>
        {isSmUp && (
          <Typography
            variant="h6"
            noWrap
            sx={{ fontWeight: 700, letterSpacing: -0.2, mr: 1, flexShrink: 0 }}
          >
            Mono Camera Geolocator
          </Typography>
        )}

        {/* ★ Below md: the drawer, which lists the pages as a group. */}
        <MainNav />

        {/* ★ md+: the three page tabs, then the shell's own links. */}
        <PageTabsBar />
        <ShellLinks />

        <CameraSwitcher current={cameraRef} />

        <Box sx={{ flex: 1 }} />

        <GlobalJobIndicator jobId={jobId} />

        <Box sx={{ flex: 1 }} />

        {/* ★ Compare moved INTO the editor (`MapPanel`'s chrome): it acts on the
            photo/map panes and means nothing on the dashboard, the DEM page or the
            project list. Settings and Help are gone entirely. */}
        <ConnectionChip />
        <DisplaySizeMenu />
        <LanguageToggle />
        <ThemeModeToggle />

        <Avatar sx={{ width: 32, height: 32, ml: 0.5, fontSize: 14 }} aria-label={t('Account')}>
          AH
        </Avatar>

        {/* ★ Phase 3: keyboard reach — ⌘K palette and the ? cheatsheet live with the
            shell, so every page gets them without asking. */}
        <CommandPalette />
        <ShortcutsDialog />
      </Toolbar>
    </AppBar>
  );
}

export default TopBar;
