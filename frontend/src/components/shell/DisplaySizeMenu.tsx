/**
 * `shell/DisplaySizeMenu.tsx` — how big the app is drawn: for the TV on the wall.
 *
 * ★ ONE CONTROL, IN THE BAR, ON EVERY PAGE. "Fit to screen" is the default and
 *   says what it chose for this display ("Fit to screen · 200 %"); the fixed
 *   sizes are there for a screen the rule misjudges — or an operator who simply
 *   wants it bigger. Ctrl + / Ctrl − / Ctrl 0 do the same from the keyboard.
 *   Rendered only inside the desktop shell: a browser has its own zoom.
 */

import { useEffect, useState, type JSX, type MouseEvent } from 'react';
import IconButton from '@mui/material/IconButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import FitScreenOutlinedIcon from '@mui/icons-material/FitScreenOutlined';
import FormatSizeOutlinedIcon from '@mui/icons-material/FormatSizeOutlined';

import {
  formatZoom,
  getDisplayZoom,
  hasDisplayZoom,
  onDisplayZoom,
  setDisplayZoom,
  type ZoomInfo,
} from '../../lib/displayZoom';
import { useT } from '../../i18n';

export function DisplaySizeMenu(): JSX.Element | null {
  const t = useT();
  const [info, setInfo] = useState<ZoomInfo | null>(null);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const available = hasDisplayZoom();

  useEffect(() => {
    if (!available) return undefined;
    let alive = true;
    void getDisplayZoom().then((i) => {
      if (alive && i !== null) setInfo(i);
    });
    const off = onDisplayZoom((i) => setInfo(i));
    return () => {
      alive = false;
      off();
    };
  }, [available]);

  if (!available) return null;

  const open = (e: MouseEvent<HTMLElement>): void => setAnchor(e.currentTarget);
  const close = (): void => setAnchor(null);
  const choose = (preference: 'auto' | number): void => {
    close();
    void setDisplayZoom(preference).then((i) => {
      if (i !== null) setInfo(i);
    });
  };

  const current = info === null ? null : formatZoom(info.zoom);
  const label = `${t('Display size')}${current === null ? '' : `: ${current}`}`;
  const isAuto = info?.preference === 'auto';

  return (
    <>
      <Tooltip title={`${label} — ${t('Ctrl + / Ctrl − / Ctrl 0')}`}>
        <IconButton
          onClick={open}
          color="inherit"
          aria-label={label}
          aria-haspopup="menu"
          aria-expanded={anchor !== null}
        >
          <FormatSizeOutlinedIcon />
        </IconButton>
      </Tooltip>
      <Menu
        open={anchor !== null}
        anchorEl={anchor}
        onClose={close}
        MenuListProps={{ 'dense': true, 'aria-label': t('Display size') }}
      >
        <MenuItem selected={isAuto} onClick={() => choose('auto')}>
          <ListItemIcon>
            {isAuto ? (
              <CheckRoundedIcon fontSize="small" />
            ) : (
              <FitScreenOutlinedIcon fontSize="small" />
            )}
          </ListItemIcon>
          <ListItemText
            primary={t('Fit to screen')}
            secondary={
              info === null ? undefined : `${t('this display')} · ${formatZoom(info.auto)}`
            }
          />
        </MenuItem>
        {(info?.steps ?? []).map((step) => {
          const selected =
            !isAuto && info !== null && Math.abs((info.preference as number) - step) < 1e-6;
          return (
            <MenuItem key={step} selected={selected} onClick={() => choose(step)}>
              <ListItemIcon>{selected && <CheckRoundedIcon fontSize="small" />}</ListItemIcon>
              <ListItemText primary={formatZoom(step)} />
            </MenuItem>
          );
        })}
        <MenuItem disabled sx={{ opacity: '1 !important' }}>
          <ListItemText
            primary={
              <Typography variant="caption" color="text.secondary">
                {t(
                  'For a TV or a large monitor, pick a bigger size — every page, map and photograph scales together.',
                )}
              </Typography>
            }
          />
        </MenuItem>
      </Menu>
    </>
  );
}

export default DisplaySizeMenu;
