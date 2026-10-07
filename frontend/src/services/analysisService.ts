import { apiGet, apiPost } from './api'
import type { AnalysisDocument, HealthReport, RepositoryAnalysis } from '../types/analysis'

export function getProjectAnalysis(projectId: string): Promise<AnalysisDocument> {
  return apiGet<AnalysisDocument>(`/api/projects/${projectId}/analysis`)
}

export function getProjectHealth(projectId: string): Promise<AnalysisDocument> {
  return apiGet<AnalysisDocument>(`/api/projects/${projectId}/health`)
}

export type AnalyzeResponse = {
  project_id: string
  status: string
  message: string
  analysis: RepositoryAnalysis | null
  health_report?: HealthReport | null
  health_error?: string | null
  error: string | null
  error_code: string | null
  analyzed_at?: string | null
  updated_at?: string | null
}

export function analyzeProject(projectId: string): Promise<AnalyzeResponse> {
  return apiPost<AnalyzeResponse>(`/api/projects/${projectId}/analyze`)
}
