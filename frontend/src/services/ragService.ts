import { apiGet, apiPost } from './api'
import type { ChatContext, ChatResponse, RagStatus } from '../types/rag'

export function getRagStatus(projectId: string): Promise<RagStatus> {
  return apiGet<RagStatus>(`/api/projects/${projectId}/rag/status`)
}

export function indexRepository(projectId: string): Promise<RagStatus> {
  return apiPost<RagStatus>(`/api/projects/${projectId}/rag/index`)
}

export function chatWithProject(
  projectId: string,
  message: string,
  context?: ChatContext,
): Promise<ChatResponse> {
  return apiPost<ChatResponse>(`/api/projects/${projectId}/chat`, context ? { message, context } : { message })
}
