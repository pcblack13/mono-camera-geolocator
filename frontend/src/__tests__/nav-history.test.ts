/**
 * The visit stack behind "← Back to …".
 *
 * ★ The bug this replaced: every page's structural parent was Home, so the control
 *   read "Back to Home" no matter where the user had come from. These tests pin the
 *   three properties that make a real trail useful — it remembers, it unwinds, and
 *   it never grows a ping-pong the user cannot walk out of.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { useNavHistoryStore } from '../store/navHistoryStore';

const visit = (path: string): void => useNavHistoryStore.getState().visit(path);
const replaceVisit = (path: string): void => useNavHistoryStore.getState().replaceVisit(path);
const previous = (): string | null => useNavHistoryStore.getState().previous();
const stack = (): string[] => useNavHistoryStore.getState().stack;

beforeEach(() => useNavHistoryStore.setState({ stack: [] }));

describe('nav history', () => {
  it('has nowhere to go back to on the first page of a session', () => {
    visit('/projects');
    expect(previous()).toBeNull();
  });

  it('★ remembers where you came from — not the structural parent', () => {
    visit('/projects'); // Workspace
    visit('/dem'); // whose structural parent is Home
    expect(previous()).toBe('/projects');
  });

  it('ignores a repeat of the current path', () => {
    visit('/projects');
    visit('/projects');
    expect(stack()).toEqual(['/projects']);
  });

  it('★ UNWINDS instead of growing when you go back', () => {
    visit('/'); // Home
    visit('/projects'); // Workspace
    visit('/dem'); // DEM
    expect(previous()).toBe('/projects');

    visit('/projects'); // the user pressed back
    expect(stack()).toEqual(['/', '/projects']);
    // ★ Back again walks further OUT, never bouncing to /dem — the ping-pong that
    //   a naive "last visited" would produce.
    expect(previous()).toBe('/');
  });

  it('walks a deep trail back out in order', () => {
    visit('/');
    visit('/projects');
    visit('/projects/abc');
    visit('/projects/abc/images/xyz');
    expect(previous()).toBe('/projects/abc');
    visit('/projects/abc');
    expect(previous()).toBe('/projects');
    visit('/projects');
    expect(previous()).toBe('/');
  });

  it('is bounded — a long session cannot grow without limit', () => {
    for (let i = 0; i < 60; i += 1) visit(`/p/${i}`);
    expect(stack().length).toBeLessThanOrEqual(20);
    // The most recent pages are the ones kept.
    expect(stack()[stack().length - 1]).toBe('/p/59');
  });
});

describe('redirects replace, they do not advance', () => {
  beforeEach(() => useNavHistoryStore.setState({ stack: [] }));

  it('★ a redirected page never becomes a back destination', () => {
    // The real sequence: Video editor tab → click a frame → the editor gate
    // REDIRECTS an un-set-up photo to its setup page.
    visit('/projects?tab=videos');
    visit('/projects/p1/images/i1'); // the editor…
    replaceVisit('/projects/p1/images/i1/setup'); // …which forwards here

    // Back must skip the forwarding URL entirely — landing on it would bounce
    // straight forward again and read as a dead button.
    expect(previous()).toBe('/projects?tab=videos');
    expect(stack()).toEqual(['/projects?tab=videos', '/projects/p1/images/i1/setup']);
  });

  it('★ keeps the query — the tab IS the page', () => {
    visit('/projects?tab=videos');
    visit('/projects/p1/videos/v1');
    // Not '/projects', which would land on the Projects tab instead.
    expect(previous()).toBe('/projects?tab=videos');
  });

  it('a replace on an empty stack simply seeds it', () => {
    replaceVisit('/projects/p1/setup');
    expect(stack()).toEqual(['/projects/p1/setup']);
    expect(previous()).toBeNull();
  });
});
