export type ArchitectureNodeKind =
  | 'frontend'
  | 'backend'
  | 'service'
  | 'module'
  | 'api'
  | 'database'
  | 'external'
  | 'config'
  | 'test'
  | 'other'

export type ArchitectureEdgeType =
  | 'calls'
  | 'imports'
  | 'uses'
  | 'contains'
  | 'exposes'
  | 'stores'
  | 'depends_on'

export type ArchitectureNode = {
  id: string
  label: string
  kind: ArchitectureNodeKind
  description?: string | null
  file_paths: string[]
  evidence: string[]
}

export type ArchitectureEdge = {
  id: string
  source: string
  target: string
  type: ArchitectureEdgeType
  label?: string | null
  evidence: string[]
}

export type ArchitectureGraph = {
  nodes: ArchitectureNode[]
  edges: ArchitectureEdge[]
  summary?: string | null
  warnings: string[]
}

export type ArchitectureDocument = {
  project_id: string
  status: 'not_generated' | 'generating' | 'completed' | 'failed'
  graph: ArchitectureGraph | null
  source: 'gemini' | 'deterministic' | null
  gemini_model?: string | null
  analysis_project_id?: string | null
  analyzed_at?: string | null
  generated_at?: string | null
  updated_at?: string | null
  error?: string | null
  error_code?: string | null
  version: number
  message?: string
}
