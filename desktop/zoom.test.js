'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { autoZoomFor, clampZoom, stepZoom, normalisePreference, ZOOM_STEPS } = require('./zoom');

test('★ a 4K panel the OS reports at scale 1 is drawn at 2×; an OS-scaled one is left alone', () => {
  assert.equal(autoZoomFor({ width: 3840, height: 2160 }), 2);
  assert.equal(autoZoomFor({ width: 1920, height: 1080 }), 1); // 4K at OS scale 2, or a plain FHD panel
  assert.equal(autoZoomFor({ width: 2560, height: 1440 }), 1.5);
  assert.equal(autoZoomFor({ width: 2160, height: 3840 }), 2); // a rotated panel counts its long side
  assert.equal(autoZoomFor({ width: 2048, height: 1152 }), 1.25);
  assert.equal(autoZoomFor(undefined), 1);
});

test('the steps are bounded and stepping never leaves them', () => {
  assert.equal(stepZoom(1, +1), 1.1);
  assert.equal(stepZoom(1, -1), 0.9);
  assert.equal(stepZoom(0.9, -1), 0.9);
  assert.equal(stepZoom(2.5, +1), 2.5);
  assert.equal(stepZoom(1.3, +1), 1.5); // off-grid values snap to the next step
  assert.equal(stepZoom(1.3, -1), 1.25);
  assert.equal(clampZoom(9), ZOOM_STEPS[ZOOM_STEPS.length - 1]);
  assert.equal(clampZoom('nonsense'), 1);
});

test('a preference is auto or a factor inside the range — garbage becomes auto', () => {
  assert.equal(normalisePreference('auto'), 'auto');
  assert.equal(normalisePreference(1.5), 1.5);
  assert.equal(normalisePreference('1.25'), 1.25);
  assert.equal(normalisePreference(7), 'auto');
  assert.equal(normalisePreference(null), 'auto');
});
