/**
 * The camera draft — the one camera being set up before it is on the server.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { EMPTY_DRAFT, draftHasContent, useCameraDraftStore } from '../store/cameraDraftStore';

beforeEach(() => {
  useCameraDraftStore.setState({ draft: EMPTY_DRAFT, touchedAt: null });
});

describe('the camera draft', () => {
  it('starts empty, patches field by field, and knows when it has content', () => {
    expect(draftHasContent(useCameraDraftStore.getState().draft)).toBe(false);
    useCameraDraftStore.getState().patch({ name: 'Gate' });
    useCameraDraftStore.getState().patch({ calibration: { fx: '1200' } });
    const d = useCameraDraftStore.getState().draft;
    expect(d.name).toBe('Gate');
    expect(d.calibration.fx).toBe('1200');
    expect(d.connection).toBe('lan');
    expect(draftHasContent(d)).toBe(true);
    expect(useCameraDraftStore.getState().touchedAt).not.toBeNull();
  });

  it('★ the server-side ids the later steps produce ride the draft until Add camera', () => {
    useCameraDraftStore.getState().patch({ project_id: 'p1', frame_image_id: 'i1' });
    useCameraDraftStore.getState().patch({ lut_site: 'gate' });
    expect(useCameraDraftStore.getState().draft).toMatchObject({
      project_id: 'p1',
      frame_image_id: 'i1',
      lut_site: 'gate',
    });
    useCameraDraftStore.getState().clear();
    expect(useCameraDraftStore.getState().draft).toEqual(EMPTY_DRAFT);
    expect(useCameraDraftStore.getState().touchedAt).toBeNull();
  });
});
