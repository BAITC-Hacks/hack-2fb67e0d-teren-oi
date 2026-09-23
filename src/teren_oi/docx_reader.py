from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile

from lxml.etree import XMLSyntaxError

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph

from .models import SourceDocument
from .parsers import TextBlock, compact_text, is_standalone_clause_id, parse_blocks


class DocumentReadError(ValueError):
    """Raised when an uploaded document cannot be read safely."""


def _iter_text_blocks(document: Document):
    paragraph_number = 0
    table_number = 0
    for block_number, item in enumerate(document.iter_inner_content(), start=1):
        if isinstance(item, Paragraph):
            paragraph_number += 1
            text = item.text.strip()
            if text:
                yield TextBlock(
                    text=text,
                    location=f"block {block_number} / paragraph {paragraph_number}",
                )
        elif isinstance(item, Table):
            table_number += 1
            for row_index, row in enumerate(item.rows, start=1):
                cells: list[tuple[int, str]] = []
                seen_xml_cells: set[int] = set()
                for column_index, cell in enumerate(row.cells, start=1):
                    xml_cell_id = id(cell._tc)
                    if xml_cell_id in seen_xml_cells:
                        continue
                    seen_xml_cells.add(xml_cell_id)
                    text = cell.text.strip()
                    if text:
                        cells.append((column_index, text))
                if not cells:
                    continue

                first_column, first_text = cells[0]
                if is_standalone_clause_id(compact_text(first_text)) and len(cells) > 1:
                    last_column = cells[-1][0]
                    combined = " ".join([first_text, " | ".join(text for _, text in cells[1:])])
                    yield TextBlock(
                        text=combined,
                        location=(
                            f"block {block_number} / table {table_number} / row {row_index} "
                            f"/ columns {first_column}-{last_column}"
                        ),
                    )
                    continue

                for column_index, text in cells:
                    yield TextBlock(
                        text=text,
                        location=(
                            f"block {block_number} / table {table_number} / row {row_index} "
                            f"/ column {column_index}"
                        ),
                    )


def read_docx(data: bytes, name: str) -> SourceDocument:
    if not name.lower().endswith(".docx"):
        raise DocumentReadError(f"Файл «{name}» не имеет расширение .docx.")
    if not data:
        raise DocumentReadError(f"Файл «{name}» пустой. Выберите документ с текстом.")
    try:
        document = Document(BytesIO(data))
        blocks = list(_iter_text_blocks(document))
    except (BadZipFile, PackageNotFoundError, XMLSyntaxError, KeyError, ValueError, OSError) as exc:
        raise DocumentReadError(
            f"Не удалось прочитать «{name}». Проверьте, что это DOCX, а не переименованный PDF."
        ) from exc
    if not blocks:
        raise DocumentReadError(f"В «{name}» не найден текст в абзацах или таблицах.")
    return parse_blocks(blocks, name)
