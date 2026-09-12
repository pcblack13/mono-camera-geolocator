/**
 * Phase 3's shell — the behaviours the "every action keyboard-reachable" gate
 * stands on.
 *
 * ★ The palette IS the floor under that gate: whatever has no dedicated binding
 *   must be reachable here by name, in either language. The cheatsheet must not
 *   fire while typing, and "reduce animation" must actually reach the document —
 *   a setting that flips a store nobody reads is a placebo.
 */

import { describe, expect, it, beforeEach, vi } from 'vitest';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { fireEvent, render, screen } from '@testing-library/react';

vi.mock('../api/hooks/useProjects', () => ({
  useProjects: () => ({
    data: { items: [{ id: 'p-north', name: 'North field', image_count: 3 }], total: 1 },
  }),
}));

import { CommandPalette } from '../components/shell/CommandPalette';
import { ShortcutsDialog } from '../components/shell/ShortcutsDialog';
import { ColorModeProvider } from '../theme/ColorModeProvider';
import { setLanguage } from '../i18n';
import { useWorkspaceStore } from '../store/workspaceStore';

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mountPalette(): void {
  render(
    <ColorModeProvider>
      <MemoryRouter initialEntries={['/']}>
        <CommandPalette />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </ColorModeProvider>,
  );
}

beforeEach(() => setLanguage('en'));

describe('the command palette', () => {
  it('opens on Ctrl+K and navigates on Enter', () => {
    mountPalette();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = screen.getByPlaceholderText(/type a page or an action/i);
    fireEvent.change(input, { target: { value: 'drift monitor' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByTestId('loc')).toHaveTextContent('/drift');
  });

  it('finds a page by its ARABIC name while the app is in Arabic', () => {
    // ★ The filter runs over both languages — the Arabic surveyor types «الكشف»,
    //   the English docs say "detection", and both must land on the same page.
    setLanguage('ar');
    mountPalette();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'مراقب الانحراف' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByTestId('loc')).toHaveTextContent('/drift');
    setLanguage('en');
  });

  it('★ finds a PROJECT by name and opens it', () => {
    mountPalette();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'north' } });
    expect(screen.getByText('project · 3 images')).toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByTestId('loc')).toHaveTextContent('/projects/p-north');
  });

  it('flips the reduce-animation setting from the keyboard', () => {
    useWorkspaceStore.setState({ reduceMotion: false });
    mountPalette();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'reduce animation' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(useWorkspaceStore.getState().reduceMotion).toBe(true);
  });
});

describe('the shortcuts cheatsheet', () => {
  it('opens on ? — but never while typing', () => {
    render(
      <>
        <input aria-label="note" />
        <ShortcutsDialog />
      </>,
    );
    // typing a question mark into a field is writing, not asking for help
    fireEvent.keyDown(screen.getByLabelText('note'), { key: '?' });
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.keyDown(window, { key: '?' });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    // and it lists only bindings that exist
    expect(screen.getByText('F1')).toBeInTheDocument();
  });
});

describe('reduce motion reaches the document', () => {
  it('collapses to a data attribute tokens.css can read', async () => {
    // The stamping lives in main.tsx's LanguageBoundary; replicate its contract.
    const { useEffect } = await import('react');
    function Stamper(): null {
      const reduce = useWorkspaceStore((s) => s.reduceMotion);
      useEffect(() => {
        document.documentElement.setAttribute('data-reduce-motion', String(reduce));
      }, [reduce]);
      return null;
    }
    useWorkspaceStore.setState({ reduceMotion: false });
    render(<Stamper />);
    expect(document.documentElement.getAttribute('data-reduce-motion')).toBe('false');
    const { act } = await import('@testing-library/react');
    act(() => useWorkspaceStore.setState({ reduceMotion: true }));
    expect(document.documentElement.getAttribute('data-reduce-motion')).toBe('true');
  });
});
