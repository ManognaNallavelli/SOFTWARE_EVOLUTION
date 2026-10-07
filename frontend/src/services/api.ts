import type { ApiErrorBody } from '../types/project'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

export class ApiError extends Error {
  status: number
  code?: string
  existingProjectId?: string

  constructor(status: number, message: string, code?: string, existingProjectId?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.existingProjectId = existingProjectId
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let message = `Request failed: ${response.status} ${response.statusText}`
  let code: string | undefined
  let existingProjectId: string | undefined

  try {
    const body = (await response.json()) as ApiErrorBody
    if (typeof body.detail === 'string') {
      message = body.detail
    } else if (body.detail && typeof body.detail === 'object') {
      message = body.detail.message || message
      code = body.detail.code
      existingProjectId = body.detail.existing_project_id
    }
  } catch {
    // ignore JSON parse failures
  }

  return new ApiError(response.status, message, code, existingProjectId)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
      ...init,
    })
  } catch {
    throw new ApiError(
      0,
      'Cannot reach the API. Start the backend on http://127.0.0.1:8000 and try again.',
      'network_error',
    )
  }

  if (response.status === 204) {
    return undefined as T
  }

  if (!response.ok) {
    throw await parseError(response)
  }

  return response.json() as Promise<T>
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function apiDelete(path: string): Promise<void> {
  return request<void>(path, { method: 'DELETE' })
}

export { API_BASE_URL }
