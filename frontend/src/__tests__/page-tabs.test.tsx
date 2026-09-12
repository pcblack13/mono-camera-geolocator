/**
 * The navbar's page tabs — three pages, no dropdown (2026-09-07).
 *
 * ★ What these pin: the registry holds the three pages of the bar and the two
 *   tools a camera's settings open (DEM processing, the drift monitor) — routed,
 *   named by the palette, but not in the bar; video detection
 *   is gone; a tab opens its page and marks the page you are on, or the page a
 *   deeper record belongs to; the shell links reach Dashboard and the guide; the
 *   palette still reaches every page by name, tools included.
 */

import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { fireEvent, render, screen, within } from '@testing-library/react';

import { PageTabsBar, ShellLinks } from '../components/shell/PageTabs';
vi.mock('../api/hooks/useProjects', () => ({
  useProjects: () => ({
    data: { items: [{ id: 'p-north', name: 'North field', image_count: 3 }], total: 1 },
  }),
}));

import { CommandPalette } from '../components/shell/CommandPalette';
import {
  NAV_PAGES,
  WORKSPACE_PAGES,
  navPageForLocation,
  pageForLegacyTab,
  pageForLocation,
  workspaceForLocation,
} from '../components/shell/workspaces';
import { ColorModeProvider } from '../theme/ColorModeProvider';
import { setLanguage } from '../i18n';

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mount(at = '/'): void {
  setLanguage('en');
  render(
    <MemoryRouter initialEntries={[at]}>
      <PageTabsBar />
      <ShellLinks />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

const tab = (name: string): HTMLElement => screen.getByRole('button', { name });
const bar = (): HTMLElement => screen.getByRole('navigation', { name: 'Pages' });

describe('the page registry', () => {
  it('★ three pages in the bar, two tools behind a camera — and no video detection', () => {
    expect(NAV_PAGES.map((p) => p.label)).toEqual([
      'Camera workspace',
      'Cameras Monitoring',
      'Recorded videos',
    ]);
    expect(NAV_PAGES.map((p) => p.path)).toEqual(['/cameras', '/monitor', '/videos']);
    expect(WORKSPACE_PAGES.filter((p) => p.tool).map((p) => p.label)).toEqual([
      'DEM processing',
      'Drift monitor',
    ]);
    expect(WORKSPACE_PAGES.some((p) => p.path === '/detect')).toBe(false);
  });

  it('names a location by its page — the tools keep their names, a clip keeps its own tab', () => {
    expect(pageForLocation('/cameras')?.key).toBe('cameras');
    expect(pageForLocation('/cameras/abc/settings')?.key).toBe('cameras');
    expect(pageForLocation('/monitor/cameras/abc')?.key).toBe('live');
    expect(pageForLocation('/videos')?.key).toBe('videos');
    expect(pageForLocation('/dem')?.key).toBe('dem');
    expect(pageForLocation('/drift')?.key).toBe('drift');
    expect(pageForLocation('/videos/abc')).toBeNull();
    expect(pageForLocation('/')).toBeNull();
    // a frame's editor and a clip belong to the one workspace there is
    expect(workspaceForLocation('/projects/p1/images/i1')).toBe('monitoring');
    expect(workspaceForLocation('/')).toBeNull();
  });

  it('★ lights the bar’s tab for what a deeper record belongs to', () => {
    expect(navPageForLocation('/videos/abc')?.key).toBe('videos');
    expect(navPageForLocation('/projects/p1/videos/v1')?.key).toBe('videos');
    expect(navPageForLocation('/projects/p1/images/i1')?.key).toBe('cameras');
    // a tool a camera's settings open is the camera's work
    expect(navPageForLocation('/dem')?.key).toBe('cameras');
    expect(navPageForLocation('/drift')?.key).toBe('cameras');
    expect(navPageForLocation('/')).toBeNull();
    expect(navPageForLocation('/guide')).toBeNull();
  });

  it('forwards the old ?tab= spellings — video detection to cameras monitoring', () => {
    expect(pageForLegacyTab('?tab=dem')?.path).toBe('/dem');
    expect(pageForLegacyTab('?tab=videos')?.path).toBe('/videos');
    expect(pageForLegacyTab('?tab=live')?.path).toBe('/monitor');
    expect(pageForLegacyTab('?tab=detect')?.path).toBe('/monitor');
    expect(pageForLegacyTab('?tab=nope')).toBeNull();
  });
});

describe('the page tabs', () => {
  it('★ one button per page, none for the tools; a press opens the page and lights its tab', () => {
    mount();
    expect(
      within(bar())
        .getAllByRole('button')
        .map((b) => b.getAttribute('aria-label')),
    ).toEqual(['Camera workspace', 'Cameras Monitoring', 'Recorded videos']);
    for (const gone of [
      'DEM processing',
      'Drift monitor',
      'Video detection',
      'Cameras Workspace',
    ]) {
      expect(screen.queryByRole('button', { name: gone }), gone).toBeNull();
    }
    expect(screen.queryByRole('menu')).toBeNull();
    expect(tab('Cameras Monitoring')).not.toHaveAttribute('aria-current');
    fireEvent.click(tab('Cameras Monitoring'));
    expect(screen.getByTestId('loc')).toHaveTextContent('/monitor');
    expect(tab('Cameras Monitoring')).toHaveAttribute('aria-current', 'page');
    fireEvent.click(tab('Recorded videos'));
    expect(screen.getByTestId('loc')).toHaveTextContent('/videos');
    expect(tab('Cameras Monitoring')).not.toHaveAttribute('aria-current');
  });

  it('marks the tab of the page a deeper record belongs to', () => {
    mount('/cameras/abc/settings');
    expect(tab('Camera workspace')).toHaveAttribute('aria-current', 'page');
    document.body.innerHTML = '';
    mount('/videos/abc');
    expect(tab('Recorded videos')).toHaveAttribute('aria-current', 'page');
    expect(tab('Camera workspace')).not.toHaveAttribute('aria-current');
  });

  it('the shell links reach the dashboard and the guide', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Dashboard' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/dashboard');
    fireEvent.click(screen.getByRole('button', { name: 'Workflow guide' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/guide');
  });

  it('speaks Arabic when the app does', () => {
    setLanguage('ar');
    render(
      <MemoryRouter>
        <PageTabsBar />
      </MemoryRouter>,
    );
    expect(screen.getByRole('button', { name: 'مساحة الكاميرا' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'الفيديوهات المسجّلة' })).toBeInTheDocument();
    setLanguage('en');
  });
});

describe('the palette', () => {
  it('★ still reaches the tools by name — and knows no video detection', () => {
    setLanguage('en');
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
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'video detection' } });
    expect(screen.queryByText('Video detection')).toBeNull();
    fireEvent.change(input, { target: { value: 'dem processing' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByTestId('loc')).toHaveTextContent('/dem');
  });
});
