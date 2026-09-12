/**
 * `ui/ErrorState.tsx` — the server's own words, the code, and a copy button.
 *
 * ★ HONEST FEEDBACK IS THE PRODUCT'S RULE, and this is its error face: never a
 *   paraphrase, never "something went wrong" over a real message. The verbatim
 *   text is what support needs, the code is what the logs key on, and the copy
 *   button is how a field surveyor gets both into a report without retyping a
 *   `LiveCaptureError` by hand.
 */

import { useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';

import { t } from '../../i18n';

export interface ErrorStateProps {
  /** The server's message, VERBATIM. */
  message: string;
  /** Error class / HTTP status, when known — `LiveCaptureError · 422`. */
  code?: string;
  /** An action that could fix it, when one exists. */
  action?: { label: string; onClick: () => void };
}

export function ErrorState({ message, code, action }: ErrorStateProps): JSX.Element {
  const [copied, setCopied] = useState(false);
  const copy = (): void => {
    void navigator.clipboard
      ?.writeText(code !== undefined ? `${message}\n[${code}]` : message)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => undefined); // clipboard denied: the text is still on screen
  };

  return (
    <Box
      role="alert"
      sx={{
        border: '1px solid',
        borderColor: 'error.main',
        borderRadius: 'var(--radius-lg)',
        p: 1.5,
        bgcolor: 'var(--bg-inset)',
      }}
    >
      <Typography
        className="le-mono"
        sx={{ fontSize: 12, color: 'text.primary', wordBreak: 'break-word' }}
      >
        {message}
      </Typography>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 1 }}>
        {code !== undefined && (
          <Typography className="le-mono" sx={{ fontSize: 10.5, color: 'text.secondary' }}>
            {code}
          </Typography>
        )}
        <Box sx={{ flex: 1 }} />
        <Button
          size="small"
          variant="text"
          startIcon={
            copied ? <CheckIcon fontSize="inherit" /> : <ContentCopyIcon fontSize="inherit" />
          }
          onClick={copy}
          sx={{ fontSize: 11, minHeight: 'var(--control-sm)' }}
        >
          {copied ? t('Copied') : t('Copy')}
        </Button>
        {action !== undefined && (
          <Button
            size="small"
            variant="outlined"
            onClick={action.onClick}
            sx={{ minHeight: 'var(--control-sm)' }}
          >
            {action.label}
          </Button>
        )}
      </Stack>
    </Box>
  );
}
