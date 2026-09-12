/**
 * `shell/CameraSwitcher.tsx` — the top bar's "which camera am I on" control.
 *
 * ★ THE CAMERA IS THE UNIT OF WORK (2026-09-04): where the bar used to name the
 *   current PROJECT and list every project, it names the current CAMERA — a
 *   registered one, or the draft being set up — and lists the server's cameras.
 *   Picking one opens its settings; the last entry is the server itself.
 */

import { useState, type JSX, type MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import ListItemText from '@mui/material/ListItemText';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import ArrowDropDownIcon from '@mui/icons-material/ArrowDropDown';
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined';

import { t } from '../../i18n';
import { connectionLabel } from '../../lib/cameras/connection';
import type { CameraRef } from '../../lib/cameras/projectCamera';
import { selectCameras, useCameraRegistryStore } from '../../store/cameraRegistryStore';

export interface CameraSwitcherProps {
  /** The camera the current page belongs to, or null outside any camera. */
  current: CameraRef | null;
}

export function CameraSwitcher({ current }: CameraSwitcherProps): JSX.Element {
  const navigate = useNavigate();
  const cameras = useCameraRegistryStore(selectCameras);
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const open = (e: MouseEvent<HTMLElement>): void => setAnchorEl(e.currentTarget);
  const close = (): void => setAnchorEl(null);
  const go = (to: string): void => {
    close();
    navigate(to);
  };
  const label =
    current === null
      ? t('Select a camera')
      : current.kind === 'draft'
        ? current.name || t('New camera')
        : current.name;

  return (
    <>
      <Button
        color="inherit"
        onClick={open}
        endIcon={<ArrowDropDownIcon />}
        aria-haspopup="menu"
        sx={{ textTransform: 'none', maxWidth: 280 }}
      >
        <ListItemText
          primary={label}
          primaryTypographyProps={{ noWrap: true, variant: 'subtitle2' }}
          sx={{ m: 0, textAlign: 'left' }}
        />
      </Button>
      <Menu anchorEl={anchorEl} open={anchorEl !== null} onClose={close}>
        {cameras.length === 0 && (
          <MenuItem disabled>
            <ListItemText primary={t('No cameras on the server yet')} />
          </MenuItem>
        )}
        {cameras.map((c) => (
          <MenuItem
            key={c.id}
            selected={current?.kind === 'camera' && current.id === c.id}
            onClick={() => go(`/cameras/${c.id}/settings`)}
          >
            <ListItemText primary={c.name} secondary={t(connectionLabel(c.connection))} />
          </MenuItem>
        ))}
        <Divider />
        <MenuItem onClick={() => go('/cameras')}>
          <DnsOutlinedIcon fontSize="small" sx={{ mr: 1 }} />
          <ListItemText primary={t('Camera workspace')} />
        </MenuItem>
      </Menu>
    </>
  );
}

export default CameraSwitcher;
