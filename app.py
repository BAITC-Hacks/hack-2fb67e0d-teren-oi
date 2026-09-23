from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from teren_oi.analyzer import AnalysisError, analyze_changes  # noqa: E402
from teren_oi.diff import compare_documents  # noqa: E402
from teren_oi.docx_reader import DocumentReadError, read_docx  # noqa: E402
from teren_oi.report import report_as_json, report_as_markdown  # noqa: E402

load_dotenv(ROOT / ".env")

st.set_page_config(page_title="Teren Oi · Анализ изменений", page_icon="◈", layout="wide")
st.title("◈ Teren Oi")
st.subheader("Сравнение редакций организационных документов")
st.caption("Загрузите старую и новую редакции положения. Сначала покажем точный diff; AI-анализ — по желанию.")
st.info("AI выводы носят рекомендательный характер. Каждое утверждение должно проверяться по показанным пунктам документа.")

old_col, new_col = st.columns(2)
with old_col:
    old_file = st.file_uploader("Старая редакция (.docx)", type=["docx"], key="old_doc", max_upload_size=25)
with new_col:
    new_file = st.file_uploader("Новая редакция (.docx)", type=["docx"], key="new_doc", max_upload_size=25)

run_ai = st.checkbox("Сформировать AI-выводы по изменениям", value=bool(os.getenv("OPENAI_API_KEY")))
if run_ai and not os.getenv("OPENAI_API_KEY"):
    st.warning("Для AI-анализа добавьте OPENAI_API_KEY в локальный .env. Точный diff работает без ключа.")

if old_file and new_file and st.button("Сравнить документы", type="primary", use_container_width=True):
    try:
        old_doc = read_docx(old_file.getvalue(), old_file.name)
        new_doc = read_docx(new_file.getvalue(), new_file.name)
        comparison = compare_documents(old_doc, new_doc)
        findings = []
        ai_error = None
        if run_ai and os.getenv("OPENAI_API_KEY"):
            with st.spinner("Анализируем только изменённые пункты…"):
                try:
                    findings = analyze_changes(comparison, os.getenv("OPENAI_MODEL", "gpt-5.4-mini"))
                except AnalysisError as exc:
                    ai_error = str(exc)
        st.session_state["comparison"] = comparison
        st.session_state["findings"] = findings
        st.session_state["ai_error"] = ai_error
        st.session_state["doc_names"] = (old_file.name, new_file.name)
    except DocumentReadError as exc:
        st.error(str(exc))

comparison = st.session_state.get("comparison")
if comparison:
    old_name, new_name = st.session_state["doc_names"]
    a, b, c, d = st.columns(4)
    a.metric("Добавлено", len(comparison.added))
    b.metric("Удалено", len(comparison.removed))
    c.metric("Изменено", len(comparison.modified))
    d.metric("Без изменений", len(comparison.unchanged))

    if st.session_state.get("ai_error"):
        st.warning(f"AI-анализ не завершился: {st.session_state['ai_error']} Точный diff доступен ниже.")
    findings = st.session_state.get("findings", [])
    if findings:
        st.header("Аналитические выводы")
        for finding in findings:
            with st.expander(f"{finding.kind}: {finding.title}", expanded=True):
                st.write(finding.explanation)
                st.caption(f"Уверенность: {finding.confidence}")
                for citation in finding.citations:
                    st.markdown(f"**{citation.document_label}, пункт {citation.clause_id}:** {citation.quote}")
    st.header("Точные изменения")
    for heading, items in (("Добавленные пункты", comparison.added),
                           ("Удалённые пункты", comparison.removed),
                           ("Изменённые пункты", comparison.modified)):
        with st.expander(f"{heading} · {len(items)}", expanded=bool(items)):
            for item in items:
                st.markdown(f"**Пункт {item.clause_id}**")
                if item.before:
                    st.markdown(f"До ({old_name}): {item.before.text}")
                if item.after:
                    st.markdown(f"После ({new_name}): {item.after.text}")
    md = report_as_markdown(comparison, findings, old_name, new_name)
    st.download_button("Скачать отчёт Markdown", md, "teren-oi-report.md", "text/markdown")
    st.download_button("Скачать данные JSON", report_as_json(comparison, findings, old_name, new_name),
                       "teren-oi-report.json", "application/json")
