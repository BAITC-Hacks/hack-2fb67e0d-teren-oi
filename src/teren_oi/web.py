"""HTTP adapter for the Teren Oi browser interface.

This module only translates requests and responses. Parsing, comparison, evidence
validation and report text remain in the shared domain modules.
"""

from __future__ import annotations

from asyncio import to_thread
import os
import re
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .analyzer import AnalysisError, analyze_changes
from .diff import compare_documents
from .docx_reader import DocumentReadError
from .export_formats import export_report
from .models import Clause, Comparison, Finding, SourceDocument
from .parsers import TextBlock, parse_blocks
from .readers import SUPPORTED_EXTENSIONS, read_document
from .report import report_as_markdown

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_TEXT_CHARS = 500_000
MAX_REPORT_CHARS = 1_000_000
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
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
    report_markdown: str = Field(min_length=1, max_length=MAX_REPORT_CHARS)
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
    if len(text) > MAX_TEXT_CHARS:
        raise ApiProblem(413, "TEXT_TOO_LARGE", "Текст превышает допустимый размер.")
    blocks = [
        TextBlock(line, f"line {number}")
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    if not blocks:
        raise ApiProblem(400, "EMPTY_DOCUMENT", f"В редакции «{name}» нет текста.")
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
        raise ApiProblem(413, "FILE_TOO_LARGE", "Файл превышает 12 МБ.")
    try:
        document = _with_fallback_clauses(await to_thread(read_document, data, name))
    except DocumentReadError as exc:
        raise ApiProblem(400, "DOCUMENT_READ_ERROR", str(exc)) from exc
    if not document.clauses:
        raise ApiProblem(400, "NO_CLAUSES", f"В «{name}» не найден текст для сравнения.")
    return document


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
    changed_ids = {
        item.clause_id
        for item in (*comparison.added, *comparison.removed, *comparison.modified)
    }
    units: list[dict[str, object]] = []
    for key in sorted(old.keys() | new.keys()):
        old_data, new_data = old.get(key), new.get(key)
        clause_ids = sorted((old_data[1] if old_data else set()) | (new_data[1] if new_data else set()))
        if old_data is None:
            status = "created"
        elif new_data is None:
            status = "removed"
        elif any(clause_id in changed_ids for clause_id in clause_ids):
            status = "transformed"
        else:
            status = "retained"
        units.append({
            "name": (new_data or old_data)[0],
            "status": status,
            "clause_ids": clause_ids,
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
                "Пункт удалён по результатам сопоставления номеров. Проверьте, "
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
    for status, items in (
        ("removed", comparison.removed),
        ("modified", comparison.modified),
        ("added", comparison.added),
        ("unchanged", comparison.unchanged),
    ):
        for item in items:
            changes.append({
                "clause_id": item.clause_id,
                "status": status,
                "before": item.before.text if item.before else None,
                "after": item.after.text if item.after else None,
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
    for citation in payload["citations"]:
        document = (
            comparison.old_document
            if citation["document_label"] == "до"
            else comparison.new_document
        )
        clause = next(
            (
                item
                for item in document.clauses
                if item.clause_id == citation["clause_id"]
                and citation["quote"] in item.text
            ),
            None,
        )
        if clause is not None:
            citation["source"] = clause.source
            citation["location"] = clause.location
    return payload


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "ai_available": bool(os.getenv("OPENAI_API_KEY")),
        "model": MODEL,
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


@app.post("/api/analyze")
async def analyze(
    before_file: UploadFile | None = File(default=None),
    after_file: UploadFile | None = File(default=None),
    before_text: str | None = Form(default=None),
    after_text: str | None = Form(default=None),
    use_ai: bool = Form(default=False),
    demo: bool = Form(default=False),
) -> dict[str, object]:
    if demo:
        if before_file or after_file or before_text or after_text:
            raise ApiProblem(400, "AMBIGUOUS_INPUT", "Демо запускается без загруженных документов.")
        old_document = _text_document(DEMO_BEFORE, "Демо: до.txt")
        new_document = _text_document(DEMO_AFTER, "Демо: после.txt")
    else:
        old_document = await _source_document(before_file, before_text, "до")
        new_document = await _source_document(after_file, after_text, "после")
    omitted_before = len(old_document.unnumbered_blocks)
    omitted_after = len(new_document.unnumbered_blocks)
    warnings: list[str] = []
    if omitted_before or omitted_after:
        warnings.append(
            "Ненумерованные фрагменты не вошли в автоматическое сравнение "
            f"(до: {omitted_before}, после: {omitted_after}). "
            "Проверьте их вручную в исходных документах."
        )
    comparison = await to_thread(compare_documents, old_document, new_document)
    findings = _structural_findings(comparison)
    ai_error: str | None = None
    if use_ai:
        if not os.getenv("OPENAI_API_KEY"):
            raise ApiProblem(400, "AI_NOT_CONFIGURED", "Для AI-анализа нужен локальный OPENAI_API_KEY.")
        try:
            ai_findings = await to_thread(analyze_changes, comparison, MODEL)
        except AnalysisError as exc:
            ai_error = str(exc)
        else:
            explained_losses = {
                citation.clause_id
                for finding in ai_findings
                if finding.kind == "потенциальная потеря функции"
                for citation in finding.citations
                if citation.document_label == "до"
            }
            findings = [
                finding for finding in findings
                if finding.citations[0].clause_id not in explained_losses
            ]
            findings.extend(ai_findings)
    units = _units(comparison)
    duplicate_count = sum(item.kind == "потенциальное дублирование" for item in findings)
    loss_count = sum(item.kind == "потенциальная потеря функции" for item in findings)
    report_markdown = await to_thread(
        report_as_markdown, comparison, findings, old_document.name, new_document.name
    )
    if ai_error:
        report_markdown += (
            "\n## Статус AI-проверки\n\n"
            f"AI-проверка не завершилась: {ai_error} Локальное сопоставление выполнено.\n"
        )
    if warnings:
        report_markdown += "\n## Охват исходных документов\n\n" + "\n\n".join(warnings) + "\n"
    if len(report_markdown) > MAX_REPORT_CHARS:
        raise ApiProblem(413, "REPORT_TOO_LARGE", "Итоговый отчёт превышает допустимый размер.")
    return {
        "summary": {
            "added": len(comparison.added),
            "removed": len(comparison.removed),
            "modified": len(comparison.modified),
            "unchanged": len(comparison.unchanged),
            "units_changed": sum(unit["status"] != "retained" for unit in units),
            "duplicate_count": duplicate_count,
            "loss_count": loss_count,
        },
        "changes": _change_payload(comparison),
        "units": units,
        "findings": [_finding_payload(finding, comparison) for finding in findings],
        "report_markdown": report_markdown,
        "source_names": {"before": old_document.name, "after": new_document.name},
        "ai_error": ai_error,
        "warnings": warnings,
    }


@app.post("/api/export")
def export(payload: ExportRequest) -> Response:
    try:
        data, media_type, filename = export_report(payload.report_markdown, payload.format)
    except (ValueError, RuntimeError) as exc:
        raise ApiProblem(500, "EXPORT_FAILED", str(exc)) from exc
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
