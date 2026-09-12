/**
 * Display size — the app scaled for a TV, through the desktop shell.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { DisplaySizeMenu } from '../components/shell/DisplaySizeMenu';
import {
  formatZoom,
  hasDisplayZoom,
  installDisplayZoomShortcuts,
  zoomActionForKey,
} from '../lib/displayZoom';
import { setLanguage } from '../i18n';

type Info = { preference: 'auto' | number; zoom: number; auto: number; steps: number[] };

function installBridge(initial: Info): {
  set: ReturnType<typeof vi.fn>;
  step: ReturnType<typeof vi.fn>;
  fire: (i: Info) => void;
} {
  let listener: ((i: Info) => void) | null = null;
  const set = vi.fn(async (preference: 'auto' | number) => ({
    ...initial,
    preference,
    zoom: preference === 'auto' ? initial.auto : preference,
  }));
  const step = vi.fn(async () => initial);
  (window as unknown as { leNative: unknown }).leNative = {
    zoom: {
      get: async () => initial,
      set,
      step,
      onChange: (cb: (i: Info) => void) => {
        listener = cb;
        return () => {
          listener = null;
        };
      },
    },
  };
  return { set, step, fire: (i) => listener?.(i) };
}

describe('the display size control', () => {
  beforeEach(() => setLanguage('en'));
  afterEach(() => {
    delete (window as unknown as { leNative?: unknown }).leNative;
  });

  it('★ is absent in a plain browser — the browser has its own zoom', () => {
    expect(hasDisplayZoom()).toBe(false);
    const { container } = render(<DisplaySizeMenu />);
    expect(container).toBeEmptyDOMElement();
  });

  it('★ names the size in force, offers Fit to screen with what it means HERE, and applies a pick', async () => {
    const { set } = installBridge({ preference: 'auto', zoom: 2, auto: 2, steps: [1, 1.5, 2] });
    render(<DisplaySizeMenu />);
    const button = await screen.findByRole('button', { name: 'Display size: 200 %' });
    fireEvent.click(button);
    expect(screen.getByRole('menuitem', { name: /Fit to screen/ })).toHaveTextContent(
      'this display · 200 %',
    );
    fireEvent.click(screen.getByRole('menuitem', { name: '150 %' }));
    expect(set).toHaveBeenCalledWith(1.5);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Display size: 150 %' })).toBeInTheDocument(),
    );
  });

  it('follows a change made elsewhere (Ctrl +, another window)', async () => {
    const { fire } = installBridge({ preference: 1, zoom: 1, auto: 1, steps: [1, 1.5] });
    render(<DisplaySizeMenu />);
    await screen.findByRole('button', { name: 'Display size: 100 %' });
    fire({ preference: 1.5, zoom: 1.5, auto: 1, steps: [1, 1.5] });
    await screen.findByRole('button', { name: 'Display size: 150 %' });
  });

  it('★ Ctrl + / Ctrl − / Ctrl 0 step the size through the shell, and only with a modifier', () => {
    const { set, step } = installBridge({ preference: 1, zoom: 1, auto: 1, steps: [1, 1.5] });
    const off = installDisplayZoomShortcuts();
    const press = (key: string, ctrlKey = true): boolean =>
      window.dispatchEvent(new KeyboardEvent('keydown', { key, ctrlKey, cancelable: true }));
    expect(press('=')).toBe(false); // handled → default prevented
    expect(step).toHaveBeenLastCalledWith(1);
    press('-');
    expect(step).toHaveBeenLastCalledWith(-1);
    press('0');
    expect(set).toHaveBeenLastCalledWith('auto');
    expect(press('=', false)).toBe(true); // a plain "=" is typing, not a shortcut
    expect(step).toHaveBeenCalledTimes(2);
    off();
    press('=');
    expect(step).toHaveBeenCalledTimes(2);
    // the pure keymap, for the record
    expect(zoomActionForKey({ key: '+', ctrlKey: false, metaKey: true, altKey: false })).toBe('in');
    expect(zoomActionForKey({ key: '0', ctrlKey: true, metaKey: false, altKey: true })).toBeNull();
    expect(zoomActionForKey({ key: 'z', ctrlKey: true, metaKey: false, altKey: false })).toBeNull();
  });

  it('formats a factor as a percentage', () => {
    expect(formatZoom(1.25)).toBe('125 %');
    expect(formatZoom(2)).toBe('200 %');
  });
});
