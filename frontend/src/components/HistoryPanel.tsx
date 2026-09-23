import { useState } from 'react'
import { downloadText } from '../workspace'
import type { Archive } from '../workspace'
import { exportArchivedReport } from '../api'
import { aiStatusLabels } from './AiSummary'

export default function HistoryPanel({ items, onDelete, onUndo, canUndo }: {
  items: Archive[]; onDelete: (id: string) => void; onUndo: () => void; canUndo: boolean
}) {
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  async function download(item: Archive, format: 'pdf' | 'docx') {
    setBusy(item.id); setError(null)
    try { await exportArchivedReport(item.markdown, format) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось скачать файл. Markdown доступен без сервера.') }
    finally { setBusy(null) }
  }
  const filtered = items.filter(item => `${item.title} ${item.before} ${item.after}`.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')))
  return <section className="surface product-panel" aria-labelledby="archive-heading">
    <div className="section-heading"><div><span className="eyebrow">ЛИЧНОЕ РАБОЧЕЕ ПРОСТРАНСТВО</span><h2 id="archive-heading">История сравнений</h2></div><span className="count-pill">{items.length} / 8</span></div>
    <p className="panel-intro">Сохранённые заключения и цитаты хранятся только в этом браузере по этому адресу. Это не общий архив команды. Очистка данных браузера удалит историю. Markdown доступен без сервера; PDF/Word требуют работающий API.</p>
    <label className="product-field">Найти сохранённое сравнение<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Название или имя документа" /></label>
    {error && <p role="alert" className="ai-warning">{error}</p>}
    {canUndo && <button className="button button--secondary" onClick={onUndo}>Отменить последнее удаление</button>}
    {!filtered.length && <div className="empty-state">{items.length ? 'Ничего не найдено. Измените поисковый запрос.' : 'Здесь появятся сохранённые сравнения. После анализа нажмите «Сохранить в историю».'}</div>}
    <div className="archive-list">{filtered.map(item => <article className="archive-card" key={item.id}>
      <h3>{item.title}</h3><p className="panel-intro">{item.before} → {item.after}</p>
      <p className="panel-intro">{new Date(item.savedAt).toLocaleString('ru-RU')} · Изменений: {item.changes} · Замечаний: {item.total}</p>
      <p className="panel-intro">ИИ при исходном анализе: {aiStatusLabels[item.aiStatus as keyof typeof aiStatusLabels] || item.aiStatus}. Скачивание не запускает модель повторно.</p>
      <div className="product-actions">
        <button className="button button--secondary" disabled={busy !== null} onClick={() => void download(item, 'pdf')}>{busy === item.id ? 'Подготовка…' : 'PDF'}</button>
        <button className="button button--secondary" disabled={busy !== null} onClick={() => void download(item, 'docx')}>Word</button>
        <button className="button button--secondary" onClick={() => downloadText(item.markdown, 'teren-oi-archive.md')}>Markdown</button>
        <button className="button button--secondary" onClick={() => onDelete(item.id)}>Удалить из истории</button>
      </div>
      <details className="coverage-details"><summary>Прочитать сохранённое заключение</summary><pre className="archive-preview">{item.markdown.slice(0, 12000)}</pre>{item.markdown.length > 12000 && <p>В предпросмотре первые 12 000 символов. Скачайте полный файл выше.</p>}</details>
    </article>)}</div>
  </section>
}
