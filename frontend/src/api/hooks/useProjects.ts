/**
 * Projects — endpoints 4–8.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { Page, Uuid } from '../../types/common';
import type {
  ProjectCreate,
  ProjectFilters,
  ProjectRead,
  ProjectSummary,
  ProjectUpdate,
} from '../../types/project';
import { projectsApi } from '../projects';
import { qk } from '../queryKeys';

export function useProjects(f: ProjectFilters = {}): UseQueryResult<Page<ProjectSummary>> {
  return useQuery({
    queryKey: qk.projects.list(f),
    queryFn: ({ signal }) => projectsApi.list(f, signal),
  });
}

export function useProject(
  projectId: Uuid | null,
  includeDeleted = false,
): UseQueryResult<ProjectRead> {
  return useQuery({
    queryKey: qk.projects.detail(projectId!),
    queryFn: ({ signal }) => projectsApi.get(projectId!, includeDeleted, signal),
    enabled: projectId !== null,
  });
}

export function useCreateProject(): UseMutationResult<ProjectRead, unknown, ProjectCreate> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectCreate) => projectsApi.create(body),
    onSuccess: (project) => {
      queryClient.setQueryData(qk.projects.detail(project.id), project);
      void queryClient.invalidateQueries({ queryKey: qk.projects.lists() });
    },
  });
}

export interface UpdateProjectVariables {
  projectId: Uuid;
  body: ProjectUpdate;
  /** `If-Match` is optional on endpoint 7; the client's registry supplies it. */
  etag?: string;
}

export function useUpdateProject(): UseMutationResult<
  ProjectRead,
  unknown,
  UpdateProjectVariables
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, body, etag }: UpdateProjectVariables) =>
      projectsApi.update(projectId, body, etag),
    onSuccess: (project) => {
      queryClient.setQueryData(qk.projects.detail(project.id), project);
      void queryClient.invalidateQueries({ queryKey: qk.projects.lists() });
    },
  });
}

export interface DeleteProjectVariables {
  projectId: Uuid;
  /** ★ `true` also drops the GCPs, exports and revision history. Requires confirmation. */
  hard?: boolean;
}

export function useDeleteProject(): UseMutationResult<void, unknown, DeleteProjectVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, hard }: DeleteProjectVariables) =>
      projectsApi.remove(projectId, hard ?? false),
    onSuccess: (_void, { projectId }) => {
      queryClient.removeQueries({ queryKey: qk.projects.detail(projectId) });
      void queryClient.invalidateQueries({ queryKey: qk.projects.lists() });
    },
  });
}
