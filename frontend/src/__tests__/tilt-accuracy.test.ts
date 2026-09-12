/**
 * Click accuracy under tilt — why the 3D pane measures its scale instead of deriving it.
 *
 * ★★ **THE FAILURE THIS GUARDS AGAINST IS A FLATTERING NUMBER.** `estimateClickAccuracy`
 *    computes ground-metres-per-pixel as `circumference · cos(lat) / worldPx`: a
 *    straight-down map. Under a pitched camera that is simply false — a pixel near the
 *    horizon covers far more ground than one at screen centre. Reusing the nadir figure in
 *    3D would report a click precision several times better than the surveyor achieved,
 *    and it would land on a survey deliverable looking exactly like a real measurement.
 *
 *    So the 3D pane unprojects two adjacent screen pixels, measures the true ground
 *    distance, and feeds it to {@link accuracyFromMetresPerPixel}. These tests pin the
 *    contract between the two: same quadrature, two ways of learning the scale.
 */

import { describe, expect, it } from 'vitest';

import {
  accuracyFromMetresPerPixel,
  estimateClickAccuracy,
  metresPerPixel,
} from '../components/map/tileMath';

const AT = { lat: 34.5, lon: 36.5 };
const ZOOM = 17;
const GEOREF_CE90 = 1.78; // Esri World Imagery's documented figure

describe('accuracyFromMetresPerPixel', () => {
  it('is what estimateClickAccuracy delegates to — one implementation, not two', () => {
    // ★ If these ever diverge, the 2D and 3D panes are quoting different maths for the
    //   same physical quantity, and a surveyor comparing them cannot tell which is right.
    const derived = estimateClickAccuracy(AT, ZOOM, GEOREF_CE90);
    const measured = accuracyFromMetresPerPixel(metresPerPixel(AT.lat, ZOOM, 256), GEOREF_CE90);
    expect(measured).toEqual(derived);
  });

  it('★ reports a WORSE accuracy as the ground scale coarsens', () => {
    // The whole point: a tilted pixel covers more ground, so precision must get worse.
    // A version that ignored the measured scale would return the same number for both.
    const atCentre = accuracyFromMetresPerPixel(0.3, GEOREF_CE90);
    const nearHorizon = accuracyFromMetresPerPixel(12.0, GEOREF_CE90);

    expect(nearHorizon.total_ce90_m).toBeGreaterThan(atCentre.total_ce90_m);
    expect(nearHorizon.click_ce90_m).toBeGreaterThan(atCentre.click_ce90_m);
  });

  it('★ quoting the nadir figure under tilt would understate the error many-fold', () => {
    // The concrete regression, expressed as a RATIO rather than absolute metres — the
    // absolute numbers depend on CLICK_PRECISION_PX and the CE90 sigma, which are policy
    // and may be retuned; the relationship between them is the invariant.
    const nadirMpp = metresPerPixel(AT.lat, ZOOM, 256);
    const tiltedMpp = 12.0;

    const nadir = estimateClickAccuracy(AT, ZOOM, GEOREF_CE90);
    const tilted = accuracyFromMetresPerPixel(tiltedMpp, GEOREF_CE90);

    // The click term scales linearly with ground resolution, so the understatement is
    // the full scale ratio — here roughly 12×.
    expect(tilted.click_ce90_m / nadir.click_ce90_m).toBeCloseTo(tiltedMpp / nadirMpp, 6);
    expect(tiltedMpp / nadirMpp).toBeGreaterThan(10);
  });

  it('names the click as the limiting term once the scale is coarse', () => {
    // ★ `dominant_term` is what tells a surveyor what to fix. Under heavy tilt the answer
    //   is "stop tilting / zoom in", not "the basemap's georeferencing is the problem".
    expect(accuracyFromMetresPerPixel(12.0, GEOREF_CE90).dominant_term).toBe('landmark_click');
    // Zoomed in and flat, the provider's own error takes over and no amount of care helps.
    expect(accuracyFromMetresPerPixel(0.05, GEOREF_CE90).dominant_term).toBe('georeference');
  });

  it('keeps the georeferencing term in quadrature, not added', () => {
    // Matches `GcpAccuracy.total_ce90_m` server-side; adding them would overstate the
    // error and, worse, put the preview on a different scale from the committed row.
    const result = accuracyFromMetresPerPixel(1.0, 3.0);
    const expected = Math.sqrt(result.click_ce90_m ** 2 + 3.0 ** 2);
    expect(result.total_ce90_m).toBeCloseTo(expected, 10);
  });

  it('treats a missing georeferencing figure as zero rather than NaN', () => {
    // A NaN would propagate silently into the readout and render as "—", hiding a real
    // click-precision number the surveyor could have acted on.
    const result = accuracyFromMetresPerPixel(1.0, Number.NaN);
    expect(Number.isFinite(result.total_ce90_m)).toBe(true);
    expect(result.georef_ce90_m).toBe(0);
  });
});
