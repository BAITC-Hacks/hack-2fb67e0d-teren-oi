from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from teren_oi.analyzer import AnalysisError, analyze_with_metadata  # noqa: E402
from teren_oi.diff import compare_documents  # noqa: E402
from teren_oi.docx_reader import DocumentReadError  # noqa: E402
from teren_oi.models import Clause, Finding, SourceDocument  # noqa: E402
from teren_oi.parsers import TextBlock, parse_blocks  # noqa: E402
from teren_oi.readers import SUPPORTED_EXTENSIONS, read_document  # noqa: E402
from teren_oi.report import report_as_json, report_as_markdown  # noqa: E402

load_dotenv(ROOT / ".env")

DEMO_BEFORE = """2.1 Департамент клиентской аналитики: анализирует причины повторных обращений и ежемесячно передаёт руководству сводку по темам.
2.2 Центр контроля качества: выборочно проверяет записи разговоров, фиксирует нарушения стандарта и назначает срок исправления.
2.3 Региональные подразделения: обрабатывают обращения клиентов, устраняют причину и закрывают заявку после подтверждения результата.
2.4 Группа обратной связи: собирает отзывы после закрытия обращений и передаёт замечания ответственному подразделению.
"""

DEMO_AFTER = """2.1 Департамент клиентской аналитики: анализирует причины повторных обращений и ежемесячно передаёт руководству сводку по темам.
2.3 Региональные подразделения: обрабатывают обращения клиентов и устраняют причину; закрытие заявки выполняется после проверки результата.
2.4 Департамент клиентского опыта: анализирует обращения и отзывы клиентов, готовит сводный отчёт и предлагает улучшения сервиса.
2.5 Группа обратной связи: собирает отзывы после закрытия обращений и передаёт замечания ответственному подразделению.
"""

DEMO_NOTICE = (
    "Демо-комплект синтетический: это иллюстративный сценарий для проверки интерфейса, "
    "а не официальные документы или сведения АО «Казахтелеком»."
)
UPLOAD_TYPES = sorted(extension.lstrip(".") for extension in SUPPORTED_EXTENSIONS)

UNIT_RE = re.compile(
    r"\b((?:департамент|управление|отдел|центр|служба|группа|дирекция)\s+[^:;,.\n]{2,90})",
    re.IGNORECASE,
)


class InputError(ValueError):
    """A supported file could not be converted into comparable document text."""


def comparable_document(document: SourceDocument) -> SourceDocument:
    """Give unnumbered-only text transparent IDs without inventing source positions."""
    if document.clauses:
        return document
    if not document.unnumbered_blocks:
        raise InputError(f"В «{document.name}» нет текста для сравнения.")
    clauses = tuple(
        Clause(
            f"Блок {number}",
            text,
            document.name,
            f"ненумерованный фрагмент {number}; точная позиция недоступна",
        )
        for number, text in enumerate(document.unnumbered_blocks, start=1)
    )
    return SourceDocument(document.name, clauses)


def source_from_text(text: str, name: str) -> SourceDocument:
    """Parse pasted text with the same clause rules used by uploaded files."""
    blocks = [
        TextBlock(line, f"line {number}")
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    return comparable_document(parse_blocks(blocks, name))


def read_uploaded(uploaded_file) -> SourceDocument:
    if uploaded_file.size > 12 * 1024 * 1024:
        raise InputError("Файл превышает 12 МБ. Разделите документ на части.")
    return comparable_document(read_document(uploaded_file.getvalue(), uploaded_file.name))


def source_rows(document: SourceDocument) -> list[dict[str, str]]:
    """Present extracted clauses alongside their exact available source locations."""
    return [
        {"Пункт": clause.clause_id, "Текст": clause.text,
         "Источник": clause.source, "Место": clause.location}
        for clause in document.clauses
    ]


def citation_source(comparison, citation) -> str:
    document = (comparison.old_document if citation.document_label == "до"
                else comparison.new_document)
    for clause in document.clauses:
        if clause.clause_id == citation.clause_id and citation.quote in clause.text:
            return f"{clause.source} · {clause.location}"
    return "точное местоположение не найдено"


def render_unit_cards(comparison) -> None:
    buckets: dict[str, dict[str, str]] = {"created": {}, "reorganized": {}, "retained": {}, "removed": {}}

    def names(text: str) -> set[str]:
        return {re.sub(r"\s+", " ", match.group(1)).strip(" -–—") for match in UNIT_RE.finditer(text)}

    # Classify each normalized name once across the complete extracted document.
    old, new = {}, {}
    for document, target in ((comparison.old_document, old), (comparison.new_document, new)):
        for clause in document.clauses:
            for name in names(clause.text):
                label, texts = target.setdefault(name.casefold(), (name, set()))
                texts.add(" ".join(clause.text.casefold().split()))
    for key in sorted(old.keys() | new.keys()):
        name = (new.get(key) or old[key])[0]
        status = ("created" if key not in old else "removed" if key not in new
                  else "retained" if old[key][1] == new[key][1] else "reorganized")
        buckets[status][key] = name

    labels = (("Преобразовано", "reorganized"), ("Создано", "created"),
              ("Сохранено", "retained"), ("Удалённые названия", "removed"))
    cols = st.columns(4)
    for col, (label, key) in zip(cols, labels):
        entries = list(buckets[key].values())
        with col:
            st.metric(label, len(entries))
            if entries:
                for entry in entries[:8]:
                    st.markdown(f"- {entry}")
                if len(entries) > 8:
                    st.caption(f"И ещё {len(entries) - 8}…")
            else:
                st.caption("Не обнаружено")
    st.caption("Названия подразделений извлекаются эвристически из всех извлечённых пунктов; проверьте их по первоисточнику.")


def risk_label(confidence: str) -> str:
    return f"ТРЕБУЕТ ПРОВЕРКИ · оценка модели: {confidence} (не вероятность и не тяжесть риска)"


st.set_page_config(page_title="Tereñ oi · Анализ изменений", page_icon="◈", layout="wide")
st.markdown("""
<style>
    :root { --ink: #17243a; --muted: #46566a; --paper: #f4f7fb; --line: #dbe3ec; --navy: #101f38; --teal: #087e8b; --teal-dark:#075e68; }
    html { scroll-behavior:smooth; }
    .stApp, [data-testid="stAppViewContainer"] { background: var(--paper); color: var(--ink); }
    header[data-testid="stHeader"] { background:var(--paper) !important; }
    [data-testid="stMain"] { color: var(--ink); }
    [data-testid="stMain"] h1, [data-testid="stMain"] h2,
    [data-testid="stMain"] h3, [data-testid="stMain"] h4 { color: var(--ink) !important; letter-spacing: -.02em; }
    [data-testid="stMain"] p, [data-testid="stMain"] li,
    [data-testid="stMain"] label, [data-testid="stMain"] [data-testid="stWidgetLabel"] { color: #34445a; }
    [data-testid="stMain"] [data-testid="stCaptionContainer"] p { color: var(--muted) !important; }
    [data-testid="stSidebar"] { background: var(--navy); }
    [data-testid="stSidebar"] * { color: #e8f0fa; }
    .block-container { max-width: 1380px; padding: 4rem 2.25rem 4rem; }
    .brandline { display:flex; align-items:center; gap:.7rem; color:#53647a; font-size:.78rem; font-weight:700; letter-spacing:.13em; text-transform:uppercase; margin-bottom:.35rem; }
    .brandmark { display:inline-flex; width:1.7rem; height:1.7rem; align-items:center; justify-content:center; background:var(--navy); color:#62d5dc; font-size:1rem; border-radius:6px; }
    .hero { background: var(--navy); color: #f6fbff; padding: 1.5rem 1.8rem; border-left: 4px solid #42cad2; border-radius:0 8px 8px 0; margin:.5rem 0 1.3rem; box-shadow:0 8px 24px rgba(16,31,56,.08); }
    .hero h1 { color:#fff !important; font-size:2rem; margin:0 0 .3rem; }
    .hero p { color:#c7d3e1 !important; margin:0; font-size:1rem; }
    .demo-note { border: 1px solid #e6cf8a; border-left:4px solid #d5a323; background: #fff8e5; color: #574100; padding: .8rem 1rem; border-radius:6px; }
    div[data-testid="stMetric"] { background: #fff; border: 1px solid var(--line); padding: .8rem 1rem; border-radius:8px; transition:border-color .18s ease, box-shadow .18s ease; }
    div[data-testid="stMetric"]:hover { border-color:#b8ccd8; box-shadow:0 5px 16px rgba(16,31,56,.06); }
    div[data-testid="stForm"] { background:#fff; border:1px solid var(--line); padding:1.25rem; border-radius:8px; transition:border-color .18s ease, box-shadow .18s ease; }
    div[data-testid="stForm"]:focus-within { border-color:#98cbd0; box-shadow:0 0 0 3px rgba(8,126,139,.08); }
    div[data-testid="stMetric"] label, div[data-testid="stMetric"] [data-testid="stMetricValue"] { color:var(--ink) !important; }
    [data-testid="stFileUploaderDropzone"] { background:#fff; border:1px dashed #aebdcd; border-radius:7px; transition:border-color .18s ease, background-color .18s ease; }
    [data-testid="stFileUploaderDropzone"]:hover { border-color:var(--teal); background:#f8fdfd; }
    [data-testid="stFileUploaderDropzone"] * { color:#33445b !important; }
    [data-testid="stTextArea"] textarea { background:#fff; color:var(--ink); border-color:#bdc9d6; }
    button[kind^="primary"] { background:var(--teal) !important; border-color:var(--teal) !important; color:#fff !important; transition:background-color .16s ease, border-color .16s ease, box-shadow .16s ease; }
    button[kind^="primary"]:hover { background:var(--teal-dark) !important; border-color:var(--teal-dark) !important; box-shadow:0 4px 12px rgba(8,126,139,.18); }
    [data-testid="stMain"] button[kind^="primary"] p { color:#fff !important; }
    button[kind="secondary"] { background:#fff !important; border-color:#bdc9d6 !important; color:#22354c !important; transition:border-color .16s ease, background-color .16s ease; }
    button[kind="secondary"] div { color:#22354c !important; }
    [data-testid="stRadioOption"] > div > div:first-child { border-color:#96a7ba !important; }
    [data-testid="stRadioOption"][data-selected="true"] > div > div:first-child { background:var(--teal) !important; border-color:var(--teal) !important; }
    [data-testid="stTabs"] button[role="tab"] { color:#43536a; transition:color .16s ease, border-color .16s ease; }
    [data-testid="stTabs"] button[aria-selected="true"] { color:#076e7a; border-bottom-color:#087e8b; }
    [data-testid="stAlert"] p { color:inherit !important; }
    [data-testid="stSidebar"] [data-testid="stAlert"] { background:#1a3150 !important; border:1px solid #506986; border-left:3px solid #d5a323; border-radius:6px; }
    [data-testid="stSidebar"] [data-testid="stAlert"] p { color:#f6d992 !important; }
    button:focus-visible, textarea:focus-visible, input:focus-visible { outline:3px solid #39aeb7 !important; outline-offset:2px; }
    @keyframes enter-soft { from { opacity:0; transform:translateY(7px); } to { opacity:1; transform:translateY(0); } }
    [data-testid="stMain"] .hero { animation:enter-soft .38s cubic-bezier(.2,.7,.2,1) both; }
    [data-testid="stMain"] .demo-note { animation:enter-soft .28s cubic-bezier(.2,.7,.2,1) both; }
    hr { border-color:var(--line); }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior:auto !important; animation-duration:.01ms !important; animation-iteration-count:1 !important; transition-duration:.01ms !important; } }
    @media (max-width: 700px) { .block-container { padding:3rem 1rem 3rem; } div[data-testid="stForm"] { padding:.9rem; } .hero { padding:1.2rem; } .hero h1 { font-size:1.6rem; } }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## ◈ Tereñ oi")
    st.caption("Сравнение положений и функций между редакциями")
    st.divider()
    if os.getenv("OPENAI_API_KEY"):
        st.success("AI-анализ подключён")
        st.caption(f"Модель: {os.getenv('OPENAI_MODEL', 'gpt-5.6-terra')}")
    else:
        st.warning("API-ключ не задан")
        st.caption("Точный diff работает без ключа. Добавьте OPENAI_API_KEY в .env для AI-выводов.")
    st.divider()
    st.markdown("**Как работает**")
    st.caption("Сопоставляем пункты, показываем точные изменения и при наличии ключа просим AI оценить контекст. Цитаты проверяются приложением.")

st.markdown("<div class='brandline'><span class='brandmark'>◈</span> Tereñ oi · Document intelligence</div>", unsafe_allow_html=True)
st.markdown("<div class='hero'><h1>Сравнение редакций документов</h1><p>Найдите изменения в обязанностях и проверьте каждый вывод по исходному пункту.</p></div>", unsafe_allow_html=True)
st.subheader("Проверка в 1 клик")
st.caption("Запустите демонстрационный сценарий без подготовки файлов или загрузите свои редакции ниже.")
demo_clicked = st.button("Загрузить контрольный демо-комплект Казахтелеком", type="primary", width="stretch",
                         help="Подставляет безопасный учебный пример и сразу выполняет сравнение.")
if demo_clicked:
    st.session_state["before_mode"] = "Текст"
    st.session_state["after_mode"] = "Текст"
    st.session_state["before_text"] = DEMO_BEFORE
    st.session_state["after_text"] = DEMO_AFTER
    st.session_state["demo_active"] = True
    st.session_state["demo_notice"] = DEMO_NOTICE

if st.session_state.get("demo_notice"):
    st.markdown(f"<div class='demo-note'>{st.session_state['demo_notice']}</div>", unsafe_allow_html=True)
    st.write("")

st.divider()
st.subheader("Исходные документы")
st.caption("Перетащите файлы в зону загрузки или переключитесь на текст, чтобы вставить и отредактировать содержимое.")
with st.form("comparison_inputs", clear_on_submit=False):
    before_col, after_col = st.columns(2)
    with before_col:
        st.markdown("### 01 · До изменений")
        before_mode = st.radio("Источник старой редакции", ["Файл", "Текст"], horizontal=True, key="before_mode")
        if before_mode == "Файл":
            before_file = st.file_uploader("Перетащите или выберите DOCX, PDF, TXT, XLSX", type=UPLOAD_TYPES, key="before_file")
            before_text = ""
        else:
            st.session_state.setdefault("before_text", "")
            before_text = st.text_area("Вставьте или отредактируйте старый текст", key="before_text", height=220,
                                       placeholder="Каждый пункт желательно начинать с номера, например 2.1")
            before_file = None
    with after_col:
        st.markdown("### 02 · После изменений")
        after_mode = st.radio("Источник новой редакции", ["Файл", "Текст"], horizontal=True, key="after_mode")
        if after_mode == "Файл":
            after_file = st.file_uploader("Перетащите или выберите DOCX, PDF, TXT, XLSX", type=UPLOAD_TYPES, key="after_file")
            after_text = ""
        else:
            st.session_state.setdefault("after_text", "")
            after_text = st.text_area("Вставьте или отредактируйте новый текст", key="after_text", height=220,
                                      placeholder="Каждый пункт желательно начинать с номера, например 2.1")
            after_file = None
    use_ai = st.checkbox("Дополнить точный diff анализом AI (потери, дублирование, ответственность)",
                         value=bool(os.getenv("OPENAI_API_KEY")), key="use_ai")
    compare_clicked = st.form_submit_button("Сравнить редакции", type="primary", width="stretch")

if use_ai and not os.getenv("OPENAI_API_KEY"):
    st.info("AI-ключ не найден. Точный diff доступен; AI-вкладки покажут подсказку по настройке ключа.")

if compare_clicked or demo_clicked:
    st.session_state.pop("comparison", None)
    try:
        if before_mode == "Файл":
            if not before_file:
                raise InputError("Выберите файл старой редакции.")
            before_doc = read_uploaded(before_file)
        else:
            before_doc = source_from_text(before_text, "Старая редакция")
        if after_mode == "Файл":
            if not after_file:
                raise InputError("Выберите файл новой редакции.")
            after_doc = read_uploaded(after_file)
        else:
            after_doc = source_from_text(after_text, "Новая редакция")

        result = compare_documents(before_doc, after_doc)
        findings: list[Finding] = []
        ai_error = None
        ai_status = "disabled" if not use_ai else "unavailable"
        ai_coverage = {}
        if use_ai and os.getenv("OPENAI_API_KEY"):
            with st.spinner("AI анализирует изменённые пункты и контекст сохранённых функций…"):
                try:
                    analysis = analyze_with_metadata(result, os.getenv("OPENAI_MODEL", "gpt-5.6-terra"))
                    findings = analysis.findings
                    ai_status = "completed" if analysis.called else "skipped"
                    ai_coverage = analysis.coverage
                except AnalysisError as exc:
                    ai_status = "failed"
                    ai_error = str(exc)
        st.session_state["comparison"] = result
        st.session_state["findings"] = findings
        st.session_state["ai_error"] = ai_error
        st.session_state["ai_status"] = ai_status
        st.session_state["ai_coverage"] = ai_coverage
        st.session_state["source_names"] = (before_doc.name, after_doc.name)
    except (InputError, DocumentReadError) as exc:
        st.error(str(exc))

comparison = st.session_state.get("comparison")
if comparison:
    old_name, new_name = st.session_state.get("source_names", (comparison.old_document.name, comparison.new_document.name))
    findings: list[Finding] = st.session_state.get("findings", [])
    ai_status = st.session_state.get("ai_status", "unavailable")
    ai_status_text = {
        "disabled": "ИИ выключен для этого результата. Выполнено локальное сравнение.",
        "unavailable": "ИИ не запущен: API-ключ недоступен. Выполнено локальное сравнение.",
        "skipped": "Модель не вызывалась: нет подходящих пунктов для проверки.",
        "failed": "ИИ-проверка завершилась ошибкой. Выполнено локальное сравнение.",
        "completed": "ИИ-проверка выполнена; проверенные цитаты приведены ниже.",
    }.get(ai_status, "Статус ИИ неизвестен. Повторите анализ.")
    st.info(ai_status_text)
    ai_coverage = st.session_state.get("ai_coverage", {})
    if ai_coverage:
        st.caption(f"Охват ИИ: {ai_coverage.get('included_clauses', 0)} из {ai_coverage.get('total_clauses', 0)} фрагментов; усечено: {ai_coverage.get('truncated_clauses', 0)}.")
    metrics = st.columns(4)
    for col, label, value in zip(metrics, ("Добавлено", "Удалено", "Изменено", "Совпадает"),
                                 (len(comparison.added), len(comparison.removed), len(comparison.modified), len(comparison.unchanged))):
        col.metric(label, value)
    if st.session_state.get("ai_error"):
        st.warning(f"AI-анализ не завершился: {st.session_state['ai_error']} Точный diff показан ниже.")

    with st.expander("Исходные пункты и места в документах"):
        for document, label in ((comparison.old_document, "До изменений"),
                                (comparison.new_document, "После изменений")):
            st.markdown(f"#### {label} · {document.name}")
            st.dataframe(source_rows(document), width="stretch", hide_index=True)
            if document.unnumbered_blocks:
                st.warning(
                    f"{len(document.unnumbered_blocks)} ненумерованных фрагментов не вошли "
                    "в сравнение пунктов. Просмотрите их вручную ниже."
                )
                st.dataframe(
                    [{"Фрагмент": number, "Текст": text}
                     for number, text in enumerate(document.unnumbered_blocks, start=1)],
                    width="stretch", hide_index=True,
                )

    status_tab, loss_tab, duplicate_tab, mapping_tab, export_tab = st.tabs(
        ["Подразделения", "Потери функций", "Дубли и конфликты", "Матрица маппинга", "Экспорт заключения"]
    )

    with status_tab:
        st.subheader("Статусы подразделений")
        render_unit_cards(comparison)
        with st.expander("Точные изменения по пунктам"):
            for title, changes in (("Создано", comparison.added), ("Изменено", comparison.modified),
                                   ("Сохранено без изменений", comparison.unchanged), ("Удалено", comparison.removed)):
                st.markdown(f"**{title} — {len(changes)}**")
                for item in changes:
                    st.markdown(f"**Пункт {item.clause_id}**")
                    if item.before:
                        st.write(f"До: {item.before.text}")
                        st.caption(f"{item.before.source} · {item.before.location}")
                    if item.after:
                        st.write(f"После: {item.after.text}")
                        st.caption(f"{item.after.source} · {item.after.location}")

    with loss_tab:
        st.subheader("Сигналы о возможной потере функций")
        loss_findings = [finding for finding in findings if finding.kind == "потенциальная потеря функции"]
        for change in comparison.removed:
            if change.before:
                st.error(f"ПУНКТ УДАЛЁН · требуется проверить перенос функции · {change.clause_id}\n\n{change.before.text}")
                st.caption(f"Источник: {change.before.source} · {change.before.location}")
        for finding in loss_findings:
            st.error(f"{risk_label(finding.confidence)} · {finding.title}\n\n{finding.explanation}")
            for citation in finding.citations:
                st.caption(f"Источник: {citation_source(comparison, citation)}, редакция {citation.document_label}, пункт {citation.clause_id} — «{citation.quote}»")
        if not comparison.removed and not loss_findings:
            st.success("Явных удалённых пунктов или подтверждённых AI-сигналов потери нет.")
        st.caption("Удаление пункта само по себе не доказывает потерю функции: она могла быть перенесена или объединена.")

    with duplicate_tab:
        st.subheader("Возможное дублирование и пересечение ответственности")
        overlap_findings = [finding for finding in findings if finding.kind in (
            "потенциальное дублирование", "потенциальный конфликт интересов", "перераспределение ответственности")]
        if overlap_findings:
            for finding in overlap_findings:
                st.warning(f"{finding.title} · {finding.confidence} уверенность\n\n{finding.explanation}")
                for citation in finding.citations:
                    st.caption(f"Источник: {citation_source(comparison, citation)}, редакция {citation.document_label}, пункт {citation.clause_id} — «{citation.quote}»")
        elif ai_status != "completed":
            st.info(ai_status_text + " Точный diff не делает выводов о конфликте функций.")
        else:
            st.info("В проверенной выборке нет подтверждённых цитатами AI-сигналов дублирования или пересечения ответственности. Это не гарантирует отсутствия рисков в полном документе.")
        st.markdown("#### Изменённые фрагменты для ручной сверки")
        for item in comparison.modified:
            with st.expander(f"Пункт {item.clause_id}"):
                st.markdown(f"**До:** {item.before.text if item.before else '—'}")
                if item.before:
                    st.caption(f"{item.before.source} · {item.before.location}")
                st.markdown(f"**После:** {item.after.text if item.after else '—'}")
                if item.after:
                    st.caption(f"{item.after.source} · {item.after.location}")

    with mapping_tab:
        st.subheader("Матрица сопоставления пунктов")
        rows = []
        for status, changes in (("Создано", comparison.added), ("Удалено", comparison.removed),
                                ("Изменено", comparison.modified), ("Сохранено", comparison.unchanged)):
            for item in changes:
                rows.append({"Статус": status, "Пункт": item.clause_id,
                             "Старая редакция": item.before.text if item.before else "—",
                             "Новая редакция": item.after.text if item.after else "—",
                             "Источник до": (f"{item.before.source} · {item.before.location}"
                                              if item.before else "—"),
                             "Источник после": (f"{item.after.source} · {item.after.location}"
                                                 if item.after else "—")})
        st.dataframe(rows, width="stretch", hide_index=True,
                     column_config={"Статус": st.column_config.TextColumn("Статус", width="small"),
                                    "Пункт": st.column_config.TextColumn("Пункт", width="small"),
                                    "Старая редакция": st.column_config.TextColumn("Старая редакция", width="large"),
                                    "Новая редакция": st.column_config.TextColumn("Новая редакция", width="large"),
                                    "Источник до": st.column_config.TextColumn("Источник до", width="medium"),
                                    "Источник после": st.column_config.TextColumn("Источник после", width="medium")})

    with export_tab:
        st.subheader("Скачать результат")
        markdown_report = report_as_markdown(comparison, findings, old_name, new_name)
        markdown_report += f"\n## Статус и охват ИИ\n\n{ai_status_text}\n\n"
        if ai_coverage:
            markdown_report += f"Проверено {ai_coverage.get('included_clauses', 0)} из {ai_coverage.get('total_clauses', 0)} фрагментов; усечено {ai_coverage.get('truncated_clauses', 0)}.\n"
        if st.session_state.get("ai_error"):
            markdown_report += (
                "\n## Статус AI-проверки\n\n"
                f"AI-проверка не завершилась: {st.session_state['ai_error']} "
                "Локальное сопоставление выполнено.\n"
            )
        omitted_before = len(comparison.old_document.unnumbered_blocks)
        omitted_after = len(comparison.new_document.unnumbered_blocks)
        if omitted_before or omitted_after:
            markdown_report += (
                "\n## Охват исходных документов\n\n"
                "Ненумерованные фрагменты не вошли в автоматическое сравнение "
                f"(до: {omitted_before}, после: {omitted_after}). "
                "Проверьте их вручную в исходных документах.\n"
            )
        json_report = report_as_json(comparison, findings, old_name, new_name)
        left, right = st.columns(2)
        left.download_button("Скачать заключение Markdown", markdown_report, "teren-oi-zaklyuchenie.md", "text/markdown", width="stretch")
        right.download_button("Скачать полный diff JSON", json_report, "teren-oi-diff.json", "application/json", width="stretch")
        st.markdown("#### Предпросмотр заключения")
        st.markdown(markdown_report)
else:
    st.markdown("### Рабочий сценарий")
    st.write("1. Загрузите две редакции или вставьте текст слева и справа.  2. Нажмите **Сравнить редакции**.  3. Проверьте источники в матрице и скачайте заключение.")
