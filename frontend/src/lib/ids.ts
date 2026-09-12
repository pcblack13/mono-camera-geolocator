/**
 * `lib/ids.ts` — client-side ids that work on EVERY origin.
 *
 * ★ `crypto.randomUUID()` exists only in secure contexts (https, localhost). The
 *   desktop loads from 127.0.0.1 and is fine; a laptop browsing a served build at
 *   `http://192.168.x.y` is not — and every id-creating action in the editor
 *   (open a correspondence, draw a shape, undo, queue an upload) threw there.
 *   `getRandomValues` is available everywhere; a v4 UUID from it is the fallback.
 */

export function newId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
