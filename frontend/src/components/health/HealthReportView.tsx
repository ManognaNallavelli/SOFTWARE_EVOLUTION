import { useMemo, useState } from 'react'
import {
  HEALTH_CATEGORY_LABELS,
  HEALTH_CATEGORY_WEIGHTS,
  HEALTH_DOMAIN_COLORS,
  HEALTH_SCORING_METHOD,
  scoreBand,
  scoreBandLabel,
} from '../../lib/healthUi'
import type { HealthRecommendation, HealthReport } from '../../types/analysis'
import { HealthScoreRing } from '../HealthScoreRing'

type Props = {
  health: HealthReport
}

type Domain = {
  key: string
  label: string
  color: string
  score: number | null
  summary: string
  strengths: string[]
  issues: string[]
}

const STRENGTH_THRESHOLD = 80
const FALLBACK_COLOR = '#94a3b8'

function bandLabel(score: number | null): string {
  return score == null ? 'Not scored' : scoreBandLabel(scoreBand(score))
}

export function HealthReportView({ health }: Props) {
  const domains = useMemo<Domain[]>(
    () =>
      Object.entries(HEALTH_CATEGORY_LABELS)
        .filter(([key]) => health.categories[key])
        .map(([key, label]) => {
          const cat = health.categories[key]
          return {
            key,
            label,
            color: HEALTH_DOMAIN_COLORS[key] ?? FALLBACK_COLOR,
            score: cat.status === 'insufficient_data' || cat.score == null ? null : cat.score,
            summary: cat.summary,
            strengths: cat.strengths ?? [],
            issues: cat.issues ?? [],
          }
        }),
    [health],
  )

  const lowestKey = useMemo(() => {
    const scored = domains.filter((d) => d.score != null)
    if (scored.length === 0) return domains[0]?.key ?? null
    return scored.reduce((low, d) => ((d.score ?? 0) < (low.score ?? 0) ? d : low)).key
  }, [domains])

  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const activeKey = selectedKey && domains.some((d) => d.key === selectedKey) ? selectedKey : lowestKey
  const active = domains.find((d) => d.key === activeKey) ?? null

  const weightGroups = useMemo(() => {
    const groups = new Map<number, string[]>()
    for (const d of domains) {
      const weight = HEALTH_CATEGORY_WEIGHTS[d.key]
      if (weight == null) continue
      groups.set(weight, [...(groups.get(weight) ?? []), d.label])
    }
    return [...groups.entries()].sort((a, b) => b[0] - a[0])
  }, [domains])

  const overallStrengths = useMemo(
    () =>
      domains
        .filter((d) => d.score != null && d.score >= STRENGTH_THRESHOLD && d.strengths.length > 0)
        .sort((a, b) => (b.score ?? 0) - (a.score ?? 0)),
    [domains],
  )

  const overallWeaknesses = useMemo(
    () =>
      domains
        .filter((d) => d.score != null && d.score < STRENGTH_THRESHOLD && d.issues.length > 0)
        .sort((a, b) => (a.score ?? 0) - (b.score ?? 0)),
    [domains],
  )

  const activeRecommendations = useMemo(
    () => (active ? health.recommendations.filter((r) => r.category === active.key) : []),
    [health.recommendations, active],
  )

  return (
    <div className="health-report">
      <div className="health-top">
        <section className="health-card health-score-card" aria-label="Overall health">
          <p className="eyebrow">Overall health</p>
          <div className="health-score-body">
            <HealthScoreRing score={health.overall_score} status={health.status} size={164} />
            {weightGroups.length > 0 && (
              <div className="health-calc">
                <h3>How the overall score is calculated</h3>
                <p>
                  A weighted average of the domain scores. Domains without enough evidence are left
                  out.
                </p>
                <dl className="health-weights">
                  {weightGroups.map(([weight, labels]) => (
                    <div key={weight}>
                      <dt>{labels.length > 1 ? `${weight}% each` : `${weight}%`}</dt>
                      <dd>{labels.join(', ')}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
          </div>
        </section>

        <section className="health-card health-domain-card" aria-label="Health domains">
          <p className="eyebrow">Health domains</p>
          <ul className="band-legend" aria-hidden>
            <li className="band-excellent">Healthy</li>
            <li className="band-good">Moderate</li>
            <li className="band-attention">Needs improvement</li>
            <li className="band-critical">Critical</li>
          </ul>
          <ul className="domain-rows">
            {domains.map((d) => {
              const band = scoreBand(d.score)
              const selected = d.key === activeKey
              return (
                <li key={d.key}>
                  <button
                    type="button"
                    className={`domain-row band-${band}${selected ? ' is-selected' : ''}`}
                    style={{ ['--domain-color' as string]: d.color }}
                    aria-pressed={selected}
                    aria-controls="health-domain-detail"
                    onClick={() => setSelectedKey(d.key)}
                  >
                    <span className="domain-dot" aria-hidden />
                    <span className="domain-row-main">
                      <span className="domain-row-name">{d.label}</span>
                      <span className="domain-bar" aria-hidden>
                        <span
                          className="domain-bar-fill"
                          style={{ width: `${Math.max(0, Math.min(100, d.score ?? 0))}%` }}
                        />
                      </span>
                    </span>
                    <span className="domain-row-score">
                      {d.score ?? '—'}
                      <span className="sr-only"> out of 100, {bandLabel(d.score)}</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      </div>

      {active && (
        <section
          id="health-domain-detail"
          className="health-card domain-detail"
          aria-live="polite"
          aria-label={`${active.label} details`}
        >
          <div className="domain-detail-head">
            <h3>{active.label}</h3>
            <span className={`level-pill band-text-${scoreBand(active.score)}`}>
              {bandLabel(active.score)}
            </span>
          </div>

          {HEALTH_SCORING_METHOD[active.key] && (
            <div className="domain-method">
              <h4>How it&apos;s scored</h4>
              <p>{HEALTH_SCORING_METHOD[active.key]}</p>
            </div>
          )}

          <div className={`domain-detail-grid${activeRecommendations.length > 0 ? ' has-recs' : ''}`}>
            <div className="domain-detail-group">
              <h4>In this repository</h4>
              {active.score == null ? (
                <p className="muted small">{active.summary}</p>
              ) : active.strengths.length === 0 && active.issues.length === 0 ? (
                <p className="muted small">No specific signals were recorded for this domain.</p>
              ) : (
                <ul className="signal-rows">
                  {active.issues.map((item) => (
                    <li key={`issue-${item}`}>
                      <span className="signal-pill down">Negative</span>
                      <span>{item}</span>
                    </li>
                  ))}
                  {active.strengths.map((item) => (
                    <li key={`strength-${item}`}>
                      <span className="signal-pill up">Positive</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {activeRecommendations.length > 0 && (
              <div className="domain-detail-group">
                <h4>Recommendations</h4>
                <ul className="signal-rows">
                  {activeRecommendations.map((rec: HealthRecommendation) => (
                    <li key={rec.title}>
                      <span className={`sev-pill sev-${rec.priority}`}>{rec.priority}</span>
                      <span>
                        {rec.title}
                        {rec.expected_impact && (
                          <span className="signal-sub">{rec.expected_impact}</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}

      {(overallStrengths.length > 0 || overallWeaknesses.length > 0) && (
        <details className="health-card overall-sw">
          <summary>
            <span className="overall-sw-chevron" aria-hidden />
            <span className="overall-sw-title">Overall strengths and weaknesses</span>
          </summary>
          <div className="overall-sw-cols">
            <OverallColumn title="Strengths" tone="up" domains={overallStrengths} pick={(d) => d.strengths} />
            <OverallColumn
              title="Weaknesses"
              tone="down"
              domains={overallWeaknesses}
              pick={(d) => d.issues}
            />
          </div>
        </details>
      )}
    </div>
  )
}

function OverallColumn({
  title,
  tone,
  domains,
  pick,
}: {
  title: string
  tone: 'up' | 'down'
  domains: Domain[]
  pick: (domain: Domain) => string[]
}) {
  return (
    <section className="overall-sw-col">
      <h4 className={`overall-sw-heading ${tone}`}>{title}</h4>
      {domains.length === 0 ? (
        <p className="muted small">
          {tone === 'up'
            ? 'No domain scored 80 or above yet.'
            : 'No domain below 80 has recorded issues.'}
        </p>
      ) : (
        <dl className="overall-sw-groups">
          {domains.map((d) => (
            <div key={d.key} style={{ ['--domain-color' as string]: d.color }}>
              <dt>
                <span className="domain-dot" aria-hidden />
                {d.label}
              </dt>
              {pick(d).map((item) => (
                <dd key={item}>{item}</dd>
              ))}
            </div>
          ))}
        </dl>
      )}
    </section>
  )
}
