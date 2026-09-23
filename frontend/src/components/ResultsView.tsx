import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { ArrowDownToLine, ChevronDown, CircleAlert, FileText, FileType2, FolderOpen, Layers3, Plus, ShieldCheck } from 'lucide-react'
import type { AnalysisResponse, ClauseChange, Finding, Unit } from '../types'
import AiSummary, { aiStatusLabels } from './AiSummary'
import SemanticAnalysis from './SemanticAnalysis'
import { changesCsv, downloadText, matchesQuery } from '../workspace'
import type { Archive } from '../workspace'

const statusLabels: Record<string, string> = {
  added: 'Добавлено', removed: 'Удалено', modified: 'Изменено', unchanged: 'Без изменений',
  created: 'Создано', retained: 'Сохранено', transformed: 'Преобразовано',
}

function statusTone(status: string): 'green' | 'amber' | 'red' | 'blue' | 'neutral' {
  if (status === 'created' || status === 'added' || status === 'retained') return 'green'
  if (status === 'removed') return 'red'
  if (status === 'transformed' || status === 'modified') return 'amber'
  return status === 'unchanged' ? 'neutral' : 'blue'
}

function findingTone(kind: string): 'red' | 'amber' | 'blue' {
  const normalized = kind.toLocaleLowerCase('ru')
  if (normalized.includes('потер') || normalized.includes('утрат')) return 'red'
  if (normalized.includes('дубл') || normalized.includes('конфликт')) return 'amber'
  return 'blue'
}

function Badge({ tone, children }: { tone: 'green' | 'amber' | 'red' | 'blue' | 'neutral'; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>
}

function MetricCard({ label, value, tone, footnote }: { label: string; value: number | null; tone: string; footnote: string }) {
  return (
    <div className={`metric-card metric-card--${tone}`}>
      <span className="metric-card__label">{label}</span>
      <strong>{value === null ? '—' : value.toLocaleString('ru-RU')}</strong>
      <span className="metric-card__footnote"><span className="metric-card__dot" />{footnote}</span>
    </div>
  )
}
function UnitsPanel({ units, active, onSelect }: { units: Unit[]; active: string | null; onSelect: (name: string | null) => void }) {
  return (
    <section className="surface units-panel" aria-labelledby="units-heading">
      <div className="section-heading"><div><span className="eyebrow">СТРУКТУРА</span><h3 id="units-heading">Подразделения</h3></div><span className="count-pill">{units.length}</span></div>
      <p className="panel-intro">При наличии используются оценки ИИ с цитатами, иначе — текстовые признаки. Все статусы требуют проверки. Выберите подразделение для фильтрации точной карты.</p>
      <div className="unit-list">
        <button type="button" className={`unit-item ${active === null ? 'is-selected' : ''}`} onClick={() => onSelect(null)} aria-pressed={active === null}>
          <span className="unit-item__symbol"><Layers3 size={16} /></span><span className="unit-item__name">Все подразделения</span><span className="unit-item__arrow">→</span>
        </button>
        {units.map((unit, index) => (
          <button type="button" key={`${unit.name}-${index}`} className={`unit-item ${active === unit.name ? 'is-selected' : ''}`} onClick={() => onSelect(unit.name)} aria-pressed={active === unit.name}>
            <span className={`unit-item__symbol unit-item__symbol--${statusTone(unit.status)}`}><FolderOpen size={16} /></span>
            <span className="unit-item__name">{unit.name}<small className="mapping-match">{unit.origin === 'ai' ? 'Оценка ИИ · источники выше' : 'По упоминаниям'}</small></span>
            <Badge tone={statusTone(unit.status)}>{statusLabels[unit.status] || unit.status}</Badge>
          </button>
        ))}
      </div>
    </section>
  )
}
function MappingTable({ changes, units, activeUnit, query }: { changes: ClauseChange[]; units: Unit[]; activeUnit: string | null; query: string }) {
  const [filter, setFilter] = useState('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [visibleCount, setVisibleCount] = useState(40)
  const tableRef = useRef<HTMLDivElement>(null)
  const revealFrom = useRef<number | null>(null)
  const reducedMotion = useReducedMotion()
  useEffect(() => {
    setVisibleCount(40)
    setExpanded(null)
    revealFrom.current = null
  }, [filter, activeUnit, query])
  useEffect(() => {
    if (revealFrom.current === null) return
    const firstNewIndex = revealFrom.current
    const frame = requestAnimationFrame(() => {
      const container = tableRef.current
      const row = container?.querySelector<HTMLElement>(`[data-row-index="${firstNewIndex}"]`)
      if (!container || !row) return
      const headerHeight = container.querySelector('thead')?.getBoundingClientRect().height || 0
      const top = Math.max(0, row.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - headerHeight)
      container.scrollTo({ top, behavior: reducedMotion ? 'auto' : 'smooth' })
    })
    revealFrom.current = null
    return () => cancelAnimationFrame(frame)
  }, [visibleCount, reducedMotion])
  const selectedUnit = units.find((unit) => unit.name === activeUnit)
  const visible = changes.filter((change) =>
    (filter === 'all' || change.status === filter) && (!selectedUnit || selectedUnit.change_ids.includes(change.id)) && matchesQuery(change, query),
  )
  const shown = visible.slice(0, visibleCount)
  const filters = [
    ['all', 'Все'], ['modified', 'Изменено'], ['removed', 'Удалено'], ['added', 'Добавлено'], ['unchanged', 'Без изменений'],
  ]
  return (
    <section className="surface mapping-panel" id="mapping" aria-labelledby="mapping-heading">
      <div className="section-heading"><div><span className="eyebrow">СОПОСТАВЛЕНИЕ</span><h3 id="mapping-heading">Карта изменений</h3></div><span className="count-pill">{visible.length}</span></div>
      {activeUnit && <p className="panel-intro">Подразделение: <strong>{activeUnit}</strong></p>}
      <div className="filter-bar" aria-label="Фильтр статуса">
        {filters.map(([key, label]) => <button key={key} type="button" className={filter === key ? 'is-active' : ''} onClick={() => setFilter(key)} aria-pressed={filter === key}>{label}</button>)}
      </div>
      {visible.length ? (
        <><p className="table-scroll-hint" id="mapping-scroll-hint">Таблицу можно прокручивать вправо. Нажмите на номер пункта, чтобы увидеть его источник.</p><div className="table-scroll" ref={tableRef} tabIndex={0} role="region" aria-label="Таблица сравнения редакций" aria-describedby="mapping-scroll-hint"><table className="mapping-table">
          <thead><tr><th scope="col">Пункт</th><th scope="col">Было</th><th scope="col">Стало</th><th scope="col">Статус</th></tr></thead>
          <tbody>{shown.map((change, index) => {
            const key = `${change.clause_id}-${index}`
            const isOpen = expanded === key
            return [
              <tr key={key} className="mapping-row" data-row-index={index}>
                <td><button type="button" className="clause-link" aria-expanded={isOpen} aria-controls={`source-${index}`} onClick={() => setExpanded(isOpen ? null : key)}>{change.before_clause_id && change.after_clause_id && change.before_clause_id !== change.after_clause_id ? `${change.before_clause_id} → ${change.after_clause_id}` : change.clause_id || '—'} <ChevronDown size={14} aria-hidden="true" /></button>{change.match_method === 'exact_text' && <small className="mapping-match">Совпадение текста</small>}</td>
                <td className={!change.before ? 'cell-empty' : ''}>{change.before || '—'}</td>
                <td className={!change.after ? 'cell-empty' : ''}>{change.after || '—'}</td>
                <td><Badge tone={statusTone(change.status)}>{statusLabels[change.status] || change.status}</Badge></td>
              </tr>,
              isOpen && <tr key={`${key}-source`} id={`source-${index}`} className="mapping-source-row"><td colSpan={4}>
                <div className="mapping-sources"><span><strong>До · {change.before_clause_id || 'Нет пункта'}</strong>{change.before_source || 'Нет пункта в исходном документе'}</span><span><strong>После · {change.after_clause_id || 'Нет пункта'}</strong>{change.after_source || 'Нет пункта в новой редакции'}</span></div>
              </td></tr>,
            ]
        })}</tbody>
        </table></div></>
      ) : <div className="empty-state">По выбранному фильтру пунктов нет. Попробуйте другой статус или подразделение.</div>}
      {visible.length > 0 && <p className="panel-intro" role="status" aria-live="polite">Показано {shown.length} из {visible.length} пунктов.</p>}
      {shown.length < visible.length && <button type="button" className="button button--secondary" onClick={() => { revealFrom.current = shown.length; setVisibleCount((count) => count + 40) }}>Показать ещё</button>}
    </section>
  )
}

function FindingCard({ finding, index, expanded, onToggle }: { finding: Finding; index: number; expanded: boolean; onToggle: () => void }) {
  const reducedMotion = useReducedMotion()
  const tone = findingTone(finding.kind)
  return (
    <article id={`finding-${finding.id}`} tabIndex={-1} className={`finding-card finding-card--${tone}`}>
      <div className="finding-card__top"><span className={`finding-icon finding-icon--${tone}`}><CircleAlert size={19} aria-hidden="true" /></span><Badge tone={tone}>{finding.origin === 'local' && finding.kind === 'потенциальная потеря функции' ? 'Удалённый пункт' : finding.kind}</Badge><span className="finding-card__index">{String(index + 1).padStart(2, '0')}</span></div>
      <span className="finding-origin">{finding.origin === 'ai' ? 'Вывод ИИ · цитаты проверены' : 'Локальное сравнение · требует оценки эксперта'}</span>
      <h4>{finding.title}</h4>

      <p>{finding.explanation}</p>
      <button type="button" className="evidence-toggle" aria-expanded={expanded} aria-controls={`finding-evidence-${finding.id}`} onClick={onToggle}>
        <span>{expanded ? 'Скрыть источники' : 'Показать источники'} <span className="evidence-count">{finding.citations?.length || 0}</span></span><ChevronDown size={17} className={expanded ? 'rotated' : ''} aria-hidden="true" />
      </button>
      <AnimatePresence initial={false}>
        {expanded && <motion.div id={`finding-evidence-${finding.id}`} className="evidence-content" initial={reducedMotion ? false : { height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={reducedMotion ? undefined : { height: 0, opacity: 0 }} transition={{ duration: reducedMotion ? 0 : 0.24 }}>
          {finding.citations?.length ? finding.citations.map((citation, citationIndex) => <blockquote key={`${citation.clause_id}-${citationIndex}`}>
            <span>{citation.source ? `${citation.source} · ` : ''}{citation.document_label} · {citation.clause_id}{citation.location ? ` · ${citation.location}` : ''}</span>
            <p>«{citation.quote}»</p>
          </blockquote>) : <p className="no-evidence">Цитаты для этого вывода не предоставлены.</p>}
        </motion.div>}
      </AnimatePresence>

    </article>
  )
}

export default function ResultsView({ result, onRestart, onExport, exporting, exportError, onSave }: {
  result: AnalysisResponse
  onSave: (archive: Archive) => void
  onRestart: () => void
  onExport: (format: 'pdf' | 'docx') => void
  exporting: 'pdf' | 'docx' | null
  exportError: string | null
}) {
  const [query, setQuery] = useState('')
  const [title, setTitle] = useState(() => `${result.source_names.before} → ${result.source_names.after}`.slice(0, 160))
  const filteredFindings = result.findings.filter(f => matchesQuery(f, query))
  const save = () => onSave({
    id: result.analysis_id, title: title.trim() || 'Сравнение документов', savedAt: new Date().toISOString(),
    before: result.source_names.before, after: result.source_names.after, aiStatus: result.ai.status,
    changes: result.summary.added + result.summary.removed + result.summary.modified,
    total: result.findings.length, markdown: result.report_markdown,
  })
  const [activeUnit, setActiveUnit] = useState<string | null>(null)
  const [visibleFindings, setVisibleFindings] = useState(8)
  const [expandedFindingId, setExpandedFindingId] = useState<string | null>(null)
  const [scrollTarget, setScrollTarget] = useState<string | null>(null)
  const reducedMotion = useReducedMotion()
  const aiCount = result.findings.filter((finding) => finding.origin === 'ai').length
  const inspectFinding = (id: string) => {
    const index = result.findings.findIndex((finding) => finding.id === id)
    if (index < 0) return
    setQuery('')
    setVisibleFindings((count) => Math.max(count, index + 1))
    setExpandedFindingId(id)
    setScrollTarget(id)
  }
  useEffect(() => {
    if (!scrollTarget) return
    const frame = requestAnimationFrame(() => {
      const card = document.getElementById(`finding-${scrollTarget}`)
      card?.focus({ preventScroll: true })
      card?.scrollIntoView({ behavior: reducedMotion ? 'instant' : 'smooth', block: 'start' })
      setScrollTarget(null)
    })
    return () => cancelAnimationFrame(frame)
  }, [scrollTarget, reducedMotion])

  return (
    <div className="results-view">
      <div className="results-header">
        <div><span className="eyebrow"><span className="eyebrow__line" />СРАВНЕНИЕ ГОТОВО</span><h2>Аналитическое заключение</h2><p><strong>{result.source_names.before}</strong><span className="results-file-arrow"> → </span><strong>{result.source_names.after}</strong></p></div>
        <button type="button" className="button button--secondary" onClick={onRestart}><Plus size={17} aria-hidden="true" />К документам</button>
      </div>
      <AiSummary result={result} onInspect={inspectFinding} />
      <div className="metric-grid">
        <MetricCard label="Изменено подразделений" value={result.summary.units_changed} tone="blue" footnote="Оценки ИИ / текстовые признаки" />
        <MetricCard label="Потери функций · ИИ" value={result.summary.ai_loss_count ?? null} tone="red" footnote={result.summary.ai_loss_count == null ? 'Не проверено' : 'Возможные · требуют проверки'} />
        <MetricCard label="Возможные дубли · ИИ" value={result.summary.ai_duplicate_count ?? null} tone="amber" footnote={result.summary.ai_duplicate_count == null ? 'Не проверено' : aiStatusLabels[result.ai.status]} />
        <MetricCard label="Удалённые пункты" value={result.summary.removed} tone="green" footnote="Точное сравнение · не потеря функции" />
        <MetricCard label="Переформулировано" value={result.summary.modified} tone="blue" footnote="Сопоставленных пунктов" />
      </div>
      <nav className="results-nav" aria-label="Разделы заключения"><a href="#findings">Замечания <span>{result.findings.length}</span></a><a href="#semantic">Подразделения и функции</a><a href="#mapping">Карта изменений</a><a href="#export">Скачать отчёт</a><a href="#coverage">Охват и ограничения</a></nav>
      <section className="surface product-panel search-panel" aria-label="Поиск по сравнению">
        <label className="product-field">Поиск по замечаниям и точной карте<input type="search" value={query} onChange={event => { setQuery(event.target.value); setVisibleFindings(8) }} placeholder="Функция, цитата, номер пункта…" /></label>
        {query && <button className="button button--secondary" onClick={() => setQuery('')}>Сбросить поиск</button>}
      </section>
      <section className="findings-section" id="findings" aria-labelledby="findings-heading">
        <div className="section-heading"><div><span className="eyebrow">ВЫВОДЫ И ИСТОЧНИКИ</span><h3 id="findings-heading">Потери, дубли и конфликты</h3></div><span className="count-pill">{result.findings.length}</span></div>
        <p className="panel-intro">Выводов ИИ: {aiCount}. Локальных замечаний: {result.findings.length - aiCount}. Откройте источник для проверки. Удалённый пункт сам по себе не доказывает потерю функции.</p>
        {result.findings.length ? <>
          {!filteredFindings.length && <div className="empty-state">По этим условиям замечаний нет. Измените запрос или сбросьте поиск.</div>}
          <div className="findings-grid">{filteredFindings.slice(0, visibleFindings).map((finding, index) => <FindingCard key={finding.id} finding={finding} index={index} expanded={expandedFindingId === finding.id} onToggle={() => setExpandedFindingId(expandedFindingId === finding.id ? null : finding.id)} />)}</div>
          <p className="panel-intro" role="status" aria-live="polite">Показано {Math.min(visibleFindings, filteredFindings.length)} из {filteredFindings.length} замечаний по фильтру.</p>
          {visibleFindings < filteredFindings.length && <button type="button" className="button button--secondary" onClick={() => setVisibleFindings((count) => count + 8)}>Показать ещё</button>}
        </> : <div className="all-clear"><FileText size={23} aria-hidden="true" /><div><strong>Замечаний с источниками нет</strong><span>Это не гарантирует отсутствие рисков. Проверьте карту изменений и охват анализа ниже.</span></div></div>}
      </section>
      <SemanticAnalysis result={result} />
      <div className="results-layout">
        <UnitsPanel units={result.units} active={activeUnit} onSelect={setActiveUnit} />
        <MappingTable changes={result.changes} units={result.units} activeUnit={activeUnit} query={query} />
      </div>
      <section className="export-panel" id="export" aria-labelledby="export-heading">
        <div className="export-panel__icon"><ArrowDownToLine size={22} aria-hidden="true" /></div>
        <div><span className="eyebrow">ГОТОВО К ВЫГРУЗКЕ</span><h3 id="export-heading">Заключение с источниками</h3><p>Отчёт по этому результату: сводка, изменения, цитаты и ограничения.</p></div>
        <div className="export-actions">
          <button type="button" className="button button--light" disabled={exporting !== null} onClick={() => onExport('pdf')}><FileType2 size={17} aria-hidden="true" />{exporting === 'pdf' ? 'Готовим PDF…' : 'Скачать PDF'}</button>
          <button type="button" className="button button--outline-light" disabled={exporting !== null} onClick={() => onExport('docx')}><FileText size={17} aria-hidden="true" />{exporting === 'docx' ? 'Готовим Word…' : 'Скачать Word'}</button>
        </div>
        {exportError && <div className="export-error" role="alert"><CircleAlert size={18} aria-hidden="true" /><span>{exportError}</span></div>}
      </section>
      <section className="surface product-panel" aria-label="Сохранение заключения">
        <h3>Сохранить результат</h3>
        <label className="product-field">Название сравнения<input maxLength={160} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <div className="product-actions">
          <button type="button" className="button button--primary" onClick={save}>Сохранить в историю</button>
          <button type="button" className="button button--secondary" onClick={() => downloadText(result.report_markdown, 'teren-oi-report.md')}>Скачать Markdown</button>
          <button type="button" className="button button--secondary" onClick={() => downloadText(changesCsv(result.changes), 'teren-oi-mapping.csv', 'text/csv;charset=utf-8')}>Вся карта в CSV</button>
        </div>
        <p className="field-hint">Сохраняется исходное заключение с цитатами. История доступна только в этом браузере; исходные файлы в неё не входят.</p>
      </section>
      <section className="coverage-panel surface" id="coverage" aria-labelledby="coverage-heading">
        <div className="section-heading"><div><span className="eyebrow">ПРЕДЕЛЫ ПРОВЕРКИ</span><h3 id="coverage-heading">Охват и ограничения</h3></div><ShieldCheck size={20} aria-hidden="true" /></div>
        <div className="coverage-grid">{(['before', 'after'] as const).map((side) => <div key={side}><strong>{side === 'before' ? 'Исходная редакция' : 'Новая редакция'}</strong><p>Распознано пунктов: {result.coverage[side].clauses}</p><p>Блоков вне нумерации: {result.coverage[side].unnumbered_blocks}{result.coverage[side].synthetic_ids ? ' · назначены условные номера' : ''}</p></div>)}</div>
        {Boolean(result.ai.omitted_refs?.length || result.ai.truncated_refs?.length) && <details className="coverage-details">
          <summary>Какие фрагменты ИИ не проверил полностью</summary>
          <p className="panel-intro">В каждом списке показаны первые 50 ссылок максимум. Полные количества: не передано — {result.ai.coverage.omitted_clauses}, передано частично — {result.ai.coverage.truncated_clauses}.</p>
          {!!result.ai.omitted_refs?.length && <div><strong>Не переданы ИИ</strong><ul>{result.ai.omitted_refs.slice(0, 50).map((reference, index) => <li key={`omitted-${index}`}>{reference}</li>)}</ul></div>}
          {!!result.ai.truncated_refs?.length && <div><strong>Переданы частично</strong><ul>{result.ai.truncated_refs.slice(0, 50).map((reference, index) => <li key={`truncated-${index}`}>{reference}</li>)}</ul></div>}
        </details>}
        {result.warnings?.map((warning, index) => <div className="ai-warning" key={`${warning}-${index}`}><CircleAlert size={18} aria-hidden="true" /><span>{warning}</span></div>)}
        <p className="panel-intro">Точное совпадение текста помогает заметить перенос пункта. Смысловая перенумерация, разделение и объединение функций могут требовать ручной проверки. Наличие точной цитаты подтверждает источник, но не доказывает вывод модели.</p>
        <p className="panel-intro">Исходный отчёт хранится на сервере до часа. Для доступа после перезапуска сохраните заключение в локальную историю или скачайте Markdown. PDF, Word и Markdown содержат один и тот же результат анализа.</p>
      </section>
    </div>
  )
}
