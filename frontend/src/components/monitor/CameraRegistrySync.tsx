/**
 * `CameraRegistrySync` — keeps `cameraRegistryStore` a cache of the server (1.3).
 *
 * ★ ONE FETCH, THEN THE STORE. On mount (and on every window focus after that) the
 *   server's camera list replaces the cached one, so a camera registered on another
 *   machine appears here without a reload. Nothing else in the app calls
 *   `GET /cameras/all` — the store is the one reader and everything subscribes to it.
 *
 * ★ THE ONE-TIME MIGRATION. A browser that ran 1.2.x holds cameras only it knows
 *   (`le.cameras.v1`, ULID ids). The first time such a browser meets a 1.3 server it
 *   is asked ONCE whether to move them across — never silently, because a camera
 *   the server never heard of is a camera nobody else can see, and never twice,
 *   because a prompt that keeps coming back trains people to dismiss it. The
 *   answer is remembered in `localStorage` under `le.cameras.migrated.v1`, whichever
 *   way it went; the per-camera monitor setups follow the cameras to their new ids.
 */

import { useEffect, useState, type JSX } from 'react';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Typography from '@mui/material/Typography';

import { camerasApi } from '../../api/cameras';
import { useNotify } from '../common/Notifications';
import { t } from '../../i18n';
import { useCameraRegistryStore } from '../../store/cameraRegistryStore';

export const MIGRATION_FLAG = 'le.cameras.migrated.v1';

function migrationDecided(): boolean {
  try {
    return localStorage.getItem(MIGRATION_FLAG) !== null;
  } catch {
    return true; // no storage = nothing to migrate from
  }
}

function rememberDecision(value: 'imported' | 'discarded'): void {
  try {
    localStorage.setItem(MIGRATION_FLAG, value);
  } catch {
    /* a browser that refuses storage will simply ask again next launch */
  }
}

export function CameraRegistrySync(): JSX.Element | null {
  const notify = useNotify();
  const hydrate = useCameraRegistryStore((s) => s.hydrate);
  const legacy = useCameraRegistryStore((s) => s.legacy);
  const migrateLegacy = useCameraRegistryStore((s) => s.migrateLegacy);
  const discardLegacy = useCameraRegistryStore((s) => s.discardLegacy);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = (): void => {
      camerasApi
        .all()
        .then((rows) => {
          if (!cancelled) hydrate(rows);
        })
        .catch(() => {
          /* offline or the API is down: the cached list stays — the chip says so */
        });
    };
    load();
    window.addEventListener('focus', load);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', load);
    };
  }, [hydrate]);

  // Legacy rows that were already decided on are dropped without a word.
  useEffect(() => {
    if (legacy.length > 0 && migrationDecided()) discardLegacy();
  }, [legacy, discardLegacy]);

  const open = legacy.length > 0 && !migrationDecided();
  if (!open) return null;

  const onImport = (): void => {
    setBusy(true);
    migrateLegacy()
      .then((n) => {
        rememberDecision('imported');
        notify(`${n} ${t(n === 1 ? 'camera moved to the server.' : 'cameras moved to the server.')}`, {
          severity: 'success',
        });
      })
      .catch((err: unknown) => {
        notify(err instanceof Error ? err.message : t('The import failed.'), { severity: 'error' });
      })
      .finally(() => setBusy(false));
  };
  const onDiscard = (): void => {
    rememberDecision('discarded');
    discardLegacy();
  };

  return (
    <Dialog open aria-labelledby="camera-migration-title">
      <DialogTitle id="camera-migration-title">{t('Move your cameras to the server?')}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" sx={{ mb: 1 }}>
          {t('This browser holds')} {legacy.length}{' '}
          {t(legacy.length === 1 ? 'camera that the server does not know about.' : 'cameras that the server does not know about.')}{' '}
          {t(
            'Since 1.3 the camera list lives on the server, so every machine sees the same cameras and the app can restart their watches after a reboot.',
          )}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('Each camera’s saved detection setup moves with it. This is asked once.')}
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onDiscard} disabled={busy}>
          {t('Forget them')}
        </Button>
        <Button onClick={onImport} variant="contained" disabled={busy}>
          {t('Move to server')}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
