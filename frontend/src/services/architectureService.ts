import { apiGet, apiPost } from './api'
import type { ArchitectureDocument } from '../types/architecture'

export function getProjectArchitecture(projectId: string): Promise<ArchitectureDocument> {
  return apiGet<ArchitectureDocument>(`/api/projects/${projectId}/architecture`)
}

export function generateProjectArchitecture(
  projectId: string,
  options?: { deterministic?: boolean },
): Promise<ArchitectureDocument> {
  const qs = options?.deterministic ? '?deterministic=true' : ''
  return apiPost<ArchitectureDocument>(`/api/projects/${projectId}/architecture/generate${qs}`)
}
