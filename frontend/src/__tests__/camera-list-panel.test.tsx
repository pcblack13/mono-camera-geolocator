/**
 * The globe's camera list — search, and the All / Live / Lost filter (2026-09-07).
 *
 * ★ What these pin: the panel lists every camera with its last-known state; the
 *   filter narrows to what the fleet is seeing, over the same states the HUD
 *   counts; search and filter combine; and the panel offers no way to add a
 *   camera — that is the camera workspace's pipeline now.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

import { CameraListPanel } from '../components/monitor/globe/CameraListPanel';
import { matchesFilter } from '../components/monitor/cameraFilter';
import { setLanguage } from '../i18n';
import type { CameraStatus, RegisteredCamera } from '../store/cameraRegistryStore';

const CAM = (id: string, name: string): RegisteredCamera => ({
  id,
  name,
  lat: 34.1,
  lon: 36.0,
  source: `http://cam/${id}`,
  created_at: '2026-09-02T08:00:00Z',
});

const CAMERAS = [CAM('a', 'gate'), CAM('b', 'roof'), CAM('c', 'yard')];
const STATUSES: Record<string, CameraStatus> = {
  a: { state: 'live', at: 1 },
  b: { state: 'lost', at: 1 },
  c: { state: 'refused', at: 1 },
  // 'yard' is refused; nothing has probed a fourth camera, so it stays unknown.
};

function mount(cameras = CAMERAS): void {
  setLanguage('en');
  render(
    <CameraListPanel cameras={cameras} statuses={STATUSES} onFly={vi.fn()} onOpen={vi.fn()} />,
  );
}

const rows = (): string[] =>
  within(screen.getByRole('complementary', { name: 'Cameras' }))
    .getAllByRole('button')
    .map((b) => b.textContent ?? '')
    .filter((text) => /gate|roof|yard/.test(text))
    .map((text) => text.replace(/[\d.,\s-]+/g, ' ').trim());

describe('the fleet filter', () => {
  it('★ live is live; lost covers a refusal too; all keeps the unknown ones', () => {
    expect(matchesFilter('live', 'live')).toBe(true);
    expect(matchesFilter('connecting', 'live')).toBe(false);
    expect(matchesFilter('lost', 'lost')).toBe(true);
    expect(matchesFilter('refused', 'lost')).toBe(true);
    expect(matchesFilter('live', 'lost')).toBe(false);
    for (const state of ['live', 'lost', 'refused', 'connecting', 'unknown'] as const) {
      expect(matchesFilter(state, 'all'), state).toBe(true);
    }
  });
});

describe('the globe’s camera list', () => {
  it('★ offers search and the filter — and no way to add a camera', () => {
    mount();
    expect(screen.getByRole('textbox', { name: 'Search cameras' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'All' })).toBeVisible();
    expect(screen.queryByRole('button', { name: /Add camera/ })).toBeNull();
    expect(screen.getByText('3 / 3')).toBeVisible();
  });

  it('★ the filter narrows to what the fleet is seeing', () => {
    mount();
    expect(rows()).toHaveLength(3);
    fireEvent.click(screen.getByRole('button', { name: 'Live' }));
    expect(rows().join(' ')).toContain('gate');
    expect(rows()).toHaveLength(1);
    expect(screen.getByText('1 / 3')).toBeVisible();
    // lost AND refused are both "Lost" — the split the HUD counts
    fireEvent.click(screen.getByRole('button', { name: 'Lost' }));
    expect(rows()).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    expect(rows()).toHaveLength(3);
  });

  it('search and filter combine', () => {
    mount();
    fireEvent.change(screen.getByRole('textbox', { name: 'Search cameras' }), {
      target: { value: 'roof' },
    });
    expect(rows()).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Live' }));
    expect(rows()).toHaveLength(0);
    expect(screen.getByText('No camera matches that search.')).toBeVisible();
  });

  it('★ an empty result names the reason: the filter, not a search nobody typed', () => {
    mount([CAM('a', 'gate')]);
    fireEvent.click(screen.getByRole('button', { name: 'Lost' }));
    expect(screen.getByText('No camera is lost right now.')).toBeVisible();
    expect(screen.queryByText('No camera matches that search.')).toBeNull();
  });

  it('with nothing registered it points at the camera workspace', () => {
    mount([]);
    expect(
      screen.getByText('No cameras yet — register one in the camera workspace.'),
    ).toBeVisible();
  });
});
