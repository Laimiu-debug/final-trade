import type { ApiErrorPayload } from '@/types/contracts'

const REQUEST_TIMEOUT = 10_000
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')
const DEFAULT_ERROR_MESSAGE = '请求失败'

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

function isAbortError(error: unknown) {
  return (
    (error instanceof DOMException && error.name === 'AbortError')
    || (error instanceof Error && error.name === 'AbortError')
  )
}

async function withTimeout(input: RequestInfo | URL, init: RequestInit, timeoutMs: number) {
  const controller = new AbortController()
  let timedOut = false

  const onExternalAbort = () => controller.abort()
  if (init.signal) {
    if (init.signal.aborted) {
      controller.abort()
    } else {
      init.signal.addEventListener('abort', onExternalAbort, { once: true })
    }
  }

  const id = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    })
  } catch (error) {
    if (timedOut && isAbortError(error)) {
      const timeoutError = new Error('REQUEST_TIMEOUT')
      timeoutError.name = 'TimeoutError'
      throw timeoutError
    }
    throw error
  } finally {
    clearTimeout(id)
    if (init.signal) {
      init.signal.removeEventListener('abort', onExternalAbort)
    }
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
) {
  const { timeoutMs = REQUEST_TIMEOUT, ...requestInit } = init
  const requestPath = path.startsWith('http://') || path.startsWith('https://')
    ? path
    : `${API_BASE_URL}${path}`

  let response: Response
  try {
    response = await withTimeout(requestPath, requestInit, timeoutMs)
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }
    if (error instanceof Error && error.name === 'TimeoutError') {
      throw new ApiError({
        code: 'REQUEST_TIMEOUT',
        message: `请求超时（${Math.ceil(timeoutMs / 1000)}秒）`,
      })
    }
    if (isAbortError(error)) {
      throw new ApiError({
        code: 'REQUEST_ABORTED',
        message: '请求已取消',
      })
    }
    throw error
  }

  if (!response.ok) {
    let payload: ApiErrorPayload = {
      code: `HTTP_${response.status}`,
      message: DEFAULT_ERROR_MESSAGE,
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
