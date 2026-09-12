/**
 * The landing page — it advertises what is built, and shows the way to learn it.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@mui/material/styles';
import { fireEvent, render, screen, within } from '@testing-library/react';

vi.mock('../api/hooks/useProjects', () => ({
  useProjects: () => ({ data: { items: [], total: 0 } }),
}));

import { HomePage } from '../pages/HomePage';
import { getTheme } from '../theme';
import { setLanguage } from '../i18n';
import { useCameraRegistryStore } from '../store/cameraRegistryStore';

function LocationProbe(): React.JSX.Element {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

function mount(): void {
  setLanguage('en');
  render(
    <ThemeProvider theme={getTheme('light')}>
      <MemoryRouter initialEntries={['/']}>
        <HomePage />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('the home page', () => {
  beforeEach(() => {
    useCameraRegistryStore.setState({ cameras: [] });
  });

  it('★ THE TWO MAIN PAGES are taught on the workflow board — one carousel each, stepping through its quick guide', () => {
    mount();
    const board = screen.getByRole('region', { name: 'Two pages, step by step' });
    const server = within(board).getByRole('article', { name: 'Camera workspace' });
    const monitoring = within(board).getByRole('article', { name: 'Cameras Monitoring' });
    // an overview of what each page contains…
    expect(within(server).getByText(/Every camera the app knows/)).toBeVisible();
    expect(within(monitoring).getByText(/Every registered camera on a globe/)).toBeVisible();
    // …and its quick guide as numbered steps, in the order the page is used
    const steps = within(server).getAllByRole('button', { name: /^Step \d/ });
    expect(steps.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Step 1: Open the page',
      'Step 2: Add the camera',
      'Step 3: Attach its DEM and calibration',
      'Step 4: Frame and control points',
      'Step 5: Build the lookup table',
    ]);
    expect(within(monitoring).getAllByRole('button', { name: /^Step \d/ })).toHaveLength(4);
    // the first step shows first; the others are hidden from assistive tech
    const slideOf = (text: RegExp): HTMLElement | null =>
      within(server).getByText(text).closest('[aria-hidden]');
    expect(steps[0]).toHaveAttribute('aria-current', 'true');
    expect(slideOf(/asks you to add the first one/)).toHaveAttribute('aria-hidden', 'false');
    expect(slideOf(/place four control points/)).toHaveAttribute('aria-hidden', 'true');
    // pick a step, or walk with the arrows — which wrap at both ends
    fireEvent.click(steps[3]);
    expect(steps[3]).toHaveAttribute('aria-current', 'true');
    expect(slideOf(/place four control points/)).toHaveAttribute('aria-hidden', 'false');
    fireEvent.click(within(server).getByRole('button', { name: 'Next step' }));
    fireEvent.click(within(server).getByRole('button', { name: 'Next step' }));
    expect(steps[0]).toHaveAttribute('aria-current', 'true');
    fireEvent.click(within(server).getByRole('button', { name: 'Previous step' }));
    expect(steps[4]).toHaveAttribute('aria-current', 'true');
    // each board's door opens its page
    fireEvent.click(within(server).getByRole('button', { name: 'Open the camera workspace' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/cameras');
    fireEvent.click(within(monitoring).getByRole('button', { name: 'Open cameras monitoring' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/monitor');
    // the hero's own door says the same name
    fireEvent.click(screen.getByRole('button', { name: 'Camera workspace' }));
    expect(screen.getByTestId('loc')).toHaveTextContent('/cameras');
  });

  it('★ the facts strip shows real figures — and an em-dash, never a zero, for nothing', () => {
    mount();
    // no cameras → "—", never a zero; and no workchain figures any more (2026-09-07).
    expect(screen.getByText('Cameras', { selector: 'div' })).toBeTruthy();
    expect(screen.getByText('Ready', { selector: 'div' })).toBeTruthy();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('Open pages')).toBeNull();
    expect(screen.queryByRole('button', { name: /^Continue:/ })).toBeNull();
  });

  it('★ counts the cameras and the ready ones from the registry', () => {
    useCameraRegistryStore.setState({
      cameras: [
        { id: 'a', name: 'A', lat: 34, lon: 36, source: 's', created_at: '', lut_site: 'a' },
        { id: 'b', name: 'B', lat: 34, lon: 36, source: 's', created_at: '' },
      ],
    });
    mount();
    expect(screen.getByText('Cameras', { selector: 'div' }).previousSibling).toHaveTextContent('2');
    expect(screen.getByText('Ready', { selector: 'div' }).previousSibling).toHaveTextContent('1');
  });

  it('★ under the hero: the board, how it works, the promises — the showcase, the guide teaser and the launcher are gone', () => {
    mount();
    expect(screen.queryAllByRole('button', { name: /Go to slide/ })).toHaveLength(0);
    expect(
      screen.queryByRole('region', { name: 'Learn the app with the workflow guide' }),
    ).toBeNull();
    expect(screen.queryByRole('navigation', { name: 'Workspaces' })).toBeNull();
    expect(screen.queryByText('Every page, one click')).toBeNull();
    expect(screen.getByText('How it works')).toBeVisible();
    const carousels = screen.getAllByRole('region', { name: /: Quick guide$/ });
    expect(carousels.map((c) => c.getAttribute('aria-label'))).toEqual([
      'Camera workspace: Quick guide',
      'Cameras Monitoring: Quick guide',
    ]);
    // the hero no longer carries the two cards — the board does
    expect(screen.queryByRole('region', { name: 'Main pages' })).toBeNull();
  });
});
