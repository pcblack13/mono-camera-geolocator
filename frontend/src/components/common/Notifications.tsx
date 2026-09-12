/**
 * `common/Notifications.tsx` — the app's toast channel.
 *
 * ★ NOT in 50-frontend §2's tree by this name. §2.1 names a "SnackbarProvider" that
 *   `AppShell` owns, and the optimistic-mutation contract (§3.3) calls
 *   `enqueueSnackbar(error, { variant: 'error' })`. No snackbar LIBRARY is in
 *   `package.json` (notistack is absent) and this environment cannot add one, so this
 *   is a minimal, self-contained provider over MUI's own `Snackbar` + `Alert`. Added
 *   "in the spirit of the tree" (§2) and flagged. If a snackbar dependency is later
 *   adopted, this file is the single swap point.
 *
 * ★ One host, one toast at a time with a FIFO queue — a field tablet stacking a dozen
 *   toasts is noise, not signal. Errors are `role="alert"` (assertive) via MUI's
 *   `Alert` and dwell longer so they are not missed.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type ReactNode,
} from 'react';
import Alert from '@mui/material/Alert';
import Snackbar from '@mui/material/Snackbar';

export type NotifySeverity = 'success' | 'info' | 'warning' | 'error';

export interface NotifyOptions {
  severity?: NotifySeverity;
  /** ms; `null` disables auto-hide. Errors default longer so they are not missed. */
  autoHideMs?: number | null;
}

export interface NotificationsContextValue {
  notify: (message: string, options?: NotifyOptions) => void;
}

interface Notice {
  key: number;
  message: string;
  severity: NotifySeverity;
  autoHideMs: number | null;
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

export function NotificationsProvider({ children }: { children: ReactNode }): JSX.Element {
  const [queue, setQueue] = useState<Notice[]>([]);
  const [current, setCurrent] = useState<Notice | null>(null);
  const [open, setOpen] = useState(false);
  const seqRef = useRef(0);

  // Promote the next queued notice whenever nothing is showing.
  useEffect(() => {
    if (current === null && queue.length > 0) {
      setCurrent(queue[0]);
      setQueue((q) => q.slice(1));
      setOpen(true);
    }
  }, [current, queue]);

  const notify = useCallback((message: string, options?: NotifyOptions) => {
    seqRef.current += 1;
    const severity = options?.severity ?? 'info';
    const notice: Notice = {
      key: seqRef.current,
      message,
      severity,
      autoHideMs:
        options?.autoHideMs === undefined
          ? severity === 'error'
            ? 8000
            : 4000
          : options.autoHideMs,
    };
    setQueue((q) => [...q, notice]);
  }, []);

  const handleClose = useCallback((_event: unknown, reason?: string) => {
    if (reason === 'clickaway') return;
    setOpen(false);
  }, []);

  const handleExited = useCallback(() => {
    setCurrent(null);
  }, []);

  const value = useMemo<NotificationsContextValue>(() => ({ notify }), [notify]);

  return (
    <NotificationsContext.Provider value={value}>
      {children}
      <Snackbar
        key={current?.key}
        open={open}
        autoHideDuration={current?.autoHideMs ?? undefined}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        TransitionProps={{ onExited: handleExited }}
      >
        {current ? (
          <Alert
            onClose={handleClose}
            severity={current.severity}
            variant="filled"
            sx={{ width: '100%' }}
          >
            {current.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </NotificationsContext.Provider>
  );
}

/**
 * The enqueue hook. Safe outside a provider — it degrades to a `console` line rather
 * than throwing, because a missing toast must never crash a survey flow (L11).
 */
export function useNotify(): (message: string, options?: NotifyOptions) => void {
  const ctx = useContext(NotificationsContext);
  return useCallback(
    (message: string, options?: NotifyOptions) => {
      if (ctx) {
        ctx.notify(message, options);
      } else if (typeof console !== 'undefined') {
        // eslint-disable-next-line no-console
        console.warn(`[notify:${options?.severity ?? 'info'}] ${message}`);
      }
    },
    [ctx],
  );
}

export default NotificationsProvider;
