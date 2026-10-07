import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageFade } from '../components/AnswerContent'
import { StatusBanner } from '../components/common/StatusBanner'
import { deriveRepoNameFromGithubUrl } from '../lib/detectedStack'
import { formatUserError } from '../lib/errors'
import { ApiError } from '../services/api'
import { createProject } from '../services/projectService'

export function CreateProjectPage() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [nameTouched, setNameTouched] = useState(false)
  const [githubUrl, setGithubUrl] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [existingProjectId, setExistingProjectId] = useState<string | null>(null)

  useEffect(() => {
    if (nameTouched) return
    const derived = deriveRepoNameFromGithubUrl(githubUrl)
    if (derived) setName(derived)
  }, [githubUrl, nameTouched])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setExistingProjectId(null)

    const trimmedUrl = githubUrl.trim()
    if (!trimmedUrl) {
      setError('A public GitHub repository URL is required.')
      return
    }

    const trimmedName = name.trim() || deriveRepoNameFromGithubUrl(trimmedUrl)
    if (!trimmedName) {
      setError('Could not derive a project name from the GitHub URL. Enter a name or use owner/repo.')
      return
    }

    setSubmitting(true)
    setStatusMessage('Validating public GitHub repository…')

    try {
      const project = await createProject({
        name: trimmedName,
        github_url: trimmedUrl,
        technologies: [],
        description: description.trim() || undefined,
      })
      setStatusMessage('Project created. Starting analysis…')
      navigate(`/projects/${project.id}`, { state: { autoAnalyze: true } })
    } catch (err) {
      setError(formatUserError(err, 'Could not create the project.'))
      if (err instanceof ApiError && err.code === 'duplicate_repository' && err.existingProjectId) {
        setExistingProjectId(err.existingProjectId)
      }
      setStatusMessage(null)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageFade>
      <div className="create-page">
        <header className="page-intro">
          <p className="eyebrow">New repository workspace</p>
          <h1>Analyze a Repository</h1>
          <p className="muted">
            Paste a public GitHub URL. Stack and technologies are detected from repository analysis
            — you do not enter them manually.
          </p>
        </header>

        <form className="create-form" onSubmit={(e) => void onSubmit(e)}>
          <label>
            <span>Public GitHub URL</span>
            <input
              value={githubUrl}
              onChange={(e) => setGithubUrl(e.target.value)}
              required
              placeholder="https://github.com/owner/repo"
              className="mono-input"
              autoFocus
            />
          </label>

          <label>
            <span>
              Project name <em className="optional">editable</em>
            </span>
            <input
              value={name}
              onChange={(e) => {
                setNameTouched(true)
                setName(e.target.value)
              }}
              maxLength={120}
              placeholder="Derived from repository name"
            />
            <span className="field-hint">Filled from the repository name; change it if you want.</span>
          </label>

          <label>
            <span>
              Description <em className="optional">optional</em>
            </span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="What this workspace is for"
            />
          </label>

          {statusMessage && <StatusBanner tone="info">{statusMessage}</StatusBanner>}
          {error && (
            <StatusBanner onDismiss={() => setError(null)}>{error}</StatusBanner>
          )}
          {existingProjectId && (
            <StatusBanner tone="info">
              This repository is already connected.{' '}
              <Link to={`/projects/${existingProjectId}`}>Open existing project</Link>
            </StatusBanner>
          )}

          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting ? 'Validating…' : 'Analyze a Repository'}
            </button>
            <Link className="btn btn-ghost" to="/dashboard">
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </PageFade>
  )
}
