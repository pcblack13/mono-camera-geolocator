/**
 * Render smoke tests for the workspace-setup rework.
 *
 * ★ WHY THIS EXISTS. `tsc` and `vite build` both passed on a previous version of this
 *   work that then crashed at runtime in the browser. A type-check proves shapes agree;
 *   it proves nothing about a component that throws on its first render. These tests
 *   mount the changed components for real, in jsdom, so that class of failure is caught
 *   here instead of by the surveyor.
 *
 * No network: `demApi` is mocked. Nothing here opens a socket (§13.1).
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';

// ── the network surfaces these components touch ─────────────────────────────
vi.mock('../api/hooks/useProviders', () => ({
  // The server's honest report for THIS deployment: Mapbox is the tokened default;
  // Esri is keyless and allowed again (restored in 1.2.6); Google and Sentinel are
  // built but unconfigured until the operator supplies credentials.
  useProviders: () => ({
    data: {
      items: [
        { name: 'esri_world_imagery', configured: true, allowed: true, is_default: false },
        {
          name: 'mapbox_satellite',
          configured: true,
          allowed: true,
          is_default: true,
          capabilities: { kinds: ['satellite'] },
        },
        { name: 'google_map_tiles', configured: false, allowed: true, is_default: false },
        { name: 'sentinel_copernicus', configured: false, allowed: true, is_default: false },
      ],
    },
  }),
}));
vi.mock('../api/dem', () => ({
  demApi: {
    projectDem: vi.fn().mockResolvedValue({ active: false, provider_enabled: false }),
    uploadProjectDem: vi.fn(),
    deleteProjectDem: vi.fn(),
  },
}));

import { WorkspaceSetupPanel } from '../components/workspace/WorkspaceSetupPanel';
import { ProjectDemCard } from '../components/project/ProjectDemCard';
import { useProjectSetupStore, DEFAULT_SETUP } from '../store/projectSetupStore';
import { asUuid } from '../types/common';

const PROJECT = asUuid('11111111-2222-3333-4444-555555555555');

beforeEach(async () => {
  useProjectSetupStore.setState({ byProject: {} });
  // vitest.config sets `restoreMocks: true`, which blanks implementations between
  // tests — re-establish the default so each test states its own starting point.
  const { demApi } = await import('../api/dem');
  vi.mocked(demApi.projectDem).mockResolvedValue({ active: false, provider_enabled: false });
});

describe('projectSetupStore', () => {
  it('defaults an unknown project to unconfigured on the deployment default (Mapbox)', () => {
    const setup = useProjectSetupStore.getState().get(PROJECT);
    expect(setup).toEqual(DEFAULT_SETUP);
    // ★ Mapbox replaced Esri as this deployment's default; Esri is banned server-side
    //   via LE_ALLOWED_PROVIDERS, so defaulting to it would offer a 403.
    expect(setup.source).toBe('mapbox');
    expect(setup.configured).toBe(false);
  });

  it('keeps per-project settings independent', () => {
    const other = asUuid('99999999-8888-7777-6666-555555555555');
    useProjectSetupStore.getState().set(PROJECT, { source: 'offline', configured: true });
    expect(useProjectSetupStore.getState().get(PROJECT).source).toBe('offline');
    // Two surveys on two sites must not share a basemap choice.
    expect(useProjectSetupStore.getState().get(other).source).toBe('mapbox');
    expect(useProjectSetupStore.getState().get(other).configured).toBe(false);
  });

  it('reopen() sends a configured project back to setup', () => {
    useProjectSetupStore.getState().set(PROJECT, { configured: true });
    useProjectSetupStore.getState().reopen(PROJECT);
    expect(useProjectSetupStore.getState().get(PROJECT).configured).toBe(false);
  });
});

describe('WorkspaceSetupPanel', () => {
  it('renders without throwing', () => {
    expect(() => render(<WorkspaceSetupPanel projectId={PROJECT} />)).not.toThrow();
  });

  it('offers all five imagery sources and points to Project settings for the DEM', async () => {
    render(<WorkspaceSetupPanel projectId={PROJECT} />);
    // Appears twice by design: the radio label, and the summary chip by "Open the map".
    expect((await screen.findAllByText(/Mapbox Satellite/)).length).toBeGreaterThan(0);
    // ★ Esri is BACK (1.2.6): keyless and allowed again alongside Mapbox (which stays
    //   the default). It is offered as its own imagery option.
    expect(screen.getByText(/Esri World Imagery/)).toBeTruthy();
    expect(screen.getByText(/Google \(Map Tiles\)/)).toBeTruthy();
    // ★ The Static API option is GONE on purpose: Map Tiles supersedes it, and the
    //   static endpoint watermarks every tile.
    expect(screen.queryByText(/Google \(Static API\)/)).toBeNull();
    expect(screen.getByText(/Sentinel \/ Copernicus/)).toBeTruthy();
    expect(screen.getByText(/Pre-cached offline tiles/)).toBeTruthy();
    // ★ The DEM MOVED to the project setup page — this panel must say where it went
    //   (it does so twice: the intro and the footer), not re-ask for it on the way
    //   into every workspace.
    expect(screen.getAllByText(/setup page/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Upload DEM/)).toBeNull();
  });

  it('★ the Sentinel caveat states the 10 m resolution limit plainly', async () => {
    render(<WorkspaceSetupPanel projectId={PROJECT} />);
    const radios = screen.getAllByRole('radio');
    // select sentinel (FOURTH option — mapbox, esri, google map tiles, sentinel, offline)
    // and expect the honesty caveat to surface
    radios[3].click();
    expect(await screen.findByText(/WRONG for precise GCP clicking/)).toBeTruthy();
  });

  it('★ offers only the basemap kinds Mapbox can serve — satellite, no hybrid/terrain', async () => {
    const { fireEvent } = await import('@testing-library/react');
    render(<WorkspaceSetupPanel projectId={PROJECT} />);
    // Mapbox (the default) reports kinds: ['satellite'] — opening the basemap select
    // must not offer Hybrid or Terrain, which the provider cannot draw.
    fireEvent.mouseDown(await screen.findByRole('combobox'));
    const options = await screen.findAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(['Satellite']);
  });

  it('"Open the map" marks the project configured', async () => {
    render(<WorkspaceSetupPanel projectId={PROJECT} />);
    const button = await screen.findByRole('button', { name: /Open the map/i });
    button.click();
    expect(useProjectSetupStore.getState().get(PROJECT).configured).toBe(true);
  });
});

// ★ The DEM uploader moved to `ProjectDemCard`, mounted on the project setup page —
//   the honest-absence rule and the degrade-don't-crash rule move with it.
describe('ProjectDemCard', () => {
  it('states plainly that Z is empty when no DEM is set', async () => {
    render(
      <MemoryRouter>
        <ProjectDemCard projectId={PROJECT} />
      </MemoryRouter>,
    );
    // ★ The honest-absence rule: no DEM must SAY no elevation, not imply one exists.
    expect(await screen.findByText(/No elevation source/)).toBeTruthy();
  });

  it('survives a failing DEM probe rather than taking the card down', async () => {
    const { demApi } = await import('../api/dem');
    vi.mocked(demApi.projectDem).mockRejectedValueOnce(new Error('backend down'));
    expect(() =>
      render(
        <MemoryRouter>
          <ProjectDemCard projectId={PROJECT} />
        </MemoryRouter>,
      ),
    ).not.toThrow();
    // The uploader must still be offered — degrading to "unknown" is fine, dying is not.
    expect(await screen.findByRole('button', { name: /Upload DEM/i })).toBeTruthy();
  });
});

describe('unconfigured sources are visible, not silent', () => {
  it('★ marks Google and Sentinel "not configured on server" up front', async () => {
    render(<WorkspaceSetupPanel projectId={PROJECT} />);
    // The chip appears per unconfigured option — the surveyor sees it BEFORE choosing,
    // instead of discovering a silent Esri fallback after "Open the map".
    // ★ TWO: Google Map Tiles and Sentinel (the Static API option is retired). The
    //   count is asserted rather than "at least one" so that a source silently
    //   losing its chip is a failure.
    expect((await screen.findAllByText(/not configured on server/i)).length).toBe(2);
  });

  it('★ selecting an unconfigured source states the fallback plainly', async () => {
    render(<WorkspaceSetupPanel projectId={PROJECT} />);
    const radios = screen.getAllByRole('radio');
    radios[2].click(); // Google (mapbox, esri, google, sentinel, offline)
    // ★ "the server's default provider", NOT a hard-coded name: which provider is
    //   the default belongs to the server (it changed once already, Esri → Mapbox).
    expect(
      await screen.findByText(/the map will stay on the server’s default provider/i),
    ).toBeTruthy();
  });
});
