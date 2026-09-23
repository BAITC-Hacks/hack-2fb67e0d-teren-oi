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


DocumentLabel = Literal["до", "после"]
Confidence = Literal["low", "medium", "high", "низкая", "средняя", "высокая"]
DepartmentStatus = Literal["created", "retained", "reorganized", "removed"]
FunctionStatus = Literal["retained", "changed", "reassigned", "lost"]
FindingKind = Literal[
    "possible_loss",
    "possible_duplication",
    "possible_conflict",
    # Legacy kinds keep the existing web and report adapters compatible.
    "потенциальная потеря функции",
    "потенциальное дублирование",
    "перераспределение ответственности",
    "другое изменение",
    "потенциальный конфликт интересов",
]


class Citation(BaseModel):
    document_label: DocumentLabel = Field(description="Точная метка document_label цитируемого фрагмента или его explicit alias.")
    clause_id: str = Field(min_length=1, description="Скопируй clause_id того же фрагмента/alias, например 2.4; не порядковый номер записи.")
    quote: str = Field(min_length=1, description="Непрерывная дословная подстрока text из того же фрагмента. Без своих кавычек, номера и многоточий.")


class DepartmentChange(BaseModel):
    name_before: str | None = Field(default=None, min_length=1)
    name_after: str | None = Field(default=None, min_length=1)
    status: DepartmentStatus
    citations: list[Citation] = Field(min_length=1)


class FunctionMapping(BaseModel):
    old_function: str = Field(min_length=1)
    new_function: str | None = Field(default=None, min_length=1)
    old_department: str | None = Field(default=None, min_length=1)
    new_department: str | None = Field(default=None, min_length=1)
    status: FunctionStatus
    confidence: Confidence
    citations: list[Citation] = Field(min_length=1)


class Finding(BaseModel):
    kind: FindingKind
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    confidence: Confidence
    citations: list[Citation] = Field(min_length=1)


class AnalysisResponse(BaseModel):
    # Empty/default structured sections keep the established summary/findings
    # constructors valid; the server replaces the unverified model summary.
    summary: str = Field(default_factory=str)
    department_changes: list[DepartmentChange] = Field(default_factory=list)
    function_mappings: list[FunctionMapping] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


def to_dict(value: object) -> dict:
    """Convert a dataclass or Pydantic model to JSON-compatible values."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return asdict(value)  # type: ignore[arg-type]
