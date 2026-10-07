import { API_BASE_URL, apiGet, apiPost } from './api'
import type { AuthMeResponse } from '../types/auth'

export function fetchAuthMe(): Promise<AuthMeResponse> {
  return apiGet<AuthMeResponse>('/api/auth/me')
}

export function logoutRequest(): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>('/api/auth/logout')
}

export function getGoogleLoginUrl(): string {
  return `${API_BASE_URL}/api/auth/google/login`
}
