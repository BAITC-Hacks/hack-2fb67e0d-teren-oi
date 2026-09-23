import type { AnalysisResponse, ClauseChange, Finding } from './types'

export type ReviewStatus = 'pending' | 'confirmed' | 'dismissed' | 'followup'
export interface Review { status: ReviewStatus; note: string }
export type Reviews = Record<string, Review>
export const reviewLabels: Record<ReviewStatus, string> = {
  pending: 'Не рассмотрено', confirmed: 'Подтверждено экспертом',
  dismissed: 'Отклонено экспертом', followup: 'Нужно уточнение',
}
export interface Archive {
  id: string; title: string; savedAt: string; before: string; after: string
  aiStatus: string; changes: number; reviewed: number; total: number; markdown: string
}
const STORAGE_KEY = 'teren-oi-archive-v1'
export function readArchives(): Archive[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    if (!Array.isArray(value)) return []
    return value.filter((item): item is Archive => item &&
      ['id', 'title', 'savedAt', 'before', 'after', 'aiStatus', 'markdown'].every(key => typeof item[key] === 'string') &&
      ['changes', 'reviewed', 'total'].every(key => typeof item[key] === 'number')).slice(0, 8)
  } catch { return [] }
}
export function writeArchives(items: Archive[]): void {
  const serialized = JSON.stringify(items)
  if (items.length > 8) throw new Error('В архиве уже 8 сравнений. Скачайте и удалите ненужное, затем сохраните новое.')
  if (serialized.length > 1_500_000) throw new Error('Архив слишком большой. Скачайте Markdown или освободите место в истории.')
  try { localStorage.setItem(STORAGE_KEY, serialized) }
  catch { throw new Error('Браузер не разрешил сохранение или закончилось место. Скачайте Markdown, чтобы сохранить результат.') }
}
export function downloadText(text: string, name: string, type = 'text/markdown;charset=utf-8'): void {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const link = document.createElement('a')
  link.href = url; link.download = name
  document.body.append(link); link.click(); link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
const literal = (text: string) => text.replace(/[\\`*_{}[\]<>#|]/g, '\\$&').replace(/\r?\n/g, ' ')
export function reviewedReport(result: AnalysisResponse, reviews: Reviews): string {
  const notes = result.findings.filter(f => reviews[f.id]?.note || (reviews[f.id]?.status && reviews[f.id].status !== 'pending'))
  if (!notes.length) return result.report_markdown
  return result.report_markdown + '\n\n## Рецензия эксперта\n\n' +
    'Пользовательские оценки и заметки. Они не являются выводами модели и не изменяют исходный анализ.\n\n' +
    notes.map(f => `### ${literal(f.title)}\n\nСтатус: ${reviewLabels[reviews[f.id].status]}\n\n${literal(reviews[f.id].note)}\n`).join('\n')
}
export function matchesQuery(item: ClauseChange | Finding, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase('ru')
  if (!needle) return true
  const values = 'citations' in item
    ? [item.title, item.explanation, ...item.citations.flatMap(c => [c.quote, c.clause_id, c.source, c.location])]
    : [item.clause_id, item.before_clause_id, item.after_clause_id, item.before, item.after, item.before_source, item.after_source]
  return values.some(value => value?.toLocaleLowerCase('ru').includes(needle))
}
export function changesCsv(changes: ClauseChange[]): string {
  // Spreadsheet formula prefixes are neutralized even inside quoted CSV cells.
  const cell = (value: string | null) => {
    let text = value || ''
    if (/^[\s]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text
    return '"' + text.replace(/"/g, '""') + '"'
  }
  const rows = [['Пункт до', 'Пункт после', 'Статус', 'До', 'После', 'Источник до', 'Источник после'],
    ...changes.map(c => [c.before_clause_id, c.after_clause_id, c.status, c.before, c.after, c.before_source, c.after_source])]
  return '\uFEFF' + rows.map(row => row.map(cell).join(';')).join('\r\n')
}
