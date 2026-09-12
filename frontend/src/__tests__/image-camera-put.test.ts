/**
 * `toPutBody` — the station written back "verbatim" (the editor's Auto toggle).
 *
 * ★ What this pins (2026-09-09): the PUT is full-replace, and the no-calibration
 *   mode plus its seed used to be LEFT OUT — so one flip of Auto in the editor
 *   reset a no-calibration station to "calibrated with no focal", the typed seed
 *   vanished, and every solve was refused for "no intrinsics" (Yamouneh2).
 */

import { describe, expect, it } from 'vitest';

import { toPutBody } from '../api/imageCamera';
import type { ImageCameraRead } from '../types/imageCamera';

const STATION: ImageCameraRead = {
  image_id: '00000000-0000-4000-8000-000000000801',
  configured: true,
  fx: null,
  fy: null,
  cx: 960,
  cy: 540,
  k1: null,
  k2: null,
  p1: null,
  p2: null,
  k3: null,
  img_w: 1920,
  img_h: 1080,
  no_calibration: true,
  fov_h_deg: 60,
  fov_v_deg: null,
  lat: 34.104413,
  lon: 36.015973,
  mast_offset_m: null,
  tilt_deg: null,
  auto_gcp_enabled: false,
  created_at: '2026-09-09T05:33:08Z',
  updated_at: '2026-09-09T06:13:41Z',
} as ImageCameraRead;

describe('toPutBody', () => {
  it('★ carries the no-calibration mode and its seed — a write-back must not wipe them', () => {
    const body = toPutBody(STATION);
    expect(body).toMatchObject({
      no_calibration: true,
      fov_h_deg: 60,
      fov_v_deg: null,
      fx: null,
      fy: null,
      cx: 960,
      cy: 540,
      lat: 34.104413,
      lon: 36.015973,
      auto_gcp_enabled: false,
    });
    // …and the editor's toggle changes ONLY the flag it owns
    expect({ ...body, auto_gcp_enabled: true }).toMatchObject({ no_calibration: true, fov_h_deg: 60 });
  });

  it('a calibrated station stays calibrated', () => {
    const body = toPutBody({ ...STATION, fx: 2800, fy: 2800, no_calibration: false, fov_h_deg: null });
    expect(body).toMatchObject({ no_calibration: false, fov_h_deg: null, fx: 2800, fy: 2800 });
  });
});
