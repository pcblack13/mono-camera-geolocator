/**
 * The camera export — one door that takes the whole camera (2026-09-12, owner ask).
 *
 * ★ What these pin: the URL the buttons point at is the one endpoint that builds
 *   the bundle, and it is offered ONLY for a camera that exists on the server —
 *   a camera still being typed has nothing to export yet.
 */

import { describe, expect, it } from 'vitest';

import { camerasApi } from '../api/cameras';
import { API_BASE_URL } from '../api/client';
import { asUuid } from '../types/common';

const CAMERA = asUuid('11111111-1111-1111-1111-111111111111');

describe('the camera export URL', () => {
  it('★ points at the endpoint that assembles the whole camera', () => {
    expect(camerasApi.exportUrl(CAMERA)).toBe(`${API_BASE_URL}/cameras/${CAMERA}/export`);
  });

  it('★ is a plain URL, so the browser downloads it rather than the app buffering it', () => {
    // A camera bundle carries the frame, the DEM and the LUT — tens of megabytes.
    // Fetching that into memory to hand it back to a link would be a waste; the
    // buttons are anchors pointed straight here.
    const url = camerasApi.exportUrl(CAMERA);
    expect(typeof url).toBe('string');
    expect(url.endsWith('/export')).toBe(true);
  });
});
