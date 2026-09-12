/**
 * `shell/PageTabs.tsx` — the navbar's page tabs, and the shell's own links beside them.
 *
 * ★ THREE TABS, NO DROPDOWN (2026-09-07, owner decision). "Camera workspace",
 *   "Cameras Monitoring" and "Recorded videos" sit in the top bar as plain
 *   buttons — one press opens the page. The workspace tab that dropped a panel of
 *   six cards is gone: the two tools a camera's settings open (DEM processing,
 *   the drift monitor) left the bar, and video detection left the product.
 *   There is no second bar and no side rail: the top bar is the whole navigation.
 *
 * ★ STATE IN COLOUR AND SHAPE. The tab of the page you are on — or of the page a
 *   deeper record belongs to (a camera's settings, a clip, a frame's editor) —
 *   is filled with the accent's quiet tint and carries `aria-current="page"`.
 *
 * ★ Desktop only (md+). Between md and lg the bar is tight (wordmark, switcher,
 *   chips), so each tab keeps its icon alone; the name stays in the tooltip and
 *   the accessible name. Below md the drawer (`MainNav`) lists the same pages.
 */

import type { JSX } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';

import { useT } from '../../i18n';
import { NAV_ITEMS, activeNavPath } from './navItems';
import { NAV_PAGES, navPageForLocation } from './workspaces';

// ─────────────────────────────────────────────────────────────────────────────
// The page tabs
// ─────────────────────────────────────────────────────────────────────────────

/** The bar's pages as tabs — one button each, the current one lit. */
export function PageTabsBar(): JSX.Element {
  const t = useT();
  const theme = useTheme();
  const isLgUp = useMediaQuery(theme.breakpoints.up('lg'));
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const current = navPageForLocation(pathname, search);

  return (
    <Stack
      direction="row"
      spacing={0.5}
      component="nav"
      aria-label={t('Pages')}
      className="le-chrome"
      sx={{ display: { xs: 'none', md: 'flex' }, alignItems: 'center', ml: 0.5 }}
    >
      {NAV_PAGES.map((page) => {
        const isCurrent = current?.key === page.key;
        const label = t(page.label);
        if (!isLgUp) {
          return (
            <Tooltip key={page.key} title={label} placement="bottom">
              <IconButton
                size="small"
                aria-label={label}
                aria-current={isCurrent ? 'page' : undefined}
                onClick={() => navigate(page.path)}
                sx={{
                  width: 36,
                  height: 36,
                  color: isCurrent ? 'var(--accent)' : 'text.secondary',
                  bgcolor: isCurrent ? 'var(--accent-quiet)' : 'transparent',
                }}
              >
                {page.icon}
              </IconButton>
            </Tooltip>
          );
        }
        return (
          <Button
            key={page.key}
            size="small"
            color="inherit"
            aria-label={label}
            aria-current={isCurrent ? 'page' : undefined}
            onClick={() => navigate(page.path)}
            startIcon={page.icon}
            sx={{
              'px': 1.25,
              'fontWeight': 600,
              'whiteSpace': 'nowrap',
              'color': isCurrent ? 'var(--accent)' : 'text.secondary',
              'bgcolor': isCurrent ? 'var(--accent-quiet)' : 'transparent',
              '&:hover': {
                bgcolor: isCurrent ? 'var(--accent-quiet)' : 'action.hover',
                color: 'text.primary',
              },
              '& .MuiButton-startIcon': { mr: 0.75 },
            }}
          >
            {label}
          </Button>
        );
      })}
    </Stack>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// The shell's own links — Dashboard and the guide (Home is the wordmark)
// ─────────────────────────────────────────────────────────────────────────────

/** Icon buttons for the shell's destinations, beside the page tabs (md+). */
export function ShellLinks(): JSX.Element {
  const t = useT();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const active = activeNavPath(pathname);

  return (
    <Stack
      direction="row"
      spacing={0.25}
      component="nav"
      aria-label={t('Main')}
      className="le-chrome"
      sx={{ display: { xs: 'none', md: 'flex' }, alignItems: 'center', ml: 0.5 }}
    >
      {NAV_ITEMS.filter((item) => item.path !== '/').map((item) => {
        const isActive = active === item.path;
        return (
          <Tooltip key={item.path} title={t(item.label)} placement="bottom">
            <IconButton
              size="small"
              aria-label={t(item.label)}
              aria-current={isActive ? 'page' : undefined}
              onClick={() => navigate(item.path)}
              sx={{
                width: 36,
                height: 36,
                color: isActive ? 'var(--accent)' : 'text.secondary',
                bgcolor: isActive ? 'var(--accent-quiet)' : 'transparent',
              }}
            >
              {item.icon}
            </IconButton>
          </Tooltip>
        );
      })}
    </Stack>
  );
}
