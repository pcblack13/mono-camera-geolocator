/**
 * Browser download helpers — CONTRACT.md §2.5 (`lib/download.ts`).
 *
 * ★ **No `fetch` here.** `src/api/` is the only `fetch()` in the app (§2.5). These
 *   functions take a `Blob` or a URL that the API layer already produced and hand it
 *   to the browser. Keeping the network out of this file is what stops it from
 *   growing into a second, unauthenticated API client.
 *
 * **Pure-ish**: touches only `document`/`URL`, never React and never a store.
 */

/**
 * ★ Every object URL created here is revoked. A leaked object URL pins the whole
 *   blob in memory for the document's lifetime — and an export of a few thousand
 *   GCPs plus a PDF report is not small. `uploadStore` makes the same promise about
 *   its preview URLs, for the same reason.
 *
 * The revoke is deferred a tick: Safari and Firefox have historically cancelled an
 * in-flight download when the URL was revoked synchronously after `click()`.
 */
const REVOKE_DELAY_MS = 1000;

function triggerAnchorDownload(href: string, filename: string, revoke: boolean): void {
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  a.rel = 'noopener';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  if (revoke) {
    window.setTimeout(() => URL.revokeObjectURL(href), REVOKE_DELAY_MS);
  }
}

/** Save a `Blob` to disk under `filename`. */
export function downloadBlob(blob: Blob, filename: string): void {
  triggerAnchorDownload(URL.createObjectURL(blob), filename, true);
}

/**
 * Save a server-hosted artefact (a signed export URL from `ExportRead.download_url`).
 *
 * ★ Not revoked — it is not an object URL. `download` is only honoured same-origin
 *   or with `Content-Disposition`, which the API sets; cross-origin without it the
 *   browser navigates instead, which is the correct fallback rather than a silent
 *   no-op.
 */
export function downloadUrl(url: string, filename: string): void {
  triggerAnchorDownload(url, filename, false);
}

/** Save a UTF-8 text payload (CSV, GeoJSON, KML) built client-side. */
export function downloadText(
  text: string,
  filename: string,
  mimeType = 'text/plain;charset=utf-8',
): void {
  downloadBlob(new Blob([text], { type: mimeType }), filename);
}

/**
 * A filesystem-safe filename: `landexplorer_gcps_2026-07-17.csv`.
 *
 * ★ Sanitised, not merely concatenated. A project name is user input and reaches
 *   this function verbatim; `../` in a download name is a real (if mild) escape, and
 *   a colon or slash simply fails to save on Windows/macOS. The surveyor should not
 *   discover that when the export they waited for silently does not appear.
 */
export function safeFilename(base: string, extension: string, date: Date = new Date()): string {
  const stem =
    base
      .normalize('NFKD')
      .replace(/[^\w\s.-]/g, '')
      .trim()
      .replace(/[\s_]+/g, '_')
      .replace(/^[._]+|[._]+$/g, '')
      .slice(0, 80) || 'landexplorer';

  const stamp = date.toISOString().slice(0, 10);
  const ext = extension.replace(/^\./, '');
  return `${stem}_${stamp}.${ext}`;
}
