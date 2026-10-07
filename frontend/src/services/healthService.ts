import { apiGet } from './api'
import type { HealthStatus } from '../types/health'

export function fetchHealth(): Promise<HealthStatus> {
  return apiGet<HealthStatus>('/api/health')
}
