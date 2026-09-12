/**
 * The nine range zones reach the photo pane's chrome: a control only when a
 * measurement has zones, a legend that states the scale, and preferences that
 * survive a reload without trusting what was stored.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

// The marker-colour picker needs the colour-mode provider; it is chrome beside the
// control under test, not the control itself.
vi.mock('../components/image/MarkerColorsControl', () => ({
  MarkerColorsControl: () => null,
}));

import { ViewerControls } from '../components/image/ViewerControls';
import { ZoneLegend } from '../components/image/ZoneLegend';
import { useWorkspaceStore } from '../store/workspaceStore';

const base = {
  scale: 1,
  minScale: 0.1,
  maxScale: 8,
  onZoomIn: () => {},
  onZoomOut: () => {},
  onFit: () => {},
  onActualSize: () => {},
  onToggleFullscreen: () => {},
  isFullscreen: false,
  brightness: 0,
  contrast: 0,
  onBrightnessChange: () => {},
  onContrastChange: () => {},
  onResetAdjustments: () => {},
};

describe('the zone control', () => {
  it('is absent until a measurement has zones', () => {
    render(<ViewerControls {...base} hasZones={false} onToggleZones={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Error zones' })).toBeNull();
  });

  it('opens a panel whose switch toggles the overlay and whose legend states the scale', () => {
    const toggle = vi.fn();
    render(
      <ViewerControls
        {...base}
        hasZones
        showZones
        onToggleZones={toggle}
        zoneOpacity={45}
        onZoneOpacityChange={() => {}}
        zoneRange={[3.2, 9.8]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Error zones' }));
    expect(screen.getByText('3.2 m')).toBeTruthy();
    expect(screen.getByText('9.8 m')).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(toggle).toHaveBeenCalledTimes(1);
  });
});

describe('the legend', () => {
  it('draws nothing without a scale, and both ends with one', () => {
    const { rerender } = render(<ZoneLegend range={null} />);
    expect(screen.queryByTestId('zone-legend')).toBeNull();
    rerender(<ZoneLegend range={[4, 8]} />);
    expect(screen.getByTestId('zone-legend').textContent).toContain('4.0 m');
    expect(screen.getByTestId('zone-legend').textContent).toContain('8.0 m');
  });
});

describe('the preferences', () => {
  it('default to shown at 45%, clamp on write, and fall back on a bad stored value', () => {
    const s = useWorkspaceStore.getState();
    expect(s.zoneOverlay).toBe(true);
    expect(s.zoneOpacity).toBe(45);
    s.setZoneOpacity(140);
    expect(useWorkspaceStore.getState().zoneOpacity).toBe(100);
    s.setZoneOpacity(-3);
    expect(useWorkspaceStore.getState().zoneOpacity).toBe(0);
    s.setZoneOverlay(false);
    expect(useWorkspaceStore.getState().zoneOverlay).toBe(false);
    // The validating merge: a stored string is not a percentage.
    const merged = (
      useWorkspaceStore.persist.getOptions().merge as (p: unknown, c: unknown) => { zoneOpacity: number; zoneOverlay: boolean }
    )({ zoneOpacity: 'loud', zoneOverlay: 'yes' }, useWorkspaceStore.getState());
    expect(merged.zoneOpacity).toBe(45);
    expect(merged.zoneOverlay).toBe(true);
  });
});
