/**
 * `shell/PageNavBar.tsx` — one slim bar under the top bar: back, and the editor's Save.
 *
 * ★ THE WORKCHAIN IS GONE (2026-09-07, owner decision). This bar used to carry a
 *   strip of open pages as tabs, kept in a persisted store and restored at launch.
 *   The navbar's three page tabs are the navigation now, so a second row of tabs
 *   was a second answer to a question already answered. What remains is the one
 *   thing the bar was also for: a way back.
 *
 * ★ BACK LEADS THE ROW, and it means "where I came from", not "up the hierarchy".
 *   `navigate(-1)` replays however the surveyor happened to arrive — after a deep
 *   link it leaves the app entirely — so the app keeps its own visit stack
 *   (`navHistoryStore`) and names the destination from it. The structural parent
 *   (`pageNav.ts`) remains the fallback for a COLD ENTRY, where there genuinely is
 *   no previous page.
 *
 * ★ THE SAVE BUTTON EXISTS ONLY WHERE A DRAFT EXISTS. Everywhere else in the product a
 *   mutation commits the moment it happens — a camera is added on click, a GCP on
 *   commit, a DEM on upload. A Save button on those pages would be a control that does
 *   nothing, which is the same class of dishonesty as a fabricated number. The one page
 *   with genuinely unsaved state is the editor (the annotation draft, debounced
 *   autosave), so that page gets a real Save with a live status; the rest get none.
 */

import { useEffect, type JSX } from 'react';
import { matchPath, useLocation, useNavigate, useNavigationType } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import { useTheme } from '@mui/material/styles';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import SaveOutlinedIcon from '@mui/icons-material/SaveOutlined';

import { asUuid, type Uuid } from '../../types/common';
import { useSaveAnnotationsNow } from '../../api/hooks/useSaveAnnotationsNow';
import { useNavHistoryStore } from '../../store/navHistoryStore';
import { resolvePageNav } from './pageNav';
import { t } from '../../i18n';

export function PageNavBar(): JSX.Element | null {
  const navigate = useNavigate();
  // ★ The arrow points where "back" is: left in English, right in Arabic.
  const rtl = useTheme().direction === 'rtl';
  const { pathname, search } = useLocation();
  const nav = resolvePageNav(pathname, search);

  const visit = useNavHistoryStore((s) => s.visit);
  const replaceVisit = useNavHistoryStore((s) => s.replaceVisit);
  const previousPath = useNavHistoryStore((s) =>
    s.stack.length >= 2 ? s.stack[s.stack.length - 2] : null,
  );
  const navigationType = useNavigationType();
  // ★ `search` is part of the identity: `?tab=videos` IS the Video editor page.
  const here = `${pathname}${search}`;
  useEffect(() => {
    // ★ A REDIRECT REPLACES, IT DOES NOT ADVANCE. The editor forwards an
    //   un-set-up photo to its setup page; recording that as a step left the
    //   forwarding URL in the trail, so "back" bounced straight forward again.
    if (navigationType === 'REPLACE') replaceVisit(here);
    else visit(here);
  }, [here, navigationType, replaceVisit, visit]);

  const backTo = previousPath ?? nav.parent;
  const backTitle =
    previousPath !== null
      ? // Titles are keyed by PATH + query, so hand both halves over.
        resolvePageNav(...splitLocation(previousPath)).title
      : nav.parentTitle;

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'stretch',
        gap: 1,
        px: 1.5,
        flexShrink: 0,
        minHeight: 36,
        borderBottom: 1,
        borderColor: 'divider',
        bgcolor: 'background.paper',
      }}
    >
      {/* ★ THE BACK CONTROL LEADS, and NAMES ITS DESTINATION, not the current
          page: "← Home" says where the press lands. The page you are on is named
          by the page itself, so it is not repeated here. */}
      <Box sx={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
        {backTo !== null ? (
          <Button
            size="small"
            color="inherit"
            startIcon={
              rtl ? <ArrowForwardIcon fontSize="small" /> : <ArrowBackIcon fontSize="small" />
            }
            aria-label={`${t('Back to')} ${t(backTitle ?? '')}`}
            onClick={() => navigate(backTo)}
            sx={{ fontWeight: 600, textTransform: 'none', whiteSpace: 'nowrap' }}
          >
            {t(backTitle ?? '')}
          </Button>
        ) : (
          // ★ ONLY the root shows its own name — with no back control the bar
          //   would otherwise be blank.
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {t(nav.title)}
          </Typography>
        )}
      </Box>

      <Box sx={{ flexGrow: 1 }} />

      {nav.hasDraft && (
        <Box sx={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
          <WorkspaceSave />
        </Box>
      )}
    </Box>
  );
}

/** `'/projects?tab=dem'` → `['/projects', '?tab=dem']`. */
function splitLocation(location: string): [string, string] {
  const q = location.indexOf('?');
  return q === -1 ? [location, ''] : [location.slice(0, q), location.slice(q)];
}

/**
 * The editor's save control — a real button over the real draft.
 *
 * Split out so the store subscription exists only on the route that has a draft.
 * ★ Ids come from `matchPath` on the pathname, NOT `useParams`: this bar mounts in the
 *   SHELL, above the route outlet, where the route context has no params — `useParams`
 *   here would quietly return `{}` and the save would silently no-op.
 */
function WorkspaceSave(): JSX.Element {
  const { pathname } = useLocation();
  const match = matchPath('/projects/:projectId/images/:imageId', pathname);
  const imageId: Uuid | null = match?.params.imageId ? asUuid(match.params.imageId) : null;
  const projectId: Uuid | undefined = match?.params.projectId
    ? asUuid(match.params.projectId)
    : undefined;

  const { save, saving, dirty, lastSavedAt } = useSaveAnnotationsNow(imageId, projectId);

  if (!dirty && lastSavedAt === null) {
    // Nothing ever edited this session: show nothing rather than a disabled control
    // that begs the question of what it would have saved.
    return <Box />;
  }

  if (!dirty) {
    return (
      <Typography
        variant="caption"
        sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: 'success.main' }}
      >
        <CheckCircleOutlineIcon sx={{ fontSize: 16 }} />
        {t('All changes saved')}
      </Typography>
    );
  }

  return (
    <Button
      size="small"
      variant="outlined"
      startIcon={<SaveOutlinedIcon fontSize="small" />}
      onClick={save}
      disabled={saving}
    >
      {saving ? t('Saving…') : t('Save')}
    </Button>
  );
}

export default PageNavBar;
