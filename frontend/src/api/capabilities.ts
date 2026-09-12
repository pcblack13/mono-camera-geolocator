/**
 * Capabilities and health — endpoints 1–3 (§7).
 *
 * ★★ `GET /capabilities` IS THE UI'S DEFERRAL GATE (SCOPE.md §4 rule 4).
 *    `CapabilitiesResponse.deferred_features` is the server-provided list of what this
 *    build does not implement, and the UI gates controls off **that one list** rather
 *    than a hard-coded constant — because SCOPE.md §7 requires that re-enabling the
 *    engine need no change outside `ai_engine/` plus flipping the endpoints. A
 *    hard-coded `DEFERRED = ['matching', …]` in the frontend would be exactly the
 *    change §7 forbids.
 *
 * ★ The report is computed ONCE in `main.py`'s lifespan and cached on `app.state`
 *   (§11.1); this endpoint reads the cache and never re-resolves. It is cheap, and
 *   `useCapabilities` treats it as near-immutable for the session.
 */

import type {
  CapabilitiesResponse,
  HealthResponse,
  LogsResponse,
  ReadinessResponse,
} from '../types/capabilities';
import { fetchJson } from './client';

export const capabilitiesApi = {
  /** Endpoint 3 — `GET /capabilities` → `200 CapabilitiesResponse`. */
  get: (signal?: AbortSignal): Promise<CapabilitiesResponse> =>
    fetchJson<CapabilitiesResponse>('/capabilities', { signal }),

  /**
   * Endpoint 1 — `GET /health` → `200 HealthResponse`.
   *
   * ★ Touches no dependency. A liveness probe that checks Postgres restarts every API
   *   container when Postgres blips, turning a 30-second hiccup into a full outage.
   */
  health: (signal?: AbortSignal): Promise<HealthResponse> =>
    fetchJson<HealthResponse>('/health', { signal }),

  /**
   * Endpoint 2 — `GET /health/ready` → `200`/`503 ReadinessResponse`.
   *
   * ★★ THE SINGLE EXPLICIT EXCEPTION TO THE ERROR ENVELOPE (§6.2): on `503` this
   *    returns a `ReadinessResponse`, **not** an `ErrorEnvelope` — a probe wants the
   *    check detail, and a not-ready instance is not an application error.
   *
   *    So `503` is passed to `okStatuses` and **this never throws on a not-ready
   *    instance**: the caller reads `status` and `components` and renders which
   *    dependency is down. A readiness endpoint that hides its diagnostics exactly
   *    when the system is unhealthy is useless (§7.1).
   *
   * ★ `check` is CSV (§7). `postgres` · `redis` · `storage` · `celery` · `imagery` ·
   *   `models` · `raster`. Only the first three gate readiness; the rest report
   *   `degraded` and still answer `200` — returning `503` because no worker is running
   *   would take the whole UI offline, **including the screen that would tell the
   *   operator the workers are down**.
   */
  readiness: (
    checks?: string[],
    verbose = false,
    signal?: AbortSignal,
  ): Promise<ReadinessResponse> =>
    fetchJson<ReadinessResponse>('/health/ready', {
      query: { verbose, check: checks },
      okStatuses: [503],
      signal,
    }),

  /**
   * `GET /health/logs` → `200 LogsResponse` — the app-status page's log monitor.
   *
   * ★ `after` is `LogsResponse.last_seq` from the previous poll, so a quiet poll
   *   ships nothing. Level/search filtering happens CLIENT-side on the page (the
   *   tail is already local); the server params exist for probes and slow links.
   */
  logs: (after = 0, limit = 1000, signal?: AbortSignal): Promise<LogsResponse> =>
    fetchJson<LogsResponse>('/health/logs', { query: { after, limit }, signal }),
};
