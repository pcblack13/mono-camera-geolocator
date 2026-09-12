/**
 * Tracks as the organising key (2026-09-11, owner ask).
 *
 * ★ What these pin: the Track column comes first; every track the run has seen
 *   is a chip and one chip filters the table AND the export to that object; a
 *   track can be renamed from its row and the name rides the CSV; and outlining
 *   an object on the picture sends a box in MEDIA pixels, through the letterbox
 *   and the zoom, so the tracker follows what the operator drew.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRef } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';

import { setLanguage } from '../i18n';
import { DetectionsDeck, marksToCsv, trackLabel } from '../components/monitor/camera/DetectionsDeck';
import { VideoHero } from '../components/monitor/camera/VideoHero';
import type { DetectionMark } from '../api/detection';

const mark = (over: Partial<DetectionMark>): DetectionMark => ({
  lat: 34.1,
  lon: 36.0,
  score: 0.9,
  cls_name: 'car',
  frame_index: 1,
  time_s: 1,
  u: 10,
  v: 10,
  track_id: null,
  predicted: false,
  detected_at: '2026-09-11T05:46:15Z',
  detected_at_local: '2026-09-11T08:46:15+03:00',
  ...over,
});
const MARKS = [
  mark({ track_id: 1, frame_index: 1 }),
  mark({ track_id: 2, cls_name: 'truck', frame_index: 2 }),
  mark({ track_id: 1, frame_index: 3 }),
  mark({ track_id: null, frame_index: 4 }),
];
const NAMES = { '1': 'white pickup' };

beforeEach(() => setLanguage('en'));

describe('the detections table, organised by track', () => {
  it('★ puts the track first, named when it has a name', () => {
    render(
      <DetectionsDeck marks={MARKS} runStartedMs={0} selectedIndex={null} onSelect={() => {}} cameraName="Y4" trackNames={NAMES} />,
    );
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers[0]).toBe('Track');
    expect(trackLabel(1, NAMES)).toBe('#1 · white pickup');
    expect(trackLabel(2, NAMES)).toBe('#2');
    expect(trackLabel(null, NAMES)).toBe('—');
    expect(screen.getAllByText('#1 · white pickup').length).toBeGreaterThan(0);
  });

  it('★ a track chip filters the rows to that object, and the chip again releases it', () => {
    render(
      <DetectionsDeck marks={MARKS} runStartedMs={0} selectedIndex={null} onSelect={() => {}} cameraName="Y4" trackNames={NAMES} />,
    );
    const rowsNow = (): number => screen.getAllByRole('row').length - 1; // minus the header
    expect(rowsNow()).toBe(4);
    const chips = within(screen.getByTestId('track-filter'));
    fireEvent.click(chips.getByText('#2'));
    expect(rowsNow()).toBe(1);
    expect(screen.getAllByRole('row')[1].textContent).toContain('truck');
    fireEvent.click(chips.getByText('#2'));
    expect(rowsNow()).toBe(4);
    fireEvent.click(chips.getByText('#1 · white pickup'));
    expect(rowsNow()).toBe(2);
  });

  it('★ renaming from the row: the pencil opens an input, Enter saves, Escape cancels', () => {
    const rename = vi.fn();
    render(
      <DetectionsDeck marks={MARKS} runStartedMs={0} selectedIndex={null} onSelect={() => {}} cameraName="Y4" trackNames={NAMES} onRenameTrack={rename} />,
    );
    // The truck's row (track 2) — newest first, so it is the third data row.
    const truckRow = screen
      .getAllByRole('row')
      .find((r) => r.textContent?.includes('truck')) as HTMLElement;
    fireEvent.click(within(truckRow).getByRole('button', { name: 'Rename track' }));
    const input = within(truckRow).getByRole('textbox', { name: 'Track name' }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: ' red bus ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(rename).toHaveBeenCalledWith(2, 'red bus');
    // Escape leaves the name alone.
    const carRow = screen
      .getAllByRole('row')
      .find((r) => r.textContent?.includes('#1 · white pickup')) as HTMLElement;
    fireEvent.click(within(carRow).getByRole('button', { name: 'Rename track' }));
    const input2 = within(carRow).getByRole('textbox', { name: 'Track name' });
    fireEvent.keyDown(input2, { key: 'Escape' });
    expect(rename).toHaveBeenCalledTimes(1);
  });

  it('★ the CSV carries the name beside the id, quoted when it needs it', () => {
    const csv = marksToCsv(MARKS, 0, { '1': 'white, pickup' });
    const [head, first] = csv.split('\n');
    expect(head.split(',').slice(7, 9)).toEqual(['track_id', 'track_name']);
    expect(first).toContain(',1,"white, pickup",');
    const noName = marksToCsv([MARKS[3]], 0, {});
    expect(noName.split('\n')[1]).toContain(',,,4,'); // no id, no name, frame 4
  });
});

/** jsdom has no PointerEvent; a MouseEvent under the pointer type name reaches React. */
function pointer(el: Element, type: string, x: number, y: number): void {
  act(() => {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 }));
  });
}

describe('draw a box to track', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 640, bottom: 480, width: 640, height: 480, toJSON: () => ({}),
    } as DOMRect);
  });
  afterEach(() => vi.restoreAllMocks());

  function mount(trackBox: { on: boolean; onToggle: () => void; onDraw: (b: unknown) => void; mediaSize?: { w: number; h: number } }) {
    const canvasRef = createRef<HTMLCanvasElement>();
    render(
      <VideoHero
        cameraName="Roof" previewUrl="http://cam/s" detectionStreamUrl={null}
        mode="canvas" status="live" streamError={null} canvasRef={canvasRef}
        onImgError={() => undefined} onReconnect={() => undefined}
        latest={null} piLatest={null} driftVerdict={null}
        toggles={{ boxes: true, labels: true, tracks: true, hud: true, drift: false, piBoxes: true }}
        onToggle={() => undefined} selectedTrack={null} onSelectBox={() => undefined}
        sinceLastFrameS={null} trackBox={trackBox}
      />,
    );
    const canvas = canvasRef.current!;
    canvas.width = 1280;
    canvas.height = 720;
  }

  it('★ the chip offers the tool; off, there is no surface', () => {
    const onToggle = vi.fn();
    mount({ on: false, onToggle, onDraw: () => {} });
    expect(screen.queryByTestId('track-box-surface')).toBeNull();
    fireEvent.click(screen.getByRole('switch', { name: 'Track box' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('★ a drag becomes a box in MEDIA pixels through the letterbox, corners ordered', () => {
    const onDraw = vi.fn();
    mount({ on: true, onToggle: () => {}, onDraw });
    const surface = screen.getByTestId('track-box-surface');
    // 1280x720 contain-fit in 640x480: scale 0.5, letterboxed 60 px top and bottom.
    pointer(surface, 'pointerdown', 200, 160);
    pointer(surface, 'pointermove', 100, 100);
    expect(screen.getByTestId('track-box-rubber')).toBeTruthy();
    pointer(surface, 'pointerup', 100, 100);
    expect(onDraw).toHaveBeenCalledWith({ x1: 200, y1: 80, x2: 400, y2: 200 });
    expect(screen.queryByTestId('track-box-rubber')).toBeNull();
  });

  it('★ a bare click draws nothing', () => {
    const onDraw = vi.fn();
    mount({ on: true, onToggle: () => {}, onDraw });
    const surface = screen.getByTestId('track-box-surface');
    pointer(surface, 'pointerdown', 100, 100);
    pointer(surface, 'pointerup', 101, 101);
    expect(onDraw).not.toHaveBeenCalled();
  });

  it("★ during a run the box is in the RUN's media pixels, not the preview's", () => {
    // The preview canvas is 1280x720 (the server resizes to 1280 wide); the run's
    // media is 1920x1080. A box read off the preview would land at two thirds.
    const onDraw = vi.fn();
    mount({ on: true, onToggle: () => {}, onDraw, mediaSize: { w: 1920, h: 1080 } });
    const surface = screen.getByTestId('track-box-surface');
    // fit of 1920x1080 in 640x480: scale 1/3, letterbox 60 px
    pointer(surface, 'pointerdown', 200, 160);
    pointer(surface, 'pointermove', 100, 100);
    pointer(surface, 'pointerup', 100, 100);
    expect(onDraw).toHaveBeenCalledWith({ x1: 300, y1: 120, x2: 600, y2: 300 });
  });

  it('★ through a zoom, the box lands on the media pixels under the pointer', () => {
    const onDraw = vi.fn();
    mount({ on: true, onToggle: () => {}, onDraw });
    fireEvent.wheel(screen.getByTestId('video-hero'), { deltaY: -100, clientX: 320, clientY: 240 });
    // Whatever zoom and pan the layer ended up with, the mapping must be THAT
    // transform followed by the same contain-fit the picture uses.
    const transform = (screen.getByTestId('zoom-layer') as HTMLElement).style.transform;
    const m = /translate\((-?[\d.]+)px, (-?[\d.]+)px\) scale\(([\d.]+)\)/.exec(transform);
    expect(m).not.toBeNull();
    const [, tx, ty, z] = m!.map(Number);
    const layer = { x: tx, y: ty, w: 640 * z, h: 480 * z };
    const fit = Math.min(layer.w / 1280, layer.h / 720);
    const offX = (layer.w - 1280 * fit) / 2;
    const offY = (layer.h - 720 * fit) / 2;
    const toMedia = (cx: number, cy: number): [number, number] => [
      (cx - layer.x - offX) / fit,
      (cy - layer.y - offY) / fit,
    ];
    const surface = screen.getByTestId('track-box-surface');
    pointer(surface, 'pointerdown', 320, 240);
    pointer(surface, 'pointermove', 420, 300);
    pointer(surface, 'pointerup', 420, 300);
    const [box] = onDraw.mock.calls[0];
    const [ax, ay] = toMedia(320, 240);
    const [bx, by] = toMedia(420, 300);
    expect(z).toBeGreaterThan(1);
    expect(box.x1).toBeCloseTo(ax, 3);
    expect(box.y1).toBeCloseTo(ay, 3);
    expect(box.x2).toBeCloseTo(bx, 3);
    expect(box.y2).toBeCloseTo(by, 3);
  });
});
