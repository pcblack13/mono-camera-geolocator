/**
 * Importing a lookup table someone else built.
 *
 * ★ THE FEATURE IS "USE MY OWN TABLE", and every page that puts a detection on the
 *   map picks that table by NAME out of one library. So what these tests pin is the
 *   round trip a surveyor actually performs: choose a bundle → it is filed → the page
 *   they were on is already using it. An import that landed in the library but left
 *   the picker on "None" would have solved nothing.
 *
 * ★ AND THE TWO HONESTIES. A name already in the library is a REFUSAL with a second,
 *   deliberate press behind it — never a checkbox ticked before anyone knew there was
 *   a conflict. And a bundle without a pose is offered for placement but withheld
 *   from the drift monitor, which re-solves geometry from that pose: a Freeze that
 *   fails seconds after it was committed to is worse than an option that was never
 *   offered.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { LutLibraryEntry } from '../api/lut';

const state = vi.hoisted(() => ({
  library: [] as unknown[],
  importMock: vi.fn(),
}));

vi.mock('../api/lut', () => ({
  lutApi: {
    library: vi.fn().mockImplementation(() => Promise.resolve(state.library)),
    list: vi.fn().mockResolvedValue([]),
    get: vi.fn(),
    create: vi.fn(),
    import: state.importMock,
  },
}));
vi.mock('../components/common/Notifications', () => ({ useNotify: () => vi.fn() }));
vi.mock('../api/hooks/useDetection', () => ({
  useDetectionAvailability: () => ({ data: undefined, isError: false }),
}));

import { LutImportDialog, siteNameFromPick } from '../components/lut/LutImportDialog';
import { DetectionSettingsBar } from '../components/detection/DetectionSettingsBar';
import { ApiError } from '../types/common';
import { setLanguage } from '../i18n';

function entry(over: Partial<LutLibraryEntry> = {}): LutLibraryEntry {
  return {
    site_name: 'yammone',
    built_utc: '2026-08-01T10:00:00Z',
    image: { width: 4032, height: 2268 },
    payload_mb: 146.3,
    validation_passed: null,
    max_error_m: null,
    center: null,
    bundle_dir: '/data/lut/yammone_lut',
    archive_available: true,
    has_pose: true,
    imported: { at_utc: '2026-08-28T09:00:00Z', source: 'yammone_lut.zip' },
    ...over,
  };
}

function apiError(status: number, message: string): ApiError {
  return new ApiError({ status, code: 'VALIDATION_ERROR', message, request_id: 'r1' } as never);
}

function renderDialog(onImported?: (e: LutLibraryEntry) => void): void {
  setLanguage('en');
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <LutImportDialog open onClose={() => undefined} onImported={onImported} />
    </QueryClientProvider>,
  );
}

/** Drop a file on the zone — the one pick route that works in jsdom. */
function dropZip(name = 'yammone_lut.zip'): void {
  const zone = screen.getByText('Drop a bundle .zip here, or choose one.').parentElement!;
  const file = new File(['zip-bytes'], name, { type: 'application/zip' });
  fireEvent.drop(zone, { dataTransfer: { files: [file] } });
}

beforeEach(() => {
  state.library = [];
  state.importMock.mockReset();
});

describe('siteNameFromPick', () => {
  it('derives the library name the server would, from a zip or a folder', () => {
    // The export this app hands out is `<site>_lut.zip`; a folder is `<site>_lut`.
    expect(siteNameFromPick('yammone_lut.zip')).toBe('yammone');
    expect(siteNameFromPick('arsal_lut')).toBe('arsal');
    expect(siteNameFromPick('Ras Baalbek (200m).zip')).toBe('Ras_Baalbek_200m');
  });
});

describe('LutImportDialog', () => {
  it('★ files the chosen bundle and hands the caller the row the library will show', async () => {
    const imported = entry({ site_name: 'yammone' });
    state.importMock.mockResolvedValue(imported);
    const onImported = vi.fn();
    renderDialog(onImported);

    dropZip();
    // The name is pre-filled from the pick, and says where it will be filed.
    expect(screen.getByDisplayValue('yammone')).toBeTruthy();
    expect(screen.getByText('Filed as yammone_lut')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => expect(onImported).toHaveBeenCalledWith(imported));
    const [form] = state.importMock.mock.calls[0];
    expect(form.file.name).toBe('yammone_lut.zip');
    expect(form.site_name).toBe('yammone');
    // ★ Never overwrite on the first attempt — a clash must be reported, not resolved.
    expect(form.overwrite).toBe(false);
  });

  it('★ a name already taken is refused, and replacing it is a second, deliberate press', async () => {
    state.importMock.mockRejectedValueOnce(
      apiError(409, "the library already holds a bundle named 'yammone'"),
    );
    renderDialog();
    dropZip();
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));

    await screen.findByText('That name is taken');
    expect(screen.getByText(/already holds a bundle named/)).toBeTruthy();

    state.importMock.mockResolvedValueOnce(entry());
    fireEvent.click(screen.getByRole('button', { name: 'Replace it' }));

    await waitFor(() => expect(state.importMock).toHaveBeenCalledTimes(2));
    expect(state.importMock.mock.calls[1][0].overwrite).toBe(true);
  });

  it('★ shows the server’s refusal verbatim — it names the actual problem', async () => {
    state.importMock.mockRejectedValue(
      apiError(
        422,
        'lat.npy ranges 34100.000…34100.000, outside ±90 — these are not decimal degrees.',
      ),
    );
    renderDialog();
    dropZip('utm_lut.zip');
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));

    await screen.findByText('That bundle was not imported');
    expect(screen.getByText(/not decimal degrees/)).toBeTruthy();
  });
});

describe('importing from a page that runs detections', () => {
  it('★ the imported table is selected on the spot — that is what "use my own" means', async () => {
    state.importMock.mockResolvedValue(entry({ site_name: 'ras_baalbek' }));
    setLanguage('en');
    const onChange = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DetectionSettingsBar
          value={{
            model: '',
            lutSite: '',
            classes: [],
            conf: 0.25,
            imgsz: 640,
            trackerStart: 0,
            trackerType: 'csrt',
          }}
          onChange={onChange}
          running={false}
          starting={false}
          disabledReason={null}
          startError={null}
          onStart={() => undefined}
          onStop={() => undefined}
          onRestart={() => undefined}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Import a lookup table' }));
    dropZip('ras_baalbek_lut.zip');
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => expect(onChange).toHaveBeenCalledWith({ lutSite: 'ras_baalbek' }));
  });
});
