import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './components/common/ProtectedRoute'
import { AuthProvider } from './context/AuthContext'
import { AppShellLayout } from './layouts/AppShellLayout'
import { MarketingLayout } from './layouts/MarketingLayout'
import { CreateProjectPage } from './pages/CreateProjectPage'
import { DashboardPage } from './pages/DashboardPage'
import { LandingPage } from './pages/LandingPage'
import { LoginPage } from './pages/LoginPage'
import { ProjectOverviewPage } from './pages/ProjectOverviewPage'
import './styles/global.css'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<MarketingLayout />}>
            <Route index element={<LandingPage />} />
            <Route path="login" element={<LoginPage />} />
          </Route>

          <Route
            element={
              <ProtectedRoute>
                <AppShellLayout />
              </ProtectedRoute>
            }
          >
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="create-project" element={<CreateProjectPage />} />
          </Route>

          <Route
            path="projects/:projectId"
            element={
              <ProtectedRoute>
                <ProjectOverviewPage />
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
