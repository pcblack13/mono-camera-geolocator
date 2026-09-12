/**
 * Which drift verdict is shown — the newest, whoever produced it.
 */

import { describe, expect, it } from 'vitest';

import type { DriftVerdict } from '../api/drift';
import { freshestVerdict } from '../components/drift/verdict';

const v = (checked_utc: string, why: string): DriftVerdict =>
  ({ checked_utc, why, state: 'OK', status: 'OK' }) as unknown as DriftVerdict;

describe('freshestVerdict', () => {
  it('★ a fresh manual check outranks a stopped monitor’s last reading', () => {
    const monitorLast = v('2026-08-24T10:00:00Z', 'from the watch, before Stop');
    const manual = v('2026-08-24T10:05:00Z', 'Check now');
    expect(freshestVerdict(monitorLast, null, manual)?.why).toBe('Check now');
  });

  it('a running watch that checked more recently still wins', () => {
    const monitorLast = v('2026-08-24T10:06:00Z', 'the clock');
    const manual = v('2026-08-24T10:05:00Z', 'Check now');
    expect(freshestVerdict(monitorLast, null, manual)?.why).toBe('the clock');
  });

  it('ignores blanks and returns null when nothing has been judged', () => {
    expect(freshestVerdict(null, undefined, null)).toBeNull();
    expect(freshestVerdict(undefined, v('2026-01-01T00:00:00Z', 'only'))?.why).toBe('only');
  });
});
