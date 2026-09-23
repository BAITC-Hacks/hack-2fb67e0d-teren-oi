import { ArrowDownRight, Sparkles } from 'lucide-react'
import type { AiAnalysis, AnalysisResponse } from '../types'

export const aiStatusLabels: Record<AiAnalysis['status'], string> = {
  disabled: 'ИИ выключен',
  unavailable: 'ИИ недоступен',
  succeeded: 'AI-проверка выполнена',
  failed: 'Ошибка AI-проверки',
  skipped: 'AI-проверка пропущена',
}

const inactiveDescriptions: Record<Exclude<AiAnalysis['status'], 'succeeded'>, string> = {
  disabled: 'Выполнено локальное сравнение. Для проверки смысла изменений включите «AI-анализ» перед следующим запуском.',
  unavailable: 'Ключ OpenAI недоступен на сервере. Локальное сравнение готово; настройте ключ и повторите запуск с ИИ.',
  failed: 'ИИ не завершил проверку. Локальное сравнение доступно ниже. Можно вернуться к документам и повторить запрос.',
  skipped: 'Вызов ИИ не выполнялся. Используйте карту изменений и обратите внимание на ограничения чтения документов.',
}

export default function AiSummary({ result, onInspect }: { result: AnalysisResponse; onInspect: (id: string) => void }) {
  const { ai } = result
  const succeeded = ai.status === 'succeeded'
  const highlights = ai.finding_ids.map((id) => result.findings.find((finding) => finding.id === id && finding.origin === 'ai')).filter((finding) => finding !== undefined).slice(0, 3)
  const unnumberedOmissions = result.coverage.before.unnumbered_blocks + result.coverage.after.unnumbered_blocks
  const partial = ai.coverage.omitted_clauses > 0 || ai.coverage.truncated_clauses > 0 || unnumberedOmissions > 0

  return (
    <section className={`ai-summary ${succeeded ? '' : 'ai-summary--inactive'}`} aria-labelledby="ai-summary-heading">
      <div className="ai-summary__icon"><Sparkles size={20} aria-hidden="true" /></div>
      <div className="ai-summary__body">
        <div className="ai-summary__heading">
          <div><span className="eyebrow">КОРОТКО О ГЛАВНОМ</span><h3 id="ai-summary-heading">{succeeded ? 'Ответ ИИ' : 'Итог сравнения'}</h3></div>
          <span className={`ai-summary__status ${succeeded ? 'is-ready' : ''}`}>{aiStatusLabels[ai.status]}</span>
        </div>
        <p className="ai-summary__lead">{succeeded
          ? (ai.summary_origin === 'verified_findings' && ai.summary) || 'ИИ не сформировал замечаний с подтверждёнными цитатами в проверенной части. Это не гарантирует отсутствие рисков.'
          : inactiveDescriptions[ai.status as Exclude<AiAnalysis['status'], 'succeeded'>]}</p>
        {ai.error && <p className="ai-summary__error" role="status">{ai.error}</p>}
        {succeeded && <>
          <p className="ai-summary__provenance">{ai.model} · Сводка собрана сервером из выводов модели с проверенными цитатами. Смысл выводов требует оценки эксперта.</p>
          {highlights.length > 0 && <ul className="ai-summary__highlights">{highlights.map((finding) => <li key={finding.id}>
            <button type="button" onClick={() => onInspect(finding.id)} className="ai-summary__finding"><span>{finding.title}</span><ArrowDownRight size={17} aria-hidden="true" /><small>{finding.explanation}</small><span className="ai-summary__source-link">Открыть цитаты · {finding.citations.length}</span></button>
          </li>)}</ul>}
          <p className={`ai-coverage ${partial ? 'ai-coverage--partial' : ''}`}>
            Передано ИИ: <strong>{ai.coverage.included_clauses} из {ai.coverage.total_clauses} фрагментов</strong>
            {ai.coverage.omitted_clauses > 0 && ` · не передано ${ai.coverage.omitted_clauses}`}
            {ai.coverage.truncated_clauses > 0 && ` · сокращено ${ai.coverage.truncated_clauses}`}
            {unnumberedOmissions > 0 && ` · отдельно исключено ненумерованных блоков: ${unnumberedOmissions}`}
            {partial && '. Выводы относятся только к переданному тексту.'}
          </p>
          <p className="ai-summary__provenance">Одинаковый текст в обеих редакциях учитывается один раз; для изменённых пунктов учитываются обе версии.</p>
          {ai.rejected_findings > 0 && <p className="ai-summary__provenance">Не показано выводов без подтверждённых источников: {ai.rejected_findings}.</p>}
        </>}
      </div>
    </section>
  )
}
