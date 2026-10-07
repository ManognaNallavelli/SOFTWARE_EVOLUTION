import { ApiError } from '../services/api'

/** Map raw failures to short, demo-friendly messages. */
export function formatUserError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.code === 'network_error') {
      return err.message
    }
    return err.message || fallback
  }
  if (err instanceof TypeError) {
    return 'Cannot reach the API. Start the backend on http://127.0.0.1:8000 and try again.'
  }
  if (err instanceof Error && err.message) {
    const lower = err.message.toLowerCase()
    if (lower.includes('failed to fetch') || lower.includes('networkerror')) {
      return 'Cannot reach the API. Start the backend on http://127.0.0.1:8000 and try again.'
    }
    return err.message
  }
  return fallback
}
