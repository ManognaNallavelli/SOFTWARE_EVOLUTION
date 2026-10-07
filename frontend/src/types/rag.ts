export type RagIndexStatus = 'not_indexed' | 'indexing' | 'ready' | 'failed'

export type RagStatus = {
  project_id: string
  status: RagIndexStatus
  chunk_count: number
  file_count: number
  indexed_at?: string | null
  updated_at?: string | null
  error?: string | null
  error_code?: string | null
  embedding_model?: string | null
  message?: string | null
}

export type ChatSource = {
  file_path: string
  language?: string | null
  symbol?: string | null
  start_line?: number | null
  end_line?: number | null
  excerpt: string
  score?: number | null
  supports?: string[]
}

export type AnalysisFileRef = {
  file_path: string
  line?: number | null
  end_line?: number | null
}

export type AnalysisFinding = {
  id: string
  kind: string
  title: string
  detail: string
  file_refs: AnalysisFileRef[]
}

export type WorkspacePage = 'overview' | 'health' | 'architecture'

export type ChatHealthSelection = {
  kind: 'issue' | 'recommendation'
  index: number
  title: string
}

/** Identifiers only; the backend resolves them against the project's stored analysis. */
export type ChatContext = {
  page?: WorkspacePage | null
  file_path?: string | null
  architecture_node_id?: string | null
  health_item?: ChatHealthSelection | null
}

export type ChatResponse = {
  project_id: string
  answer: string
  sources: ChatSource[]
  context_insufficient: boolean
  model?: string | null
  analysis_findings?: AnalysisFinding[]
  analysis_notes?: string[]
  context_applied?: string | null
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: ChatSource[]
  context_insufficient?: boolean
  analysis_findings?: AnalysisFinding[]
  analysis_notes?: string[]
  context_applied?: string | null
  /** Selection shown to the user when the question was sent. */
  context_label?: string | null
}
