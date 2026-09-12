import { describe, expect, it } from 'vitest';

import { gcpBounds } from '../lib/geo/gcpBounds';

describe('gcpBounds', () => {
  it('frames the points with a margin, and a floor for a tight cluster', () => {
    const b = gcpBounds([
      { lat: 34.104, lon: 36.016 },
      { lat: 34.108, lon: 36.021 },
    ]);
    expect(b).not.toBeNull();
    // 20 % padding on each side of the span
    expect(b!.min_lat).toBeCloseTo(34.104 - 0.004 * 0.2, 6);
    expect(b!.max_lon).toBeCloseTo(36.021 + 0.005 * 0.2, 6);
    const one = gcpBounds([{ lat: 34.1, lon: 36.0 }])!;
    expect(one.max_lat - one.min_lat).toBeCloseTo(0.0016, 6);
  });

  it('is null for nothing, and ignores a point that is not a number', () => {
    expect(gcpBounds([])).toBeNull();
    expect(gcpBounds([{ lat: Number.NaN, lon: 1 }])).toBeNull();
  });
});
