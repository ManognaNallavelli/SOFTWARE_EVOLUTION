import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { PageFade } from '../components/AnswerContent'
import { ArchitectureCanvas } from '../components/architecture/ArchitectureCanvas'
import { CopilotDrawer } from '../components/chat/CopilotDrawer'
import { ProjectChatPanel } from '../components/chat/ProjectChatPanel'
import { StatusBanner } from '../components/common/StatusBanner'
import { HealthReportView } from '../components/health/HealthReportView'
import { IconArrowLeft, IconChat, IconGithub, IconMore } from '../components/icons'
import { WorkspaceOverview } from '../components/workspace/WorkspaceOverview'
import { formatRelativeTime } from '../lib/healthUi'
import { formatUserError } from '../lib/errors'
import { analyzeProject, getProjectAnalysis } from '../services/analysisService'
import {
  generateProjectArchitecture,
  getProjectArchitecture,
} from '../services/architectureService'
import { deleteProject, getProject } from '../services/projectService'
import { ApiError } from '../services/api'
import { indexRepository } from '../services/ragService'
import type {
  AnalysisDocument,
  HealthReport,
  RepositoryAnalysis,
} from '../types/analysis'
import type { ArchitectureDocument, ArchitectureNode } from '../types/architecture'
import type { Project } from '../types/project'
import type { ChatContext, WorkspacePage } from '../types/rag'

type WorkspacePanel = WorkspacePage

const PANEL_LABELS: Record<WorkspacePanel, string> = {
  overview: 'Overview',
  health: 'Health',
  architecture: 'Architecture',
}

const STACK_VISIBLE = 6

// Must match the global.css breakpoint where the drawer docks beside the workspace;
// below it the drawer is a full overlay, so it starts minimized.
const COPILOT_DOCK_QUERY = '(min-width: 1280px)'

function copilotOpensByDefault(): boolean {
  return typeof window !== 'undefined' && window.matchMedia(COPILOT_DOCK_QUERY).matches
}

function statusLabel(status: string): string {
  switch (status) {
    case 'created':
    case 'pending':
    case 'not_analyzed':
      return 'Not analyzed'
    case 'validating':
    case 'cloning':
    case 'analyzing':
      return 'Analyzing'
    case 'completed':
      return 'Analyzed'
    case 'failed':
      return 'Failed'
    default:
      return status.replace(/_/g, ' ')
  }
}

const ARCH_STAGES = ['Preparing', 'Analyzing', 'Generating', 'Ready'] as const

function archStageIndex(progress: string | null, generating: boolean, hasGraph: boolean): number {
  if (!progress && !generating) return hasGraph ? 3 : -1
  if (!progress) return 0
  if (progress.toLowerCase().includes('ready')) return 3
  if (progress.toLowerCase().includes('generat')) return 2
  if (progress.toLowerCase().includes('analyz')) return 1
  return 0
}

export function ProjectOverviewPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [project, setProject] = useState<Project | null>(null)
  const [analysisDoc, setAnalysisDoc] = useState<AnalysisDocument | null>(null)
  const [architectureDoc, setArchitectureDoc] = useState<ArchitectureDocument | null>(null)
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [generatingArch, setGeneratingArch] = useState(false)
  const [archProgress, setArchProgress] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [fileFilter, setFileFilter] = useState('')
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [activePanel, setActivePanel] = useState<WorkspacePanel>('overview')
  const [menuOpen, setMenuOpen] = useState(false)
  const [stackOpen, setStackOpen] = useState(false)
  const [downloadingArch, setDownloadingArch] = useState(false)
  const [refreshConfirmOpen, setRefreshConfirmOpen] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshProgress, setRefreshProgress] = useState<string | null>(null)
  const [indexEpoch, setIndexEpoch] = useState(0)
  const [copilotOpen, setCopilotOpen] = useState(copilotOpensByDefault)
  const [copilotFocus, setCopilotFocus] = useState(0)
  const [selectedNode, setSelectedNode] = useState<ArchitectureNode | null>(null)
  const [selectedFile, setSelectedFile] = useState<{ path: string; page: WorkspacePanel } | null>(
    null,
  )
  const menuRef = useRef<HTMLDivElement>(null)
  const stackRef = useRef<HTMLDivElement>(null)
  const downloadArchRef = useRef<(() => Promise<void>) | null>(null)
  const autoAnalyzeStartedRef = useRef(false)

  const handleArchDownloadReady = useCallback((fn: (() => Promise<void>) | null) => {
    downloadArchRef.current = fn
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedNode(null)
    setSelectedFile(null)
  }, [])

  const openPanel = useCallback(
    (panel: WorkspacePanel) => {
      setActivePanel(panel)
      clearSelection()
    },
    [clearSelection],
  )

  const openCopilot = useCallback(() => {
    setCopilotOpen(true)
    setCopilotFocus((value) => value + 1)
  }, [])

  const closeCopilot = useCallback(() => setCopilotOpen(false), [])

  const handleNodeSelection = useCallback((node: ArchitectureNode | null) => {
    setSelectedNode(node)
    setSelectedFile(null)
  }, [])

  const toggleFileSelection = useCallback((path: string, page: WorkspacePanel) => {
    setSelectedFile((current) => (current?.path === path ? null : { path, page }))
  }, [])

  const load = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    try {
      const [proj, analysis, architecture] = await Promise.all([
        getProject(projectId),
        getProjectAnalysis(projectId),
        getProjectArchitecture(projectId),
      ])
      setProject(proj)
      setAnalysisDoc(analysis)
      setArchitectureDoc(architecture)
    } catch (err) {
      setError(formatUserError(err, 'Failed to load project'))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      const target = event.target as Node
      if (menuRef.current && !menuRef.current.contains(target)) setMenuOpen(false)
      if (stackRef.current && !stackRef.current.contains(target)) setStackOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  const handleAnalyze = useCallback(async () => {
    if (!projectId) return
    setAnalyzing(true)
    setError(null)
    try {
      const result = await analyzeProject(projectId)
      setAnalysisDoc({
        project_id: result.project_id,
        status: result.status,
        analysis: result.analysis,
        health_report: result.health_report,
        health_error: result.health_error,
        error: result.error,
        error_code: result.error_code,
        analyzed_at: result.analyzed_at ?? null,
        updated_at: result.updated_at ?? null,
      })
      if (result.status === 'completed') setIndexEpoch((value) => value + 1)
      setProject(await getProject(projectId))
    } catch (err) {
      setError(formatUserError(err, 'Analysis failed'))
      try {
        setAnalysisDoc(await getProjectAnalysis(projectId))
        setProject(await getProject(projectId))
      } catch {
        // ignore
      }
    } finally {
      setAnalyzing(false)
    }
  }, [projectId])

  useEffect(() => {
    autoAnalyzeStartedRef.current = false
    clearSelection()
  }, [projectId, clearSelection])

  useEffect(() => {
    if (!projectId || loading || !project || analyzing || autoAnalyzeStartedRef.current) return
    if (analysisDoc?.status === 'completed' && analysisDoc.analysis) return
    if (analysisDoc?.status === 'failed') return

    const status = analysisDoc?.status || project.status
    const shouldAutoAnalyze =
      status === 'created' || status === 'pending' || status === 'not_analyzed'
    if (!shouldAutoAnalyze) return

    autoAnalyzeStartedRef.current = true
    if ((location.state as { autoAnalyze?: boolean } | null)?.autoAnalyze) {
      navigate(location.pathname, { replace: true, state: {} })
    }
    void handleAnalyze()
  }, [
    projectId,
    loading,
    project,
    analysisDoc,
    analyzing,
    handleAnalyze,
    location.pathname,
    location.state,
    navigate,
  ])

  async function handleRefreshRepository() {
    if (!projectId) return
    setRefreshConfirmOpen(false)
    setRefreshing(true)
    setError(null)
    setRefreshProgress('Re-analyzing the latest GitHub repository…')

    try {
      setAnalyzing(true)
      const result = await analyzeProject(projectId)
      setAnalysisDoc({
        project_id: result.project_id,
        status: result.status,
        analysis: result.analysis,
        health_report: result.health_report,
        health_error: result.health_error,
        error: result.error,
        error_code: result.error_code,
        analyzed_at: result.analyzed_at ?? null,
        updated_at: result.updated_at ?? null,
      })
      setProject(await getProject(projectId))
      setAnalyzing(false)

      if (result.status !== 'completed' || !result.analysis) {
        throw new Error(result.error || 'Repository analysis did not complete successfully.')
      }
      setIndexEpoch((value) => value + 1)

      setRefreshProgress('Regenerating architecture…')
      setGeneratingArch(true)
      setArchProgress('Generating architecture...')
      const architecture = await generateProjectArchitecture(projectId)
      setArchitectureDoc(architecture)
      setArchProgress('Architecture ready')
      setGeneratingArch(false)
      window.setTimeout(() => {
        setArchProgress((current) => (current === 'Architecture ready' ? null : current))
      }, 2500)

      setRefreshProgress('Refreshing the AI Copilot code index…')
      try {
        await indexRepository(projectId)
      } catch (err) {
        // Analysis above already started a background index; the Copilot shows its progress.
        if (!(err instanceof ApiError && err.code === 'rag_indexing_in_progress')) throw err
      }
      setIndexEpoch((value) => value + 1)

      setRefreshProgress('Repository intelligence refreshed')
      window.setTimeout(() => {
        setRefreshProgress((current) =>
          current === 'Repository intelligence refreshed' ? null : current,
        )
      }, 2500)
    } catch (err) {
      setError(formatUserError(err, 'Refresh failed'))
      setRefreshProgress(null)
      setArchProgress(null)
      try {
        setAnalysisDoc(await getProjectAnalysis(projectId))
        setArchitectureDoc(await getProjectArchitecture(projectId))
        setProject(await getProject(projectId))
      } catch {
        // ignore
      }
    } finally {
      setAnalyzing(false)
      setGeneratingArch(false)
      setRefreshing(false)
    }
  }

  async function handleDelete() {
    if (!project) return
    if (!window.confirm(`Delete project "${project.name}"? This cannot be undone.`)) return
    setMenuOpen(false)
    setDeleting(true)
    try {
      await deleteProject(project.id)
      navigate('/dashboard')
    } catch (err) {
      setError(formatUserError(err, 'Delete failed'))
      setDeleting(false)
    }
  }

  async function handleGenerateArchitecture() {
    if (!projectId) return
    setGeneratingArch(true)
    setError(null)
    setArchProgress(null)
    setActivePanel('architecture')

    try {
      setArchProgress('Preparing repository analysis...')
      let latestAnalysis = await getProjectAnalysis(projectId)
      setAnalysisDoc(latestAnalysis)

      const hasCompletedAnalysis =
        latestAnalysis.status === 'completed' && latestAnalysis.analysis != null

      if (!hasCompletedAnalysis) {
        setArchProgress('Analyzing repository...')
        setAnalyzing(true)
        try {
          const result = await analyzeProject(projectId)
          latestAnalysis = {
            project_id: result.project_id,
            status: result.status,
            analysis: result.analysis,
            health_report: result.health_report,
            health_error: result.health_error,
            error: result.error,
            error_code: result.error_code,
            analyzed_at: result.analyzed_at ?? null,
            updated_at: result.updated_at ?? null,
          }
          setAnalysisDoc(latestAnalysis)
          if (latestAnalysis.status === 'completed') setIndexEpoch((value) => value + 1)
          setProject(await getProject(projectId))
        } catch (err) {
          setError(formatUserError(err, 'Analysis failed'))
          setArchProgress(null)
          try {
            setAnalysisDoc(await getProjectAnalysis(projectId))
            setProject(await getProject(projectId))
          } catch {
            // ignore
          }
          return
        } finally {
          setAnalyzing(false)
        }

        if (latestAnalysis.status !== 'completed' || !latestAnalysis.analysis) {
          setError(
            latestAnalysis.error ||
              'Repository analysis did not complete successfully. Architecture was not generated.',
          )
          setArchProgress(null)
          return
        }
      }

      setArchProgress('Generating architecture...')
      const result = await generateProjectArchitecture(projectId)
      setArchitectureDoc(result)
      setArchProgress('Architecture ready')
    } catch (err) {
      setError(formatUserError(err, 'Architecture generation failed'))
      setArchProgress(null)
      try {
        setArchitectureDoc(await getProjectArchitecture(projectId))
      } catch {
        // ignore
      }
    } finally {
      setGeneratingArch(false)
      window.setTimeout(() => {
        setArchProgress((current) => (current === 'Architecture ready' ? null : current))
      }, 2500)
    }
  }

  const analysis: RepositoryAnalysis | null = analysisDoc?.analysis ?? null
  const health: HealthReport | null = analysisDoc?.health_report ?? null
  const displayStatus = analysisDoc?.status || project?.status || 'created'
  const stageIdx = archStageIndex(archProgress, generatingArch, Boolean(architectureDoc?.graph))

  const filteredFiles = useMemo(() => {
    if (!analysis) return []
    const q = fileFilter.trim().toLowerCase()
    if (!q) return analysis.files.slice(0, 200)
    return analysis.files.filter((f) => f.path.toLowerCase().includes(q)).slice(0, 200)
  }, [analysis, fileFilter])

  const productionRoutes = useMemo(() => {
    if (!analysis) return []
    return analysis.detections.api_routes.filter((r) => (r.code_role || 'production') === 'production')
  }, [analysis])

  const nonProductionRoutes = useMemo(() => {
    if (!analysis) return []
    return analysis.detections.api_routes.filter((r) =>
      ['test', 'example'].includes(r.code_role || ''),
    )
  }, [analysis])

  const copilotContext = useMemo<ChatContext>(() => {
    const ctx: ChatContext = { page: activePanel }
    if (selectedFile && selectedFile.page === activePanel) {
      ctx.file_path = selectedFile.path
    } else if (activePanel === 'architecture' && selectedNode) {
      ctx.architecture_node_id = selectedNode.id
    }
    return ctx
  }, [activePanel, selectedFile, selectedNode])

  const copilotContextLabel = useMemo(() => {
    if (copilotContext.file_path) return `File: ${copilotContext.file_path}`
    if (copilotContext.architecture_node_id && selectedNode) return `Component: ${selectedNode.label}`
    return `${PANEL_LABELS[activePanel]} page`
  }, [copilotContext, selectedNode, activePanel])

  const stack = project?.technologies ?? []
  const visibleStack = stack.slice(0, STACK_VISIBLE)
  const hiddenStackCount = Math.max(0, stack.length - STACK_VISIBLE)

  // Only show the skeleton on first load so a retry never unmounts the Copilot thread.
  if (loading && !project) {
    return (
      <PageFade>
        <div className="repo-workspace">
          <div className="project-loading">
            <div className="skeleton-card tall" />
            <div className="skeleton-grid">
              <div className="skeleton-card" />
              <div className="skeleton-card" />
              <div className="skeleton-card" />
            </div>
          </div>
        </div>
      </PageFade>
    )
  }

  if (!project) {
    return (
      <PageFade>
        <div className="repo-workspace">
          <div className="empty-workspace">
            <StatusBanner onRetry={() => void load()}>{error || 'Project not found'}</StatusBanner>
            <Link className="btn btn-secondary" to="/dashboard">
              ← All Repositories
            </Link>
          </div>
        </div>
      </PageFade>
    )
  }

  const navItems = (Object.keys(PANEL_LABELS) as WorkspacePanel[]).map((id) => ({
    id,
    label: PANEL_LABELS[id],
  }))

  return (
    <PageFade>
      <div className={`repo-workspace${copilotOpen ? ' has-copilot' : ''}`}>
        <header className="ws-header">
          <Link className="ws-back" to="/dashboard">
            <IconArrowLeft />
            All Repositories
          </Link>

          <div className="ws-header-row">
            <div className="ws-identity">
              <h1>{project.name}</h1>
              <a
                className="repo-link"
                href={project.normalized_github_url}
                target="_blank"
                rel="noreferrer"
              >
                <IconGithub />
                <span className="mono">
                  {project.github_full_name
                    ? `github.com/${project.github_full_name}`
                    : project.normalized_github_url}
                </span>
              </a>
              <div className="ws-status-row">
                <span className={`status-chip status-${displayStatus}`}>
                  {statusLabel(displayStatus).toUpperCase()}
                </span>
                <span className="meta-time">{formatRelativeTime(analysisDoc?.analyzed_at)}</span>
              </div>
            </div>

            <div className="ws-header-actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={refreshing || analyzing || generatingArch}
                onClick={() => setRefreshConfirmOpen(true)}
              >
                {refreshing ? 'Refreshing…' : 'Refresh Repository'}
              </button>
              <div className="ws-overflow" ref={menuRef}>
                <button
                  type="button"
                  className="btn btn-ghost btn-icon"
                  aria-label="More actions"
                  aria-expanded={menuOpen}
                  onClick={() => setMenuOpen((open) => !open)}
                >
                  <IconMore />
                </button>
                {menuOpen && (
                  <div className="ws-menu" role="menu">
                    <button
                      type="button"
                      className="ws-menu-item danger"
                      role="menuitem"
                      disabled={deleting || refreshing}
                      onClick={() => void handleDelete()}
                    >
                      {deleting ? 'Deleting…' : 'Delete repository'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="ws-stack" ref={stackRef}>
            <span className="stack-label">Detected Stack</span>
            {stack.length === 0 ? (
              <p className="muted small stack-empty">
                {displayStatus === 'completed'
                  ? 'No stack signals stored yet'
                  : 'Run Analyze to detect stack'}
              </p>
            ) : (
              <div className="ws-stack-row">
                <div className="tech-badges">
                  {visibleStack.map((tech) => (
                    <span key={tech} className="tech-badge">
                      {tech}
                    </span>
                  ))}
                </div>
                {hiddenStackCount > 0 && (
                  <button
                    type="button"
                    className="stack-more"
                    onClick={() => setStackOpen((open) => !open)}
                  >
                    View all{hiddenStackCount > 0 ? ` (+${hiddenStackCount})` : ''}
                  </button>
                )}
                {stackOpen && (
                  <div className="stack-popover" role="dialog" aria-label="Full detected stack">
                    <p className="stack-label">All detected technologies</p>
                    <div className="tech-badges">
                      {stack.map((tech) => (
                        <span key={tech} className="tech-badge">
                          {tech}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </header>

        {error && (
          <StatusBanner
            onDismiss={() => setError(null)}
            onRetry={() => void load()}
          >
            {error}
          </StatusBanner>
        )}
        {(refreshing || refreshProgress) && (
          <StatusBanner tone="info">
            {refreshProgress || 'Refreshing repository intelligence…'}
          </StatusBanner>
        )}
        {analyzing && !refreshing && (
          <StatusBanner tone="info">
            Cloning and analyzing the repository, then calculating the health report…
          </StatusBanner>
        )}
        {(analysisDoc?.error || project.last_error) && displayStatus === 'failed' && (
          <StatusBanner>{analysisDoc?.error || project.last_error}</StatusBanner>
        )}

        {refreshConfirmOpen && (
          <div
            className="ws-confirm-backdrop"
            role="presentation"
            onClick={() => !refreshing && setRefreshConfirmOpen(false)}
          >
            <div
              className="ws-confirm-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="refresh-repo-title"
              onClick={(event) => event.stopPropagation()}
            >
              <h2 id="refresh-repo-title">Refresh repository intelligence?</h2>
              <p className="muted">
                This will re-analyze the latest GitHub code, regenerate the architecture, and refresh
                the AI Copilot’s code index. Your Copilot conversation is kept. This may take a few
                minutes.
              </p>
              <div className="ws-confirm-actions">
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={refreshing}
                  onClick={() => setRefreshConfirmOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={refreshing}
                  onClick={() => void handleRefreshRepository()}
                >
                  Refresh
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="ws-body">
          <aside className="ws-nav" aria-label="Repository workspace">
            <p className="ws-nav-label">Workspace</p>
            <nav className="ws-nav-list">
              {navItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`ws-nav-item${activePanel === item.id ? ' is-active' : ''}`}
                  aria-current={activePanel === item.id ? 'page' : undefined}
                  onClick={() => openPanel(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </nav>
          </aside>

          <main className="ws-main">
            {activePanel === 'overview' && (
              <WorkspaceOverview
                analysisDoc={analysisDoc}
                analysis={analysis}
                health={health}
                architectureDoc={architectureDoc}
                onOpenHealth={() => openPanel('health')}
              />
            )}

            {activePanel === 'health' && (
              <section className="workspace-panel health-panel">
                {!analysis && !analyzing ? (
                  <div className="panel-empty">
                    <h2>No health report yet</h2>
                    <p className="muted">
                      Analyze the repository to unlock category scores, strengths, issues, and
                      recommendations.
                    </p>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => void handleAnalyze()}
                    >
                      Analyze Repository
                    </button>
                  </div>
                ) : (
                  <>
                    {analysisDoc?.health_error && (
                      <StatusBanner>
                        Raw analysis succeeded, but health scoring failed: {analysisDoc.health_error}
                      </StatusBanner>
                    )}

                    {health && (
                      <>
                        <HealthReportView health={health} />

                        <section className="analysis-basis" aria-label="Analysis basis">
                          <h3>Analysis basis</h3>
                          <p>
                            This report is based on static structural analysis of repository files,
                            symbols, dependencies, tests, and configuration. It does not execute the
                            code or perform runtime monitoring, CVE scanning, or dependency
                            vulnerability scanning.
                          </p>
                        </section>
                      </>
                    )}

                    {analysis && (
                      <div className="tech-details-wrap">
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => setDetailsOpen((open) => !open)}
                        >
                          {detailsOpen ? 'Hide technical details' : 'View technical details'}
                        </button>
                        {detailsOpen && (
                          <div className="tech-details">
                            <dl className="meta-grid">
                              <div>
                                <dt>Files</dt>
                                <dd>{analysis.summary.total_files}</dd>
                              </div>
                              <div>
                                <dt>Directories</dt>
                                <dd>{analysis.summary.total_directories}</dd>
                              </div>
                              <div>
                                <dt>Symbols</dt>
                                <dd>{analysis.summary.symbol_count}</dd>
                              </div>
                              <div>
                                <dt>Production / test routes</dt>
                                <dd>
                                  {analysis.summary.production_route_count ??
                                    productionRoutes.length}{' '}
                                  /{' '}
                                  {analysis.summary.test_or_example_route_count ??
                                    nonProductionRoutes.length}
                                </dd>
                              </div>
                            </dl>
                            <h4>Important files</h4>
                            <ul className="path-list">
                              {analysis.summary.important_files.map((path) => (
                                <li key={path}>{path}</li>
                              ))}
                            </ul>
                            <div className="filter-row">
                              <h4>Files</h4>
                              <input
                                className="filter-input"
                                value={fileFilter}
                                onChange={(e) => setFileFilter(e.target.value)}
                                placeholder="Filter by path…"
                              />
                            </div>
                            <p className="muted small">
                              Select a file to give the AI Copilot context about it.
                            </p>
                            <ul className="path-list scrollable">
                              {filteredFiles.map((file) => (
                                <li key={file.path}>
                                  <button
                                    type="button"
                                    className={`path-select${selectedFile?.path === file.path ? ' is-selected' : ''}`}
                                    aria-pressed={selectedFile?.path === file.path}
                                    onClick={() => toggleFileSelection(file.path, 'health')}
                                  >
                                    {file.path}
                                  </button>
                                  <span className="muted">
                                    {' '}
                                    · {file.code_role || 'production'} ·{' '}
                                    {file.language || 'unknown'}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </section>
            )}

            {activePanel === 'architecture' && (
              <section className="workspace-panel architecture-panel">
                <div className="section-heading">
                  <div>
                    <h2>Architecture Map</h2>
                  </div>
                  <div className="arch-actions">
                    {architectureDoc?.graph && (
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={downloadingArch || generatingArch}
                        onClick={() => {
                          void (async () => {
                            if (!downloadArchRef.current) return
                            setDownloadingArch(true)
                            try {
                              await downloadArchRef.current()
                            } finally {
                              setDownloadingArch(false)
                            }
                          })()
                        }}
                      >
                        {downloadingArch ? 'Downloading…' : 'Download Architecture'}
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={generatingArch || analyzing}
                      onClick={() => void handleGenerateArchitecture()}
                    >
                      {generatingArch
                        ? 'Working…'
                        : architectureDoc?.graph
                          ? 'Regenerate Architecture'
                          : 'Generate Architecture'}
                    </button>
                  </div>
                </div>

                {(generatingArch || archProgress) && (
                  <div className="arch-pipeline" aria-live="polite">
                    {ARCH_STAGES.map((stage, idx) => (
                      <span
                        key={stage}
                        className={`arch-stage${idx <= stageIdx ? ' is-done' : ''}${idx === stageIdx ? ' is-current' : ''}`}
                      >
                        {stage}
                      </span>
                    ))}
                  </div>
                )}

                {architectureDoc?.status === 'failed' && architectureDoc.error && (
                  <StatusBanner>{architectureDoc.error}</StatusBanner>
                )}

                {!architectureDoc?.graph && !generatingArch && !archProgress && (
                  <div className="panel-empty architecture-empty-state">
                    <h3>No architecture graph yet</h3>
                    <p className="muted">
                      Generate a validated diagram from structural evidence. If analysis is missing,
                      it runs automatically first.
                    </p>
                  </div>
                )}

                {architectureDoc?.graph && (
                  <>
                    <div className="arch-meta-row">
                      <span>Generated Architecture</span>
                      {architectureDoc.generated_at && (
                        <span className="muted">
                          Generated {new Date(architectureDoc.generated_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                    {architectureDoc.graph.summary && (
                      <p className="arch-summary">{architectureDoc.graph.summary}</p>
                    )}
                    <ArchitectureCanvas
                      graph={architectureDoc.graph}
                      onDownloadReady={handleArchDownloadReady}
                      onSelectionChange={handleNodeSelection}
                      selectedFile={
                        selectedFile?.page === 'architecture' ? selectedFile.path : null
                      }
                      onSelectFile={(path) => toggleFileSelection(path, 'architecture')}
                      onAskCopilot={openCopilot}
                    />
                    {architectureDoc.graph.warnings.length > 0 && (
                      <details className="arch-warnings">
                        <summary>Validation notes</summary>
                        <ul>
                          {architectureDoc.graph.warnings.slice(0, 12).map((w) => (
                            <li key={w}>{w}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </>
                )}
              </section>
            )}

          </main>
        </div>

        <button
          type="button"
          className={`copilot-fab${copilotOpen ? ' is-hidden' : ''}`}
          aria-label="Ask Copilot"
          aria-expanded={copilotOpen}
          aria-controls="copilot-drawer"
          onClick={openCopilot}
        >
          <IconChat />
          <span className="copilot-fab-label">Ask Copilot</span>
        </button>

        {projectId && (
          <CopilotDrawer open={copilotOpen} onClose={closeCopilot}>
            <ProjectChatPanel
              key={projectId}
              projectId={projectId}
              indexEpoch={indexEpoch}
              analysisAvailable={Boolean(analysis)}
              analyzing={analyzing}
              context={copilotContext}
              contextLabel={copilotContextLabel}
              onClearContext={clearSelection}
              onClose={closeCopilot}
              focusSignal={copilotFocus}
            />
          </CopilotDrawer>
        )}
      </div>
    </PageFade>
  )
}
