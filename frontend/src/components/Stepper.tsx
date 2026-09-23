import { Check } from 'lucide-react'
import type { Step } from '../types'

export default function Stepper({ step, hasResult, goTo }: { step: Step; hasResult: boolean; goTo: (step: Step) => void }) {
  const steps: { key: Step; title: string; caption: string }[] = [
    { key: 'import', title: 'Документы', caption: '01 / Загрузка' },
    { key: 'analysis', title: 'Анализ', caption: '02 / Обработка' },
    { key: 'results', title: 'Заключение', caption: '03 / Результат' },
  ]
  const current = steps.findIndex((item) => item.key === step)
  return (
    <nav className="stepper" aria-label="Этапы анализа">
      {steps.map((item, index) => (
        <button
          key={item.key}
          type="button"
          className={`stepper__item ${index === current ? 'is-active' : ''} ${index < current ? 'is-complete' : ''}`}
          disabled={step === 'analysis' || item.key === 'analysis' || (item.key === 'results' && !hasResult)}
          aria-current={index === current ? 'step' : undefined}
          onClick={() => goTo(item.key)}
        >
          <span className="stepper__number">{index < current ? <Check size={15} aria-hidden="true" /> : `0${index + 1}`}</span>
          <span><small>{item.caption}</small><strong>{item.title}</strong></span>
        </button>
      ))}
    </nav>
  )
}
