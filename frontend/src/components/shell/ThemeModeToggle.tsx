/**
 * `shell/ThemeModeToggle.tsx` — light / dark / system cycle (50-frontend §2.2 / §9.3). **(pure)**
 *
 * ★ Cycles the `ColorModePreference` (light → dark → system) via `useColorMode`
 *   (IU-23's context, deliberately not a Zustand store — §9.3). Dark is the default
 *   preference because "a bright chrome surrounding a photograph biases perception of
 *   that photograph's exposure" — the surveyor is judging the image, and the frame
 *   must not lie to their eye.
 */

import type { JSX } from 'react';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined';
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined';
import SettingsBrightnessOutlinedIcon from '@mui/icons-material/SettingsBrightnessOutlined';

import { useColorMode } from '../../theme';
import { useT } from '../../i18n';

export function ThemeModeToggle(): JSX.Element {
  const { preference, toggle } = useColorMode();
  const t = useT();

  const icon =
    preference === 'light' ? (
      <LightModeOutlinedIcon />
    ) : preference === 'dark' ? (
      <DarkModeOutlinedIcon />
    ) : (
      <SettingsBrightnessOutlinedIcon />
    );

  const label =
    preference === 'light'
      ? t('Light theme')
      : preference === 'dark'
        ? t('Dark theme')
        : t('System theme');

  return (
    <Tooltip title={`${label} — ${t('click to change')}`}>
      <IconButton
        onClick={toggle}
        aria-label={`${t('Theme')}: ${label}. ${t('Change theme.')}`}
        color="inherit"
      >
        {icon}
      </IconButton>
    </Tooltip>
  );
}

export default ThemeModeToggle;
