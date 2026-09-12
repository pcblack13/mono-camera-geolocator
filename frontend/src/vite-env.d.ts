/// <reference types="vite/client" />

/**
 * ★ The frontend's env surface — CONTRACT.md §9.11, exhaustively.
 *
 * ★ `VITE_*` IS BUILD-TIME AND NEVER SECRET. Anything here is compiled into the
 *   bundle and is public (§7). "There is no way to call a keyed tile API from a
 *   browser without exposing the key" — which is precisely why keyed providers are
 *   proxied server-side (endpoint 52) and why no `VITE_*_TOKEN` exists or ever may.
 *
 * ★ L10's spirit applies here too: every var has a working default and the app never
 *   requires one to be set. `docker compose up` with an empty `.env` yields a
 *   working app on the keyless provider (L2).
 *
 * ★ DELETED, deliberately, so nobody re-adds them:
 *   - `VITE_MAP_TILE_URL` / `VITE_MAP_ATTRIBUTION` — the backend is the single
 *     source of truth for provider config; the SPA calls `GET /imagery/providers`.
 *     An escape hatch that lets the bundle disagree with the server about which
 *     provider's ToS applies is exactly the divergence this system cannot afford.
 *   - `VITE_JOB_SSE_ENABLED` — SSE is out of scope for v1 (§12 C-07). Polling +
 *     `?wait=` long-poll only.
 */
interface ImportMetaEnv {
  /** Default `/api/v1`. Same-origin in dev (Vite proxy) and prod (nginx). */
  readonly VITE_API_BASE_URL?: string;
  /** Default `Mono Camera Geolocator`. Consumer: `shell/TopBar`. */
  readonly VITE_APP_NAME?: string;
  /** Default `0,0` — `"lat,lon"`. Consumer: `store/mapStore`. */
  readonly VITE_MAP_DEFAULT_CENTER?: string;
  /** Default `3`. Consumer: `store/mapStore`. */
  readonly VITE_MAP_DEFAULT_ZOOM?: string;
  /** Default `1500`. ★ The FLOOR for `useJob`'s adaptive schedule (§8.4). */
  readonly VITE_JOB_POLL_INTERVAL_MS?: string;
  /** Default `500`. Mirrors `LE_UPLOAD_MAX_BYTES` (§12 C-06). Consumer: `upload/UploadDropzone`. */
  readonly VITE_MAX_UPLOAD_MB?: string;
  /** Default `false`. Consumer: `main.tsx`. */
  readonly VITE_ENABLE_DEVTOOLS?: string;
  /** Default `4` — ★ a homography needs ≥ 4. Consumer: `annotation/AnnotationToolbar`. */
  readonly VITE_MIN_LANDMARKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
