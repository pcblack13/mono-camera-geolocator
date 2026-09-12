/**
 * `annotation/LandmarkSuggestions.tsx` — 50-frontend.md §2.13 / SCOPE.md §4 rule 4.
 *
 * ★★ DEFERRED SURFACE, RENDERED HONESTLY. Automatic landmark suggestion needs
 *    optional AI models (SAM/DINOv2) that this build does not ship. Per SCOPE.md the
 *    classical/manual path is the EXPECTED default on a fresh machine — so this
 *    renders a calm, non-alarming explainer, never an error and never a dead spinner.
 *    The seam is real: the props and the `useSuggestions` query stay wired, so
 *    enabling the models later lights this panel up with no caller change (§7).
 *
 * ★ The gate is `useSuggestionsDeferral()` (the server's `deferred_features` list),
 *   checked BEFORE any request — the honest tooltip must arrive before the click, not
 *   after a 501.
 */

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';

import type { Uuid } from '../../types/common';
import type { LandmarkSuggestionRead } from '../../types/suggestion';
import { useSuggestions, useSuggestionsDeferral } from '../../api/hooks/useSuggestions';
import { t } from '../../i18n';

export interface LandmarkSuggestionsProps {
  imageId: Uuid;
  onAccept: (suggestion: LandmarkSuggestionRead) => void;
  onAcceptAll: (suggestions: LandmarkSuggestionRead[]) => void;
  onDismiss: (id: string) => void;
}

export function LandmarkSuggestions({
  imageId,
  onAccept,
  onAcceptAll: _onAcceptAll,
  onDismiss: _onDismiss,
}: LandmarkSuggestionsProps): JSX.Element {
  const { disabled, tooltip } = useSuggestionsDeferral();
  // The query is `enabled` only when the capability exists; in this build it does not,
  // so it never fires. It stays declared for the moment the models are installed.
  const { data } = useSuggestions(disabled ? null : imageId);
  const suggestions = data?.items ?? [];

  if (disabled) {
    return (
      <Stack spacing={1.5}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <AutoAwesomeIcon fontSize="small" color="disabled" />
          <Typography variant="subtitle2" color="text.secondary">
            {t('Landmark suggestions')}
          </Typography>
        </Stack>
        <Alert severity="info" variant="outlined" icon={false} sx={{ py: 0.5 }}>
          {tooltip ??
            'Automatic landmark suggestions need optional AI models, which aren’t installed. Mark landmarks manually — accuracy is unaffected.'}
        </Alert>
      </Stack>
    );
  }

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        {t('Landmark suggestions')}
      </Typography>
      <List dense disablePadding>
        {suggestions.map((s) => (
          <ListItemButton key={s.id} onClick={() => onAccept(s)}>
            <ListItemText
              primary={s.kind}
              secondary={s.rationale ?? `Score ${s.score.toFixed(2)}`}
            />
          </ListItemButton>
        ))}
      </List>
    </Box>
  );
}
