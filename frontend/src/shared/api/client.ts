import type { ApiErrorPayload } from '@/types/contracts'

const REQUEST_TIMEOUT = 10_000
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

export class ApiError extends Error {
  code: string
  degraded?: boolean
  degraded_reason?: string
  trace_id?: string

  constructor(payload: ApiErrorPayload) {
    super(payload.message)
    this.code = payload.code
    this.degraded = payload.degraded
    this.degraded_reason = payload.degraded_reason
    this.trace_id = payload.trace_id
  }
}

async function withTimeout(input: RequestInfo | URL, init: RequestInit, timeoutMs: number) {
  const controller = new AbortController()
  const id = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    })
  } finally {
    clearTimeout(id)
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}) {
  const requestPath = path.startsWith('http://') || path.startsWith('https://')
    ? path
    : `${API_BASE_URL}${path}`
  const response = await withTimeout(requestPath, init, REQUEST_TIMEOUT)

  if (!response.ok) {
    let payload: ApiErrorPayload = {
      code: `HTTP_${response.status}`,
      message: '请求失败',
    }
    try {
      payload = (await response.json()) as ApiErrorPayload
    } catch {
      payload = {
        code: `HTTP_${response.status}`,
        message: response.statusText,
      }
    }
    throw new ApiError(payload)
  }

  return (await response.json()) as T
}
