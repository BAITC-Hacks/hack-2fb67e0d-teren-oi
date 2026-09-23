import { useEffect, useState } from 'react'
import { Clock3, Layers3 } from 'lucide-react'

export default function AnalysisView({ useAi, model }: { useAi: boolean; model?: string }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <section className="analysis-view" aria-labelledby="processing-heading" aria-busy="true">
      <div className="analysis-orb" aria-hidden="true"><Layers3 size={36} strokeWidth={1.4} /></div>
      <span className="eyebrow">ЗАПРОС ОТПРАВЛЕН</span>
      <h2 id="processing-heading">Документы на проверке</h2>
      <p className="analysis-description" role="status">Сервер сопоставляет редакции{useAi ? ` с AI-проверкой${model ? ` (${model})` : ''}` : ' без обращения к ИИ'}.</p>
      <div className="analysis-progress" aria-hidden="true"><span /></div>
      <p className="analysis-elapsed"><Clock3 size={15} aria-hidden="true" /> <span role="timer" aria-label="Время ожидания">{seconds} с</span></p>
      <p className="analysis-hint">Ждём итоговый ответ сервера. Время зависит от размера документов{useAi ? ' и ответа модели' : ''}. Ваши файлы и текст сохранены на этой странице.</p>
      {seconds >= 30 && <p className="analysis-hint" role="status">Проверка ещё выполняется. Повторно отправлять документы не нужно.</p>}
      <div className="skeleton-grid" aria-hidden="true">
        {[0, 1, 2].map((item) => <div className="skeleton-card" key={item}><i /><i /><i /></div>)}
      </div>
    </section>
  )
}
