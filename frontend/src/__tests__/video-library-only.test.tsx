/**
 * A clip without a project — the library-only lane.
 *
 * ★ Uploading a clip for detection or drift work must not force a survey project on
 *   it. These pin: the upload form omits `project_id` when none is chosen, the clip's
 *   page has its own address, the shell knows that address, and the upload dialog
 *   says plainly where a project-less clip goes.
 */

import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import { resolvePageNav } from '../components/shell/pageNav';
import { workspaceForLocation } from '../components/shell/workspaces';
import { videoHref } from '../lib/videoHref';
import type { Uuid } from '../types/common';

vi.mock('../api/hooks/useVideos', () => ({
  useUploadVideo: () => ({ mutate: vi.fn(), isPending: false }),
  useAllVideos: () => ({
    data: { items: [], total: 0 },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useDeleteVideo: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('../api/hooks/useProjects', () => ({
  useProjects: () => ({
    data: { items: [{ id: 'p1', name: 'Yammouneh', image_count: 1 }], total: 1 },
  }),
  useCreateProject: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('../api/hooks/useImages', () => ({
  useImages: () => ({ data: { items: [] }, isLoading: false }),
}));

import { MemoryRouter } from 'react-router-dom';
import { fireEvent, within } from '@testing-library/react';
import { NotificationsProvider } from '../components/common/Notifications';
import { VideoLibrary } from '../components/video/VideoLibrary';
import { VideoUploadDialog } from '../components/video/VideoUploadDialog';

const V = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' as Uuid;
const P = '11111111-2222-3333-4444-555555555555' as Uuid;

describe('a library-only clip', () => {
  it('★ has its own address, and the shell knows it', () => {
    expect(videoHref({ id: V, project_id: null })).toBe(`/videos/${V}`);
    expect(videoHref({ id: V, project_id: P })).toBe(`/projects/${P}/videos/${V}`);
    expect(resolvePageNav(`/videos/${V}`)).toMatchObject({
      title: 'Video',
      parent: '/videos',
      parentTitle: 'Recorded videos',
    });
    expect(workspaceForLocation(`/videos/${V}`)).toBe('monitoring');
  });

  it('★ the upload form carries no project_id when none was chosen', async () => {
    const { toFormData } = await import('../api/videos');
    const file = new File([new Uint8Array([1, 2, 3])], 'clip.mp4', { type: 'video/mp4' });
    const without = toFormData({ file });
    expect(without.has('project_id')).toBe(false);
    expect(without.has('file')).toBe(true);
    const withProject = toFormData({ file, project_id: P });
    expect(withProject.get('project_id')).toBe(P);
    const byPath = toFormData({
      source_path: '/mnt/clips/a.mp4',
      filename: 'a.mp4',
      project_id: null,
    });
    expect(byPath.has('project_id')).toBe(false);
    expect(byPath.get('source_path')).toBe('/mnt/clips/a.mp4');
  });

  it('the upload dialog says where a project-less clip goes', () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <VideoUploadDialog
          open
          projectId={null}
          onClose={() => undefined}
          onUploaded={() => undefined}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/the clip goes to the video library only/)).toBeInTheDocument();
  });

  it('★ the Video editor’s picker offers the skip lane, and it opens a project-less upload', () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <NotificationsProvider>
          <MemoryRouter initialEntries={['/videos']}>
            <VideoLibrary />
          </MemoryRouter>
        </NotificationsProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getAllByRole('button', { name: /Upload video/ })[0]);
    const picker = screen.getByRole('dialog');
    // a project is offered, but not forced
    expect(within(picker).getByRole('button', { name: 'Continue' })).toBeDisabled();
    fireEvent.click(within(picker).getByRole('button', { name: 'Skip — library only' }));
    expect(screen.getByText(/the clip goes to the video library only/)).toBeInTheDocument();
  });
});
