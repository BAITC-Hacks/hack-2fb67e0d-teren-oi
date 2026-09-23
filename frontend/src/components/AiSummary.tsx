import { ArrowDownRight, CheckCircle2, Sparkles } from 'lucide-react'
import type { AnalysisResponse } from '../types'

export default function AiSummary({ result, aiUsed }: { result: AnalysisResponse; aiUsed: boolean }) {
  const highlights = result.findings.slice(0, 3)
  const total = result.findings.length

  return (
    <section className={`ai-summary ${aiUsed ? '' : 'ai-summary--inactive'}`} aria-labelledby="ai-summary-heading">
      <div className="ai-summary__icon"><Sparkles size={20} aria-hidden="true" /></div>
      <div className="ai-summary__body">
        <div className="ai-summary__heading">
          <div><span className="eyebrow">КОРОТКО О ГЛАВНОМ</span><h3 id="ai-summary-heading">Ответ ИИ</h3></div>
          <span className={`ai-summary__status ${aiUsed ? 'is-ready' : ''}`}>{aiUsed ? 'AI-проверка выполнена' : result.ai_error ? 'AI-проверка не завершилась' : 'AI-проверка выключена'}</span>
        </div>
        {aiUsed ? <>
          <p className="ai-summary__lead">{total
            ? `Найдено ${total} ${total === 1 ? 'замечание' : total < 5 ? 'замечания' : 'замечаний'}. Проверьте их по цитатам из документов перед принятием решения.`
            : 'Дополнительных замечаний не найдено. Проверьте карту изменений перед принятием решения.'}</p>
          {highlights.length > 0 && <ul className="ai-summary__highlights">{highlights.map((finding, index) => <li key={`${finding.kind}-${index}`}><span className="ai-summary__bullet" /><span>{finding.title}</span></li>)}</ul>}
          {total > 0 && <a className="ai-summary__link" href="#findings">Посмотреть выводы и источники <ArrowDownRight size={16} aria-hidden="true" /></a>}
        </> : <p className="ai-summary__lead">{result.ai_error
          ? 'Сравнение документов готово, но ИИ не ответил. Причина показана выше; выводы ниже основаны на локальном сопоставлении.'
          : 'Этот анализ выполнен без ИИ. Чтобы получить смысловые выводы, включите «AI-анализ» перед запуском следующего сравнения.'}</p>}
      </div>
      {aiUsed && total === 0 && <CheckCircle2 className="ai-summary__clear-icon" size={23} aria-hidden="true" />}
    </section>
  )
}
