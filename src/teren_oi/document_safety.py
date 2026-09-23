"""Resource and text limits shared by document readers and exports."""
from __future__ import annotations

import re
from io import BytesIO
from zipfile import ZipFile

MAX_TEXT_CHARS = 500_000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096
MAX_SHEET_CELLS = 500_000
MAX_PDF_PAGES = 500
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


class DocumentReadError(ValueError):
    """An unreadable or unsupported document, safe to describe to the user."""


def validate_text(text: str) -> None:
    if _INVALID_XML.search(text):
        raise DocumentReadError(
            "Текст содержит недопустимые управляющие символы. "
            "Пересохраните документ как UTF-8 TXT или DOCX и загрузите снова."
        )


def validate_office_archive(data: bytes) -> None:
    # Inspect metadata before python-docx/openpyxl expand the ZIP package.
    with ZipFile(BytesIO(data)) as archive:
        members = archive.infolist()
        if (len(members) > MAX_ARCHIVE_ENTRIES
                or sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES):
            raise DocumentReadError(
                "Слишком большой распакованный документ (лимит 64 МБ / 4096 частей). "
                "Удалите лишние изображения и листы или разделите файл."
            )
        if any(member.flag_bits & 1 for member in members):
            raise DocumentReadError("Документ защищён паролем. Загрузите копию без пароля.")


def bounded_blocks(blocks):
    total = 0
    for block in blocks:
        validate_text(block.text)
        total += len(block.text)
        if total > MAX_TEXT_CHARS:
            raise DocumentReadError(
                "Извлечённый текст превышает 500 000 символов. Разделите документ на части."
            )
        yield block
