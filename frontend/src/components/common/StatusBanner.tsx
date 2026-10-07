import type { ReactNode } from 'react'

type Props = {
  tone?: 'error' | 'info'
  children: ReactNode
  onDismiss?: () => void
  onRetry?: () => void
  retryLabel?: string
}

export function StatusBanner({
  tone = 'error',
  children,
  onDismiss,
  onRetry,
  retryLabel = 'Retry',
}: Props) {
  return (
    <div className={`banner banner-${tone} status-banner`} role={tone === 'error' ? 'alert' : 'status'}>
      <div className="status-banner-body">{children}</div>
      {(onRetry || onDismiss) && (
        <div className="status-banner-actions">
          {onRetry ? (
            <button type="button" className="btn btn-ghost status-banner-btn" onClick={onRetry}>
              {retryLabel}
            </button>
          ) : null}
          {onDismiss ? (
            <button
              type="button"
              className="btn btn-ghost status-banner-btn"
              onClick={onDismiss}
              aria-label="Dismiss"
            >
              Dismiss
            </button>
          ) : null}
        </div>
      )}
    </div>
  )
}
