from __future__ import annotations

import re
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

import pymupdf
from lxml.etree import XMLSyntaxError
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .docx_reader import DocumentReadError, read_docx
from .document_safety import (
    MAX_PDF_PAGES, MAX_SHEET_CELLS, MAX_TEXT_CHARS, bounded_blocks,
    validate_office_archive, validate_text,
)
from .models import SourceDocument
from .parsers import TextBlock, compact_text, is_standalone_clause_id, parse_blocks

SUPPORTED_EXTENSIONS = frozenset({".docx", ".pdf", ".xlsx", ".txt"})
_SIMPLE_SHEET_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё.-]*$")


def _validate_input(data: bytes, name: str, extension: str) -> None:
    if Path(name).suffix.lower() != extension:
        raise DocumentReadError(f"Файл «{name}» не имеет расширение {extension}.")
    if not data:
        raise DocumentReadError(f"Файл «{name}» пустой. Выберите документ с текстом.")


def read_pdf(data: bytes, name: str) -> SourceDocument:
    """Read text-layer PDF blocks with page-level source locations.

    OCR is intentionally outside the MVP. A PDF with no extractable text therefore
    produces an actionable error instead of an empty or fabricated document.
    """

    _validate_input(data, name, ".pdf")
    blocks: list[TextBlock] = []
    extracted_chars = 0
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise DocumentReadError("PDF защищён паролем. Загрузите копию без пароля.")
            if len(document) > MAX_PDF_PAGES:
                raise DocumentReadError("PDF превышает 500 страниц. Разделите документ на части.")
            for page_number, page in enumerate(document, start=1):
                for fallback_number, raw_block in enumerate(
                    page.get_text("blocks", sort=True), start=1
                ):
                    if len(raw_block) > 6 and raw_block[6] != 0:
                        continue
                    text = str(raw_block[4]).strip()
                    validate_text(text)
                    extracted_chars += len(text)
                    if extracted_chars > MAX_TEXT_CHARS:
                        raise DocumentReadError("Извлечённый текст превышает 500 000 символов. Разделите PDF на части.")
                    if not compact_text(text):
                        continue
                    block_number = int(raw_block[5]) + 1 if len(raw_block) > 5 else fallback_number
                    blocks.append(
                        TextBlock(
                            text=text,
                            location=f"page {page_number} / block {block_number}",
                        )
                    )
    except DocumentReadError:
        raise
    except (
        pymupdf.FileDataError,
        pymupdf.EmptyFileError,
        RuntimeError,
        ValueError,
        OSError,
    ) as exc:
        raise DocumentReadError(
            f"Не удалось прочитать «{name}». Проверьте, что файл является корректным PDF."
        ) from exc

    if not blocks:
        raise DocumentReadError(
            f"В «{name}» не найден извлекаемый текст. Распознавание сканов (OCR) пока недоступно. "
            "Загрузите PDF с выделяемым текстом, DOCX или вставьте распознанный текст."
        )
    return parse_blocks(blocks, name)


def _sheet_reference(sheet_name: str, coordinate: str) -> str:
    if _SIMPLE_SHEET_NAME_RE.fullmatch(sheet_name):
        return f"{sheet_name}!{coordinate}"
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'!{coordinate}"


def _xlsx_row_blocks(sheet: Any, row: Iterable[Any]) -> list[TextBlock]:
    cells = [
        (cell.coordinate, compact_text(cell.value))
        for cell in row
        if cell.value is not None and compact_text(cell.value)
    ]
    blocks: list[TextBlock] = []
    index = 0
    while index < len(cells):
        coordinate, text = cells[index]
        if is_standalone_clause_id(text) and index + 1 < len(cells):
            end = index + 1
            while end + 1 < len(cells) and not is_standalone_clause_id(cells[end + 1][1]):
                end += 1
            body = " | ".join(value for _, value in cells[index + 1 : end + 1])
            start_ref = _sheet_reference(sheet.title, coordinate)
            blocks.append(
                TextBlock(
                    text=f"{text} {body}",
                    location=f"{start_ref}:{cells[end][0]}",
                )
            )
            index = end + 1
            continue

        blocks.append(
            TextBlock(
                text=text,
                location=_sheet_reference(sheet.title, coordinate),
            )
        )
        index += 1
    return blocks


def read_xlsx(data: bytes, name: str) -> SourceDocument:
    """Read visible cell values in workbook, sheet, row and column order."""

    _validate_input(data, name, ".xlsx")
    workbook = None
    try:
        validate_office_archive(data)
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=False)
        def iter_blocks():
            scanned = 0
            for sheet in workbook.worksheets:
                if (sheet.max_row or 0) * (sheet.max_column or 0) > MAX_SHEET_CELLS:
                    raise DocumentReadError("Область листа XLSX превышает 500 000 ячеек. Удалите пустые форматированные строки/столбцы или разделите файл.")
                for row in sheet.iter_rows():
                    scanned += len(row)
                    if scanned > MAX_SHEET_CELLS:
                        raise DocumentReadError("XLSX превышает 500 000 ячеек. Разделите файл на части.")
                    yield from _xlsx_row_blocks(sheet, row)
        blocks = list(bounded_blocks(iter_blocks()))
    except DocumentReadError:
        raise
    except (BadZipFile, InvalidFileException, XMLSyntaxError, ParseError, KeyError, ValueError, OSError) as exc:
        raise DocumentReadError(
            f"Не удалось прочитать «{name}». Проверьте, что файл является корректным XLSX."
        ) from exc
    finally:
        if workbook is not None:
            workbook.close()

    if not blocks:
        raise DocumentReadError(f"В «{name}» не найдены заполненные ячейки.")
    return parse_blocks(blocks, name)


def read_txt(data: bytes, name: str) -> SourceDocument:
    _validate_input(data, name, ".txt")
    text: str | None = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise DocumentReadError(
            f"Не удалось прочитать «{name}». Поддерживаются кодировки UTF-8 и Windows-1251."
        )

    validate_text(text)
    if len(text) > MAX_TEXT_CHARS:
        raise DocumentReadError("Текст превышает 500 000 символов. Разделите документ на части.")

    blocks = [
        TextBlock(line, f"line {line_number}")
        for line_number, line in enumerate(text.splitlines(), start=1)
        if compact_text(line)
    ]
    if not blocks:
        raise DocumentReadError(f"В «{name}» не найден текст.")
    return parse_blocks(blocks, name)


def read_document(data: bytes, name: str) -> SourceDocument:
    """Dispatch a supported upload without changing the shared ``SourceDocument`` API."""

    extension = Path(name).suffix.lower()
    readers = {
        ".docx": read_docx,
        ".pdf": read_pdf,
        ".xlsx": read_xlsx,
        ".txt": read_txt,
    }
    reader = readers.get(extension)
    if reader is None:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise DocumentReadError(
            f"Формат файла «{name}» не поддерживается. Поддерживаемые форматы: {supported}."
        )
    return reader(data, name)
