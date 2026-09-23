from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Clause:
    clause_id: str
    text: str
    source: str
    location: str


@dataclass(frozen=True)
class SourceDocument:
    name: str
    clauses: tuple[Clause, ...]
    unnumbered_blocks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Change:
    clause_id: str
    before: Clause | None
    after: Clause | None


@dataclass(frozen=True)
class Comparison:
    old_document: SourceDocument
    new_document: SourceDocument
    added: tuple[Change, ...]
    removed: tuple[Change, ...]
    modified: tuple[Change, ...]
    unchanged: tuple[Change, ...]


class Citation(BaseModel):
    document_label: Literal["до", "после"] = Field(description="Точная метка document_label цитируемого фрагмента.")
    clause_id: str = Field(description="Скопируй clause_id цитируемого фрагмента, например 2.4; не порядковый номер записи.")
    quote: str = Field(min_length=1, description="Непрерывная дословная подстрока text из того же фрагмента. Без своих кавычек, номера и многоточий.")


class Finding(BaseModel):
    kind: Literal["потенциальная потеря функции", "потенциальное дублирование",
                  "перераспределение ответственности", "другое изменение"]
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    confidence: Literal["низкая", "средняя", "высокая"]
    citations: list[Citation] = Field(min_length=1)


class AnalysisResponse(BaseModel):
    summary: str
    findings: list[Finding]


def to_dict(value: object) -> dict:
    """Convert a dataclass or Pydantic model to JSON-compatible values."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return asdict(value)  # type: ignore[arg-type]
