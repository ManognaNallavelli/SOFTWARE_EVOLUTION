import { apiDelete, apiGet, apiPost } from './api'
import type { Project, ProjectCreateInput } from '../types/project'

export function listProjects(): Promise<{ projects: Project[] }> {
  return apiGet<{ projects: Project[] }>('/api/projects')
}

export function createProject(input: ProjectCreateInput): Promise<Project> {
  return apiPost<Project>('/api/projects', input)
}

export function getProject(projectId: string): Promise<Project> {
  return apiGet<Project>(`/api/projects/${projectId}`)
}

export function deleteProject(projectId: string): Promise<void> {
  return apiDelete(`/api/projects/${projectId}`)
}
