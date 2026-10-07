import type { HealthReport, RepositoryAnalysis } from '../types/analysis'

export type KeyFinding = {
  id: string
  tone: 'positive' | 'risk' | 'neutral'
  text: string
}

/** Compact findings from existing health/analysis evidence only — never invented. */
export function buildKeyFindings(
  health: HealthReport | null,
  analysis: RepositoryAnalysis | null,
  limit = 4,
): KeyFinding[] {
  const findings: KeyFinding[] = []

  if (health) {
    for (const issue of health.issues) {
      if (findings.length >= limit) break
      if (issue.severity === 'critical' || issue.severity === 'high') {
        findings.push({
          id: `issue-${issue.title}`,
          tone: 'risk',
          text: issue.title,
        })
      }
    }
    for (const strength of health.strengths) {
      if (findings.length >= limit) break
      findings.push({
        id: `strength-${strength}`,
        tone: 'positive',
        text: strength,
      })
    }
    const testing = health.categories.testing
    if (testing?.summary && findings.length < limit) {
      findings.push({
        id: 'testing-summary',
        tone: testing.score != null && testing.score < 55 ? 'risk' : 'neutral',
        text: testing.summary,
      })
    }
    const security = health.categories.security
    if (security?.summary && findings.length < limit) {
      const risky =
        security.score != null && security.score < 60
          ? true
          : /sensitive|secret|credential|risk/i.test(security.summary)
      findings.push({
        id: 'security-summary',
        tone: risky ? 'risk' : 'positive',
        text: security.summary,
      })
    }
  }

  if (analysis && findings.length < limit) {
    const manifests = analysis.summary.dependency_manifests
    if (manifests.length > 0) {
      findings.push({
        id: 'manifests',
        tone: 'neutral',
        text: `Dependency manifests detected (${manifests.length})`,
      })
    }
  }

  if (health?.architecture_overview && findings.length < limit) {
    const layers = [
      health.architecture_overview.api_layer.length > 0,
      health.architecture_overview.data_layer.length > 0,
      health.architecture_overview.test_layer.length > 0,
      health.architecture_overview.major_modules.length > 0,
    ].filter(Boolean).length
    if (layers >= 2) {
      findings.push({
        id: 'layers',
        tone: 'positive',
        text: 'Multiple architectural layers detected',
      })
    }
  }

  const seen = new Set<string>()
  return findings
    .filter((item) => {
      const key = item.text.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .slice(0, limit)
}
