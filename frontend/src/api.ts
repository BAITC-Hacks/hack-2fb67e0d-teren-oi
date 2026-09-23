import type { AnalysisInput, AnalysisResponse, HealthResponse } from './types'

const baseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function explainError(response: Response): Promise<string> {
  let detail = `Ошибка сервера (${response.status})`
  try {
    const payload: unknown = await response.json()
    if (typeof payload === 'object' && payload !== null) {
      const error = 'error' in payload ? (payload as { error: unknown }).error : undefined
      const value = typeof error === 'object' && error !== null && 'message' in error
        ? (error as { message: unknown }).message
        : 'detail' in payload ? (payload as { detail: unknown }).detail : undefined
      if (typeof value === 'string') detail = value
      else if (Array.isArray(value)) {
        detail = value.map((item) => typeof item === 'object' && item !== null && 'msg' in item ? String(item.msg) : String(item)).join('; ')
      }
    }
  } catch {
    // A non-JSON error keeps the useful HTTP status above.
  }
  return detail
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${baseUrl}/api/health`, { signal })
  if (!response.ok) throw new Error(await explainError(response))
  return response.json() as Promise<HealthResponse>
}

export async function analyze(input: AnalysisInput): Promise<AnalysisResponse> {
  const form = new FormData()
  if (input.beforeFile) form.append('before_file', input.beforeFile)
  if (input.afterFile) form.append('after_file', input.afterFile)
  form.append('before_text', input.beforeFile ? '' : input.beforeText)
  form.append('after_text', input.afterFile ? '' : input.afterText)
  form.append('use_ai', String(input.useAi))
  form.append('demo', input.demo ? '1' : '0')

  let response: Response
  try {
    response = await fetch(`${baseUrl}/api/analyze`, { method: 'POST', body: form })
  } catch {
    throw new Error('Не удалось связаться с сервером анализа. Проверьте, что API запущен.')
  }
  if (!response.ok) throw new Error(await explainError(response))
  return response.json() as Promise<AnalysisResponse>
}

export async function exportReport(analysisId: string, format: 'pdf' | 'docx'): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${baseUrl}/api/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ analysis_id: analysisId, format }),
    })
  } catch {
    throw new Error('Не удалось связаться с сервером экспорта.')
  }
  if (!response.ok) throw new Error(await explainError(response))
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `teren-oi-zaklyuchenie.${format}`
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
