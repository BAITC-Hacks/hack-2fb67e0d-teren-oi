import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { ArrowDownToLine, CheckCircle2, ChevronDown, CircleAlert, FileText, FileType2, FolderOpen, Layers3, Plus, ShieldCheck } from 'lucide-react'
import type { AnalysisResponse, ClauseChange, Finding, Unit } from '../types'

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

function MetricCard({ label, value, tone, footnote }: { label: string; value: number; tone: string; footnote: string }) {
  return (
    <div className={`metric-card metric-card--${tone}`}>
      <span className="metric-card__label">{label}</span>
      <strong>{value.toLocaleString('ru-RU')}</strong>
      <span className="metric-card__footnote"><span className="metric-card__dot" />{footnote}</span>
    </div>
  )
}
function UnitsPanel({ units, active, onSelect }: { units: Unit[]; active: string | null; onSelect: (name: string | null) => void }) {
  return (
    <section className="surface units-panel" aria-labelledby="units-heading">
      <div className="section-heading"><div><span className="eyebrow">СТРУКТУРА</span><h3 id="units-heading">Подразделения</h3></div><span className="count-pill">{units.length}</span></div>
      <p className="panel-intro">Выберите подразделение, чтобы отфильтровать таблицу пунктов.</p>
      <div className="unit-list">
        <button type="button" className={`unit-item ${active === null ? 'is-selected' : ''}`} onClick={() => onSelect(null)} aria-pressed={active === null}>
          <span className="unit-item__symbol"><Layers3 size={16} /></span><span className="unit-item__name">Все подразделения</span><span className="unit-item__arrow">→</span>
        </button>
        {units.map((unit, index) => (
          <button type="button" key={`${unit.name}-${index}`} className={`unit-item ${active === unit.name ? 'is-selected' : ''}`} onClick={() => onSelect(unit.name)} aria-pressed={active === unit.name}>
            <span className={`unit-item__symbol unit-item__symbol--${statusTone(unit.status)}`}><FolderOpen size={16} /></span>
            <span className="unit-item__name">{unit.name}</span>
            <Badge tone={statusTone(unit.status)}>{statusLabels[unit.status] || unit.status}</Badge>
          </button>
        ))}
      </div>
    </section>
  )
}
function MappingTable({ changes, units, activeUnit }: { changes: ClauseChange[]; units: Unit[]; activeUnit: string | null }) {
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
  }, [filter, activeUnit])
  useEffect(() => {
    if (revealFrom.current === null) return
    const firstNewIndex = revealFrom.current
    const frame = requestAnimationFrame(() => {
      const container = tableRef.current
      const row = container?.querySelector<HTMLElement>(`[data-row-index="${firstNewIndex}"]`)
      if (!container || !row) return
      const top = row.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
      container.scrollTo({ top, behavior: reducedMotion ? 'auto' : 'smooth' })
    })
    revealFrom.current = null
    return () => cancelAnimationFrame(frame)
  }, [visibleCount, reducedMotion])
  const selectedUnit = units.find((unit) => unit.name === activeUnit)
  const visible = changes.filter((change) =>
    (filter === 'all' || change.status === filter) && (!selectedUnit || selectedUnit.clause_ids.includes(change.clause_id)),
  )
  const shown = visible.slice(0, visibleCount)
  const filters = [
    ['all', 'Все'], ['modified', 'Изменено'], ['removed', 'Удалено'], ['added', 'Добавлено'],
  ]
  return (
    <section className="surface mapping-panel" id="mapping" aria-labelledby="mapping-heading">
      <div className="section-heading"><div><span className="eyebrow">СОПОСТАВЛЕНИЕ</span><h3 id="mapping-heading">Карта изменений</h3></div><span className="count-pill">{visible.length}</span></div>
      <div className="filter-bar" aria-label="Фильтр статуса">
        {filters.map(([key, label]) => <button key={key} type="button" className={filter === key ? 'is-active' : ''} onClick={() => setFilter(key)} aria-pressed={filter === key}>{label}</button>)}
      </div>
      {visible.length ? (
        <div className="table-scroll" ref={tableRef}><table className="mapping-table">
          <thead><tr><th scope="col">Пункт</th><th scope="col">Было</th><th scope="col">Стало</th><th scope="col">Статус</th></tr></thead>
          <tbody>{shown.map((change, index) => {
            const key = `${change.clause_id}-${index}`
            const isOpen = expanded === key
            return [
              <tr key={key} className="mapping-row" data-row-index={index}>
                <td><button type="button" className="clause-link" aria-expanded={isOpen} aria-controls={`source-${index}`} onClick={() => setExpanded(isOpen ? null : key)}>{change.clause_id || '—'} <ChevronDown size={14} aria-hidden="true" /></button></td>
                <td className={!change.before ? 'cell-empty' : ''}>{change.before || '—'}</td>
                <td className={!change.after ? 'cell-empty' : ''}>{change.after || '—'}</td>
                <td><Badge tone={statusTone(change.status)}>{statusLabels[change.status] || change.status}</Badge></td>
              </tr>,
              isOpen && <tr key={`${key}-source`} id={`source-${index}`} className="mapping-source-row"><td colSpan={4}>
                <div className="mapping-sources"><span><strong>Источник «до»</strong>{change.before_source || 'Нет пункта в исходном документе'}</span><span><strong>Источник «после»</strong>{change.after_source || 'Нет пункта в новой редакции'}</span></div>
              </td></tr>,
            ]
        })}</tbody>
        </table></div>
      ) : <div className="empty-state">По выбранному фильтру пунктов нет. Попробуйте другой статус или подразделение.</div>}
      {visible.length > 0 && <p className="panel-intro" role="status" aria-live="polite">Показано {shown.length} из {visible.length} пунктов.</p>}
      {shown.length < visible.length && <button type="button" className="button button--secondary" onClick={() => { revealFrom.current = shown.length; setVisibleCount((count) => count + 40) }}>Показать ещё</button>}
    </section>
  )
}

function FindingCard({ finding, index }: { finding: Finding; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const reducedMotion = useReducedMotion()
  const tone = findingTone(finding.kind)
  return (
    <article className={`finding-card finding-card--${tone}`}>
      <div className="finding-card__top"><span className={`finding-icon finding-icon--${tone}`}><CircleAlert size={19} aria-hidden="true" /></span><Badge tone={tone}>{finding.kind}</Badge><span className="finding-card__index">{String(index + 1).padStart(2, '0')}</span></div>
      <h4>{finding.title}</h4>
      <p>{finding.explanation}</p>
      <button type="button" className="evidence-toggle" aria-expanded={expanded} aria-controls={`finding-evidence-${index}`} onClick={() => setExpanded(!expanded)}>
        <span>Показать источники <span className="evidence-count">{finding.citations?.length || 0}</span></span><ChevronDown size={17} className={expanded ? 'rotated' : ''} aria-hidden="true" />
      </button>
      <AnimatePresence initial={false}>
        {expanded && <motion.div id={`finding-evidence-${index}`} className="evidence-content" initial={reducedMotion ? false : { height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={reducedMotion ? undefined : { height: 0, opacity: 0 }} transition={{ duration: reducedMotion ? 0 : 0.24 }}>
          {finding.citations?.length ? finding.citations.map((citation, citationIndex) => <blockquote key={`${citation.clause_id}-${citationIndex}`}>
            <span>{citation.source ? `${citation.source} · ` : ''}{citation.document_label} · {citation.clause_id}{citation.location ? ` · ${citation.location}` : ''}</span>
            <p>«{citation.quote}»</p>
          </blockquote>) : <p className="no-evidence">Цитаты для этого вывода не предоставлены.</p>}
          {finding.confidence != null && <p className="confidence">Уверенность: {String(finding.confidence)}</p>}
        </motion.div>}
      </AnimatePresence>
    </article>
  )
}

export default function ResultsView({ result, aiUsed, onRestart, onExport, exporting }: {
  result: AnalysisResponse
  aiUsed: boolean
  onRestart: () => void
  onExport: (format: 'pdf' | 'docx') => void
  exporting: 'pdf' | 'docx' | null
}) {
  const [activeUnit, setActiveUnit] = useState<string | null>(null)
  const [visibleFindings, setVisibleFindings] = useState(8)
  const riskCount = result.summary.loss_count + result.summary.duplicate_count
  return (
    <div className="results-view">
      <div className="results-header">
        <div><span className="eyebrow"><span className="eyebrow__line" />АНАЛИЗ ЗАВЕРШЁН</span><h2>Аналитическое заключение</h2><p>Сравнение <strong>{result.source_names.before}</strong> и <strong>{result.source_names.after}</strong></p></div>
        <button type="button" className="button button--secondary" onClick={onRestart}><Plus size={17} />Новый анализ</button>
      </div>
      {result.ai_error && <div className="ai-warning" role="status"><CircleAlert size={18} aria-hidden="true" /><span><strong>Локальное сравнение готово, но AI-проверка не завершилась.</strong> {result.ai_error}</span></div>}
      {result.warnings?.map((warning, index) => <div className="ai-warning" role="status" key={`${warning}-${index}`}><CircleAlert size={18} aria-hidden="true" /><span>{warning}</span></div>)}
      <div className="metric-grid">
        <MetricCard label="Изменено подразделений" value={result.summary.units_changed} tone="blue" footnote="Структурные изменения" />
        <MetricCard label="Потенциальные потери" value={result.summary.loss_count} tone="red" footnote="Требуют проверки" />
        <MetricCard label="Возможные дубли" value={result.summary.duplicate_count} tone="amber" footnote={aiUsed ? 'AI-проверка выполнена' : result.ai_error ? 'AI-проверка не завершилась' : 'AI-проверка выключена'} />
        <MetricCard label="Изменено пунктов" value={result.summary.modified} tone="green" footnote="В двух редакциях" />
      </div>
      <div className="results-layout">
        <UnitsPanel units={result.units} active={activeUnit} onSelect={setActiveUnit} />
        <MappingTable changes={result.changes} units={result.units} activeUnit={activeUnit} />
      </div>
      <section className="findings-section" id="findings" aria-labelledby="findings-heading">
        <div className="section-heading"><div><span className="eyebrow">ВЫВОДЫ И ИСТОЧНИКИ</span><h3 id="findings-heading">Точки внимания</h3></div><span className="count-pill">{result.findings.length}</span></div>
        <p className="panel-intro">Откройте карточку, чтобы увидеть точную цитату и исходный пункт документа.</p>
        {result.findings.length ? <>
          <div className="findings-grid">{result.findings.slice(0, visibleFindings).map((finding, index) => <FindingCard key={`${finding.kind}-${index}`} finding={finding} index={index} />)}</div>
          <p className="panel-intro" role="status" aria-live="polite">Показано {Math.min(visibleFindings, result.findings.length)} из {result.findings.length} выводов.</p>
          {visibleFindings < result.findings.length && <button type="button" className="button button--secondary" onClick={() => setVisibleFindings((count) => count + 8)}>Показать ещё</button>}
        </> : <div className="all-clear"><CheckCircle2 size={21} /><div><strong>Структурных отклонений не найдено</strong><span>{aiUsed ? 'AI-проверка не сформировала выводов по этим документам.' : result.ai_error ? 'Удалённых пунктов нет; AI-проверка не завершилась.' : 'Удалённых пунктов нет; AI-проверка дублирования не запускалась.'}</span></div></div>}
      </section>
      <section className="export-panel" id="export" aria-labelledby="export-heading">
        <div className="export-panel__icon"><ArrowDownToLine size={22} aria-hidden="true" /></div>
        <div><span className="eyebrow">ГОТОВО К ВЫГРУЗКЕ</span><h3 id="export-heading">Заберите заключение с собой</h3><p>Сводка, изменения, выводы и ссылки на исходные пункты в одном документе.</p></div>
        <div className="export-actions">
          <button type="button" className="button button--light" disabled={exporting !== null} onClick={() => onExport('pdf')}><FileType2 size={17} />{exporting === 'pdf' ? 'Готовим PDF…' : 'Скачать PDF'}</button>
          <button type="button" className="button button--outline-light" disabled={exporting !== null} onClick={() => onExport('docx')}><FileText size={17} />{exporting === 'docx' ? 'Готовим Word…' : 'Скачать Word'}</button>
        </div>
      </section>
      <p className="results-disclaimer"><ShieldCheck size={15} aria-hidden="true" />Выводы помогают эксперту проверить изменения и требуют содержательной проверки перед принятием решений. {riskCount > 0 ? `Всего точек риска: ${riskCount}.` : ''}</p>
    </div>
  )
}
