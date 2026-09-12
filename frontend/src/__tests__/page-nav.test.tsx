/**
 * Page navigation — back goes UP the hierarchy, and Save exists only over a draft.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { resolvePageNav } from '../components/shell/pageNav';
import { PageNavBar } from '../components/shell/PageNavBar';
import { useAnnotationStore } from '../store/annotationStore';
import { useNavHistoryStore } from '../store/navHistoryStore';

const P = '11111111-2222-3333-4444-555555555555';
const I = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

/** The bar as the app mounts it: inside the router AND the query client (main.tsx). */
function renderBar(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <PageNavBar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('resolvePageNav', () => {
  it('★ back is structural: every page goes to its parent, not browser history', () => {
    // [pathname, expected parent]
    const cases: Array<[string, string | null]> = [
      ['/', null], // the root has no up
      ['/dashboard', '/'],
      ['/cameras', '/'],
      ['/cameras/new', '/cameras'],
      ['/cameras/abc/settings', '/cameras'],
      ['/cameras/abc/editor', '/cameras/abc/settings'],
      ['/cameras/new/editor', '/cameras/new'],
      ['/dem', '/'],
      ['/videos', '/'],
      ['/drift', '/'],
      // ★ A frame's editor and setup with no camera behind them go to the server of
      //   cameras — there is no project page any more (2026-09-04).
      [`/projects/${P}/images/${I}`, '/cameras'],
      [`/projects/${P}/images/${I}/setup`, '/cameras'],
      [`/projects/${P}/videos/${I}`, '/videos'],
      ['/videos/recordings/Field-gate-20260902-120000', '/videos'],
    ];
    for (const [path, parent] of cases) {
      expect(resolvePageNav(path).parent, path).toBe(parent);
    }
  });

  it('an unknown route offers the way home rather than nothing', () => {
    const nav = resolvePageNav('/no/such/page');
    expect(nav.parent).toBe('/');
    expect(nav.title).toBe('Not found');
  });

  it('only the editor hosts the draft', () => {
    expect(resolvePageNav(`/projects/${P}/images/${I}`).hasDraft).toBe(true);
    expect(resolvePageNav('/cameras/abc/editor').hasDraft).toBe(true);
    for (const path of [
      '/',
      '/cameras',
      '/cameras/abc/settings',
      `/projects/${P}/images/${I}/setup`,
    ]) {
      expect(resolvePageNav(path).hasDraft, path).toBe(false);
    }
  });

  it('★ speaks the product vocabulary: the camera workspace, Editor, Image setup', () => {
    // The three-pane annotation screen is the "Editor" wherever it is addressed;
    // a clip's photograph keeps its "Image setup"; the retired Projects page
    // resolves to the camera workspace, where the work lives now.
    expect(resolvePageNav('/projects').title).toBe('Camera workspace');
    expect(resolvePageNav(`/projects/${P}/images/${I}`).title).toBe('Editor');
    expect(resolvePageNav('/cameras/abc/editor').title).toBe('Editor');
    expect(resolvePageNav('/cameras/new/editor').title).toBe('Editor');
    expect(resolvePageNav(`/projects/${P}/images/${I}/setup`).title).toBe('Image setup');
  });

  it('★ names the work pages at their own addresses — and from the old ?tab= spelling', () => {
    expect(resolvePageNav('/dem').title).toBe('DEM processing');
    expect(resolvePageNav('/drift').title).toBe('Drift monitor');
    expect(resolvePageNav('/projects', '?tab=dem').title).toBe('DEM processing');
    expect(resolvePageNav('/projects', '?tab=drift').title).toBe('Drift monitor');
    // ★ The Live stream tab became the Monitor (2026-08-28); its old URL forwards.
    expect(resolvePageNav('/projects', '?tab=live&x=1').title).toBe('Cameras Monitoring');
    expect(resolvePageNav('/monitor').title).toBe('Cameras Monitoring');
    // a camera's recording, watched in the app (2026-09-07)
    expect(resolvePageNav('/videos/recordings/x')).toMatchObject({
      title: 'Recording',
      parentTitle: 'Recorded videos',
    });
    expect(resolvePageNav('/monitor/cameras/abc').parent).toBe('/monitor');
    // ★ A page UNDER a workspace page keeps its own name (2026-09-04): the camera's
    //   monitor page is "Camera", a camera's settings are "Camera settings".
    expect(resolvePageNav('/monitor/cameras/abc').title).toBe('Camera');
    expect(resolvePageNav('/cameras').title).toBe('Camera workspace');
    expect(resolvePageNav('/cameras/new').title).toBe('New camera');
    expect(resolvePageNav('/cameras/abc/settings').title).toBe('Camera settings');
    expect(resolvePageNav('/cameras/abc/settings').parent).toBe('/cameras');
    expect(resolvePageNav('/cameras/abc/settings').parentTitle).toBe('Camera workspace');
    // a retired tab is the camera workspace — where the forwarder sends it
    expect(resolvePageNav('/projects', '?tab=nope').title).toBe('Camera workspace');
    expect(resolvePageNav('/projects', '?tab=gcps').parent).toBe('/');
  });
});

describe('PageNavBar', () => {
  // ★ A COLD ENTRY each time: no visit history, so the bar falls back to the
  //   structural parent — which is exactly the deep-link/reload case.
  beforeEach(() => {
    useNavHistoryStore.setState({ stack: [] });
  });

  it('★ the back control NAMES ITS DESTINATION, not the page you are on', () => {
    // The bar used to read "← Workspace" while standing on the projects list.
    // Now the visible label is where the press LANDS.
    renderBar('/cameras/abc/settings');
    const back = screen.getByRole('button', { name: /Back to Camera workspace/i });
    expect(back.textContent).toContain('Camera workspace');
    // ★ The back control LEADS the row (2026-09-07): it is the bar's first control.
    expect(screen.getAllByRole('button')[0]).toBe(back);
  });

  it('the camera workspace itself offers a way back to Home', () => {
    renderBar('/cameras');
    const back = screen.getByRole('button', { name: /Back to Home/i });
    expect(back.textContent).toContain('Home');
    expect(screen.queryByText('Workspace')).toBeNull();
  });

  it('shows no back button on the home page — there is no up from the root', () => {
    renderBar('/');
    expect(screen.queryByRole('button', { name: /Back to/i })).toBeNull();
    // ★ The ROOT still names itself: with no back control the bar would be blank.
    expect(screen.getByText('Home')).toBeTruthy();
  });

  it('★ the workchain is gone: no tab strip anywhere, on any kind of page', () => {
    for (const path of [
      '/',
      '/dashboard',
      '/guide',
      '/cameras',
      '/monitor',
      '/dem',
      `/projects/${P}/images/${I}`,
    ]) {
      document.body.innerHTML = '';
      renderBar(path);
      expect(screen.queryByRole('tablist'), path).toBeNull();
      expect(screen.queryAllByRole('tab'), path).toHaveLength(0);
    }
  });

  it('★ shows NO save control outside the workspace — nothing there is unsaved', () => {
    renderBar('/cameras');
    expect(screen.queryByRole('button', { name: /Save/i })).toBeNull();
    expect(screen.queryByText(/All changes saved/i)).toBeNull();
  });

  it('★ on the workspace, a dirty draft shows a live Save button', () => {
    useAnnotationStore.setState({ dirty: true } as never);
    renderBar(`/projects/${P}/images/${I}`);
    expect(screen.getByRole('button', { name: /Save/i })).toBeTruthy();
    useAnnotationStore.setState({ dirty: false } as never);
  });

  it('a clean, previously-saved draft reads "All changes saved"', () => {
    useAnnotationStore.setState({ dirty: false, lastSavedAt: 1234 } as never);
    renderBar(`/projects/${P}/images/${I}`);
    expect(screen.getByText(/All changes saved/i)).toBeTruthy();
    useAnnotationStore.setState({ lastSavedAt: null } as never);
  });
});
