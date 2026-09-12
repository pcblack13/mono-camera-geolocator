/**
 * The workflow guide — a manual is only useful if it stays true.
 *
 * ★ A guide's failure mode is silent rot: a door that navigates to a tab that no
 *   longer exists, a step that stops matching the product. These tests pin the
 *   course's contract: all ten steps on the rail in order, one step in focus at
 *   a time, every door landing on a real destination, honest "where it lives"
 *   notes for steps without a page, and a progress tick that is the reader's own.
 *
 * ★ AND THE SECOND VIEW (2026-09-12): the Pages view lists every page the app has
 *   with what each is responsible for, and the two views are wired to each other —
 *   a step's page chip crosses to that card, a card's step chip crosses back. A
 *   guide that could not answer "what is this page FOR?" sent the reader to the
 *   product to guess.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { fireEvent, render, screen, within } from '@testing-library/react';

import { GuidePage } from '../pages/GuidePage';
import { setLanguage } from '../i18n';
import { useGuideProgressStore } from '../store/guideProgressStore';

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mount(): void {
  setLanguage('en');
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/guide']}>
        <GuidePage />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const STEP_TITLES = [
  'Register the camera',
  'Prepare the elevation model (DEM)',
  'Attach the camera’s DEM',
  'Describe the camera',
  'Choose the frame',
  'Place control points in the Editor',
  'Build the lookup table',
  'Watch and detect',
  'Record the scene',
  'Export and hand over',
];

const rail = (): HTMLElement => screen.getByRole('tablist', { name: 'Steps' });
const pane = (): HTMLElement => screen.getByRole('tabpanel');
const selectStep = (title: string): void => {
  fireEvent.click(within(rail()).getByRole('tab', { name: new RegExp(title) }));
};

beforeEach(() => useGuideProgressStore.setState({ done: [] }));

describe('the workflow guide', () => {
  it('shows the whole method — all ten steps, in order, on the rail', () => {
    mount();
    const tabs = within(rail()).getAllByRole('tab');
    expect(tabs).toHaveLength(STEP_TITLES.length);
    for (let i = 0; i < STEP_TITLES.length; i += 1) {
      expect(tabs[i].textContent).toContain(STEP_TITLES[i]);
    }
  });

  it('★ one step in focus: step 1 greets the visitor; picking step 2 swaps the pane', () => {
    mount();
    expect(within(rail()).getByRole('tab', { name: /Register the camera/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(
      within(pane()).getByText(/Open the camera workspace — with no cameras yet/),
    ).toBeVisible();
    expect(
      screen.queryByText(
        'Crop it to the camera’s working area and reproject it to a metric CRS — the page suggests the UTM zone.',
      ),
    ).toBeNull();

    selectStep('Prepare the elevation model');
    expect(
      within(pane()).getByText(
        'Crop it to the camera’s working area and reproject it to a metric CRS — the page suggests the UTM zone.',
      ),
    ).toBeVisible();
    expect(within(pane()).getByText('STEP 2 / 10', { exact: false })).toBeInTheDocument();
  });

  it('every door opens the page it names', () => {
    // ★ The doors are the guide's whole claim to being interactive — each must
    //   land where its step happens, tab param and all.
    for (const [step, label, to] of [
      ['Register the camera', 'Open the camera workspace', '/cameras'],
      ['Prepare the elevation model', 'Open DEM processing', '/dem'],
      ['Choose the frame', 'Open Recorded videos', '/videos'],
      ['Watch and detect', 'Open cameras monitoring', '/monitor'],
      ['Record the scene', 'Open Recorded videos', '/videos'],
      ['Export and hand over', 'Open the camera workspace', '/cameras'],
    ] as const) {
      mount();
      selectStep(step);
      fireEvent.click(within(pane()).getByRole('button', { name: label }));
      expect(screen.getByTestId('loc'), label).toHaveTextContent(to);
      document.body.innerHTML = '';
    }
  });

  it('steps without a page of their own say where they live instead of faking a door', () => {
    mount();
    selectStep('Describe the camera');
    expect(
      within(pane()).getByText(
        'Lives on the camera’s settings page (step 5) — optional data, but the lookup table needs it.',
      ),
    ).toBeVisible();
    expect(within(pane()).queryByRole('button', { name: /^Open/ })).toBeNull();
    selectStep('Build the lookup table');
    expect(
      within(pane()).getByText(
        'Built from the editor’s strip or the camera’s settings page (step 7).',
      ),
    ).toBeVisible();
  });

  it('★ Next / Previous walk the route; the arrow keys do too', () => {
    mount();
    fireEvent.click(within(pane()).getByRole('button', { name: 'Next step' }));
    expect(within(rail()).getByRole('tab', { name: /Prepare the elevation/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    fireEvent.click(within(pane()).getByRole('button', { name: 'Previous' }));
    expect(within(rail()).getByRole('tab', { name: /Register the camera/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    fireEvent.keyDown(rail(), { key: 'ArrowDown' });
    fireEvent.keyDown(rail(), { key: 'ArrowDown' });
    expect(within(rail()).getByRole('tab', { name: /Attach the camera’s DEM/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    fireEvent.keyDown(rail(), { key: 'End' });
    expect(within(rail()).getByRole('tab', { name: /Export and hand over/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    // the last step has no Next
    expect(within(pane()).getByRole('button', { name: 'Next step' })).toBeDisabled();
  });

  it('★ "Mark as done" ticks the step, advances, and is the reader’s own (reset clears it)', () => {
    mount();
    expect(screen.getByText('0 / 10 done')).toBeInTheDocument();
    fireEvent.click(within(pane()).getByRole('button', { name: 'Mark as done' }));
    expect(screen.getByText('1 / 10 done')).toBeInTheDocument();
    expect(useGuideProgressStore.getState().done).toEqual(['Register the camera']);
    // moved on to step 2
    expect(within(rail()).getByRole('tab', { name: /Prepare the elevation/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    // tick a second one from further along the route, then reset from there
    selectStep('Export and hand over');
    fireEvent.click(within(pane()).getByRole('button', { name: 'Mark as done' }));
    expect(screen.getByText('2 / 10 done')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset progress' }));
    expect(screen.getByText('0 / 10 done')).toBeInTheDocument();
    expect(useGuideProgressStore.getState().done).toEqual([]);
    // every node is un-ticked again and the route starts over
    expect(within(rail()).getByRole('tab', { name: /Register the camera/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });
});

// ── the Pages view, and the wiring between the two (2026-09-12) ──────────────

const showPages = (): void => {
  fireEvent.click(screen.getByRole('button', { name: 'Pages' }));
};

describe('the Pages view — what every page is responsible for', () => {
  it('★ lists every page the app has, grouped by where it lives', () => {
    mount();
    showPages();
    // The three in the bar, the two tools, the pages a camera opens, the records,
    // and the rest — a reader must be able to find ANY page here.
    for (const name of [
      'Camera workspace',
      'Cameras Monitoring',
      'Recorded videos',
      'A camera’s settings',
      'The control-point editor',
      'A camera’s monitoring page',
      'DEM processing',
      'Drift monitor',
      'A recording',
      'A clip',
      'Dashboard',
      'App status & logs',
    ]) {
      expect(screen.getByRole('article', { name }), name).toBeInTheDocument();
    }
    for (const group of ['In the navbar', 'Inside a camera', 'Tools', 'Records', 'Elsewhere']) {
      expect(screen.getByRole('region', { name: group }), group).toBeInTheDocument();
    }
  });

  it('★ every card says what its page is RESPONSIBLE for — not what it looks like', () => {
    mount();
    showPages();
    const workspace = screen.getByRole('article', { name: 'Camera workspace' });
    expect(within(workspace).getByText(/The registry: which cameras exist at all/)).toBeVisible();
    const editor = screen.getByRole('article', { name: 'The control-point editor' });
    expect(
      within(editor).getByText(/Pairing pixels in the frame with positions on the satellite map/),
    ).toBeVisible();
  });

  it('★ a page with no address of its own says how to reach it instead of faking a door', () => {
    mount();
    showPages();
    const settings = screen.getByRole('article', { name: 'A camera’s settings' });
    expect(within(settings).getByText('no address of its own')).toBeVisible();
    expect(within(settings).getByText(/Open a camera from the camera workspace/)).toBeVisible();
    expect(within(settings).queryByRole('button', { name: 'Open' })).toBeNull();
    // ...while one that HAS an address offers the door.
    const dem = screen.getByRole('article', { name: 'DEM processing' });
    expect(within(dem).getByRole('button', { name: 'Open' })).toBeInTheDocument();
  });

  it('★ the search narrows the pages, over what is actually on the cards', () => {
    mount();
    showPages();
    fireEvent.change(screen.getByRole('textbox', { name: 'Search the pages' }), {
      target: { value: 'drift' },
    });
    expect(screen.getByRole('article', { name: 'Drift monitor' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'DEM processing' })).toBeNull();

    fireEvent.change(screen.getByRole('textbox', { name: 'Search the pages' }), {
      target: { value: 'zzzz' },
    });
    expect(screen.getByText('No page matches.')).toBeVisible();
  });

  it('★ a card’s Open button navigates to that page', () => {
    mount();
    showPages();
    const dem = screen.getByRole('article', { name: 'DEM processing' });
    fireEvent.click(within(dem).getByRole('button', { name: 'Open' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/dem');
  });
});

describe('the two views are wired to each other', () => {
  it('★ a step’s page chip crosses to that page’s card', () => {
    mount();
    selectStep('Place control points in the Editor');
    fireEvent.click(
      within(pane()).getByRole('button', { name: 'What is The control-point editor for?' }),
    );
    // we are in the Pages view now, on that card
    expect(screen.getByRole('article', { name: 'The control-point editor' })).toBeInTheDocument();
    expect(screen.queryByRole('tablist', { name: 'Steps' })).toBeNull();
  });

  it('★ a card’s step chip crosses back to that step of the route', () => {
    mount();
    showPages();
    const editor = screen.getByRole('article', { name: 'The control-point editor' });
    // The editor is where step 6 happens.
    fireEvent.click(within(editor).getByRole('button', { name: /Step 6/ }));
    expect(within(rail()).getByRole('tab', { name: /Place control points/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('★ the wiring is consistent both ways — every step a card claims claims it back', () => {
    // A one-sided link is how a map starts lying: the card says "step 6 happens
    // here" while the step never mentions the page.
    mount();
    showPages();
    for (const [pageName, stepIndexes] of [
      ['DEM processing', [2]],
      ['Drift monitor', [8]],
      ['A recording', [9]],
    ] as const) {
      const card = screen.getByRole('article', { name: pageName });
      for (const n of stepIndexes) {
        expect(within(card).getByRole('button', { name: `Step ${n}` }), pageName).toBeVisible();
      }
    }
  });
});
