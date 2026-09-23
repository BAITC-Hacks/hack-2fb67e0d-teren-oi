from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Hashable, Sequence
from typing import TypeVar

from .evidence import resolve_citation
from .models import (
    AnalysisResponse,
    Change,
    Citation,
    Comparison,
    DepartmentChange,
    DocumentLabel,
    Finding,
    FindingKind,
    FunctionMapping,
    SourceDocument,
)

Key = TypeVar("Key", bound=Hashable)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _positions(values: list[Key], remaining: set[int]) -> dict[Key, list[int]]:
    """Group document positions, retaining every occurrence and its original order."""
    groups: defaultdict[Key, list[int]] = defaultdict(list)
    for index, value in enumerate(values):
        if index in remaining:
            groups[value].append(index)
    return groups


def compare_documents(old: SourceDocument, new: SourceDocument) -> Comparison:
    """Match exact unique text first, then exact text within an ID, then ID occurrence.

    Cross-ID matches require nonempty text occurring exactly once in each complete
    document. Repeated text cannot establish a unique move, even after other clauses
    have been matched. Residual duplicate IDs are paired in document order; that is
    a structural comparison, not evidence of semantic or organizational continuity.
    """
    old_remaining = set(range(len(old.clauses)))
    new_remaining = set(range(len(new.clauses)))
    old_texts = [normalize(clause.text) for clause in old.clauses]
    new_texts = [normalize(clause.text) for clause in new.clauses]
    modified: list[Change] = []
    unchanged: list[Change] = []

    def pair(old_index: int, new_index: int) -> None:
        before, after = old.clauses[old_index], new.clauses[new_index]
        target = unchanged if old_texts[old_index] == new_texts[new_index] else modified
        target.append(Change(after.clause_id, before, after))
        old_remaining.remove(old_index)
        new_remaining.remove(new_index)

    # Reserve every unambiguous exact match before an ID match can consume it.
    old_by_text = _positions(old_texts, old_remaining)
    new_by_text = _positions(new_texts, new_remaining)
    for text, old_positions in old_by_text.items():
        new_positions = new_by_text.get(text, [])
        if text and len(old_positions) == len(new_positions) == 1:
            pair(old_positions[0], new_positions[0])

    # Same-ID repeated text remains comparable without inventing a cross-ID move.
    old_exact = _positions(
        [(clause.clause_id, text) for clause, text in zip(old.clauses, old_texts)],
        old_remaining,
    )
    new_exact = _positions(
        [(clause.clause_id, text) for clause, text in zip(new.clauses, new_texts)],
        new_remaining,
    )
    for key, old_positions in old_exact.items():
        for old_index, new_index in zip(old_positions, new_exact.get(key, [])):
            pair(old_index, new_index)

    old_by_id = _positions([clause.clause_id for clause in old.clauses], old_remaining)
    new_by_id = _positions([clause.clause_id for clause in new.clauses], new_remaining)
    for clause_id, old_positions in old_by_id.items():
        for old_index, new_index in zip(old_positions, new_by_id.get(clause_id, [])):
            pair(old_index, new_index)

    added = [Change(new.clauses[i].clause_id, None, new.clauses[i])
             for i in sorted(new_remaining)]
    removed = [Change(old.clauses[i].clause_id, old.clauses[i], None)
               for i in sorted(old_remaining)]

    def key_order(item: Change) -> list[str | int]:
        return [int(part) if part.isdigit() else part
                for part in re.split(r"(\d+)", item.clause_id)]

    return Comparison(
        old, new,
        tuple(sorted(added, key=key_order)), tuple(sorted(removed, key=key_order)),
        tuple(sorted(modified, key=key_order)), tuple(sorted(unchanged, key=key_order)),
    )


_LEGACY_FINDING_KINDS: dict[str, FindingKind] = {
    "потенциальная потеря функции": "possible_loss",
    "потенциальное дублирование": "possible_duplication",
    "потенциальный конфликт интересов": "possible_conflict",
}


def _citation_is_valid(
    citation: Citation,
    comparison: Comparison,
    allowed_evidence: Sequence[tuple[DocumentLabel, str, str]] | None,
) -> bool:
    label = citation.document_label
    clause_id = citation.clause_id
    quote = citation.quote.strip()
    # A matching substring in several occurrences cannot establish a source.
    # Share this rule with the UI and reports rather than silently selecting one.
    citation_is_from_source = resolve_citation(comparison, citation) is not None
    if not citation_is_from_source or allowed_evidence is None:
        return citation_is_from_source
    return any(
        allowed_label == label and allowed_id == clause_id and quote in body
        for allowed_label, allowed_id, body in allowed_evidence
    )


def validate_analysis_response(
    result: AnalysisResponse,
    comparison: Comparison,
    *,
    before_complete: bool = False,
    after_complete: bool = False,
    allowed_evidence: Sequence[tuple[DocumentLabel, str, str]] | None = None,
) -> AnalysisResponse:
    """Keep only outputs whose exact citations and negative claims are verifiable.

    Completeness flags refer to the context sent to the model, not just to the
    full parsed documents. They prevent a bounded sample from being treated as
    proof that a department or function is absent.
    """

    def valid_citations(citations: Sequence[Citation]) -> bool:
        return bool(citations) and all(
            _citation_is_valid(item, comparison, allowed_evidence) for item in citations
        )

    departments: list[DepartmentChange] = []
    for change in result.department_changes:
        labels = {citation.document_label for citation in change.citations}
        if not valid_citations(change.citations):
            continue
        if change.status == "created":
            valid = (
                before_complete
                and change.name_before is None
                and bool(change.name_after)
                and labels == {"после"}
            )
        elif change.status == "removed":
            valid = (
                after_complete
                and bool(change.name_before)
                and change.name_after is None
                and labels == {"до"}
            )
        else:
            valid = bool(change.name_before and change.name_after and {"до", "после"} <= labels)
        if valid:
            departments.append(change)

    mappings: list[FunctionMapping] = []
    for mapping in result.function_mappings:
        labels = {citation.document_label for citation in mapping.citations}
        if not valid_citations(mapping.citations) or not mapping.old_function.strip():
            continue
        if mapping.status == "lost":
            valid = after_complete and "до" in labels and mapping.new_function is None
        else:
            valid = bool(mapping.new_function and {"до", "после"} <= labels)
            if mapping.status == "reassigned":
                valid = valid and bool(mapping.old_department and mapping.new_department)
        if valid:
            mappings.append(mapping)

    findings: list[Finding] = []
    for finding in result.findings:
        if not valid_citations(finding.citations):
            continue
        kind = _LEGACY_FINDING_KINDS.get(finding.kind, finding.kind)
        if kind not in {
            "possible_loss", "possible_duplication", "possible_conflict",
            "перераспределение ответственности", "другое изменение",
        }:
            continue
        labels = {citation.document_label for citation in finding.citations}
        if kind == "possible_loss":
            valid = "до" in labels and ("после" in labels or after_complete)
        elif kind in {"possible_duplication", "possible_conflict"}:
            # Different excerpts of the same point are still one source. Repeated
            # IDs may establish two sources only if quotes resolve each occurrence.
            after_evidence = {
                resolve_citation(comparison, citation)
                for citation in finding.citations
                if citation.document_label == "после"
            }
            valid = len(after_evidence) >= 2
        else:
            valid = True
        if valid:
            findings.append(finding.model_copy(update={"kind": kind}))

    summary = (
        f"Оставлено {len(departments)} изменений подразделений, "
        f"{len(mappings)} сопоставлений функций "
        f"и {len(findings)} сигналов с проверенными цитатами."
    )
    return AnalysisResponse(
        summary=summary,
        department_changes=departments,
        function_mappings=mappings,
        findings=findings,
    )
