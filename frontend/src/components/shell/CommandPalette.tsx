/**
 * `shell/CommandPalette.tsx` — ⌘K / Ctrl-K: every page and setting, one keystroke away.
 *
 * ★ PHASE 3'S GATE IS "every action keyboard-reachable", and this is the floor
 *   under that promise: whatever has no dedicated shortcut is still reachable by
 *   name. Navigation (every page), the theme, the language,
 *   reduced motion and the shortcut cheatsheet all live here from day one;
 *   feature actions join as their pages migrate.
 *
 * ★ MATCHES IN BOTH LANGUAGES, always. A surveyor working in Arabic must find
 *   «مساحة العمل» — but muscle memory from the English docs must keep working
 *   too, so the filter runs over the translated AND the English label.
 *
 * ★ No new dependency: a Dialog, an input and a filtered list. A fuzzy-search
 *   library for ~20 commands is weight the field laptop pays for nothing.
 */

import { useEffect, useMemo, useRef, useState, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@mui/material/Box';
import Dialog from '@mui/material/Dialog';
import InputBase from '@mui/material/InputBase';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import Typography from '@mui/material/Typography';
import SearchIcon from '@mui/icons-material/Search';

import { t } from '../../i18n';
import { setLanguage, useLanguage } from '../../i18n';
import { useColorMode } from '../../theme';
import { useWorkspaceStore } from '../../store';
import { useProjects } from '../../api/hooks/useProjects';
import { WORKSPACE_PAGES } from './workspaces';

interface Command {
  /** English — the stable id AND one side of the match. */
  label: string;
  /** A mono hint on the right: a destination or a key. */
  hint?: string;
  run: () => void;
}

export function CommandPalette(): JSX.Element {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const { toggle } = useColorMode();
  const language = useLanguage();
  const reduceMotion = useWorkspaceStore((s) => s.reduceMotion);
  const setReduceMotion = useWorkspaceStore((s) => s.setReduceMotion);
  const listRef = useRef<HTMLUListElement>(null);
  // ★ Projects by name — once a survey has dozens of them, typing the site is
  //   faster than any list. Fails soft: offline, the palette is pages only.
  const projects = useProjects({ limit: 100 });
  const projectItems = projects.data?.items ?? [];

  // ── open on ⌘K / Ctrl-K, anywhere ──────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
        setQuery('');
        setActive(0);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const commands = useMemo((): Command[] => {
    const go = (path: string) => () => navigate(path);
    return [
      { label: 'Home', hint: '/', run: go('/') },
      { label: 'Dashboard', hint: '/dashboard', run: go('/dashboard') },
      { label: 'Workflow guide', hint: '/guide', run: go('/guide') },
      // ★ The pages, from the one registry the navbar renders — the tools a
      //   camera's settings open too, reachable by name — the hint is the page's
      //   own address.
      ...WORKSPACE_PAGES.map((page) => ({
        label: page.label,
        hint: page.path,
        run: go(page.path),
      })),
      { label: 'Change theme', hint: 'light · dark · system', run: toggle },
      {
        label: 'Switch language',
        hint: language === 'ar' ? 'English' : 'العربية',
        run: () => setLanguage(language === 'ar' ? 'en' : 'ar'),
      },
      {
        // ★ Field machines are not all fast — this is a first-class setting,
        //   not a buried checkbox. tokens.css collapses every duration on it.
        label: reduceMotion ? 'Turn animations on' : 'Reduce animation',
        hint: 'motion',
        run: () => setReduceMotion(!reduceMotion),
      },
      {
        // ★ Workspace actions: they flip layout state that only the workspace
        //   renders — harmless anywhere, meaningful where it counts.
        label: 'Focus the photograph',
        hint: '⇧F',
        run: () => useWorkspaceStore.getState().setFocusPane('image'),
      },
      {
        label: 'Focus the map',
        hint: '⇧F',
        run: () => useWorkspaceStore.getState().setFocusPane('map'),
      },
      {
        label: 'Exit focus mode',
        hint: 'esc',
        run: () => useWorkspaceStore.getState().setFocusPane(null),
      },
      {
        label: 'Swap the photo and map panes',
        hint: 'layout',
        run: () => useWorkspaceStore.getState().toggleSwapPanes(),
      },
      {
        label: 'Keyboard shortcuts',
        hint: '?',
        run: () => window.dispatchEvent(new CustomEvent('le:shortcuts')),
      },
      ...projectItems.map((p) => ({
        label: p.name,
        hint: `${t('project')} · ${p.image_count} ${t(p.image_count === 1 ? 'image' : 'images')}`,
        run: go(`/projects/${p.id}`),
      })),
    ];
  }, [navigate, toggle, language, reduceMotion, setReduceMotion, projectItems]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q === '') return commands;
    // English and translated label both match — see the header note.
    return commands.filter(
      (c) => c.label.toLowerCase().includes(q) || t(c.label).toLowerCase().includes(q),
    );
  }, [commands, query]);

  const runActive = (index: number): void => {
    const cmd = shown[index];
    if (cmd === undefined) return;
    setOpen(false);
    cmd.run();
  };

  return (
    <Dialog
      open={open}
      onClose={() => setOpen(false)}
      maxWidth="sm"
      fullWidth
      // ★ Near the top, like every palette people already know — centred dialogs
      //   are for decisions; palettes are for velocity.
      sx={{ '& .MuiDialog-container': { alignItems: 'flex-start', pt: '12vh' } }}
      PaperProps={{ sx: { borderRadius: 'var(--radius-lg)' } }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          px: 2,
          py: 1.25,
          borderBottom: '1px solid var(--hairline)',
        }}
      >
        <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
        <InputBase
          autoFocus
          fullWidth
          placeholder={t('Type a page or an action…')}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, shown.length - 1));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === 'Enter') {
              e.preventDefault();
              runActive(active);
            }
          }}
          inputProps={{ 'aria-label': t('Type a page or an action…') }}
        />
        <Typography className="le-mono" sx={{ fontSize: 10, color: 'text.disabled' }}>
          esc
        </Typography>
      </Box>
      <List ref={listRef} dense sx={{ maxHeight: '40vh', overflowY: 'auto', py: 0.5 }}>
        {shown.length === 0 && (
          <Typography
            variant="caption"
            sx={{ display: 'block', px: 2, py: 1.5, color: 'text.disabled' }}
          >
            {t('Nothing matches — try another word.')}
          </Typography>
        )}
        {shown.map((c, i) => (
          <ListItemButton
            key={`${i}:${c.label}`}
            selected={i === active}
            onMouseEnter={() => setActive(i)}
            onClick={() => runActive(i)}
            sx={{ mx: 0.5, borderRadius: 'var(--radius-sm)' }}
          >
            <ListItemText primaryTypographyProps={{ fontSize: 13 }} primary={t(c.label)} />
            {c.hint !== undefined && (
              <Typography className="le-mono" sx={{ fontSize: 10, color: 'text.disabled', ml: 2 }}>
                {c.hint}
              </Typography>
            )}
          </ListItemButton>
        ))}
      </List>
    </Dialog>
  );
}
