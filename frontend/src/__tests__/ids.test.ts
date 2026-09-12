/**
 * Client ids on every origin — the editor must not depend on a secure context.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { newId } from '../lib/ids';

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('newId', () => {
  afterEach(() => vi.restoreAllMocks());

  it('is a v4 UUID', () => {
    expect(newId()).toMatch(V4);
    expect(newId()).not.toBe(newId());
  });

  it('★ still works when crypto.randomUUID is absent (plain-http LAN origin)', () => {
    const c = globalThis.crypto;
    vi.spyOn(globalThis, 'crypto', 'get').mockReturnValue({
      getRandomValues: c.getRandomValues.bind(c),
    } as unknown as Crypto);
    expect(typeof (globalThis.crypto as { randomUUID?: unknown }).randomUUID).toBe('undefined');
    expect(newId()).toMatch(V4);
  });
});
