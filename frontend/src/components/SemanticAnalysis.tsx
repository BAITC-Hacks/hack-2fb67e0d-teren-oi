import type { AnalysisResponse, Citation } from '../types'

const labels: Record<string, string> = {
  created: 'Создано', retained: 'Сохранено', reorganized: 'Преобразовано', removed: 'Удалено',
  changed: 'Изменено', reassigned: 'Передано', lost: 'Возможная потеря',
}

function Evidence({ citations }: { citations: Citation[] }) {
  return <details className="semantic-evidence"><summary>Источники · {citations.length}</summary>
    {citations.map((citation, index) => <blockquote key={index}>
      <small>{citation.document_label} · {citation.clause_id} · {citation.source}{citation.location && ` · ${citation.location}`}</small>
      <p>«{citation.quote}»</p>
    </blockquote>)}
  </details>
}

export default function SemanticAnalysis({ result }: { result: AnalysisResponse }) {
  const departments = result.department_changes || []
  const mappings = result.function_mappings || []
  return <section className="surface semantic-panel" id="semantic" aria-labelledby="semantic-heading">
    <div className="section-heading"><div><span className="eyebrow">СМЫСЛОВОЙ АНАЛИЗ</span><h3 id="semantic-heading">Подразделения и функции · ИИ</h3></div></div>
    <p className="panel-intro">Оценки модели по проверенным цитатам. Сохранение функции по смыслу может сопровождаться изменением текста в точной карте пунктов.</p>
    {result.ai.status !== 'succeeded' ? <div className="empty-state">Смысловая проверка не выполнена. Точное сравнение доступно ниже; для карты функций запустите анализ с ИИ.</div> : <>
      {departments.length > 0 && <><h4>Оценка подразделений</h4><div className="semantic-departments">
        {departments.map((item, index) => <article className="semantic-department" key={index}>
          <span className="badge badge--blue">{labels[item.status]}</span>
          <p><strong>{item.name_before || 'Не указано'} → {item.name_after || 'Не указано'}</strong></p>
          <Evidence citations={item.citations} />
        </article>)}
      </div></>}
      <h4>Сопоставление функций</h4>
      {mappings.length ? <><p className="table-scroll-hint" id="semantic-scroll-hint">На небольшом экране таблица прокручивается вправо. Раскройте источники для проверки вывода.</p>
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Смысловая карта функций" aria-describedby="semantic-scroll-hint">
          <table className="mapping-table semantic-table"><thead><tr><th scope="col">Функция до</th><th scope="col">Функция после</th><th scope="col">Оценка ИИ и источники</th></tr></thead>
            <tbody>{mappings.map((item, index) => <tr key={index}>
              <td><p>{item.old_function}</p><small>Подразделение: {item.old_department || 'Не указано'}</small></td>
              <td><p>{item.new_function || 'Соответствие не указано'}</p><small>Подразделение: {item.new_department || 'Не указано'}</small></td>
              <td><span className={`badge badge--${item.status === 'lost' ? 'red' : item.status === 'retained' ? 'green' : 'amber'}`}>{labels[item.status]}</span><Evidence citations={item.citations} /></td>
            </tr>)}</tbody>
          </table>
        </div></> : <div className="empty-state">ИИ не вернул сопоставлений функций с достаточными доказательствами. Это не подтверждает отсутствие изменений или потерь.</div>}
    </>}
  </section>
}
