/**
 * `shell/LanguageToggle.tsx` — English ⇄ العربية, beside the theme switch.
 *
 * ★ A TWO-WAY SWITCH, NOT A MENU. There are exactly two languages, so a menu would
 *   be one extra click to reach the only other option. The button therefore shows
 *   the language it will switch TO — the same shape as the theme toggle next to it.
 *
 * ★ It says its target in that target's own script («العربية» / "English"), because
 *   someone who cannot read the current language must still recognise the way out.
 */

import type { JSX } from 'react';
import Button from '@mui/material/Button';
import Tooltip from '@mui/material/Tooltip';
import TranslateIcon from '@mui/icons-material/Translate';

import { setLanguage, useLanguage, useT } from '../../i18n';

export function LanguageToggle(): JSX.Element {
  const language = useLanguage();
  const t = useT();
  const next = language === 'ar' ? 'en' : 'ar';
  const nextLabel = next === 'ar' ? 'العربية' : 'English';

  return (
    <Tooltip title={`${t('Language')}: ${nextLabel}`}>
      <Button
        onClick={() => setLanguage(next)}
        color="inherit"
        size="small"
        startIcon={<TranslateIcon />}
        aria-label={`${t('Language')}: ${nextLabel}`}
        // The Arabic name needs its own direction so it renders correctly even
        // while the surrounding chrome is still left-to-right.
        sx={{ minWidth: 0, px: 1, textTransform: 'none' }}
      >
        <span dir={next === 'ar' ? 'rtl' : 'ltr'}>{nextLabel}</span>
      </Button>
    </Tooltip>
  );
}

export default LanguageToggle;
