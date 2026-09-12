/**
 * The popped-out satellite map — its address and its wire vocabulary.
 */

import { describe, expect, it } from 'vitest';

import { isMapWindowMessage, mapChannelName, mapWindowUrl } from '../lib/monitor/mapWindow';

describe('the map window', () => {
  it('★ opens on the app’s own route, carrying the run and the table', () => {
    expect(mapWindowUrl('cam-1', { session: 'abc123', lut: 'MONODEMO' })).toBe(
      '/monitor/cameras/cam-1/map?session=abc123&lut=MONODEMO',
    );
    // before any run, and before any table, the address is still valid
    expect(mapWindowUrl('cam-1', { session: null, lut: '' })).toBe('/monitor/cameras/cam-1/map');
    // ids are escaped, never trusted into the path
    expect(mapWindowUrl('a/b', { session: null, lut: '' })).toBe('/monitor/cameras/a%2Fb/map');
  });

  it('keeps one channel per camera', () => {
    expect(mapChannelName('cam-1')).not.toBe(mapChannelName('cam-2'));
  });

  it('★ accepts only the four messages it speaks — a stray post is dropped, not acted on', () => {
    expect(isMapWindowMessage({ type: 'hello' })).toBe(true);
    expect(isMapWindowMessage({ type: 'closed' })).toBe(true);
    expect(isMapWindowMessage({ type: 'select', index: 3 })).toBe(true);
    expect(isMapWindowMessage({ type: 'select', index: -1 })).toBe(false);
    expect(isMapWindowMessage({ type: 'select', index: '3' })).toBe(false);
    expect(isMapWindowMessage({ type: 'state', session: null, lut: '', selectedIndex: null })).toBe(
      true,
    );
    expect(isMapWindowMessage({ type: 'state' })).toBe(false);
    expect(isMapWindowMessage({ type: 'reload' })).toBe(false);
    expect(isMapWindowMessage(null)).toBe(false);
    expect(isMapWindowMessage('hello')).toBe(false);
  });
});
