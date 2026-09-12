/**
 * `nativeFilePicker` — desktop-safe file picking.
 *
 * ★ In the desktop app, the in-page `<input type=file>` chooser is BANNED: on
 *   modern GNOME it either needs two attempts (GTK4) or SIGTRAPs the whole app
 *   while browsing (GTK3) — both reproduced in the field. The Electron preload
 *   exposes `window.leNative.pickFiles`, which runs an OUT-OF-PROCESS system
 *   dialog and returns the bytes. In a plain browser tab `leNative` is absent
 *   and callers fall back to their hidden `<input>` — same UX as always.
 *
 * Usage at a picker site:
 *   const files = await pickFilesNative(FILTERS, multiple);
 *   if (files === null) inputRef.current?.click();   // browser fallback
 *   else files.forEach(acceptFile);                  // may be [] on cancel
 */

export interface NativeFileFilter {
  name: string;
  /** Extensions WITHOUT dots, e.g. ['tif', 'tiff']. */
  extensions: string[];
}

interface NativePickedFile {
  name: string;
  data: Uint8Array;
}

/** A pick the main process REFUSED to load (unreadable, or beyond the 1 GiB
 *  bytes-over-IPC ceiling). Surfaced so a click never silently does nothing. */
export interface NativeSkippedFile {
  name: string;
  reason: string;
}

/** A path pick: name + absolute path + size, no bytes. The multi-GB route. */
export interface NativePickedPath {
  name: string;
  path: string;
  size: number;
}

/** Newer desktop shells return this; older ones returned a bare array. */
interface NativePickFilesResult {
  files: NativePickedFile[];
  skipped?: NativeSkippedFile[];
}

declare global {
  interface Window {
    leNative?: {
      pickFiles: (
        filters: NativeFileFilter[],
        multiple: boolean,
      ) => Promise<NativePickedFile[] | NativePickFilesResult>;
      /** Absent on desktop shells older than the source_path upload route. */
      pickPaths?: (filters: NativeFileFilter[], multiple: boolean) => Promise<NativePickedPath[]>;
      /** Absent on shells older than the live-capture save-to-folder feature. */
      pickDirectory?: () => Promise<string>;
    };
  }
}

/** True when running inside the desktop shell with the native picker available. */
export function hasNativePicker(): boolean {
  return typeof window !== 'undefined' && typeof window.leNative?.pickFiles === 'function';
}

/** True when the desktop shell can pick PATHS (the zero-copy, multi-GB route). */
export function hasNativePathPicker(): boolean {
  return typeof window !== 'undefined' && typeof window.leNative?.pickPaths === 'function';
}

/** True when the desktop shell can pick a FOLDER (live-capture save-to-directory). */
export function hasNativeDirectoryPicker(): boolean {
  return typeof window !== 'undefined' && typeof window.leNative?.pickDirectory === 'function';
}

/**
 * Pick a folder via the native dialog. Returns the absolute path, `''` if the user
 * cancelled, or `null` when there is no native picker (plain browser).
 */
export async function pickDirectoryNative(): Promise<string | null> {
  if (!hasNativeDirectoryPicker()) return null;
  return window.leNative!.pickDirectory!();
}

/**
 * Pick file PATHS via the native dialog — no bytes are read.
 * Returns `null` when unsupported (browser, or an old desktop shell);
 * `[]` when the user cancelled.
 */
export async function pickFilePathsNative(
  filters: NativeFileFilter[],
  multiple = false,
): Promise<NativePickedPath[] | null> {
  if (!hasNativePathPicker()) return null;
  return window.leNative!.pickPaths!(filters, multiple);
}

/** Known mimes in our `accept` attrs → extensions (zenity filters are glob-based). */
const MIME_EXTENSIONS: Record<string, string[]> = {
  'image/jpeg': ['jpg', 'jpeg'],
  'image/png': ['png'],
  'image/tiff': ['tif', 'tiff'],
  'image/tif': ['tif'],
  'text/csv': ['csv'],
  'application/json': ['json'],
  'application/geo+json': ['geojson'],
};

/** Wildcard `accept` families → the extensions our dialogs actually meet. */
const WILDCARD_EXTENSIONS: Record<string, string[]> = {
  'image/*': ['jpg', 'jpeg', 'png', 'tif', 'tiff', 'webp'],
  'video/*': [
    'mp4',
    'm4v',
    'mov',
    'qt',
    'avi',
    'mkv',
    'webm',
    'mpg',
    'mpeg',
    'ts',
    'mts',
    'm2ts',
    'wmv',
    'flv',
    '3gp',
  ],
};

/** Build native filters from an `<input accept="…">` string. */
export function filtersFromAccept(accept: string, label: string): NativeFileFilter[] {
  const extensions = new Set<string>();
  for (const raw of accept.split(',')) {
    const token = raw.trim().toLowerCase();
    if (token.startsWith('.')) extensions.add(token.slice(1));
    else if (token in MIME_EXTENSIONS) for (const e of MIME_EXTENSIONS[token]) extensions.add(e);
    else if (token in WILDCARD_EXTENSIONS)
      for (const e of WILDCARD_EXTENSIONS[token]) extensions.add(e);
  }
  return extensions.size > 0 ? [{ name: label, extensions: [...extensions] }] : [];
}

/**
 * The one-liner for picker sites: native dialog when available, else the
 * hidden `<input>`. `onFiles` fires only when the user actually picked.
 * `onSkipped` fires when the shell could not LOAD a pick (unreadable, or too
 * large for the in-memory route) — without it a skip looks like a dead click.
 */
export function browseNativeOrInput(
  input: HTMLInputElement | null,
  filters: NativeFileFilter[],
  onFiles: (files: File[]) => void,
  multiple = false,
  onSkipped?: (skipped: NativeSkippedFile[]) => void,
): void {
  void pickFilesNativeDetailed(filters, multiple).then((result) => {
    if (result === null) {
      input?.click();
      return;
    }
    if (result.skipped.length > 0) {
      if (onSkipped) onSkipped(result.skipped);
      // eslint-disable-next-line no-console
      else console.warn('native file pick skipped:', result.skipped);
    }
    if (result.files.length > 0) onFiles(result.files);
  });
}

/**
 * Pick files via the native out-of-process dialog, with the skip report.
 * Returns `null` when no native picker exists (browser — use the `<input>`).
 */
export async function pickFilesNativeDetailed(
  filters: NativeFileFilter[],
  multiple = false,
): Promise<{ files: File[]; skipped: NativeSkippedFile[] } | null> {
  if (!hasNativePicker()) return null;
  const raw = await window.leNative!.pickFiles(filters, multiple);
  // Old desktop shells returned a bare array; new ones return {files, skipped}.
  const picked = Array.isArray(raw) ? raw : raw.files;
  const skipped = Array.isArray(raw) ? [] : (raw.skipped ?? []);
  // ★ A typeless File goes over multipart as application/octet-stream, which the
  //   image upload endpoint (rightly) refuses — infer the MIME from the name,
  //   exactly as a browser's <input> would have.
  const files = picked.map(
    (f) => new File([f.data.slice().buffer as ArrayBuffer], f.name, { type: mimeFromName(f.name) }),
  );
  return { files, skipped };
}

/**
 * Pick files via the native out-of-process dialog.
 * Returns `null` when no native picker exists (browser — use the `<input>`);
 * `[]` when the user cancelled; otherwise real `File` objects.
 */
export async function pickFilesNative(
  filters: NativeFileFilter[],
  multiple = false,
): Promise<File[] | null> {
  const result = await pickFilesNativeDetailed(filters, multiple);
  return result === null ? null : result.files;
}

const EXT_MIME: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  tif: 'image/tiff',
  tiff: 'image/tiff',
  csv: 'text/csv',
  json: 'application/json',
  geojson: 'application/geo+json',
  kml: 'application/vnd.google-earth.kml+xml',
  kmz: 'application/vnd.google-earth.kmz',
};

function mimeFromName(name: string): string {
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : '';
  return EXT_MIME[ext] ?? '';
}
