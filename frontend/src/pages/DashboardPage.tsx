import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageFade } from '../components/AnswerContent'
import { StatusBanner } from '../components/common/StatusBanner'
import { HealthScoreRing } from '../components/HealthScoreRing'
import { IconGithub, IconPlus, IconSearch } from '../components/icons'
import { useAuth } from '../hooks/useAuth'
import { stackForProjectCard } from '../lib/detectedStack'
import { formatUserError } from '../lib/errors'
import { formatRelativeTime, scoreBand, scoreBandLabel } from '../lib/healthUi'
import { getProjectAnalysis } from '../services/analysisService'
import { deleteProject, listProjects } from '../services/projectService'
import type { AnalysisDocument, HealthReport } from '../types/analysis'
import type { Project } from '../types/project'

type ProjectInsight = {
  analysisStatus: string | null
  analyzedAt: string | null
  health: HealthReport | null
  analysisDoc: AnalysisDocument | null
}

function projectMatchesQuery(project: Project, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const haystack = [
    project.name,
    project.github_full_name,
    project.normalized_github_url,
    project.github_url,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return haystack.includes(q)
}

export function DashboardPage() {
  const { user } = useAuth()
  const [projects, setProjects] = useState<Project[]>([])
  const [insights, setInsights] = useState<Record<string, ProjectInsight>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listProjects()
      setProjects(data.projects)
      const entries = await Promise.all(
        data.projects.map(async (project) => {
          try {
            const analysis = await getProjectAnalysis(project.id)
            return [
              project.id,
              {
                analysisStatus: analysis.status,
                analyzedAt: analysis.analyzed_at,
                health: analysis.health_report ?? null,
                analysisDoc: analysis,
              } satisfies ProjectInsight,
            ] as const
          } catch {
            return [
              project.id,
              {
                analysisStatus: null,
                analyzedAt: null,
                health: null,
                analysisDoc: null,
              } satisfies ProjectInsight,
            ] as const
          }
        }),
      )
      setInsights(Object.fromEntries(entries))
    } catch (err) {
      setError(formatUserError(err, 'Failed to load projects'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const filteredProjects = useMemo(
    () => projects.filter((project) => projectMatchesQuery(project, searchQuery)),
    [projects, searchQuery],
  )

  async function handleDelete(project: Project) {
    const confirmed = window.confirm(`Delete project "${project.name}"? This cannot be undone.`)
    if (!confirmed) return
    setDeletingId(project.id)
    try {
      await deleteProject(project.id)
      setProjects((prev) => prev.filter((p) => p.id !== project.id))
    } catch (err) {
      setError(formatUserError(err, 'Delete failed'))
    } finally {
      setDeletingId(null)
    }
  }

  const firstName = user?.name?.split(/\s+/)[0] || 'there'

  return (
    <PageFade>
      <div className="dashboard-page">
        <header className="command-header">
          <div>
            <p className="eyebrow">Engineering workspace</p>
            <h1>Welcome back, {firstName}</h1>
            <p className="muted">
              Your repository command center — health, architecture, and grounded code intelligence
              from public GitHub projects.
            </p>
          </div>
        </header>

        {loading && (
          <div className="skeleton-grid" aria-hidden>
            <div className="skeleton-card" />
            <div className="skeleton-card" />
            <div className="skeleton-card" />
          </div>
        )}

        {error && (
          <StatusBanner
            onDismiss={() => setError(null)}
            onRetry={() => void load()}
          >
            {error}
          </StatusBanner>
        )}

        {!loading && !error && projects.length === 0 && (
          <div className="empty-workspace">
            <div className="empty-workspace-visual" aria-hidden />
            <h2>No repositories analyzed yet</h2>
            <p className="muted">
              Connect a public GitHub repository. The platform discovers repository health,
              architecture structure, and code intelligence from the real codebase — not manual
              labels.
            </p>
            <Link className="btn btn-primary" to="/create-project">
              <IconPlus />
              Analyze a Repository
            </Link>
          </div>
        )}

        {!loading && projects.length > 0 && (
          <section className="dashboard-repos" id="projects">
            <div className="dashboard-repos-toolbar">
              <div>
                <p className="eyebrow">Your repositories</p>
                <h2 className="dashboard-repos-title">
                  {filteredProjects.length === projects.length
                    ? `${projects.length} connected`
                    : `${filteredProjects.length} of ${projects.length} shown`}
                </h2>
              </div>
              <label className="dashboard-search">
                <IconSearch />
                <input
                  type="search"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search repositories by name or GitHub URL..."
                  aria-label="Search repositories by name or GitHub URL"
                />
              </label>
            </div>

            {filteredProjects.length === 0 ? (
              <div className="dashboard-search-empty">
                <h3>No repositories found</h3>
                <p className="muted">
                  No matches for “{searchQuery.trim()}”. Try another name or GitHub URL.
                </p>
              </div>
            ) : (
              <div className="project-workspace-grid">
                {filteredProjects.map((project) => {
                  const insight = insights[project.id]
                  const health = insight?.health
                  const score = health?.overall_score ?? null
                  const band = scoreBand(score)
                  const healthLabel = scoreBandLabel(band, health?.status)
                  const status = insight?.analysisStatus || project.status
                  const stack = stackForProjectCard(project.technologies, insight?.analysisDoc)

                  return (
                    <article key={project.id} className={`repo-card band-${band}`}>
                      <Link to={`/projects/${project.id}`} className="repo-card-main">
                        <div className="repo-card-top">
                          <div className="repo-card-identity">
                            <h2>{project.name}</h2>
                            <p className="repo-path">
                              <IconGithub />
                              <span>{project.github_full_name || project.normalized_github_url}</span>
                            </p>
                          </div>
                          <div className="repo-card-score">
                            <HealthScoreRing score={score} status={health?.status} size={88} />
                            <span className={`health-chip band-text-${band}`}>{healthLabel}</span>
                          </div>
                        </div>

                        <div className="repo-card-meta">
                          <span className={`status-chip status-${status}`}>{formatStatus(status)}</span>
                          <span className="meta-time">
                            Last analyzed {formatRelativeTime(insight?.analyzedAt)}
                          </span>
                        </div>

                        <div className="repo-stack">
                          <span className="stack-label">Detected Stack</span>
                          {stack.length > 0 ? (
                            <div className="tech-badges">
                              {stack.slice(0, 6).map((tech) => (
                                <span key={tech} className="tech-badge">
                                  {tech}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <p className="muted small stack-empty">
                              {status === 'completed' || insight?.analysisDoc?.analysis
                                ? 'No stack signals found yet'
                                : 'Run Analyze to detect stack'}
                            </p>
                          )}
                        </div>
                      </Link>
                      <div className="repo-card-actions">
                        <Link className="btn btn-secondary" to={`/projects/${project.id}`}>
                          Open workspace
                        </Link>
                        <button
                          type="button"
                          className="btn btn-danger"
                          disabled={deletingId === project.id}
                          onClick={() => void handleDelete(project)}
                        >
                          {deletingId === project.id ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </section>
        )}
      </div>
    </PageFade>
  )
}

function formatStatus(status: string): string {
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
