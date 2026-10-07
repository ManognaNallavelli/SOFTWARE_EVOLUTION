import { scoreBand, scoreBandLabel, type ScoreBand } from '../lib/healthUi'

type Props = {
  score: number | null | undefined
  status?: string | null
  size?: number
  className?: string
  animate?: boolean
}

function bandClass(band: ScoreBand): string {
  return `score-band-${band}`
}

export function HealthScoreRing({
  score,
  status,
  size = 168,
  className = '',
  animate = true,
}: Props) {
  const band = scoreBand(score)
  const label = scoreBandLabel(band, status)
  const radius = 54
  const circumference = 2 * Math.PI * radius
  const clamped = score == null ? 0 : Math.max(0, Math.min(100, score))
  const offset = circumference - (clamped / 100) * circumference

  return (
    <div
      className={`health-ring ${bandClass(band)} ${animate ? 'health-ring-animate' : ''} ${className}`.trim()}
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 132 132" width={size} height={size} aria-hidden>
        <circle className="health-ring-track" cx="66" cy="66" r={radius} />
        <circle
          className="health-ring-progress"
          cx="66"
          cy="66"
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="health-ring-center">
        <span className="health-ring-value" style={{ fontSize: size < 110 ? '1.05rem' : undefined }}>
          {score == null ? '—' : Math.round(score)}
        </span>
        {size >= 110 && <span className="health-ring-denom">/100</span>}
        {size >= 120 && <span className="health-ring-label">{label}</span>}
      </div>
    </div>
  )
}
