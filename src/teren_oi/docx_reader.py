from __future__ import annotations

import re
from io import BytesIO
from zipfile import BadZipFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from .models import Clause, SourceDocument

CLAUSE_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,7})(?:[.)])?\s+(.+?)\s*$", re.DOTALL)


class DocumentReadError(ValueError):
    """Raised when an uploaded file is not a readable DOCX document."""


def _iter_text_blocks(document: Document):
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if text:
                yield text
        elif isinstance(item, Table):
            for row_index, row in enumerate(item.rows, start=1):
                cells = [" ".join(cell.text.split()) for cell in row.cells]
                line = " | ".join(cell for cell in cells if cell)
                if line:
                    yield f"[Таблица, строка {row_index}] {line}"


def read_docx(data: bytes, name: str) -> SourceDocument:
    if not name.lower().endswith(".docx"):
        raise DocumentReadError(f"Файл «{name}» не имеет расширение .docx.")
    if not data:
        raise DocumentReadError(f"Файл «{name}» пустой.")
    try:
        document = Document(BytesIO(data))
        blocks = list(_iter_text_blocks(document))
    except (BadZipFile, KeyError, ValueError, OSError) as exc:
        raise DocumentReadError(f"Не удалось прочитать «{name}». Проверьте, что это DOCX, а не переименованный PDF.") from exc
    if not blocks:
        raise DocumentReadError(f"В «{name}» не найден текст в абзацах или таблицах.")

    clauses: list[Clause] = []
    unnumbered: list[str] = []
    for index, block in enumerate(blocks, start=1):
        match = CLAUSE_RE.match(block)
        if match:
            clause_id = match.group(1).rstrip(".")
            body = match.group(2).strip()
            clauses.append(Clause(clause_id, body, name, f"блок {index}"))
        else:
            unnumbered.append(block)
    if not clauses:
        raise DocumentReadError(f"В «{name}» не найдены пункты вида 1.2 или 3.4. Проверьте формат документа.")
    return SourceDocument(name, tuple(clauses), tuple(unnumbered))
