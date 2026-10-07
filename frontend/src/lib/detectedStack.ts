import type { AnalysisDocument, RepositoryAnalysis } from '../types/analysis'



/** Mirror of backend stack hints — filename/path evidence only, never invented. */

const MANIFEST_HINTS: Array<[string, string]> = [

  ['package.json', 'Node.js'],

  ['package-lock.json', 'Node.js'],

  ['yarn.lock', 'Node.js'],

  ['pnpm-lock.yaml', 'Node.js'],

  ['requirements.txt', 'Python'],

  ['pyproject.toml', 'Python'],

  ['pipfile', 'Python'],

  ['poetry.lock', 'Python'],

  ['go.mod', 'Go'],

  ['cargo.toml', 'Rust'],

  ['pom.xml', 'Java'],

  ['build.gradle', 'Java'],

  ['gemfile', 'Ruby'],

  ['composer.json', 'PHP'],

  ['dockerfile', 'Docker'],

  ['docker-compose', 'Docker'],

  ['tsconfig.json', 'TypeScript'],

]



const CONFIG_HINTS: Array<[string, string]> = [

  ['vite.config', 'Vite'],

  ['next.config', 'Next.js'],

  ['nuxt.config', 'Nuxt'],

  ['angular.json', 'Angular'],

  ['manage.py', 'Django'],

  ['fastapi', 'FastAPI'],

  ['flask', 'Flask'],

  ['prisma', 'Prisma'],

]



const LANGUAGE_NORMALIZE: Record<string, string> = {

  javascript: 'JavaScript',

  typescript: 'TypeScript',

  python: 'Python',

  go: 'Go',

  rust: 'Rust',

  java: 'Java',

  ruby: 'Ruby',

  php: 'PHP',

  c: 'C',

  'c++': 'C++',

  'c#': 'C#',

  csharp: 'C#',

  swift: 'Swift',

  kotlin: 'Kotlin',

  shell: 'Shell',

  html: 'HTML',

  css: 'CSS',

  scss: 'SCSS',

  vue: 'Vue',

  svelte: 'Svelte',

  sql: 'SQL',

}



const LANGUAGE_SKIP = new Set([

  'markdown',

  'json',

  'yaml',

  'yml',

  'toml',

  'xml',

  'ini',

  'text',

  'plaintext',

  'restructuredtext',

  'rst',

  'csv',

  'tsv',

  'lock',

  'gitignore',

  'dockerfile',

])



function addLabel(ordered: string[], seen: Set<string>, label: string) {

  const key = label.trim().toLowerCase()

  if (!key || seen.has(key)) return

  seen.add(key)

  ordered.push(label.trim())

}



function matchHints(

  paths: string[],

  hints: Array<[string, string]>,

  ordered: string[],

  seen: Set<string>,

) {

  const lowered = paths.map((p) => p.replace(/\\/g, '/').toLowerCase())

  for (const [fragment, label] of hints) {

    if (lowered.some((path) => path.includes(fragment))) {

      addLabel(ordered, seen, label)

    }

  }

}



export function deriveDetectedStack(analysis: RepositoryAnalysis | null | undefined, limit = 8): string[] {

  if (!analysis) return []

  const ordered: string[] = []

  const seen = new Set<string>()



  matchHints(analysis.summary.dependency_manifests, MANIFEST_HINTS, ordered, seen)

  matchHints(analysis.summary.important_files, MANIFEST_HINTS, ordered, seen)

  matchHints(analysis.detections.configuration_files, CONFIG_HINTS, ordered, seen)

  matchHints(analysis.summary.important_files, CONFIG_HINTS, ordered, seen)

  matchHints(

    [

      ...analysis.detections.backend_services,

      ...analysis.detections.frontend_components,

      ...analysis.detections.integrations,

    ],

    CONFIG_HINTS,

    ordered,

    seen,

  )



  const ranked = [...analysis.summary.languages].sort(

    (a, b) => b.total_bytes - a.total_bytes || b.file_count - a.file_count,

  )

  for (const lang of ranked) {

    const raw = (lang.language || '').trim()

    if (!raw) continue

    const key = raw.toLowerCase()

    if (LANGUAGE_SKIP.has(key)) continue

    const label =

      LANGUAGE_NORMALIZE[key] ?? (raw === raw.toLowerCase() ? raw.replace(/^\w/, (c) => c.toUpperCase()) : raw)

    addLabel(ordered, seen, label)

  }



  return ordered.slice(0, limit)

}



export function stackForProjectCard(

  projectTechnologies: string[],

  analysisDoc: AnalysisDocument | null | undefined,

): string[] {

  if (projectTechnologies.length > 0) return projectTechnologies.slice(0, 8)

  return deriveDetectedStack(analysisDoc?.analysis ?? null)

}



export function deriveRepoNameFromGithubUrl(url: string): string {

  const cleaned = url.trim().replace(/\.git$/i, '')

  const match = cleaned.match(/github\.com[/:]([^/]+)\/([^/#?]+)/i)

  if (!match) return ''

  return decodeURIComponent(match[2]).replace(/\/+$/, '')

}


