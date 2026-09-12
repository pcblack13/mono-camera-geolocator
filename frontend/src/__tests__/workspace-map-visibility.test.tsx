/**
 * Does the map pane stay mounted when no correspondence is open?
 *
 * ★ The reported fault: after committing a GCP the satellite map goes blank, and only
 *   comes back on "New GCP". That is exactly the moment `correspondenceOpen` flips
 *   true → false, so the gate I added around the map pane is the first suspect and this
 *   test is the cheapest way to convict or clear it.
 *
 * Leaflet cannot mount in jsdom, so `MapPanel` is mocked to a sentinel. That is the right
 * scope: what is under test is the WORKSPACE'S DECISION to render it, not Leaflet.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../components/map/MapPanel', () => ({
  MapPanel: () => <div data-testid="map-pane">MAP</div>,
}));
vi.mock('../components/image/ImagePanel', () => ({
  ImagePanel: () => <div data-testid="image-pane">IMAGE</div>,
}));
vi.mock('../components/gcp/GcpTable', () => ({ GcpTable: () => <div>GCPS</div> }));
vi.mock('../components/annotation/ToolRail', () => ({ ToolRail: () => <div>RAIL</div> }));
vi.mock('../components/annotation/AnnotationInspector', () => ({
  AnnotationInspector: () => <div data-testid="inspector">INSPECTOR</div>,
}));
vi.mock('../api/hooks/useImages', () => ({ useImage: () => ({ data: null }) }));
vi.mock('../api/dem', () => ({
  demApi: { projectDem: vi.fn().mockResolvedValue({ active: false, provider_enabled: false }) },
}));

import { Workspace } from '../components/workspace/Workspace';

/** As the app mounts it: inside the query client (main.tsx). No network — retries off,
 *  and the providers query simply stays pending in jsdom. */
function renderWorkspace(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}
import { useProjectSetupStore } from '../store/projectSetupStore';
import { useCorrespondenceStore } from '../store/correspondenceStore';
import { useSelectionStore } from '../store/selectionStore';
import { asUuid } from '../types/common';

const PROJECT = asUuid('11111111-2222-3333-4444-555555555555');
const IMAGE = asUuid('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');

/** A configured project — the state the surveyor is in after setup. */
function configure(): void {
  useProjectSetupStore.setState({
    byProject: { [PROJECT]: { configured: true, source: 'mapbox', basemap: 'satellite' } },
  });
}

beforeEach(() => {
  useProjectSetupStore.setState({ byProject: {} });
  useCorrespondenceStore.setState({ status: 'idle' } as never);
  useSelectionStore.setState({ selected: [] } as never);
});

describe('map pane visibility', () => {
  it('★ shows the map EVEN while setup is still pending — setup is a dialog, not a pane', () => {
    renderWorkspace(<Workspace projectId={PROJECT} imageId={IMAGE} />);
    // The map slot is unconditional now: nothing may take the map off screen.
    expect(screen.getByTestId('map-pane')).toBeTruthy();
    expect(screen.getByText(/Set up this project/i)).toBeTruthy();
  });

  it('shows setup once per PROJECT, and not again once configured', () => {
    configure();
    renderWorkspace(<Workspace projectId={PROJECT} imageId={IMAGE} />);
    expect(screen.getByTestId('map-pane')).toBeTruthy();
    // ★ The reported complaint: it must not reappear for every new GCP.
    expect(screen.queryByText(/Set up this project/i)).toBeNull();
  });

  it('★ shows the map with NO correspondence open — the reported fault', () => {
    configure();
    renderWorkspace(<Workspace projectId={PROJECT} imageId={IMAGE} />);
    expect(screen.getByTestId('map-pane')).toBeTruthy();
    // …and the idle inspector must NOT be occupying a column.
    expect(screen.queryByTestId('inspector')).toBeNull();
  });

  it('keeps the map mounted while a correspondence is open', () => {
    configure();
    useCorrespondenceStore.setState({ status: 'placing' } as never);
    renderWorkspace(<Workspace projectId={PROJECT} imageId={IMAGE} />);
    expect(screen.getByTestId('map-pane')).toBeTruthy();
    expect(screen.getByTestId('inspector')).toBeTruthy();
  });

  it('★ keeps the map mounted across a correspondence opening AND closing', () => {
    configure();
    useCorrespondenceStore.setState({ status: 'placing' } as never);
    // ★ rerender() swaps the WHOLE tree, so the QueryClientProvider must be part of
    //   the element we pass both times — the helper's hidden wrapper would vanish on
    //   the second render and crash on a missing client instead of testing anything.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
    const tree = (
      <QueryClientProvider client={qc}>
        <Workspace projectId={PROJECT} imageId={IMAGE} />
      </QueryClientProvider>
    );
    const { rerender } = render(tree);
    const before = screen.getByTestId('map-pane');

    // Commit → correspondence closes. The map must not unmount: a remount would
    // re-seed Leaflet and is the shape of "the map went blank".
    useCorrespondenceStore.setState({ status: 'idle' } as never);
    rerender(tree);

    const after = screen.getByTestId('map-pane');
    expect(after).toBeTruthy();
    expect(after).toBe(before);
  });
});

describe('grid integrity', () => {
  it('★ no grid child is display:none when the inspector is closed', async () => {
    // THE BUG THIS GUARDS: a `display:none` grid child is removed from layout, so every
    // later sibling shifts back one cell and the MAP lands in the 6px splitter column —
    // a six-pixel map that reads as "the satellite map disappeared".
    //
    // `WorkspaceGrid` is rendered DIRECTLY: in jsdom the workspace's width is 0, so the
    // full `Workspace` demotes to the tabbed layout and the grid never mounts.
    const { WorkspaceGrid } = await import('../components/workspace/WorkspaceGrid');
    const { container } = render(
      <WorkspaceGrid
        paneSizes={{ imageFr: 1, mapFr: 1, inspectorPx: 280, dockPx: 240 }}
        inspectorOpen={false}
        dockOpen={false}
        dockHeight={240}
        onResizeColumns={() => {}}
        onResizeDock={() => {}}
        onResetColumns={() => {}}
        imagePane={<div>IMAGE</div>}
        toolRail={<div>RAIL</div>}
        inspector={<div data-testid="inspector">INSPECTOR</div>}
        mapPane={<div data-testid="map-pane">MAP</div>}
        dock={<div>DOCK</div>}
      />,
    );

    const map = screen.getByTestId('map-pane');
    const gridEl = map.parentElement?.parentElement as HTMLElement;
    const children = Array.from(gridEl.children) as HTMLElement[];
    // Five columns are declared (one seam since 2026-09-10); five children must
    // occupy them, all in layout.
    expect(children.length).toBe(5);
    for (const child of children) {
      expect(
        window.getComputedStyle(child).display,
        'grid children must never be display:none',
      ).not.toBe('none');
    }
    // And the map must be the LAST child — the one the mapFr column belongs to.
    expect(children[children.length - 1].contains(map)).toBe(true);
    void container;
  });
});
