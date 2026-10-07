import { useEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { IconPlus } from '../components/icons'
import { useAuth } from '../hooks/useAuth'

export function AppShellLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const showAnalyzeCta = location.pathname === '/dashboard'

  const initials =
    user?.name
      ?.split(/\s+/)
      .map((part) => part[0])
      .join('')
      .slice(0, 2)
      .toUpperCase() || 'U'

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  async function handleLogout() {
    setMenuOpen(false)
    await logout()
    navigate('/')
  }

  return (
    <div className="app-frame app-frame-full">
      <div className="app-top-actions">
        <div className="app-account" ref={menuRef}>
          <button
            type="button"
            className="app-account-trigger"
            aria-label="Account menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {user?.picture ? (
              <img className="user-avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />
            ) : (
              <span className="user-avatar fallback">{initials}</span>
            )}
          </button>
          {menuOpen && (
            <div className="app-account-menu" role="menu">
              <div className="app-account-meta">
                <span className="app-account-name">{user?.name || 'Signed in'}</span>
                {user?.email && <span className="app-account-email">{user.email}</span>}
              </div>
              <button
                type="button"
                className="app-account-logout"
                role="menuitem"
                onClick={() => void handleLogout()}
              >
                Log out
              </button>
            </div>
          )}
        </div>

        {showAnalyzeCta && (
          <Link className="btn btn-primary app-analyze-cta" to="/create-project">
            <IconPlus />
            Analyze a Repository
          </Link>
        )}
      </div>

      <div className="app-content">
        <Outlet />
      </div>
    </div>
  )
}
