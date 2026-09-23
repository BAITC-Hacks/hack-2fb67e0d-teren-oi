import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Activity, CircleAlert, Layers3, Moon, RefreshCw, ShieldCheck, Sparkles, Sun, X } from 'lucide-react'
import { analyze, exportReport, getHealth } from './api'
import type { AnalysisResponse, DocumentSide, HealthResponse, Step } from './types'
import AnalysisView, { analysisStages } from './components/AnalysisView'
import ImportView from './components/ImportView'
import type { Documents, UploadedDocument } from './components/ImportView'
import ResultsView from './components/ResultsView'
import Stepper from './components/Stepper'

type Theme = 'light' | 'dark'
const emptyDocument = (): UploadedDocument => ({ file: null, text: '', progress: 0, ready: false })
const defaultExtensions = ['.docx', '.pdf', '.xlsx', '.txt']
function extensionOf(filename: string): string {
  return `.${filename.split('.').pop()?.toLocaleLowerCase() || ''}`
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => localStorage.getItem('teren-oi-theme') === 'dark' ? 'dark' : 'light')
  const [step, setStep] = useState<Step>('import')
  const [documents, setDocuments] = useState<Documents>({ before: emptyDocument(), after: emptyDocument() })
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [connected, setConnected] = useState(false)
  const [useAi, setUseAi] = useState(false)
  const [result, setResult] = useState<AnalysisResponse | null>(null)
  const [analysisUsedAi, setAnalysisUsedAi] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stage, setStage] = useState(0)
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null)
  const reducedMotion = useReducedMotion()

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('teren-oi-theme', theme) }, [theme])
  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal).then((data) => { setHealth(data); setConnected(true) }).catch(() => setConnected(false))
    return () => controller.abort()
  }, [])
  useEffect(() => {
    if (step !== 'analysis') return
    const timer = window.setInterval(() => setStage((current) => Math.min(current + 1, analysisStages.length - 1)), 1900)
    return () => window.clearInterval(timer)
  }, [step])

  const acceptedExtensions = useMemo(() => {
    const supported = health?.supported_extensions?.length ? health.supported_extensions : defaultExtensions
    return supported.map((item) => item.startsWith('.') ? item.toLowerCase() : `.${item.toLowerCase()}`)
  }, [health])

  const updateFile = (side: DocumentSide, file: File) => {
    setError(null)
    if (!acceptedExtensions.includes(extensionOf(file.name))) {
      setError(`Формат ${extensionOf(file.name)} не поддерживается. Выберите ${acceptedExtensions.join(', ')}.`)
      return
    }
    if (file.size > 12 * 1024 * 1024) {
      setError('Файл превышает 12 МБ. Выберите документ меньшего размера.')
      return
    }
    setDocuments((current) => ({ ...current, [side]: { file, text: '', progress: 0, ready: false } }))
    const reader = new FileReader()
    reader.onprogress = (event) => {
      if (!event.lengthComputable) return
      const progress = Math.min(99, Math.round(event.loaded / event.total * 100))
      setDocuments((current) => current[side].file === file ? { ...current, [side]: { ...current[side], progress } } : current)
    }
    reader.onload = () => setDocuments((current) => current[side].file === file ? { ...current, [side]: { ...current[side], progress: 100, ready: true } } : current)
    reader.onerror = () => {
      setDocuments((current) => current[side].file === file ? { ...current, [side]: emptyDocument() } : current)
      setError(`Не удалось прочитать файл ${file.name}. Попробуйте выбрать его ещё раз.`)
    }
    reader.readAsArrayBuffer(file)
  }
  const removeFile = (side: DocumentSide) => setDocuments((current) => ({ ...current, [side]: emptyDocument() }))
  const updateText = (side: DocumentSide, text: string) => setDocuments((current) => ({ ...current, [side]: { ...current[side], text } }))
  const refreshHealth = () => getHealth().then((data) => { setHealth(data); setConnected(true) }).catch(() => setConnected(false))

  const runAnalysis = async (demo: boolean) => {
    setError(null)
    if (!demo && (!documents.before.file && !documents.before.text.trim() || !documents.after.file && !documents.after.text.trim())) {
      setError('Добавьте обе версии документа: файл или текст для каждой колонки.')
      return
    }
    if (!demo && (documents.before.file && !documents.before.ready || documents.after.file && !documents.after.ready)) {
      setError('Подождите, пока файлы подготовятся к анализу.')
      return
    }
    setStage(0)
    setStep('analysis')
    try {
      const aiRequested = useAi && Boolean(health?.ai_available)
      const data = await analyze({
        beforeFile: demo ? null : documents.before.file,
        afterFile: demo ? null : documents.after.file,
        beforeText: demo ? '' : documents.before.text.trim(),
        afterText: demo ? '' : documents.after.text.trim(),
        useAi: aiRequested,
        demo,
      })
      setResult(data)
      setAnalysisUsedAi(aiRequested)
      setStep('results')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось выполнить анализ.')
      setStep('import')
    }
  }

  const download = async (format: 'pdf' | 'docx') => {
    if (!result) return
    setExporting(format)
    setError(null)
    try { await exportReport(result.report_markdown, format) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось скачать заключение.') }
    finally { setExporting(null) }
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
          <div className="sidebar__info sidebar__info--ai"><span className="sidebar__info-icon"><Sparkles size={17} /></span><span><strong>AI-анализ</strong><small>{health?.ai_available ? 'Ключ подключён на сервере' : 'Ключ не задан на сервере'}</small></span></div>
          <span className="sidebar__version">TEREN OI · ВЕРСИЯ 0.1</span>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar"><div className="topbar__trail">Рабочее пространство <span>/</span> <strong>Сравнение редакций</strong></div><div className="topbar__actions">
          <button type="button" className={`connection-pill ${connected ? 'is-connected' : ''}`} onClick={refreshHealth} title="Проверить соединение с API" aria-label={connected ? 'API подключён. Проверить снова' : 'API недоступен. Проверить снова'}><span />{connected ? 'API подключён' : 'API недоступен'}<RefreshCw size={13} /></button>
          <button type="button" className="theme-toggle" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} aria-label={theme === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему'} title={theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}>{theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}</button>
        </div></header>

        <main id="main-content" className="main-content">
          {step === 'import' && <div className="page-intro"><div><span className="eyebrow"><span className="eyebrow__line" />AI-АССИСТЕНТ ДЛЯ АНАЛИЗА ДОКУМЕНТОВ</span><h1>Сравнение редакций<br /><span>без слепых зон.</span></h1><p>Загрузите две версии положения. Teren Oi покажет, что изменилось в структуре и функциях, и приложит цитаты для проверки.</p></div><div className="intro-aside"><span className="intro-aside__icon"><Sparkles size={20} /></span><span>От документа<br />к ясному решению</span></div></div>}
          <Stepper step={step} hasResult={Boolean(result)} goTo={setStep} />
          {error && <div className="error-banner" role="alert"><CircleAlert size={18} /><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Закрыть сообщение"><X size={16} /></button></div>}
          <AnimatePresence mode="wait">
            {step === 'import' && <motion.div key="import" {...pageMotion} transition={{ duration: 0.35 }}>
              <ImportView documents={documents} acceptedExtensions={acceptedExtensions} health={health} useAi={useAi} onAiChange={setUseAi} onFile={updateFile} onRemove={removeFile} onText={updateText} onAnalyze={runAnalysis} />
            </motion.div>}
            {step === 'analysis' && <motion.div key="analysis" {...pageMotion} transition={{ duration: 0.35 }}><AnalysisView stage={stage} reducedMotion={reducedMotion} /></motion.div>}
            {step === 'results' && result && <motion.div key="results" {...pageMotion} transition={{ duration: 0.35 }}><ResultsView result={result} aiUsed={analysisUsedAi} onRestart={() => { setStep('import'); setError(null) }} onExport={(format) => void download(format)} exporting={exporting} /></motion.div>}
          </AnimatePresence>
          <footer className="footer"><span>© {new Date().getFullYear()} Teren Oi</span><span>Анализ документов с опорой на исходные пункты</span></footer>
        </main>
      </div>
    </div>
  )
}
