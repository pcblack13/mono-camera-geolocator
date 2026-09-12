/**
 * `lib/cameras/urlScheme.ts` — an address as a SCHEME plus the rest of it.
 *
 * ★ THE OPERATOR PICKS THE PROTOCOL, NEVER TYPES IT (2026-09-11, owner ask).
 *   "rtsp://" and "ws://" are the parts of an address that are chosen from a
 *   short list of things the server can actually open — so they are a dropdown,
 *   and what is left to type is the host and path. A scheme this app cannot
 *   open is not on the list, which is the only way the list stays honest.
 *
 * ★ AN UNKNOWN STORED SCHEME IS KEPT, NOT REWRITTEN. A camera saved before this
 *   list existed (or by hand) keeps whatever it has: the splitter returns it, the
 *   picker offers it alongside the known ones, and nothing changes until the
 *   operator chooses. Silently turning someone's address into a different one is
 *   how a working camera stops working overnight.
 */

/** What the capture can open — `live_stream_service._ALLOWED_SCHEMES`. */
export const STREAM_SCHEMES = ['rtsp://', 'http://', 'https://'] as const;

/** What a data feed can open — `live_data_service._FEED_SCHEMES`, minus serial
 *  (which has its own port + baud form). */
export const DATA_SCHEMES = ['http://', 'https://', 'ws://', 'wss://', 'tcp://'] as const;

export interface SchemeParts {
  /** Including the `://`, e.g. `rtsp://`. */
  scheme: string;
  /** Everything after it — host, port, path, query. */
  rest: string;
}

/**
 * Split an address into its scheme and the rest.
 *
 * An empty address takes `fallback` and an empty rest, so the picker opens on a
 * sensible protocol without inventing an address. An address whose scheme is not
 * in `schemes` keeps its own (see the header).
 */
export function splitScheme(
  url: string,
  schemes: readonly string[],
  fallback: string,
): SchemeParts {
  const value = (url ?? '').trim();
  if (value === '') return { scheme: fallback, rest: '' };
  const known = schemes.find((s) => value.toLowerCase().startsWith(s));
  if (known !== undefined) return { scheme: known, rest: value.slice(known.length) };
  const mark = value.indexOf('://');
  if (mark > 0) {
    return { scheme: value.slice(0, mark + 3).toLowerCase(), rest: value.slice(mark + 3) };
  }
  return { scheme: fallback, rest: value };
}

/**
 * Put an address back together.
 *
 * ★ An empty rest is an EMPTY ADDRESS, not a bare scheme: choosing a protocol
 *   before typing a host must not produce "rtsp://" and the validation error
 *   that comes with it.
 */
export function joinScheme(scheme: string, rest: string): string {
  const tail = (rest ?? '').trim();
  return tail === '' ? '' : `${scheme}${tail}`;
}

/** The schemes to offer: the known ones, plus `current` when it is not among them. */
export function schemeOptions(schemes: readonly string[], current: string): string[] {
  return schemes.includes(current) ? [...schemes] : [...schemes, current];
}
