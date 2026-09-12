/**
 * `lib/drift/bannerDismissal.ts` — when the operator has closed the drift banner.
 *
 * ★ TWO WAYS TO CLOSE IT (owner ask 2026-09-10). "Show later" snoozes the banner
 *   for a while; "Don't show again" silences it for THIS reference's alarm. Both
 *   are keyed by reference AND verdict, so a re-frozen reference — or the same
 *   camera going from MOVED to CHANGED — is a new alarm and is shown again. The
 *   record lives in localStorage, so a reload does not bring back what was
 *   silenced; nothing here is ever sent to the server.
 */

export const STORAGE_KEY = 'landexplorer.driftBanner.closed';
export const SHOW_LATER_MS = 30 * 60 * 1000;

/** `until` is epoch ms, or `'never'`. */
type Record_ = Record<string, number | 'never'>;

export function bannerKey(refId: string, status: string): string {
  return `${refId}:${status}`;
}

function read(storage: Storage | null): Record_ {
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed !== null && typeof parsed === 'object' ? (parsed as Record_) : {};
  } catch {
    return {};
  }
}

function write(storage: Storage | null, rec: Record_): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(rec));
  } catch {
    // storage blocked — the banner will simply return on the next mount
  }
}

function storageOf(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

/** True while the banner for `key` should stay hidden. */
export function isClosed(key: string, now = Date.now(), storage = storageOf()): boolean {
  const until = read(storage)[key];
  if (until === undefined) return false;
  if (until === 'never') return true;
  return typeof until === 'number' && until > now;
}

export function showLater(key: string, now = Date.now(), storage = storageOf()): void {
  const rec = read(storage);
  rec[key] = now + SHOW_LATER_MS;
  write(storage, rec);
}

export function dontShowAgain(key: string, storage = storageOf()): void {
  const rec = read(storage);
  rec[key] = 'never';
  write(storage, rec);
}

/** For tests and a future "reset" button. */
export function clearClosed(storage = storageOf()): void {
  try {
    storage?.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
