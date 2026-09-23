import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { Activity, ArrowRight, Check, FileSpreadsheet, FileText, FileType2, ShieldCheck, Sparkles, UploadCloud, X } from 'lucide-react'
import type { DocumentSide, HealthResponse } from '../types'

export type UploadedDocument = { files: File[]; text: string; progress: number; ready: boolean }
export type Documents = Record<DocumentSide, UploadedDocument>

function fileSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

function extensionOf(filename: string): string {
  return `.${filename.split('.').pop()?.toLocaleLowerCase() || ''}`
}

function FileIcon({ filename }: { filename: string }) {
  const extension = extensionOf(filename)
  if (extension === '.xlsx') return <FileSpreadsheet aria-hidden="true" />
  if (extension === '.pdf') return <FileType2 aria-hidden="true" />
  return <FileText aria-hidden="true" />
}

function DocumentInput({
  side, number, title, subtitle, value, accept, onFile, onRemove, onText,
}: {
  side: DocumentSide
  number: string
  title: string
  subtitle: string
  value: UploadedDocument
  accept: string
  onFile: (side: DocumentSide, files: File[]) => void
  onRemove: (side: DocumentSide, index: number) => void
  onText: (side: DocumentSide, text: string) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const reducedMotion = useReducedMotion()
  const drop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault()
    setDragging(false)
    const files = Array.from(event.dataTransfer.files)
    if (files.length) onFile(side, files)
  }
  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || [])
    if (files.length) onFile(side, files)
    event.target.value = ''
  }

  return (
    <section className="document-panel" aria-labelledby={`${side}-heading`}>
      <div className="document-panel__heading">
        <span className="document-panel__number">{number}</span>
        <div>
          <h3 id={`${side}-heading`}>{title}</h3>
          <p>{subtitle}</p>
        </div>
      </div>
      <input className="visually-hidden" ref={inputRef} type="file" multiple accept={accept} onChange={choose} aria-label={`Выбрать файл: ${title}`} />
      {value.files.length < 8 && (
        <button
          type="button"
          className={`dropzone ${dragging ? 'dropzone--active' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => { event.preventDefault(); setDragging(false) }}
          onDrop={drop}
        >
          <span className="dropzone__icon"><UploadCloud size={26} strokeWidth={1.8} aria-hidden="true" /></span>
          <strong>Добавьте файлы комплекта</strong>
          <span>или <span className="dropzone__link">выберите на компьютере</span></span>
          <span className="dropzone__types" aria-hidden="true"><span>DOCX</span><span>PDF</span><span>XLSX</span><span>TXT</span></span>
        </button>
      )}
      {value.files.map((file, index) => (
        <motion.div key={file.name} className="file-card" initial={reducedMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <span className="file-card__icon"><FileIcon filename={file.name} /></span>
          <div className="file-card__body">
            <strong title={file.name}>{file.name}</strong>
            <span>{fileSize(file.size)} · {value.ready ? 'Готов к анализу' : 'Подготовка файла'}</span>
            <div className="file-progress" role="progressbar" aria-label={`Подготовка ${file.name}`} aria-valuenow={value.progress} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${value.progress}%` }} />
            </div>
          </div>
          {value.ready && <motion.span className="file-card__check" initial={reducedMotion ? false : { scale: 0 }} animate={{ scale: 1 }} transition={reducedMotion ? { duration: 0 } : { type: 'spring', stiffness: 400, damping: 20 }}><Check size={16} aria-label="Файл готов" /></motion.span>}
          <button type="button" className="icon-button file-card__remove" aria-label={`Удалить ${file.name}`} onClick={() => onRemove(side, index)}><X size={17} /></button>
        </motion.div>
      ))}
      <p className="field-hint">До 8 файлов. У соответствующих документов до/после должны совпадать имена; внутри комплекта имена уникальны.</p>
      <div className="text-input-head"><span>ИЛИ ВСТАВЬТЕ ТЕКСТ</span><span>Для быстрой проверки</span></div>
      <label className="visually-hidden" htmlFor={`${side}-text`}>Текст: {title}</label>
      <textarea
        id={`${side}-text`}
        rows={5}
        placeholder={side === 'before' ? 'Вставьте текст исходного положения…' : 'Вставьте текст новой редакции…'}
        value={value.text}
        onChange={(event) => onText(side, event.target.value)}
        disabled={Boolean(value.files.length)}
        aria-describedby={value.files.length ? `${side}-text-hint` : undefined}
      />
      {value.files.length > 0 && <p id={`${side}-text-hint`} className="field-hint">Чтобы вставить текст, сначала удалите файлы.</p>}
    </section>
  )
}


export default function ImportView({ documents, acceptedExtensions, health, connected, useAi, onAiChange: setUseAi, onFile: updateFile, onRemove: removeFile, onText: updateText, onAnalyze: runAnalysis, onSwap, onClear }: {
  documents: Documents
  onSwap: () => void
  onClear: () => void
  acceptedExtensions: string[]
  health: HealthResponse | null
  connected: boolean
  useAi: boolean
  onAiChange: (value: boolean) => void
  onFile: (side: DocumentSide, files: File[]) => void
  onRemove: (side: DocumentSide, index: number) => void
  onText: (side: DocumentSide, text: string) => void
  onAnalyze: (demo: boolean) => Promise<void>
}) {
  const beforeReady = documents.before.files.length ? documents.before.ready : Boolean(documents.before.text.trim())
  const afterReady = documents.after.files.length ? documents.after.ready : Boolean(documents.after.text.trim())
  const ready = beforeReady && afterReady
  const aiAvailable = connected && Boolean(health?.ai_available)
  return <>
              <div className="section-title-row"><div><span className="eyebrow">ШАГ 01 / ИСХОДНЫЕ ДАННЫЕ</span><h2>Добавьте документы для сравнения</h2><p>Word, PDF с текстовым слоем, Excel или TXT, до 8 файлов на редакцию и 12 МБ на файл.</p></div></div>
              <div className="demo-callout"><div><strong>Посмотрите, как это работает</strong><p>Демо за один клик: две редакции, изменения и цитаты. Выбранный ниже режим ИИ применяется и к демо.</p></div><button type="button" className="demo-button" onClick={() => void runAnalysis(true)}><Sparkles size={18} aria-hidden="true" /><span>Загрузить контрольный демо-комплект Казахтелеком</span><ArrowRight size={17} aria-hidden="true" /></button></div>
              <div className="product-actions import-actions"><span className="panel-intro">Слева — старая редакция, справа — новая.</span><button className="button button--secondary" onClick={onSwap} disabled={Boolean((documents.before.files.length && !documents.before.ready) || (documents.after.files.length && !documents.after.ready))}>Поменять редакции местами</button><button className="button button--secondary" onClick={onClear}>Очистить ввод</button></div>
              <div className="document-grid">
                <DocumentInput side="before" number="01" title="До изменений" subtitle="Исходная редакция документа" value={documents.before} accept={acceptedExtensions.join(',')} onFile={updateFile} onRemove={removeFile} onText={updateText} />
                <DocumentInput side="after" number="02" title="После изменений" subtitle="Новая редакция документа" value={documents.after} accept={acceptedExtensions.join(',')} onFile={updateFile} onRemove={removeFile} onText={updateText} />
              </div>
              <div className="analysis-toolbar">
                <div className="analysis-toolbar__controls">
                  <div className={`ai-option ${useAi ? 'is-enabled' : ''}`}>
                    <label className={`ai-switch ${!aiAvailable ? 'is-disabled' : ''}`}>
                      <input type="checkbox" role="switch" aria-describedby="ai-mode-description" checked={useAi} disabled={!aiAvailable && !useAi} onChange={(event) => setUseAi(event.target.checked)} />
                      <span className="ai-switch__track" /><span>AI-анализ <small>{!connected ? 'Сервер недоступен' : health?.ai_available ? `${useAi ? 'Включён' : 'Выключен'} · ${health.model}` : 'Нужен API-ключ на сервере'}</small></span>
                    </label>
                    <p id="ai-mode-description">{useAi ? 'Текст документов будет отправлен в OpenAI API для смысловой проверки.' : 'Сейчас выбрано локальное сравнение. Включите ИИ для проверки смысла изменений.'}</p>
                  </div>
                  <div className="analysis-action">
                    <button type="button" className="button button--primary" disabled={!ready} aria-describedby="analyze-hint" onClick={() => void runAnalysis(false)}><Activity size={18} aria-hidden="true" /><span>Запустить анализ структуры</span><ArrowRight size={17} aria-hidden="true" /></button>
                    <p id="analyze-hint">{ready ? 'Обе редакции готовы к сравнению' : 'Добавьте обе редакции, чтобы начать'}</p>
                  </div>
                </div>
                <div className="analysis-toolbar__note"><ShieldCheck size={18} aria-hidden="true" /><span>Демо-комплект синтетический и не является официальным документом Казахтелекома.</span></div>
              </div>
  </>
}
