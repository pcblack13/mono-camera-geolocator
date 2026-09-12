/**
 * `shell/ShortcutsDialog.tsx` — the cheatsheet, on `?`.
 *
 * ★ ONLY SHORTCUTS THAT EXIST. A cheatsheet that lists aspirations trains people
 *   to distrust it; every row here is a binding some component actually owns
 *   today, and new bindings must add their row in the same change.
 *
 * ★ `?` is ignored while typing — a question mark belongs in a note field more
 *   often than anyone needs this dialog.
 */

import { useEffect, useState, type JSX } from 'react';
import Box from '@mui/material/Box';
import Dialog from '@mui/material/Dialog';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { t } from '../../i18n';

const GROUPS: ReadonlyArray<{ title: string; rows: ReadonlyArray<[string, string]> }> = [
  {
    title: 'Everywhere',
    rows: [
      ['⌘K / Ctrl+K', 'Command palette'],
      ['?', 'Keyboard shortcuts'],
      ['Esc', 'Close dialog / cancel'],
    ],
  },
  {
    title: 'Editor',
    rows: [
      ['F1', 'Commit the open correspondence'],
      ['⇧F', 'Focus one pane / cycle'],
      ['A', 'Adjust the selected GCP'],
      ['Del', 'Delete the selected GCP'],
      ['⌘Z / Ctrl+Z', 'Undo'],
    ],
  },
  {
    title: 'Photograph',
    rows: [
      ['F', 'Fit to view'],
      ['+ / −', 'Zoom in / out'],
      ['⇧⌘R', 'Reset brightness and contrast'],
    ],
  },
];

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (el === null) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
}

export function ShortcutsDialog(): JSX.Element {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === '?' && !isTyping(e.target) && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setOpen(true);
      }
    };
    // The palette's own "Keyboard shortcuts" entry arrives as this event.
    const onOpen = (): void => setOpen(true);
    window.addEventListener('keydown', onKey);
    window.addEventListener('le:shortcuts', onOpen);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('le:shortcuts', onOpen);
    };
  }, []);

  return (
    <Dialog open={open} onClose={() => setOpen(false)} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ pb: 1 }}>{t('Keyboard shortcuts')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          {GROUPS.map((g) => (
            <Box key={g.title}>
              <Typography
                className="le-mono"
                sx={{
                  fontSize: 10,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  color: 'text.disabled',
                  mb: 0.75,
                }}
              >
                {t(g.title)}
              </Typography>
              {g.rows.map(([keys, what]) => (
                <Stack
                  key={keys}
                  direction="row"
                  justifyContent="space-between"
                  alignItems="baseline"
                  sx={{ py: 0.4, borderBottom: '1px solid var(--hairline)' }}
                >
                  <Typography variant="caption" color="text.secondary">
                    {t(what)}
                  </Typography>
                  <Typography
                    className="le-mono"
                    sx={{
                      fontSize: 11,
                      px: 0.75,
                      py: 0.1,
                      border: '1px solid var(--hairline-strong)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'text.primary',
                    }}
                  >
                    {keys}
                  </Typography>
                </Stack>
              ))}
            </Box>
          ))}
        </Stack>
      </DialogContent>
    </Dialog>
  );
}
