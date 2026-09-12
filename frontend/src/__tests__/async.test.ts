/**
 * The two in-flight disciplines: last caller wins, and an effect’s request dies with it.
 */

import { describe, expect, it } from 'vitest';

import { createSequence, openEffectScope } from '../lib/async';

describe('createSequence', () => {
  it('★ only the newest ticket is current', () => {
    const seq = createSequence();
    const a = seq.next();
    const b = seq.next();
    expect(seq.isCurrent(a)).toBe(false);
    expect(seq.isCurrent(b)).toBe(true);
    seq.next();
    expect(seq.isCurrent(b)).toBe(false);
  });
});

describe('openEffectScope', () => {
  it('★ closing aborts the signal and flags the scope cancelled', () => {
    const scope = openEffectScope();
    expect(scope.cancelled).toBe(false);
    expect(scope.signal.aborted).toBe(false);
    scope.close();
    expect(scope.cancelled).toBe(true);
    expect(scope.signal.aborted).toBe(true);
  });
});
