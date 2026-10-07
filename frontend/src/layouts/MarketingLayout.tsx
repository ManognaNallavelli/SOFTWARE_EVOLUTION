import { Link, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { getGoogleLoginUrl } from '../services/authService'

export function MarketingLayout() {
  const { isAuthenticated, loading } = useAuth()
  const location = useLocation()
  const isLanding = location.pathname === '/'

  return (
    <div className={`marketing-shell${isLanding ? ' is-landing' : ''}`}>
      <header className="marketing-header">
        <Link to="/" className="sidebar-brand compact">
          <span className="brand-mark" aria-hidden>
            <span />
            <span />
          </span>
          <span className="brand-text">
            <strong>AI Software Evolution Platform</strong>
          </span>
        </Link>
        <div className="marketing-actions">
          {!loading && isAuthenticated ? (
            <Link className="btn btn-primary" to="/dashboard">
              Open Dashboard
            </Link>
          ) : (
            !loading && (
              <a className="btn btn-primary" href={getGoogleLoginUrl()}>
                Sign in with Google
              </a>
            )
          )}
        </div>
      </header>
      <main className="marketing-main">
        <Outlet />
      </main>
    </div>
  )
}
