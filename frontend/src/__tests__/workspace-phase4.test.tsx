/**
 * Phase 4 — focus mode, swapped panes, and the pairing HUD.
 *
 * ★ The gate for this phase is "no change may touch coordinate maths or the
 *   photo↔map mapping": everything here is layout state and display text, and
 *   these tests pin the behaviours that make that layout honest — focus does not
 *   survive a reload, the HUD never swallows a click, and the commit key appears
 *   exactly when the pair becomes committable.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';

import { PairingHud } from '../components/workspace/PairingHud';
import { useCorrespondenceStore } from '../store/correspondenceStore';
import { useWorkspaceStore } from '../store/workspaceStore';
import { setLanguage } from '../i18n';

beforeEach(() => {
  setLanguage('en');
  useWorkspaceStore.setState({ focusPane: null, panesSwapped: false });
});

describe('focus mode state', () => {
  it('cycles image → map → off', () => {
    const s = (): ReturnType<typeof useWorkspaceStore.getState> => useWorkspaceStore.getState();
    s().setFocusPane('image');
    expect(s().focusPane).toBe('image');
    s().setFocusPane('map');
    expect(s().focusPane).toBe('map');
    s().setFocusPane(null);
    expect(s().focusPane).toBeNull();
  });

  it('is NOT restored by the persistence merge — a reload opens the full layout', () => {
    // ★ Arriving into a maximised pane with no memory of choosing it reads as a
    //   broken workspace. The merge validator forces it back to null.
    interface PersistShape {
      merge?: (
        persisted: unknown,
        current: ReturnType<typeof useWorkspaceStore.getState>,
      ) => unknown;
    }
    const opts = (
      useWorkspaceStore as unknown as { persist: { getOptions: () => PersistShape } }
    ).persist.getOptions();
    const merged = opts.merge!(
      { focusPane: 'map', panesSwapped: true },
      useWorkspaceStore.getState(),
    ) as { focusPane: unknown; panesSwapped: unknown };
    expect(merged.focusPane).toBeNull(); // transient, by design
    expect(merged.panesSwapped).toBe(true); // a real preference, kept
  });
});

describe('the pairing HUD', () => {
  const setStatus = (status: string): void => {
    act(() => {
      useCorrespondenceStore.setState({ status } as never);
    });
  };

  it('renders nothing while no pairing is open', () => {
    setStatus('idle');
    const { container } = render(<PairingHud />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows which endpoint is owed, and F1 only when committable', () => {
    setStatus('awaiting_map_point');
    const { rerender } = render(<PairingHud />);
    // photo done, map pending — and no commit key yet: the pair is not committable
    expect(screen.getByText(/Photograph ✓/)).toBeInTheDocument();
    expect(screen.getByText(/Map…/)).toBeInTheDocument();
    expect(screen.queryByText(/F1/)).toBeNull();

    setStatus('ready');
    rerender(<PairingHud />);
    expect(screen.getByText(/F1/)).toBeInTheDocument();
  });

  it('never swallows a click — pointer events are off', () => {
    // ★ The HUD floats over the map's bottom edge. One stolen click and it has
    //   broken the very interaction it narrates.
    setStatus('ready');
    render(<PairingHud />);
    const hud = screen.getByRole('status');
    expect(getComputedStyle(hud).pointerEvents).toBe('none');
  });
});
