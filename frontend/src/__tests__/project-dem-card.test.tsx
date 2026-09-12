/**
 * The project DEM card's probe fires ONCE — not once per render.
 *
 * ★ THE BUG THIS PINS (2026-09-02): `useRequestSequence` returned a fresh object
 *   every render, `refreshDem` listed it in its deps, and the mount effect keyed
 *   on `refreshDem` re-ran forever — `GET /projects/{id}/dem` hammered an idle
 *   Project-settings page with its loading bar animating untouched ("the dem
 *   loading icon moves without touching anything").
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { act, render, screen } from '@testing-library/react';

vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));
vi.mock('../api/dem', () => ({
  demApi: {
    projectDem: vi.fn(async () => null),
    uploadProjectDem: vi.fn(),
    deleteProjectDem: vi.fn(),
  },
}));
// The library panel pulls its own queries; the card only opens it on demand.
vi.mock('../components/dem/DemLibraryPanel', () => ({ DemLibraryPanel: () => null }));

import { demApi } from '../api/dem';
import { ProjectDemCard } from '../components/project/ProjectDemCard';
import { setLanguage } from '../i18n';
import type { Uuid } from '../types/common';

const PROJECT = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' as Uuid;

beforeEach(() => {
  setLanguage('en');
  vi.mocked(demApi.projectDem).mockClear();
});

describe('the project DEM card', () => {
  it('★ probes the DEM once and settles — never a refetch loop on an idle page', async () => {
    const onDemChange = vi.fn();
    render(
      <MemoryRouter>
        <ProjectDemCard projectId={PROJECT} onDemChange={onDemChange} />
      </MemoryRouter>,
    );
    // Let the probe resolve, then give a looping effect every chance to betray
    // itself: several macrotask turns, then a parent-independent re-render.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(await screen.findByText('No elevation source')).toBeVisible();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(vi.mocked(demApi.projectDem)).toHaveBeenCalledTimes(1);
    expect(onDemChange).toHaveBeenCalledWith(false);
  });
});
