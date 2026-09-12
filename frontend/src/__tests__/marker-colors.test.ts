/**
 * User-chosen marker colours — the two places a bad value does damage silently.
 *
 * ★ WHY THIS IS WORTH TESTING. Both failures here are INVISIBLE rather than loud: a
 *   colour the renderers cannot parse draws nothing (which reads as missing data, not
 *   a bad setting), and white-on-pale label text vanishes while its chip still draws.
 *   Neither throws, so neither shows up anywhere except a surveyor's confusion.
 */

import { describe, expect, it, beforeEach } from 'vitest';

import { luminance, readableOn } from '../lib/contrast';
import { useWorkspaceStore } from '../store/workspaceStore';

describe('readableOn', () => {
  it('puts dark ink on light colours and light ink on dark ones', () => {
    expect(readableOn('#ffffff')).toBe('#000000');
    expect(readableOn('#000000')).toBe('#ffffff');
    // ★ Luminance, not lightness: yellow READS light and must take black ink, while
    //   pure blue reads dark and must take white — a naive average gets both wrong.
    expect(readableOn('#ffff00')).toBe('#000000');
    expect(readableOn('#0000ff')).toBe('#ffffff');
  });

  it('handles the short hex form and refuses to guess at anything else', () => {
    expect(readableOn('#fff')).toBe('#000000');
    expect(luminance('#fff')).toBeCloseTo(luminance('#ffffff'), 6);
    // An unparseable value sits at mid-luminance rather than claiming either ink.
    expect(luminance('rebeccapurple')).toBe(0.5);
  });

  it('keeps the app default readable', () => {
    // The magenta the suggestion boxes ship with — its rank label must stay legible.
    expect(readableOn('#d946ef')).toBe('#ffffff');
  });
});

describe('marker colour preferences', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetMarkerColors();
  });

  it('defaults to colouring points BY ACCURACY, not by preference', () => {
    // ★ Null is the honest default: a point's colour is its confidence band, and a
    //   flat colour trades that reading away. The choice exists; it is not the default.
    expect(useWorkspaceStore.getState().photoMarkColor).toBeNull();
    expect(useWorkspaceStore.getState().mapMarkColor).toBeNull();
    expect(useWorkspaceStore.getState().suggestionColor).toBe('#d946ef');
    expect(useWorkspaceStore.getState().pointColors).toEqual({});
  });

  it('names the two settings by SURFACE — the photograph and the map', () => {
    // ★ The vocabulary this replaced ("gcp"/"landmark") described two states of one
    //   database row; a surveyor means "the points on the photo" and "the ones on the
    //   map". The two are independent: colouring one must not touch the other.
    const { setPhotoMarkColor, setMapMarkColor } = useWorkspaceStore.getState();
    setPhotoMarkColor('#facc15');
    expect(useWorkspaceStore.getState().mapMarkColor).toBeNull();
    setMapMarkColor('#1e90ff');
    expect(useWorkspaceStore.getState().photoMarkColor).toBe('#facc15');
    expect(useWorkspaceStore.getState().mapMarkColor).toBe('#1e90ff');
  });

  it('refuses a colour no renderer could draw', () => {
    const { setSuggestionColor, setMapMarkColor } = useWorkspaceStore.getState();
    setSuggestionColor('not a colour');
    // Falls back to the default rather than storing an unpaintable value.
    expect(useWorkspaceStore.getState().suggestionColor).toBe('#d946ef');

    setMapMarkColor('rgb(1,2,3)'); // valid CSS, but `hexToRgba` cannot parse it
    expect(useWorkspaceStore.getState().mapMarkColor).toBeNull();

    setMapMarkColor('#1e90ff');
    expect(useWorkspaceStore.getState().mapMarkColor).toBe('#1e90ff');
  });

  it('takes null for "back to the theme"', () => {
    const { setPhotoMarkColor, setMapMarkColor } = useWorkspaceStore.getState();
    setPhotoMarkColor('#facc15');
    setMapMarkColor('#1e90ff');
    setPhotoMarkColor(null);
    setMapMarkColor(null);
    expect(useWorkspaceStore.getState().photoMarkColor).toBeNull();
    expect(useWorkspaceStore.getState().mapMarkColor).toBeNull();
  });
});

describe('one point, one colour', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().resetMarkerColors();
  });

  it('stores an override per point and clears it back to nothing', () => {
    const { setPointColor } = useWorkspaceStore.getState();
    setPointColor('gcp-7', '#ff0000');
    expect(useWorkspaceStore.getState().pointColors['gcp-7']).toBe('#ff0000');

    // ★ Clearing DELETES the key rather than storing null — an entry meaning "no
    //   override" would accumulate forever and make the count in the UI a lie.
    setPointColor('gcp-7', null);
    expect('gcp-7' in useWorkspaceStore.getState().pointColors).toBe(false);
  });

  it('rejects an unpaintable override instead of hiding the point', () => {
    // An unparseable colour would draw NOTHING, which reads as a lost point.
    useWorkspaceStore.getState().setPointColor('gcp-9', 'chartreuse');
    expect('gcp-9' in useWorkspaceStore.getState().pointColors).toBe(false);
  });

  it('is wiped by Reset all, along with the surface colours', () => {
    const st = useWorkspaceStore.getState();
    st.setPointColor('gcp-1', '#ff0000');
    st.setPhotoMarkColor('#facc15');
    st.setSuggestionColor('#00ff00');
    useWorkspaceStore.getState().resetMarkerColors();
    expect(useWorkspaceStore.getState().pointColors).toEqual({});
    expect(useWorkspaceStore.getState().photoMarkColor).toBeNull();
    expect(useWorkspaceStore.getState().suggestionColor).toBe('#d946ef');
  });
});
