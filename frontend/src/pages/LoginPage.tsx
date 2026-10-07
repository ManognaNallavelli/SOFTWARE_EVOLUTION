import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { PageFade } from '../components/AnswerContent'
import { useAuth } from '../hooks/useAuth'
import { getGoogleLoginUrl } from '../services/authService'

const ERROR_MESSAGES: Record<string, string> = {
  oauth_denied: 'Google sign-in was cancelled or denied.',
  invalid_state: 'Login session expired or was invalid. Please try again.',
  token_exchange: 'Could not complete Google sign-in (token exchange failed).',
  userinfo: 'Could not load your Google profile.',
  oauth_network: 'Network error while contacting Google. Try again.',
  incomplete_profile: 'Google did not return a usable account profile.',
  oauth_not_configured: 'Google OAuth is not configured on the server yet.',
}

export function LoginPage() {
  const { isAuthenticated, loading } = useAuth()
  const [params] = useSearchParams()
  const location = useLocation()
  const errorKey = params.get('error')
  const errorMessage = errorKey ? ERROR_MESSAGES[errorKey] || 'Sign-in failed. Please try again.' : null
  const from = (location.state as { from?: string } | null)?.from

  if (!loading && isAuthenticated) {
    return <Navigate to={from || '/dashboard'} replace />
  }

  return (
    <PageFade>
      <div className="login-page">
        <div className="login-panel">
          <p className="eyebrow">Secure access</p>
          <h1>Sign in to continue</h1>
          <p className="muted">
            Use Google to open your workspace. Sessions stay on the server and are delivered as an
            HttpOnly cookie.
          </p>
          {errorMessage && <p className="banner banner-error">{errorMessage}</p>}
          <a className="btn btn-primary btn-lg btn-block" href={getGoogleLoginUrl()}>
            Continue with Google
          </a>
          <p className="muted small">
            <Link to="/">Back to home</Link>
          </p>
        </div>
      </div>
    </PageFade>
  )
}
