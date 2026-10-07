export type ScoreBand = 'excellent' | 'good' | 'attention' | 'critical' | 'unknown'

export function scoreBand(score: number | null | undefined): ScoreBand {
  if (score == null || Number.isNaN(score)) return 'unknown'
  if (score >= 80) return 'excellent'
  if (score >= 60) return 'good'
  if (score >= 40) return 'attention'
  return 'critical'
}

export function scoreBandLabel(band: ScoreBand, apiStatus?: string | null): string {
  if (apiStatus) {
    const normalized = apiStatus.trim().toLowerCase()
    if (normalized.includes('healthy') || normalized.includes('excellent')) return 'Healthy'
    if (normalized.includes('good') || normalized.includes('moderate')) return 'Moderate'
    if (normalized.includes('attention') || normalized.includes('fair') || normalized.includes('needs')) {
      return 'Needs improvement'
    }
    if (normalized.includes('critical') || normalized.includes('poor')) return 'Critical'
  }
  switch (band) {
    case 'excellent':
      return 'Healthy'
    case 'good':
      return 'Moderate'
    case 'attention':
      return 'Needs improvement'
    case 'critical':
      return 'Critical'
    default:
      return 'Not scored'
  }
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return 'Never'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const diffMs = Date.now() - date.getTime()
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours}h ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export const HEALTH_CATEGORY_LABELS: Record<string, string> = {
  code_quality: 'Code Quality',
  maintainability: 'Maintainability',
  architecture: 'Architecture',
  testing: 'Testing',
  security: 'Security',
  documentation: 'Documentation',
  dependency_health: 'Dependency Health',
  technical_debt: 'Technical Debt',
}

/** Percent of the overall score. Must match CATEGORY_WEIGHTS in backend/app/services/health_engine.py. */
export const HEALTH_CATEGORY_WEIGHTS: Record<string, number> = {
  code_quality: 15,
  maintainability: 15,
  architecture: 15,
  testing: 15,
  security: 10,
  documentation: 10,
  dependency_health: 10,
  technical_debt: 10,
}

/** Plain-language description of each calculate_* function in health_engine.py. */
export const HEALTH_SCORING_METHOD: Record<string, string> = {
  code_quality:
    'We look at your production source files. Very large files lower the score. Extracted code symbols, deep parsing support, and using more than one language raise it. An incomplete repository scan lowers it.',
  maintainability:
    'We look at average production file size, how many files sit in each folder, whether there are clear top-level modules, and how many symbols each file holds. Small files and a modular layout raise the score. Large files, crowded folders, and dense files lower it.',
  architecture:
    'We count which layers are present: UI, backend services, data access, production API routes, and configuration. More layers, real API routes, and external integrations raise the score. Routes that exist only in tests or examples lower it.',
  testing:
    'We compare the number of test files to production source files. More tests per source file means a higher score, and a dedicated tests folder adds a little. This counts files. It does not measure runtime coverage.',
  security:
    'We check the file tree for common secret files, such as .env files, private keys, and credential files. Each one found lowers the score. A .env.example file raises it. No CVE or vulnerability scan is run.',
  documentation:
    'We check for a README and other documentation files. A README counts the most. More documentation files and a dedicated docs folder add to the score.',
  dependency_health:
    'We check that dependency manifests exist and match the languages we detect, such as package.json for JavaScript. Missing or mismatched manifests lower the score. Package age and known vulnerabilities are not checked.',
  technical_debt:
    'A higher score means less debt. Oversized production files, few tests compared with source, demo code outweighing real code, and an incomplete scan lower the score.',
}

/** Identity colors for health domains — distinct from the score band colors. */
export const HEALTH_DOMAIN_COLORS: Record<string, string> = {
  code_quality: '#2dd4bf',
  maintainability: '#38bdf8',
  architecture: '#818cf8',
  testing: '#c084fc',
  security: '#f472b6',
  documentation: '#fbbf24',
  dependency_health: '#a3e635',
  technical_debt: '#fb923c',
}
