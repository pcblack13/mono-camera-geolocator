/**
 * The predict surface on the video (2026-09-10): the pointer's place becomes a
 * MEDIA pixel through the same contain-fit the boxes use; a click pins; the
 * readout says what the table answered and Copy hands it over.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRef } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { VideoHero, type VideoHeroProps } from '../components/monitor/camera/VideoHero';
import type { LivePredict } from '../hooks/useLivePredict';
import { setLanguage } from '../i18n';

function live(over: Partial<LivePredict> = {}): LivePredict {
  return {
    prediction: null,
    pinned: false,
    pending: false,
    cursor: vi.fn(),
    leave: vi.fn(),
    pin: vi.fn(),
    unpin: vi.fn(),
    copyText: null,
    copy: vi.fn(async () => null),
    ...over,
  };
}

/** jsdom has no PointerEvent — React listens for the event TYPE, and a MouseEvent
 *  carries the coordinates, so that is what is dispatched. */
function pointer(el: Element, type: 'pointermove', clientX: number, clientY: number): void {
  el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX, clientY }));
}

function mount(predict: VideoHeroProps['predict']): void {
  const canvasRef = createRef<HTMLCanvasElement>();
  render(
    <VideoHero
      cameraName="Roof"
      previewUrl="http://cam/s"
      detectionStreamUrl={null}
      mode="canvas"
      status="live"
      streamError={null}
      canvasRef={canvasRef}
      onImgError={() => undefined}
      onReconnect={() => undefined}
      latest={null}
      piLatest={null}
      driftVerdict={null}
      toggles={{ boxes: true, labels: true, tracks: true, hud: true, drift: false, piBoxes: true }}
      onToggle={() => undefined}
      selectedTrack={null}
      onSelectBox={() => undefined}
      sinceLastFrameS={null}
      predict={predict}
    />,
  );
  // the decoded picture: 1280×720, drawn contain-fit into a 640×480 stage
  const canvas = canvasRef.current!;
  canvas.width = 1280;
  canvas.height = 720;
}

describe('VideoHero · live predict', () => {
  beforeEach(() => {
    setLanguage('en');
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 640, bottom: 480, width: 640, height: 480, toJSON: () => ({}),
    } as DOMRect);
  });
  afterEach(() => vi.restoreAllMocks());

  it('is offered only when the camera has a table, and off by default', () => {
    mount({ available: false, on: false, onToggle: vi.fn(), live: live(), onCopied: vi.fn() });
    expect(screen.queryByRole('switch', { name: 'Predict' })).toBeNull();
    expect(screen.queryByTestId('predict-surface')).toBeNull();
  });

  it('★ the pointer becomes a MEDIA pixel through the contain fit; a click pins', () => {
    const l = live();
    mount({ available: true, on: true, onToggle: vi.fn(), live: l, onCopied: vi.fn() });
    const surface = screen.getByTestId('predict-surface');
    // 1280×720 in 640×480: scale 0.5, letterboxed 60px top and bottom.
    pointer(surface, 'pointermove', 320, 240);
    expect(l.cursor).toHaveBeenCalledWith({ u: 640, v: 360, w: 1280, h: 720 });
    // in the letterbox → off the picture
    pointer(surface, 'pointermove', 320, 10);
    expect(l.leave).toHaveBeenCalled();
    fireEvent.click(surface, { clientX: 64, clientY: 96 });
    expect(l.pin).toHaveBeenCalledWith({ u: 128, v: 72, w: 1280, h: 720 });
  });

  it('★ the readout says the answer; Copy (and the c key) hand it over', async () => {
    const onCopied = vi.fn();
    const l = live({
      prediction: { u: 1, v: 1, placed: true, lat: 34.104413, lon: 36.015914, elevationM: 1312.4, reason: null },
      copyText: '34.104413, 36.015914, 1312.4',
      copy: vi.fn(async () => '34.104413, 36.015914, 1312.4'),
    });
    mount({ available: true, on: true, onToggle: vi.fn(), live: l, onCopied });
    expect(screen.getByTestId('predict-readout')).toHaveTextContent('34.104413, 36.015914 · z 1312.4 m');
    fireEvent.click(screen.getByRole('button', { name: 'Copy the coordinates' }));
    await vi.waitFor(() => expect(onCopied).toHaveBeenCalledWith('34.104413, 36.015914, 1312.4'));
    fireEvent.keyDown(window, { key: 'c' });
    await vi.waitFor(() => expect(l.copy).toHaveBeenCalledTimes(2));
  });

  it('sky is said as sky, not as a number', () => {
    const l = live({
      prediction: { u: 1, v: 1, placed: false, lat: null, lon: null, elevationM: null, reason: 'no_terrain' },
    });
    mount({ available: true, on: true, onToggle: vi.fn(), live: l, onCopied: vi.fn() });
    expect(screen.getByTestId('predict-readout')).toHaveTextContent('Sky, or ground the table does not cover');
    expect(screen.getByRole('button', { name: 'Copy the coordinates' })).toBeDisabled();
  });
});
