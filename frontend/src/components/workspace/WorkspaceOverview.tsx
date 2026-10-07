import { HealthScoreRing } from '../HealthScoreRing'
import { buildKeyFindings } from '../../lib/keyFindings'
import { scoreBand, scoreBandLabel } from '../../lib/healthUi'
import type { AnalysisDocument, HealthReport, RepositoryAnalysis } from '../../types/analysis'
import type { ArchitectureDocument } from '../../types/architecture'

type Props = {
  analysisDoc: AnalysisDocument | null
  analysis: RepositoryAnalysis | null
  health: HealthReport | null
  architectureDoc: ArchitectureDocument | null
  onOpenHealth: () => void
}

export function WorkspaceOverview({
  analysisDoc,
  analysis,
  health,
  architectureDoc,
  onOpenHealth,
}: Props) {
  const band = scoreBand(health?.overall_score)
  const healthLabel = scoreBandLabel(band, health?.status)
  const findings = buildKeyFindings(health, analysis, 4)
  const productionRoutes =
    analysis?.summary.production_route_count ??
    analysis?.detections.api_routes.filter((r) => (r.code_role || 'production') === 'production')
      .length ??
    null
  const hasArchitecture = Boolean(architectureDoc?.graph)
  const archLabel = hasArchitecture
    ? 'Mapped'
    : analysisDoc?.status === 'completed'
      ? 'Not generated'
      : '—'

  if (!analysis && !health) {
    return (
      <section className="ws-overview">
        <div className="panel-empty">
          <h2>No analysis yet</h2>
          <p className="muted">Use Refresh Repository in the header to analyze this repository.</p>
        </div>
      </section>
    )
  }

  return (
    <section className="ws-overview">
      <header className="ws-section-head">
        <p className="eyebrow">Repository snapshot</p>
      </header>

      <div className="snapshot-grid" aria-label="Repository snapshot metrics">
        <article className="snapshot-card">
          <span className="snapshot-card-label">Health</span>
          <div className="snapshot-card-health">
            <HealthScoreRing score={health?.overall_score ?? null} status={health?.status} size={72} />
            <div>
              <strong className="snapshot-card-value">
                {health?.overall_score != null ? Math.round(health.overall_score) : '—'}
              </strong>
              <span className={`band-text-${band}`}>{health ? healthLabel : 'Not scored'}</span>
            </div>
          </div>
        </article>

        <article className="snapshot-card">
          <span className="snapshot-card-label">Files</span>
          <strong className="snapshot-card-value">
            {analysis ? analysis.summary.total_files : '—'}
          </strong>
        </article>

        <article className="snapshot-card">
          <span className="snapshot-card-label">Symbols</span>
          <strong className="snapshot-card-value">
            {analysis ? analysis.summary.symbol_count : '—'}
          </strong>
        </article>

        <article className="snapshot-card">
          <span className="snapshot-card-label">Directories</span>
          <strong className="snapshot-card-value">
            {analysis ? analysis.summary.total_directories : '—'}
          </strong>
        </article>

        <article className="snapshot-card">
          <span className="snapshot-card-label">API routes</span>
          <strong className="snapshot-card-value">
            {productionRoutes != null ? productionRoutes : '—'}
          </strong>
          <span className="snapshot-card-note muted small">Production</span>
        </article>

        <article className="snapshot-card">
          <span className="snapshot-card-label">Architecture</span>
          <strong className="snapshot-card-value snapshot-card-value-sm">{archLabel}</strong>
        </article>
      </div>

      <div className="key-findings">
        <div className="ws-section-head compact">
          <p className="eyebrow">Key findings</p>
          <h3>Signals from analysis</h3>
        </div>
        {findings.length === 0 ? (
          <p className="muted">No compact findings available yet. Open Health for full detail.</p>
        ) : (
          <ul className="finding-list">
            {findings.map((finding) => (
              <li key={finding.id} className={`finding-item tone-${finding.tone}`}>
                <span className="finding-dot" aria-hidden />
                <span>{finding.text}</span>
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="text-link" onClick={onOpenHealth}>
          View full health report →
        </button>
      </div>
    </section>
  )
}
