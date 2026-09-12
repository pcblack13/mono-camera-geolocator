/**
 * Bare-click GCPs must keep a marker on the photo after commit.
 *
 * ★ THE BUG THIS GUARDS. While a correspondence is open, the photo marker belongs to
 *   `correspondenceStore` and rightly disappears on commit. An annotation-linked GCP is
 *   then drawn by its annotation — but a BARE-CLICK GCP has no annotation, so nothing
 *   drew it at all: the point sat in the table and on the map while vanishing from the
 *   very photograph it was placed on.
 *
 * `unlinkedGcps` is the pure selection the layer renders from; testing it directly
 * avoids mounting Konva (which jsdom cannot host without a canvas shim).
 */

import { describe, expect, it } from 'vitest';

import { unlinkedGcps } from '../components/image/unlinkedGcps';
import type { AnnotationRead } from '../types/annotation';
import type { GcpSummary } from '../types/gcp';

function gcp(id: string): GcpSummary {
  return {
    id,
    image_id: 'img-1',
    code: null,
    image_px: { x: 100, y: 200 },
    lat: 34.1,
    lon: 36.0,
    source: 'manual',
    confidence: 80,
    declared_confidence: 4,
    total_ce90_m: 8,
    manually_adjusted: false,
    is_stale: false,
  } as unknown as GcpSummary;
}

function annotation(id: string, gcpId: string | null, deleted = false): AnnotationRead {
  return {
    id,
    gcp_id: gcpId,
    is_deleted: deleted,
    geom_type: 'point',
    pixel_x: 10,
    pixel_y: 20,
  } as unknown as AnnotationRead;
}

describe('unlinkedGcps', () => {
  it('★ a bare-click GCP (no annotation) is selected for direct drawing', () => {
    // The commit-then-vanish scenario: one committed GCP, zero annotations.
    const result = unlinkedGcps([], [gcp('g1')]);
    expect(result.map((g) => g.id)).toEqual(['g1']);
  });

  it('an annotation-linked GCP is NOT drawn twice', () => {
    const result = unlinkedGcps([annotation('a1', 'g1')], [gcp('g1')]);
    expect(result).toEqual([]);
  });

  it('★ a DELETED annotation no longer represents its GCP — falls through to direct', () => {
    // Deleting the landmark must not make the committed point invisible.
    const result = unlinkedGcps([annotation('a1', 'g1', true)], [gcp('g1')]);
    expect(result.map((g) => g.id)).toEqual(['g1']);
  });

  it('mixed: only the bare ones are selected', () => {
    const result = unlinkedGcps(
      [annotation('a1', 'g1'), annotation('a2', null)],
      [gcp('g1'), gcp('g2'), gcp('g3')],
    );
    expect(result.map((g) => g.id)).toEqual(['g2', 'g3']);
  });
});
