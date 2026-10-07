export type LanguageCount = {
  language: string
  file_count: number
  total_bytes: number
}

export type AnalysisSummary = {
  total_files: number
  total_directories: number
  languages: LanguageCount[]
  important_files: string[]
  has_readme: boolean
  dependency_manifests: string[]
  deep_analysis_languages: string[]
  truncated: boolean
  symbol_count: number
  import_count: number
  export_count: number
  route_count: number
  production_route_count?: number
  test_or_example_route_count?: number
}

export type AnalysisFile = {
  path: string
  language: string | null
  size: number
  extension: string
  category: string
  code_role?: string
}

export type AnalysisSymbol = {
  name: string
  type: string
  file_path: string
  start_line: number | null
  end_line: number | null
  parent: string | null
}

export type AnalysisRoute = {
  file_path: string
  function: string | null
  method: string
  path: string | null
  line: number | null
  evidence: string
  code_role?: string
}

export type AnalysisDetections = {
  frontend_components: string[]
  backend_services: string[]
  api_routes: AnalysisRoute[]
  data_access_modules: string[]
  configuration_files: string[]
  tests: string[]
  integrations: string[]
}

export type RepositoryAnalysis = {
  project_id: string
  repository: {
    name: string
    url: string
    branch: string
    full_name?: string | null
  }
  summary: AnalysisSummary
  files: AnalysisFile[]
  symbols: AnalysisSymbol[]
  imports: { source_file: string; imported_module: string; names: string[]; line: number | null }[]
  exports: { source_file: string; name: string; export_type: string; line: number | null }[]
  detections: AnalysisDetections
  limits: Record<string, unknown>
}

export type HealthCategoryResult = {
  score: number | null
  status: 'scored' | 'insufficient_data'
  summary: string
  issues: string[]
  strengths: string[]
}

export type HealthIssue = {
  severity: 'critical' | 'high' | 'medium' | 'low'
  title: string
  detail: string
  category: string
  evidence: string[]
}

export type HealthRecommendation = {
  title: string
  reason: string
  priority: 'critical' | 'high' | 'medium' | 'low'
  expected_impact: string
  category: string
}

export type ArchitectureOverview = {
  main_technologies: string[]
  major_modules: string[]
  api_layer: string[]
  data_layer: string[]
  test_layer: string[]
  important_dependencies: string[]
  production_route_count: number
  test_or_example_route_count: number
  notes: string[]
}

export type HealthReport = {
  overall_score: number | null
  status: string
  categories: Record<string, HealthCategoryResult>
  strengths: string[]
  issues: HealthIssue[]
  recommendations: HealthRecommendation[]
  architecture_overview: ArchitectureOverview
  scoring_notes: string[]
  generated_from_analysis: boolean
}

export type AnalysisDocument = {
  project_id: string
  status: string
  analysis: RepositoryAnalysis | null
  health_report?: HealthReport | null
  health_error?: string | null
  error: string | null
  error_code: string | null
  analyzed_at: string | null
  updated_at: string | null
}
