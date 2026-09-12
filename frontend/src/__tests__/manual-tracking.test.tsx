/**
 * Manual tracking — the click-to-track overlay and the toolbar button (2026-09-03).
 *
 * ★ What these pin: in tracking mode a single click TRACKS the object at a media
 *   pixel (after the double-click grace), a double-click LOCKS it and cancels the
 *   track that would otherwise fire, and outside tracking mode a click still just
 *   selects. Tracking is ARMED WITH THE RUN (2026-09-08): the header offers no
 *   button, only a count of the objects being followed.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen } from '@testing-library/react';

import { setLanguage } from '../i18n';
import { DetectionOverlay } from '../components/monitor/camera/DetectionOverlay';
import { MonitorHeader, type MonitorHeaderProps } from '../components/monitor/camera/MonitorHeader';
import type { DetectionLatest } from '../api/detection';

const LATEST: DetectionLatest = {
  seq: 1,
  frame_index: 0,
  time_s: 0,
  width: 400,
  height: 300,
  boxes: [
    { x1: 60, y1: 40, x2: 180, y2: 160, score: 0.9, cls_name: 'car', track_id: null, predicted: false, placed: false },
  ],
};

function overlay(over: Partial<React.ComponentProps<typeof DetectionOverlay>> = {}): void {
  render(
    <DetectionOverlay
      latest={LATEST}
      toggles={{ boxes: true, labels: true, tracks: true, hud: false }}
      selectedTrack={null}
      pictureHasBoxes
      {...over}
    />,
  );
  // jsdom gives a zero-size rect; pin it so media == css (scale 1, no letterbox).
  const canvas = screen.getByTestId('detection-overlay');
  canvas.getBoundingClientRect = () =>
    ({ width: 400, height: 300, left: 0, top: 0, right: 400, bottom: 300, x: 0, y: 0, toJSON() {} }) as DOMRect;
}

describe('the click-to-track overlay', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('★ a click in tracking mode tracks the object at that media pixel', () => {
    const onTrackAt = vi.fn();
    overlay({ trackingMode: true, onTrackAt });
    fireEvent.click(screen.getByTestId('detection-overlay'), { clientX: 120, clientY: 100 });
    // Deferred so a double-click can cancel it — nothing fires yet.
    expect(onTrackAt).not.toHaveBeenCalled();
    vi.advanceTimersByTime(250);
    expect(onTrackAt).toHaveBeenCalledWith(120, 100);
  });

  it('★ a double-click LOCKS and cancels the pending track', () => {
    const onTrackAt = vi.fn();
    const onLockAt = vi.fn();
    overlay({ trackingMode: true, onTrackAt, onLockAt });
    const canvas = screen.getByTestId('detection-overlay');
    fireEvent.click(canvas, { clientX: 120, clientY: 100 });
    fireEvent.doubleClick(canvas, { clientX: 120, clientY: 100 });
    vi.advanceTimersByTime(250);
    expect(onLockAt).toHaveBeenCalledWith(120, 100);
    expect(onTrackAt).not.toHaveBeenCalled(); // the track was cancelled by the lock
  });

  it('outside tracking mode a click still just selects', () => {
    const onSelect = vi.fn();
    const onTrackAt = vi.fn();
    overlay({ trackingMode: false, onSelect, onTrackAt });
    fireEvent.click(screen.getByTestId('detection-overlay'), { clientX: 120, clientY: 100 });
    expect(onTrackAt).not.toHaveBeenCalled();
    expect(onSelect).toHaveBeenCalledWith(null, 0); // the box under the pointer, by index
  });
});

const HEADER: MonitorHeaderProps = {
  camera: { id: 'c', name: 'gate', lat: 34.1, lon: 36, source: 'http://cam/s', created_at: new Date().toISOString() },
  status: 'live',
  dirty: false,
  detecting: true,
  starting: false,
  runStartedAt: Date.now(),
  startBlocker: null,
  startError: null,
  onDismissError: () => undefined,
  onApply: () => undefined,
  onStart: () => undefined,
  onStop: () => undefined,
  trackedCount: 0,
  onCapture: () => undefined,
  captureBusy: false,
  recordingStartedAt: null,
  recordBusy: false,
  onToggleRecord: () => undefined,
  onOpenLibrary: () => undefined,
};

describe('tracking armed with the run — the header shows a count, never a button', () => {
  beforeEach(() => setLanguage('en'));

  function header(over: Partial<MonitorHeaderProps>): void {
    render(
      <MemoryRouter>
        <MonitorHeader {...HEADER} {...over} />
      </MemoryRouter>,
    );
  }

  it('★ offers no Start tracking button — the tracker runs with detection', () => {
    header({});
    expect(screen.queryByRole('button', { name: /Start tracking/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /tracking/i })).toBeNull();
  });

  it('reads "Tracking · N" while objects are followed, and says nothing otherwise', () => {
    header({ trackedCount: 3 });
    expect(screen.getByTestId('tracking-count')).toHaveTextContent('Tracking · 3');
    document.body.innerHTML = '';
    header({ trackedCount: 0 });
    expect(screen.queryByTestId('tracking-count')).toBeNull();
    document.body.innerHTML = '';
    header({ detecting: false, trackedCount: 3 });
    expect(screen.queryByTestId('tracking-count')).toBeNull();
  });
});
