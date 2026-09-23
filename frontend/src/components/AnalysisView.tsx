import { AnimatePresence, motion } from 'framer-motion'
import { Layers3 } from 'lucide-react'

export const analysisStages = [
  { title: 'Извлекаем структуру документов', detail: 'Находим разделы, пункты и названия подразделений.' },
  { title: 'Сопоставляем две редакции', detail: 'Сравниваем формулировки и связи между пунктами.' },
  { title: 'Проверяем изменения функций', detail: 'Ищем возможные потери, дубли и точки внимания.' },
  { title: 'Готовим заключение', detail: 'Собираем таблицу изменений и цитаты источников.' },
]

export default function AnalysisView({ stage, reducedMotion }: { stage: number; reducedMotion: boolean | null }) {
  return (
    <div className="analysis-view" aria-live="polite">
      <div className="analysis-orb" aria-hidden="true"><Layers3 size={36} strokeWidth={1.4} /></div>
      <span className="eyebrow">АНАЛИЗ В ПРОЦЕССЕ</span>
      <AnimatePresence mode="wait">
        <motion.div key={stage} initial={reducedMotion ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={reducedMotion ? undefined : { opacity: 0, y: -8 }} transition={{ duration: 0.32 }}>
          <h2>{analysisStages[stage].title}</h2>
          <p>{analysisStages[stage].detail}</p>
        </motion.div>
      </AnimatePresence>
      <div className="analysis-progress" aria-label="Анализ выполняется"><span /></div>
      <p className="analysis-hint">Этапы отображаются ориентировочно. Итог появится после ответа сервера.</p>
      <div className="skeleton-grid" aria-hidden="true">
        <div className="skeleton-card"><i /><i /><i /></div>
        <div className="skeleton-card"><i /><i /><i /></div>
        <div className="skeleton-card"><i /><i /><i /></div>
      </div>
    </div>
  )
}
