import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Activity, CircleAlert, Layers3, Moon, RefreshCw, ShieldCheck, Sparkles, Sun, X } from 'lucide-react'
import { analyze, exportReport, getHealth } from './api'
import type { AnalysisResponse, DocumentSide, HealthResponse, Step } from './types'
import AnalysisView from './components/AnalysisView'
import ImportView from './components/ImportView'
import type { Documents, UploadedDocument } from './components/ImportView'
import ResultsView from './components/ResultsView'
import Stepper from './components/Stepper'
import HistoryPanel from './components/HistoryPanel'
import { readArchives, writeArchives } from './workspace'
import type { Archive } from './workspace'

type Theme = 'light' | 'dark'
const emptyDocument = (): UploadedDocument => ({ files: [], text: '', progress: 0, ready: false })
const defaultExtensions = ['.docx', '.pdf', '.xlsx', '.txt']
function extensionOf(filename: string): string {
  return `.${filename.split('.').pop()?.toLocaleLowerCase() || ''}`
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => { try { return localStorage.getItem('teren-oi-theme') === 'dark' ? 'dark' : 'light' } catch { return 'light' } })
  const [archives, setArchives] = useState<Archive[]>(readArchives)
  const [showHistory, setShowHistory] = useState(false)
  const [deletedArchive, setDeletedArchive] = useState<Archive | null>(null)
  const [archiveMessage, setArchiveMessage] = useState<string | null>(null)
  const [step, setStep] = useState<Step>('import')
  const [documents, setDocuments] = useState<Documents>({ before: emptyDocument(), after: emptyDocument() })
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [connected, setConnected] = useState(false)
  const [useAi, setUseAi] = useState(false)
  const [result, setResult] = useState<AnalysisResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null)
  const exportRequestId = useRef(0)
  const analysisPending = useRef(false)
  const reducedMotion = useReducedMotion()

  useEffect(() => {
    const syncHistory = () => setArchives(readArchives())
    window.addEventListener('storage', syncHistory)
    return () => window.removeEventListener('storage', syncHistory)
  }, [])

  useEffect(() => { document.documentElement.dataset.theme = theme; try { localStorage.setItem('teren-oi-theme', theme) } catch { /* Theme still works when storage is unavailable. */ } }, [theme])
  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal).then((data) => { setHealth(data); setConnected(true) }).catch(() => setConnected(false))
    return () => controller.abort()
  }, [])
  useEffect(() => {
    document.getElementById('main-content')?.focus({ preventScroll: true })
    window.scrollTo({ top: 0, behavior: 'instant' })
  }, [step])

  const acceptedExtensions = useMemo(() => {
    const supported = health?.supported_extensions?.length ? health.supported_extensions : defaultExtensions
    return supported.map((item) => item.startsWith('.') ? item.toLowerCase() : `.${item.toLowerCase()}`)
  }, [health])

  const updateFile = (side: DocumentSide, files: File[]) => {
    setError(null)
    const combined = [...documents[side].files, ...files]
    if (combined.length > 8) { setError('Не более 8 файлов на редакцию.'); return }
    if (new Set(combined.map(f => f.name.toLocaleLowerCase())).size !== combined.length) { setError('Имена файлов в комплекте должны быть уникальны.'); return }
    for (const file of files) {
      if (!acceptedExtensions.includes(extensionOf(file.name)) || file.size === 0 || file.size > 12 * 1024 * 1024) {
        setError(`Проверьте файл ${file.name}: допустимы ${acceptedExtensions.join(', ')}, от 1 байта до 12 МБ.`); return
      }
    }
    setDocuments(current => ({...current, [side]: { files: combined, text: '', ready: true, progress: 100 }}))
  }
  const removeFile = (side: DocumentSide, index: number) => setDocuments(current => {
    const files = current[side].files.filter((_, i) => i !== index)
    return {...current, [side]: {...current[side], files, ready: files.length > 0}}
  })
  const updateText = (side: DocumentSide, text: string) => setDocuments((current) => ({ ...current, [side]: { ...current[side], text } }))
  const refreshHealth = () => getHealth().then((data) => { setHealth(data); setConnected(true) }).catch(() => setConnected(false))

  const saveArchive = (item: Archive) => {
    try {
      const next = [item, ...readArchives().filter(previous => previous.id !== item.id)]
      writeArchives(next); setArchives(next); setArchiveMessage('Сохранено в истории этого браузера. Повторное сохранение обновит эту запись.')
    } catch (reason) { setArchiveMessage(reason instanceof Error ? reason.message : 'Не удалось сохранить.') }
  }
  const deleteArchive = (id: string) => {
    try {
      const current = readArchives()
      const next = current.filter(item => item.id !== id)
      writeArchives(next); setDeletedArchive(current.find(item => item.id === id) || null); setArchives(next)
    } catch (reason) { setArchiveMessage(reason instanceof Error ? reason.message : 'Не удалось удалить.') }
  }
  const undoDelete = () => {
    if (!deletedArchive) return
    try {
      const next = [deletedArchive, ...readArchives().filter(item => item.id !== deletedArchive.id)]
      writeArchives(next); setArchives(next); setDeletedArchive(null)
    } catch (reason) { setArchiveMessage(reason instanceof Error ? reason.message : 'Не удалось восстановить.') }
  }

  const runAnalysis = async (demo: boolean) => {
    if (analysisPending.current) return
    setError(null)
    if (!demo && (!documents.before.files.length && !documents.before.text.trim() || !documents.after.files.length && !documents.after.text.trim())) {
      setError('Добавьте обе версии документа: файл или текст для каждой колонки.')
      return
    }
    if (!demo && (documents.before.files.length && !documents.before.ready || documents.after.files.length && !documents.after.ready)) {
      setError('Подождите, пока файлы подготовятся к анализу.')
      return
    }
    analysisPending.current = true
    setStep('analysis')
    try {
      const data = await analyze({
        beforeFiles: demo ? [] : documents.before.files,
        afterFiles: demo ? [] : documents.after.files,
        beforeText: demo ? '' : documents.before.text.trim(),
        afterText: demo ? '' : documents.after.text.trim(),
        useAi,
        demo,
      })
      setResult(data)
      setArchiveMessage(null)
      exportRequestId.current += 1
      setExporting(null)
      setExportError(null)
      setStep('results')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось выполнить анализ.')
      setStep('import')
    } finally {
      analysisPending.current = false
    }
  }

  const download = async (format: 'pdf' | 'docx') => {
    if (!result) return
    const requestId = ++exportRequestId.current
    setExporting(format)
    setExportError(null)
    try { await exportReport(result.analysis_id, format) }
    catch (reason) {
      if (exportRequestId.current === requestId) setExportError(reason instanceof Error ? reason.message : 'Не удалось скачать заключение.')
    }
    finally { if (exportRequestId.current === requestId) setExporting(null) }
  }

  const pageMotion = reducedMotion ? { initial: false as const, animate: { opacity: 1 }, exit: undefined } : {
    initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -10 },
  }

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Перейти к содержимому</a>
      <aside className="sidebar" aria-label="Навигация по рабочему пространству">
        <div className="brand"><span className="brand__mark"><Layers3 size={22} strokeWidth={2.1} /></span><span><strong>TEREN OI</strong><small>DOCUMENT INTELLIGENCE</small></span></div>
        <div className="sidebar__section-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
        <div className="sidebar__nav"><span className="sidebar__nav-icon"><Activity size={18} /></span><span>Анализ структуры</span><span className="sidebar__nav-dot" /></div>
        <div className="sidebar__bottom">
          <div className="sidebar__info"><span className="sidebar__info-icon"><ShieldCheck size={17} /></span><span><strong>Проверяемые выводы</strong><small>Каждый вывод связан с источником</small></span></div>
          <div className="sidebar__info sidebar__info--ai"><span className="sidebar__info-icon"><Sparkles size={17} /></span><span><strong>AI-анализ</strong><small>{!connected ? 'Нет связи с сервером' : health?.ai_available ? 'Ключ настроен на сервере' : 'Ключ не задан на сервере'}</small></span></div>
          <span className="sidebar__version">TEREN OI · ВЕРСИЯ 0.1</span>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar"><div className="topbar__trail">Рабочее пространство <span>/</span> <strong>Сравнение редакций</strong></div><div className="topbar__actions">
          <button type="button" className="button button--secondary history-button" disabled={step === 'analysis'} aria-pressed={showHistory} onClick={() => { setShowHistory(!showHistory); setArchiveMessage(null) }}>{showHistory ? 'К сравнению' : `История (${archives.length})`}</button>
          <button type="button" className={`connection-pill ${connected ? 'is-connected' : ''}`} onClick={refreshHealth} title="Проверить соединение с API" aria-label={connected ? 'API подключён. Проверить снова' : 'API недоступен. Проверить снова'}><span />{connected ? 'API подключён' : 'API недоступен'}<RefreshCw size={13} /></button>
          <button type="button" className="theme-toggle" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} aria-label={theme === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему'} title={theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}>{theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}</button>
        </div></header>

        <main id="main-content" className="main-content" tabIndex={-1}>
          {!showHistory && step === 'import' && <div className="page-intro"><div><span className="eyebrow"><span className="eyebrow__line" />AI-АССИСТЕНТ ДЛЯ АНАЛИЗА ДОКУМЕНТОВ</span><h1>Сравнение редакций<br /><span>с опорой на источники.</span></h1><p>Загрузите две версии положения. Teren Oi покажет, что изменилось в структуре и функциях, и приложит цитаты для проверки.</p></div><div className="intro-aside"><span className="intro-aside__icon"><Sparkles size={20} /></span><span>От документа<br />к ясному решению</span></div></div>}
          {archiveMessage && <p className="product-notice" role="status">{archiveMessage}</p>}
          {showHistory && <HistoryPanel items={archives} onDelete={deleteArchive} onUndo={undoDelete} canUndo={Boolean(deletedArchive)} />}
          <div hidden={showHistory}>
          <Stepper step={step} hasResult={Boolean(result)} goTo={setStep} />
          {error && <div className="error-banner" role="alert"><CircleAlert size={18} /><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Закрыть сообщение"><X size={16} /></button></div>}
          <AnimatePresence mode="wait">
            {step === 'import' && <motion.div key="import" {...pageMotion} transition={{ duration: 0.35 }}>
              <ImportView documents={documents} acceptedExtensions={acceptedExtensions} health={health} connected={connected} useAi={useAi} onAiChange={setUseAi} onFile={updateFile} onRemove={removeFile} onText={updateText} onAnalyze={runAnalysis} onSwap={() => setDocuments(current => ({before: current.after, after: current.before}))} onClear={() => setDocuments({before: emptyDocument(), after: emptyDocument()})} />
            </motion.div>}
            {step === 'analysis' && <motion.div key="analysis" {...pageMotion} transition={{ duration: 0.35 }}><AnalysisView useAi={useAi} model={health?.model} /></motion.div>}
          </AnimatePresence>
          {result && <div hidden={step !== 'results'}><ResultsView key={result.analysis_id} result={result} onSave={saveArchive} onRestart={() => { setStep('import'); setError(null) }} onExport={(format) => void download(format)} exporting={exporting} exportError={exportError} /></div>}
          </div>
          <footer className="footer"><span>© {new Date().getFullYear()} Teren Oi</span><span>Анализ документов с опорой на исходные пункты</span></footer>
        </main>
      </div>
    </div>
  )
}
