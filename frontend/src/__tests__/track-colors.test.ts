/**
 * Track colours on the live map — an identity keeps one hue, and two identities
 * never share one (within the palette's size).
 *
 * ★ WHY. Two tracked cars are the same class; colouring by class painted both
 *   trails identically and the map could not say which route was whose. The
 *   marks now colour by TRACK — these pin the contract that makes that reading
 *   trustworthy.
 */

import { describe, expect, it } from 'vitest';

import {
  DETECTION_CLASS_COLOURS,
  DETECTION_CLASS_FALLBACK,
  DETECTION_TRACK_COLOURS,
  detectionMarkColour,
  detectionTrackColour,
} from '../theme/dataColors';

describe('track colours', () => {
  it('★ two tracks get two different colours — the whole point', () => {
    expect(detectionTrackColour(1)).not.toBe(detectionTrackColour(2));
    // Every pair within one palette cycle is distinct.
    const cycle = DETECTION_TRACK_COLOURS.map((_c, i) => detectionTrackColour(i));
    expect(new Set(cycle).size).toBe(DETECTION_TRACK_COLOURS.length);
  });

  it('a track keeps its colour for the whole run', () => {
    expect(detectionTrackColour(3)).toBe(detectionTrackColour(3));
  });

  it('cycles rather than crashing when tracks outnumber the palette', () => {
    const n = DETECTION_TRACK_COLOURS.length;
    expect(detectionTrackColour(n)).toBe(detectionTrackColour(0));
    expect(detectionTrackColour(n + 1)).toBe(detectionTrackColour(1));
  });

  it('★ a mark WITH a track wears the track hue; an untracked sighting keeps its class hue', () => {
    expect(detectionMarkColour('car', 1)).toBe(detectionTrackColour(1));
    // Two cars, two tracks — different colours despite the shared class.
    expect(detectionMarkColour('car', 1)).not.toBe(detectionMarkColour('car', 2));
    // No identity yet → the class speaks.
    expect(detectionMarkColour('car', null)).toBe(DETECTION_CLASS_COLOURS.car);
    expect(detectionMarkColour('llama', null)).toBe(DETECTION_CLASS_FALLBACK);
  });

  it('every palette entry is a parseable hex colour (an unparseable one draws NOTHING)', () => {
    for (const c of DETECTION_TRACK_COLOURS) expect(c).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });
});
