/**
 * Zoom on the live video (2026-09-10): the wheel zooms around the cursor, the
 * buttons step, the chip resets, and the predict reading still lands on the
 * right pixel through the zoom.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRef } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';

import { VideoHero, type VideoHeroProps } from '../components/monitor/camera/VideoHero';
import { ZOOM_STEP, clampView, layerRect, zoomAround } from '../lib/monitor/zoom';
import type { LivePredict } from '../hooks/useLivePredict';
import { setLanguage } from '../i18n';

function live(): LivePredict {
  return {
    prediction: null, pinned: false, pending: false,
    cursor: vi.fn(), leave: vi.fn(), pin: vi.fn(), unpin: vi.fn(),
    copyText: null, copy: vi.fn(async () => null),
  };
}

function mount(predict?: VideoHeroProps['predict']): void {
  const canvasRef = createRef<HTMLCanvasElement>();
  render(
    <VideoHero
      cameraName="Roof" previewUrl="http://cam/s" detectionStreamUrl={null}
      mode="canvas" status="live" streamError={null} canvasRef={canvasRef}
      onImgError={() => undefined} onReconnect={() => undefined}
      latest={null} piLatest={null} driftVerdict={null}
      toggles={{ boxes: true, labels: true, tracks: true, hud: true, drift: false, piBoxes: true }}
      onToggle={() => undefined} selectedTrack={null} onSelectBox={() => undefined}
      sinceLastFrameS={null} predict={predict}
    />,
  );
  const canvas = canvasRef.current!;
  canvas.width = 1280;
  canvas.height = 720;
}

const transformOf = (): string => (screen.getByTestId('zoom-layer') as HTMLElement).style.transform;
const scaleOf = (): number => Number(/scale\(([\d.]+)\)/.exec(transformOf())?.[1] ?? 1);

describe('VideoHero · zoom', () => {
  beforeEach(() => {
    setLanguage('en');
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 640, bottom: 480, width: 640, height: 480, toJSON: () => ({}),
    } as DOMRect);
  });
  afterEach(() => vi.restoreAllMocks());

  it('the geometry: zooming around a point keeps it still, and the pan is clamped', () => {
    const v1 = zoomAround({ zoom: 1, x: 0, y: 0 }, 2, 100, 50, 640, 480);
    // the picture point under (100, 50) stays under (100, 50): pan = c - (c - 0)·2
    expect(v1).toEqual({ zoom: 2, x: -100, y: -50 });
    expect(clampView({ zoom: 2, x: 9999, y: -9999 }, 640, 480)).toEqual({ zoom: 2, x: 320, y: -240 });
    expect(clampView({ zoom: 0.5, x: 10, y: 10 }, 640, 480)).toEqual({ zoom: 1, x: 0, y: 0 });
    expect(layerRect({ zoom: 2, x: 0, y: 0 }, 640, 480)).toEqual({ x: -320, y: -240, w: 1280, h: 960 });
  });

  it('★ the wheel zooms in and out, the buttons step, the chip resets', () => {
    mount();
    expect(transformOf()).toBe('');
    const stage = screen.getByTestId('video-hero');
    fireEvent.wheel(stage, { deltaY: -100, clientX: 320, clientY: 240 });
    expect(transformOf()).toContain(`scale(${ZOOM_STEP})`);
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(scaleOf()).toBeCloseTo(ZOOM_STEP * ZOOM_STEP, 6);
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    fireEvent.wheel(stage, { deltaY: 100, clientX: 320, clientY: 240 });
    expect(transformOf()).toBe('');
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled();
    fireEvent.wheel(stage, { deltaY: -100, clientX: 0, clientY: 0 });
    fireEvent.click(screen.getByTestId('zoom-chip'));
    expect(transformOf()).toBe('');
  });

  it('★ the predict reading goes through the zoom: the same screen point is a different pixel', () => {
    const l = live();
    mount({ available: true, on: true, onToggle: vi.fn(), live: l, onCopied: vi.fn() });
    const surface = screen.getByTestId('predict-surface');
    const move = (x: number, y: number): void => {
      surface.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: x, clientY: y }));
    };
    move(420, 240);
    // 1280×720 in 640×480 at 1×: scale 0.5, letterbox 60 → (420, 240) is (840, 360)
    expect(l.cursor).toHaveBeenLastCalledWith({ u: 840, v: 360, w: 1280, h: 720 });
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' })); // centred, pan 0
    move(420, 240);
    // layer 736×552 at (-48, -36); fit scale 0.575, fit.y 69 → u = 468/0.575, v = (276-69)/0.575
    const last = vi.mocked(l.cursor).mock.calls.at(-1)![0];
    expect(last.u).toBeCloseTo(813.9, 0);
    expect(last.v).toBeCloseTo(360, 5);
  });
});

describe('VideoHero · drag to pan', () => {
  beforeEach(() => {
    setLanguage('en');
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 640, bottom: 480, width: 640, height: 480, toJSON: () => ({}),
    } as DOMRect);
  });
  afterEach(() => vi.restoreAllMocks());

  it('★ a drag pans the zoomed picture, and the click it would end with is swallowed', () => {
    const onSelect = vi.fn();
    mount();
    const stage = screen.getByTestId('video-hero');
    // Native dispatch, wrapped in act so React flushes the state it sets.
    const pe = (type: string, x: number, y: number, button = 0): void => {
      act(() => {
        stage.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button }));
      });
    };
    // at 1× a left drag does nothing (there is nothing to pan)
    pe('pointerdown', 320, 240); pe('pointermove', 200, 180); pe('pointerup', 200, 180);
    expect(transformOf()).toBe('');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' })); // ≈ 2.01×
    pe('pointerdown', 320, 240); pe('pointermove', 300, 230); pe('pointermove', 200, 180); pe('pointerup', 200, 180);
    expect(transformOf()).toContain('translate(-120px, -60px)');
    // the release's click is swallowed once; the next click goes through
    const clickSpy = vi.fn();
    stage.addEventListener('click', clickSpy);
    fireEvent.click(stage);
    expect(clickSpy).not.toHaveBeenCalled();
    fireEvent.click(stage);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });
});
