/**
 * `shell/MainNav.tsx` — the small-screen navigation: one drawer, every destination.
 *
 * ★ IT MUST NOT CROWD THE WORKSPACE. `/projects/:projectId/images/:imageId` is a
 *   dense three-pane surveying tool (§1.1); the chrome above it is a strip, not a
 *   ribbon. Below `md` a single icon button opens this drawer; at `md` and up the
 *   navbar's page tabs and the icon rail own navigation and this renders
 *   nothing.
 *
 * ★ THE DRAWER MIRRORS THE NAVBAR: the shell's own destinations (`NAV_ITEMS`),
 *   then the pages as a titled group — the same registry the navbar's tabs render
 *   (the tools a camera's settings open stay out of both), so the phone and the
 *   desktop never disagree about what exists.
 *
 * ★ ACTIVE STATE IS SEMANTIC, NOT JUST VISUAL. The active row carries
 *   `aria-current="page"`, and the colour is layered on top of that — a screen
 *   reader announces the current page without depending on the colour.
 */

import { useState, type JSX } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Divider from '@mui/material/Divider';
import Drawer from '@mui/material/Drawer';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import ListSubheader from '@mui/material/ListSubheader';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';
import MenuIcon from '@mui/icons-material/Menu';

import { NAV_ITEMS, activeNavPath } from './navItems';
import { WORKSPACES, pageForLocation } from './workspaces';
import { useT } from '../../i18n';

/** The collapsed form — below `md`, where the workspace needs every pixel. */
function DrawerNav({ activePath }: { activePath: string | null }): JSX.Element {
  const t = useT();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const [open, setOpen] = useState(false);
  const currentPage = pageForLocation(pathname, search);

  return (
    <>
      <Tooltip title={t('Menu')}>
        <IconButton
          color="inherit"
          aria-label={t('Open navigation menu')}
          aria-expanded={open}
          onClick={() => setOpen(true)}
        >
          <MenuIcon />
        </IconButton>
      </Tooltip>
      <Drawer anchor="left" open={open} onClose={() => setOpen(false)}>
        <Box sx={{ width: 280 }} role="presentation">
          <Typography variant="h6" sx={{ px: 2, py: 1.5, fontWeight: 700 }}>
            Mono Camera Geolocator
          </Typography>
          <Divider />
          <List component="nav" aria-label={t('Main')} dense>
            {NAV_ITEMS.map((item) => {
              const active = item.path === activePath;
              return (
                <ListItemButton
                  key={item.path}
                  component={item.disabled ? 'div' : NavLink}
                  to={item.disabled ? undefined : item.path}
                  end={item.path === '/'}
                  disabled={item.disabled}
                  selected={active}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => setOpen(false)}
                >
                  <ListItemIcon sx={{ minWidth: 36, color: active ? 'primary.main' : undefined }}>
                    {item.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={t(item.label)}
                    secondary={item.disabled ? item.title : undefined}
                    primaryTypographyProps={{ fontWeight: active ? 700 : 500 }}
                  />
                </ListItemButton>
              );
            })}
          </List>

          {WORKSPACES.map((ws) => (
            <Box key={ws.key}>
              <Divider />
              <List
                component="nav"
                aria-label={t(ws.label)}
                dense
                subheader={
                  <ListSubheader
                    component="div"
                    disableSticky
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1,
                      lineHeight: '36px',
                      fontWeight: 700,
                      color: 'text.primary',
                      bgcolor: 'transparent',
                    }}
                  >
                    <Box component="span" sx={{ display: 'inline-flex', color: 'var(--accent)' }}>
                      {ws.icon}
                    </Box>
                    {t(ws.label)}
                  </ListSubheader>
                }
              >
                {ws.pages
                  .filter((page) => !page.tool)
                  .map((page) => {
                    const active = currentPage?.key === page.key;
                    return (
                      <ListItemButton
                        key={page.key}
                        selected={active}
                        aria-current={active ? 'page' : undefined}
                        onClick={() => {
                          setOpen(false);
                          navigate(page.path);
                        }}
                        sx={{ pl: 3 }}
                      >
                        <ListItemIcon
                          sx={{ minWidth: 36, color: active ? 'primary.main' : undefined }}
                        >
                          {page.icon}
                        </ListItemIcon>
                        <ListItemText
                          primary={t(page.label)}
                          primaryTypographyProps={{ fontWeight: active ? 700 : 500 }}
                        />
                      </ListItemButton>
                    );
                  })}
              </List>
            </Box>
          ))}
        </Box>
      </Drawer>
    </>
  );
}

export function MainNav(): JSX.Element | null {
  const theme = useTheme();
  const isMdUp = useMediaQuery(theme.breakpoints.up('md'));
  const { pathname } = useLocation();
  const activePath = activeNavPath(pathname);

  // ★ At md+ the navbar's page tabs and the icon rail own navigation, so
  //   the drawer retires there. Below md it stays: the rail is desktop-only, and
  //   a phone still needs a way around.
  return isMdUp ? null : <DrawerNav activePath={activePath} />;
}

export default MainNav;
