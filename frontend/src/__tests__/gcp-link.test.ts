/**
 * Which GCP a landmark carries — the wire sends `gcp_ids`, never `gcp_id`.
 */

import { describe, expect, it } from 'vitest';

import { unlinkedGcps } from '../components/image/unlinkedGcps';
import { linkedGcpId } from '../lib/gcpLink';
import type { AnnotationRead } from '../types/annotation';
import type { Uuid } from '../types/common';
import type { GcpSummary } from '../types/gcp';

const G1 = 'aaaaaaaa-0000-0000-0000-000000000001' as Uuid;
const G2 = 'aaaaaaaa-0000-0000-0000-000000000002' as Uuid;

const annotation = (over: Partial<AnnotationRead>): AnnotationRead =>
  ({
    id: 'l1',
    gcp_id: null,
    gcp_ids: [],
    is_deleted: false,
    ...over,
  }) as unknown as AnnotationRead;

describe('linkedGcpId', () => {
  it('★ reads the list the server actually sends, falling back to the legacy scalar', () => {
    expect(linkedGcpId(annotation({ gcp_ids: [G1] }))).toBe(G1);
    expect(linkedGcpId(annotation({ gcp_id: G2, gcp_ids: [] }))).toBe(G2);
    expect(linkedGcpId(annotation({ gcp_ids: undefined, gcp_id: null }))).toBeNull();
    expect(linkedGcpId(annotation({}))).toBeNull();
  });
});

describe('unlinkedGcps with gcp_ids', () => {
  it('★ a landmark linked via gcp_ids is NOT drawn a second time as a bare GCP', () => {
    const gcps = [{ id: G1 }, { id: G2 }] as unknown as GcpSummary[];
    const annotations = [annotation({ gcp_ids: [G1] })];
    expect(unlinkedGcps(annotations, gcps).map((g) => g.id)).toEqual([G2]);
  });

  it('a deleted landmark hands its GCP back to the direct marker', () => {
    const gcps = [{ id: G1 }] as unknown as GcpSummary[];
    expect(unlinkedGcps([annotation({ gcp_ids: [G1], is_deleted: true })], gcps)).toHaveLength(1);
  });
});
