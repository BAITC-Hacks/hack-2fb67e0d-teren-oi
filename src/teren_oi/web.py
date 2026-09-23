"""HTTP adapter for the Teren Oi browser interface.

This module only translates requests and responses. Parsing, comparison, evidence
validation and report text remain in the shared domain modules.
"""

from __future__ import annotations

from asyncio import to_thread
from collections import Counter
import os
import re
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analyzer import AnalysisError, analyze_with_metadata, evidence_coverage, evidence_omissions
from .diff import compare_documents, validate_analysis_response
from .evidence import resolve_citation, validated_findings
from .docx_reader import DocumentReadError
from .document_safety import validate_text
from .export_formats import MAX_REPORT_LENGTH, export_report
from .models import Clause, Comparison, Finding, FunctionMapping, SourceDocument
from .parsers import TextBlock, parse_blocks
from .readers import SUPPORTED_EXTENSIONS, read_document
from .report import escape_markdown, report_as_markdown
from .report_store import ReportStore
from .semantic_view import evidence_payload, semantic_units, semantic_report

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_TEXT_CHARS = 500_000
MAX_REPORT_CHARS = MAX_REPORT_LENGTH
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
REPORTS = ReportStore()
UNIT_PATTERN = re.compile(
    r"\b((?:Департамент|Управление|Отдел|Центр|Служба|Группа|Дирекция|"
    r"ДЕПАРТАМЕНТ|УПРАВЛЕНИЕ|ОТДЕЛ|ЦЕНТР|СЛУЖБА|ГРУППА|ДИРЕКЦИЯ)\s+[^:;,.\n]{2,90})",
)

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


class ApiProblem(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class ExportRequest(BaseModel):
    analysis_id: str | None = Field(default=None, min_length=1, max_length=128)
    # Retained for older clients. The current UI exports server snapshots only.
    report_markdown: str | None = Field(default=None, min_length=1, max_length=MAX_REPORT_CHARS)
    format: Literal["pdf", "docx"]


app = FastAPI(title="Teren Oi API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(ApiProblem)
async def api_problem_handler(_request: Request, problem: ApiProblem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status_code,
        content={"error": {"code": problem.code, "message": problem.message}},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_request: Request, _error: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Некорректные поля запроса."}},
    )


def _text_document(text: str, name: str) -> SourceDocument:
    try:
        validate_text(text)
    except DocumentReadError as exc:
        raise ApiProblem(400, "INVALID_TEXT", str(exc)) from exc
    if len(text) > MAX_TEXT_CHARS:
        raise ApiProblem(413, "TEXT_TOO_LARGE", "Текст превышает 500 000 символов. Разделите документ на части.")
    blocks = [
        TextBlock(line, f"line {number}")
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    if not blocks:
        raise ApiProblem(400, "EMPTY_DOCUMENT", f"В редакции «{name}» нет текста. Вставьте текст или выберите заполненный документ.")
    parsed = parse_blocks(blocks, name)
    if parsed.clauses:
        return parsed
    # Plain prose can still be compared as one traceable block.
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    clauses = tuple(
        Clause(f"Текст {number}", paragraph, name, f"block {number}")
        for number, paragraph in enumerate(paragraphs, start=1)
    )
    return SourceDocument(name, clauses)


def _with_fallback_clauses(document: SourceDocument) -> SourceDocument:
    if document.clauses or not document.unnumbered_blocks:
        return document
    # Some spreadsheets and prose documents have no numeric clause IDs. Give
    # their blocks transparent synthetic IDs so they remain comparable.
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


async def _source_document(file: UploadFile | None, text: str | None, label: str) -> SourceDocument:
    has_text = bool(text and text.strip())
    if file is not None and has_text:
        raise ApiProblem(400, "AMBIGUOUS_INPUT", f"Для редакции «{label}» выберите файл или текст.")
    if file is None:
        if not has_text:
            raise ApiProblem(400, "MISSING_INPUT", f"Добавьте документ или текст редакции «{label}».")
        return _text_document(text or "", f"Редакция {label}.txt")

    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name or Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ApiProblem(400, "UNSUPPORTED_FORMAT", "Поддерживаются DOCX, PDF, XLSX и TXT.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiProblem(413, "FILE_TOO_LARGE", "Файл превышает 12 МБ. Разделите документ на части или загрузите текстовую версию.")
    try:
        validate_text(name)
        document = _with_fallback_clauses(await to_thread(read_document, data, name))
    except DocumentReadError as exc:
        raise ApiProblem(400, "DOCUMENT_READ_ERROR", str(exc)) from exc
    if not document.clauses:
        raise ApiProblem(400, "NO_CLAUSES", f"В «{name}» не найден текст для сравнения.")
    if sum(len(item.text) for item in document.clauses) + sum(map(len, document.unnumbered_blocks)) > MAX_TEXT_CHARS:
        raise ApiProblem(413, "TEXT_TOO_LARGE", "Извлечённый текст превышает 500 000 символов. Разделите документ на части.")
    return document


async def _source_bundle(files: list[UploadFile], text: str | None, label: str, scoped: bool) -> SourceDocument:
    if not files:
        document = await _source_document(None, text, label)
        documents = [document]
    else:
        if text and text.strip():
            raise ApiProblem(400, "AMBIGUOUS_INPUT", "Выберите комплект файлов или текст для каждой редакции.")
        if len(files) > 8:
            raise ApiProblem(400, "TOO_MANY_FILES", "Не более 8 файлов на редакцию.")
        names = [(file.filename or "").replace("\\", "/").rsplit("/", 1)[-1] for file in files]
        if len({name.casefold() for name in names}) != len(names):
            raise ApiProblem(400, "DUPLICATE_FILENAME", "В комплекте есть одинаковые имена файлов. Переименуйте их для однозначных источников.")
        documents = []
        total = 0
        for file in files:
            document = await _source_document(file, None, label)
            total += sum(len(c.text) for c in document.clauses) + sum(map(len, document.unnumbered_blocks))
            if total > MAX_TEXT_CHARS:
                raise ApiProblem(413, "BUNDLE_TOO_LARGE", "Комплект превышает 500 000 символов. Уменьшите число документов.")
            documents.append(document)
    if not scoped:
        return documents[0]
    # Length-prefixed filename avoids collisions and preserves original clause IDs.
    clauses = tuple(Clause(f"{len(d.name)}:{d.name} :: {c.clause_id}", c.text, c.source,
                           f"Пункт {c.clause_id} · {c.location}") for d in documents for c in d.clauses)
    return SourceDocument("; ".join(d.name for d in documents), clauses,
                          tuple(block for d in documents for block in d.unnumbered_blocks))


def _unit_names(clause: Clause) -> set[str]:
    return {
        " ".join(match.group(1).split()).strip(" -–—")
        for match in UNIT_PATTERN.finditer(clause.text)
    }


def _units(comparison: Comparison) -> list[dict[str, object]]:
    old: dict[str, tuple[str, set[str]]] = {}
    new: dict[str, tuple[str, set[str]]] = {}
    for document, target in (
        (comparison.old_document, old),
        (comparison.new_document, new),
    ):
        for clause in document.clauses:
            for name in _unit_names(clause):
                key = name.casefold()
                if key not in target:
                    target[key] = (name, set())
                target[key][1].add(clause.clause_id)
    changed_names = {
        name.casefold()
        for item in (*comparison.added, *comparison.removed, *comparison.modified)
        for clause in (item.before, item.after) if clause
        for name in _unit_names(clause)
    }
    change_ids_by_name: dict[str, list[str]] = {}
    for index, change in enumerate(
        (*comparison.removed, *comparison.modified, *comparison.added, *comparison.unchanged), 1
    ):
        names = {name.casefold() for clause in (change.before, change.after) if clause
                 for name in _unit_names(clause)}
        for name in names:
            change_ids_by_name.setdefault(name, []).append(f"change-{index}")
    units: list[dict[str, object]] = []
    for key in sorted(old.keys() | new.keys()):
        old_data, new_data = old.get(key), new.get(key)
        clause_ids = sorted((old_data[1] if old_data else set()) | (new_data[1] if new_data else set()))
        if old_data is None:
            status = "created"
        elif new_data is None:
            status = "removed"
        elif key in changed_names:
            status = "transformed"
        else:
            status = "retained"
        units.append({
            "name": (new_data or old_data)[0],
            "status": status,
            "clause_ids": clause_ids,
            "change_ids": change_ids_by_name.get(key, []),
        })
    return units


def _structural_findings(comparison: Comparison) -> list[Finding]:
    """Surface removed points for verification without claiming a proven function loss."""
    findings: list[Finding] = []
    for item in comparison.removed:
        if item.before is None:
            continue
        clause = item.before
        findings.append(Finding.model_validate({
            "kind": "потенциальная потеря функции",
            "title": f"Пункт {clause.clause_id} отсутствует в новой редакции",
            "explanation": (
                "Пункт не найден при точном сопоставлении текста и номеров. Проверьте, "
                "перенесена ли его функция в другой пункт или документ."
            ),
            "confidence": "низкая",
            "citations": [{
                "document_label": "до",
                "clause_id": clause.clause_id,
                "quote": clause.text[:240],
            }],
        }))
    return findings


def _change_payload(comparison: Comparison) -> list[dict[str, str | None]]:
    changes: list[dict[str, str | None]] = []
    repeated_ids = {
        label: {key for key, count in Counter(clause.clause_id for clause in document.clauses).items() if count > 1}
        for label, document in (("before", comparison.old_document), ("after", comparison.new_document))
    }
    for status, items in (
        ("removed", comparison.removed),
        ("modified", comparison.modified),
        ("added", comparison.added),
        ("unchanged", comparison.unchanged),
    ):
        for item in items:
            changes.append({
                "id": f"change-{len(changes) + 1}",
                "clause_id": item.clause_id,
                "status": status,
                "before": item.before.text if item.before else None,
                "after": item.after.text if item.after else None,
                "before_clause_id": item.before.clause_id if item.before else None,
                "after_clause_id": item.after.clause_id if item.after else None,
                "match_method": (
                    "exact_text" if status == "unchanged" else "occurrence"
                    if (item.before and item.before.clause_id in repeated_ids["before"])
                    or (item.after and item.after.clause_id in repeated_ids["after"])
                    else "number"
                ),
                "before_source": (
                    f"{item.before.source} · {item.before.location}" if item.before else None
                ),
                "after_source": (
                    f"{item.after.source} · {item.after.location}" if item.after else None
                ),
            })
    return changes


def _finding_payload(finding: Finding, comparison: Comparison) -> dict[str, object]:
    payload = finding.model_dump(mode="json")
    for citation, original in zip(payload["citations"], finding.citations):
        clause = resolve_citation(comparison, original)
        if clause is not None:
            citation["source"] = clause.source
            citation["location"] = clause.location
    return payload


def _mapped_old_clauses(
    comparison: Comparison,
    mappings: list[FunctionMapping],
) -> set[Clause]:
    """Return exact old clause occurrences covered by validated non-lost mappings."""
    resolved_old: set[Clause] = set()
    for mapping in mappings:
        if mapping.status not in {"retained", "changed", "reassigned"}:
            continue
        resolved = [resolve_citation(comparison, citation) for citation in mapping.citations]
        if not resolved or any(clause is None for clause in resolved):
            continue
        resolved_old.update(
            clause
            for citation, clause in zip(mapping.citations, resolved)
            if citation.document_label == "до" and clause is not None
        )
    return resolved_old


def _document_coverage(document: SourceDocument) -> dict[str, object]:
    return {
        "clauses": len(document.clauses),
        "unnumbered_blocks": len(document.unnumbered_blocks),
        "synthetic_ids": any(clause.clause_id.startswith(("Текст ", "Блок ")) for clause in document.clauses),
    }


def _report_context(ai: dict, coverage: dict, summary: dict, warnings: list[str]) -> list[str]:
    statuses = {
        "disabled": "AI-проверка выключена пользователем; выполнено локальное сравнение.",
        "unavailable": "AI-проверка недоступна: ключ не настроен. Локальное сравнение выполнено.",
        "failed": "AI-проверка не завершилась. Локальное сравнение выполнено.",
        "skipped": "AI-проверка не запускалась: изменений для проверки не найдено.",
        "succeeded": "AI-проверка выполнена. Цитаты проверены на присутствие в источниках.",
    }
    lines = ["## Статус AI-проверки", "", statuses[ai["status"]], ""]
    if ai["requested"]:
        lines.extend([f"Модель: {escape_markdown(ai['model'], inline=True)}", ""])
    if ai["error"]:
        lines.extend([str(ai["error"]), ""])
    if ai["summary"]:
        lines.extend(["Сводка составлена приложением по проверенным выводам модели:", str(ai["summary"]), ""])
    lines.extend([
        f"Удалённых пунктов по точному сравнению: {summary['removed']}. "
        f"Возможные потери функций по ИИ: {summary['ai_loss_count'] if summary['ai_loss_count'] is not None else 'не проверено'}; "
        f"возможные дубли по ИИ: {summary['ai_duplicate_count'] if summary['ai_duplicate_count'] is not None else 'не проверено'}. "
        f"Подразделений с изменениями: {summary['units_changed']} (оценки ИИ при наличии, иначе текстовые признаки).", "",
        "## Охват исходных документов", "",
        f"Пунктов до: {coverage['before']['clauses']}; после: {coverage['after']['clauses']}.", "",
    ])
    if ai["status"] == "succeeded":
        selected = ai["coverage"]
        lines.extend([
            f"В AI-проверку включено фрагментов: {selected['included_clauses']} из {selected['total_clauses']}; "
            f"пропущено: {selected['omitted_clauses']}; усечено: {selected['truncated_clauses']}.", "",
            "Сохранённый одинаковый текст учитывается один раз, изменённый — для каждой редакции.", "",
            "Полный контекст для ИИ: до — " + ("да" if selected.get("before_complete") else "нет")
            + "; после — " + ("да" if selected.get("after_complete") else "нет") + ".", "",
        ])
        for field, title in (("omitted_refs", "Не переданы"), ("truncated_refs", "Переданы частично")):
            if ai[field]:
                lines.extend([f"{title} (до 50 фрагментов): {escape_markdown(', '.join(ai[field]), inline=True)}.", ""])
    for warning in warnings:
        lines.extend([warning, ""])
    return lines


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "ai_available": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "model": MODEL,
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


@app.post("/api/analyze")
async def analyze(
    before_file: UploadFile | None = File(default=None),
    after_file: UploadFile | None = File(default=None),
    before_files: list[UploadFile] | None = File(default=None),
    after_files: list[UploadFile] | None = File(default=None),
    before_text: str | None = Form(default=None),
    after_text: str | None = Form(default=None),
    use_ai: bool = Form(default=False),
    demo: bool = Form(default=False),
) -> dict[str, object]:
    if demo:
        if before_file or after_file or before_files or after_files or before_text or after_text:
            raise ApiProblem(400, "AMBIGUOUS_INPUT", "Демо запускается без загруженных документов.")
        old_document = _text_document(DEMO_BEFORE, "Демо: до.txt")
        new_document = _text_document(DEMO_AFTER, "Демо: после.txt")
    else:
        if (before_file and before_files) or (after_file and after_files):
            raise ApiProblem(400, "AMBIGUOUS_INPUT", "Используйте одиночное поле файла или комплект, не оба одновременно.")
        old_files = before_files or ([before_file] if before_file else [])
        new_files = after_files or ([after_file] if after_file else [])
        scoped = max(len(old_files), len(new_files)) > 1
        old_document = await _source_bundle(old_files, before_text, "до", scoped)
        new_document = await _source_bundle(new_files, after_text, "после", scoped)
    omitted_before = len(old_document.unnumbered_blocks)
    omitted_after = len(new_document.unnumbered_blocks)
    warnings: list[str] = []
    if not demo and scoped:
        warnings.append("Комплекты: номера пунктов привязаны к имени файла. Для сопоставления изменённого текста по номеру имена соответствующих файлов должны совпадать. Разные имена сопоставляются по однозначному совпадению текста; смысловые переносы проверяет ИИ в пределах охвата.")
    if omitted_before or omitted_after:
        warnings.append(
            "Ненумерованные фрагменты не вошли в автоматическое сравнение "
            f"(до: {omitted_before}, после: {omitted_after}). "
            "Проверьте их вручную в исходных документах."
        )
    comparison = await to_thread(compare_documents, old_document, new_document)
    local_findings = _structural_findings(comparison)
    findings = [item for item, _ in validated_findings(comparison, local_findings)]
    if len(findings) < len(local_findings):
        warnings.append("Некоторые локальные сигналы не показаны: одинаковые номера и цитаты не позволяют однозначно выбрать источник. Все пункты сохранены в карте изменений.")
    origins = ["local"] * len(findings)
    coverage = {"before": _document_coverage(old_document), "after": _document_coverage(new_document)}
    for label, document in (("до", old_document), ("после", new_document)):
        if _document_coverage(document)["synthetic_ids"]:
            warnings.append(f"Редакция «{label}» без нумерации: используются временные номера блоков. Сопоставление по порядку требует ручной проверки.")
        if any(count > 1 for count in Counter(clause.clause_id for clause in document.clauses).values()):
            warnings.append(f"В редакции «{label}» повторяются номера пунктов. Фрагменты сохранены отдельно; неоднозначные изменения проверьте по позициям в источнике.")
    ai: dict = {
        "status": "disabled", "requested": use_ai, "model": MODEL,
        "summary": None, "summary_origin": None, "finding_ids": [], "error": None,
        "coverage": evidence_coverage(comparison), "rejected_findings": 0,
        "omitted_refs": [], "truncated_refs": [],
    }
    departments = []
    mappings = []
    if use_ai:
        if not os.getenv("OPENAI_API_KEY", "").strip():
            ai["status"] = "unavailable"
            ai["error"] = "Ключ OpenAI не настроен на сервере. Добавьте OPENAI_API_KEY в локальный .env и перезапустите API."
        else:
            try:
                analysis = await to_thread(analyze_with_metadata, comparison, MODEL)
            except AnalysisError as exc:
                ai["status"], ai["error"] = "failed", str(exc)
            else:
                ai["status"] = "succeeded" if analysis.called else "skipped"
                ai["coverage"] = analysis.coverage
                if analysis.called and analysis.structured is not None:
                    # Reuse the validated structured result of the SAME call; keep
                    # its metadata and the legacy findings adapter compatible.
                    structured = validate_analysis_response(
                        analysis.structured, comparison,
                        before_complete=bool(analysis.coverage.get("before_complete")),
                        after_complete=bool(analysis.coverage.get("after_complete")),
                    )
                    departments = structured.department_changes
                    mappings = structured.function_mappings
                verified_ai = [item for item, _ in validated_findings(comparison, analysis.findings)]
                ai["rejected_findings"] = analysis.rejected_findings + len(analysis.findings) - len(verified_ai)
                explained_losses = {
                    resolve_citation(comparison, citation)
                    for finding in verified_ai if finding.kind == "потенциальная потеря функции"
                    for citation in finding.citations if citation.document_label == "до"
                }
                explained_losses.discard(None)
                explained_losses.update(_mapped_old_clauses(comparison, mappings))
                findings = [
                    item for item in findings
                    if resolve_citation(comparison, item.citations[0]) not in explained_losses
                ]
                origins = ["local"] * len(findings) + ["ai"] * len(verified_ai)
                findings.extend(verified_ai)
                if analysis.called:
                    ai.update(evidence_omissions(comparison))
                    ai["summary_origin"] = "verified_findings"
                    ai["summary"] = (
                        f"Выводов модели с проверенными цитатами: {len(verified_ai)}. "
                        "Ниже приведены формулировки модели; их смысловую корректность следует проверить по источникам."
                        if verified_ai else
                        "Модель не вернула выводов с проверяемыми цитатами. Это не подтверждает отсутствие рисков в документах."
                    )
                if ai["rejected_findings"]:
                    warnings.append(f"Не показаны выводы модели, не прошедшие проверку цитат, редакций или полноты контекста: {ai['rejected_findings']}.")
    units = semantic_units(_units(comparison), departments, comparison)
    department_payloads = [evidence_payload(item, comparison) for item in departments]
    mapping_payloads = [evidence_payload(item, comparison) for item in mappings]
    if ai["status"] == "succeeded":
        ai["summary"] = (
            f"Результаты модели с проверенными цитатами: замечаний — {sum(origin == 'ai' for origin in origins)}; "
            f"оценок подразделений — {len(departments)}; сопоставлений функций: {len(mappings)}. "
            "Смысловую корректность оценок следует проверить по источникам; отсутствие результатов не доказывает отсутствие рисков."
        )
    duplicate_count = sum(item.kind == "потенциальное дублирование" for item in findings)
    loss_count = sum(item.kind == "потенциальная потеря функции" for item in findings)
    ai_loss_count = sum(item.kind == "потенциальная потеря функции" and origin == "ai"
                        for item, origin in zip(findings, origins)) if ai["status"] == "succeeded" else None
    ai_duplicate_count = sum(item.kind == "потенциальное дублирование" and origin == "ai"
                             for item, origin in zip(findings, origins)) if ai["status"] == "succeeded" else None
    summary = {
        "added": len(comparison.added), "removed": len(comparison.removed),
        "modified": len(comparison.modified), "unchanged": len(comparison.unchanged),
        "units_changed": sum(unit["status"] != "retained" for unit in units),
        "duplicate_count": duplicate_count, "loss_count": ai_loss_count if ai_loss_count is not None else loss_count,
        "ai_loss_count": ai_loss_count, "ai_duplicate_count": ai_duplicate_count,
    }
    finding_payloads = []
    for index, (finding, origin) in enumerate(zip(findings, origins), 1):
        payload = {**_finding_payload(finding, comparison), "id": f"finding-{index}", "origin": origin}
        finding_payloads.append(payload)
        if origin == "ai":
            ai["finding_ids"].append(payload["id"])
    report_markdown = await to_thread(
        report_as_markdown, comparison, findings, old_document.name, new_document.name,
        finding_origins=origins, context=_report_context(ai, coverage, summary, warnings)
        + semantic_report(department_payloads, mapping_payloads),
    )
    if len(report_markdown) > MAX_REPORT_CHARS:
        raise ApiProblem(413, "REPORT_TOO_LARGE", "Итоговый отчёт превышает 4 млн символов. Сравните документы по отдельным разделам.")
    return {
        "analysis_id": REPORTS.put(report_markdown),
        "summary": summary,
        "changes": _change_payload(comparison),
        "units": units,
        "findings": finding_payloads,
        "department_changes": department_payloads,
        "function_mappings": mapping_payloads,
        "ai_summary": ai["summary"],
        "report_markdown": report_markdown,
        "source_names": {"before": old_document.name, "after": new_document.name},
        "ai": ai,
        "coverage": coverage,
        "ai_error": ai["error"],
        "warnings": warnings,
    }


@app.post("/api/export")
def export(payload: ExportRequest) -> Response:
    if bool(payload.analysis_id) == bool(payload.report_markdown):
        raise ApiProblem(400, "AMBIGUOUS_EXPORT", "Укажите идентификатор анализа или текст отчёта, но не оба сразу.")
    markdown = REPORTS.get(payload.analysis_id) if payload.analysis_id else payload.report_markdown
    if markdown is None:
        raise ApiProblem(410, "REPORT_EXPIRED", "Отчёт больше не хранится на сервере. Повторите анализ и скачайте его снова.")
    try:
        data, media_type, filename = export_report(markdown, payload.format)
    except DocumentReadError as exc:
        raise ApiProblem(400, "INVALID_REPORT_TEXT", str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise ApiProblem(500, "EXPORT_FAILED", str(exc)) from exc
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# The launcher/container serves UI and API from one origin. Development with
# Vite on 5173 remains available. Mount last so API routes keep their priority.
UI_DIST = Path(os.getenv("TEREN_UI_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
if (UI_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="frontend")
