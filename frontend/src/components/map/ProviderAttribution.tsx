/**
 * `map/ProviderAttribution.tsx` (pure) — 50-frontend §2.21.
 *
 * ★★ ATTRIBUTION IS A ToS OBLIGATION, NOT DECORATION (task brief, §2.21). It is
 *    **non-dismissible and never conditionally hidden**: attribution is a licence
 *    condition for every provider we support, so it is structural, not a feature flag.
 *    If `attribution.text` is empty this renders the provider label rather than
 *    nothing — silence is not a permitted state.
 *
 * ★ Renders the active provider's text + terms link. Links carry
 *   `rel="noopener noreferrer"`. `compact` truncates to a single line (the maximum
 *   compression permitted) for narrow panes; the full text remains in the `title`.
 *
 * **Pure.** Props in, markup out. No store, no query.
 */

import Box from '@mui/material/Box';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';

import type { ProviderAttribution as ProviderAttributionData } from '../../types/geo';
import { t } from '../../i18n';
import { ON_MEDIA } from '../../theme/paint';

export interface ProviderAttributionProps {
  attribution: ProviderAttributionData;
  /** Fallback shown when `attribution.text` is empty — never render nothing. */
  providerLabel: string;
  compact?: boolean;
}

export function ProviderAttribution({
  attribution,
  providerLabel,
  compact = false,
}: ProviderAttributionProps): JSX.Element {
  const text = attribution.text.trim().length > 0 ? attribution.text : providerLabel;

  return (
    <Box
      // ★ Not interactive as a whole; it is a licence notice. Pointer events pass
      //   through to the map except on the terms link itself.
      sx={{
        pointerEvents: 'none',
        px: 0.75,
        py: 0.25,
        maxWidth: compact ? 220 : 420,
        borderRadius: 1,
        bgcolor: 'rgba(0, 0, 0, 0.55)',
        color: ON_MEDIA,
        backdropFilter: 'blur(2px)',
      }}
    >
      <Typography
        variant="caption"
        component="p"
        title={text}
        sx={{
          m: 0,
          lineHeight: 1.3,
          fontSize: 11,
          ...(compact
            ? { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }
            : {}),
        }}
      >
        {text}
        {attribution.terms_url ? (
          <>
            {' · '}
            <Link
              href={attribution.terms_url}
              target="_blank"
              rel="noopener noreferrer"
              underline="always"
              sx={{ color: ON_MEDIA, pointerEvents: 'auto' }}
            >
              {t('Terms')}
            </Link>
          </>
        ) : null}
      </Typography>
    </Box>
  );
}
