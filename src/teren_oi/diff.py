from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

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


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _clause_index(document: SourceDocument) -> dict[str, str]:
    """Index clauses by stable id; duplicate IDs are kept distinct instead of silently lost."""
    totals: defaultdict[str, int] = defaultdict(int)
    index: dict[str, str] = {}
    for clause in document.clauses:
        totals[clause.clause_id] += 1
        key = (
            clause.clause_id
            if totals[clause.clause_id] == 1
            else f"{clause.clause_id}#{totals[clause.clause_id]}"
        )
        index[key] = clause.clause_id
    return index


def compare_documents(old: SourceDocument, new: SourceDocument) -> Comparison:
    old_index, new_index = _clause_index(old), _clause_index(new)
    old_by_key = {key: clause for clause, (key, _) in zip(old.clauses, old_index.items())}
    new_by_key = {key: clause for clause, (key, _) in zip(new.clauses, new_index.items())}
    added: list[Change] = []
    removed: list[Change] = []
    modified: list[Change] = []
    unchanged: list[Change] = []
    for key in old_by_key.keys() | new_by_key.keys():
        before, after = old_by_key.get(key), new_by_key.get(key)
        clause_id = (after or before).clause_id  # type: ignore[union-attr]
        if before is None:
            added.append(Change(clause_id, None, after))
        elif after is None:
            removed.append(Change(clause_id, before, None))
        elif normalize(before.text) == normalize(after.text):
            unchanged.append(Change(clause_id, before, after))
        else:
            modified.append(Change(clause_id, before, after))
    def key_order(item: Change) -> list[int | str]:
        return [
            int(part) if part.isdigit() else part
            for part in re.split(r"(\d+)", item.clause_id)
        ]

    return Comparison(
        old,
        new,
        tuple(sorted(added, key=key_order)),
        tuple(sorted(removed, key=key_order)),
        tuple(sorted(modified, key=key_order)),
        tuple(sorted(unchanged, key=key_order)),
    )


_LEGACY_FINDING_KINDS: dict[str, FindingKind] = {
    "потенциальная потеря функции": "possible_loss",
    "потенциальное дублирование": "possible_duplication",
    "потенциальный конфликт интересов": "possible_conflict",
    "перераспределение ответственности": "possible_conflict",
}


def _citation_is_valid(
    citation: Citation,
    comparison: Comparison,
    allowed_evidence: Sequence[tuple[DocumentLabel, str, str]] | None,
) -> bool:
    label = citation.document_label
    clause_id = citation.clause_id
    quote = citation.quote.strip()
    document = (
        comparison.old_document if label == "до"
        else comparison.new_document if label == "после"
        else None
    )
    citation_is_from_source = bool(
        document
        and clause_id
        and quote
        and any(
            clause.clause_id == clause_id and quote in clause.text
            for clause in document.clauses
        )
    )
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
        if kind not in {"possible_loss", "possible_duplication", "possible_conflict"}:
            continue
        labels = {citation.document_label for citation in finding.citations}
        if kind == "possible_loss":
            valid = "до" in labels and ("после" in labels or after_complete)
        elif kind in {"possible_duplication", "possible_conflict"}:
            after_evidence = {
                (citation.clause_id, citation.quote.strip())
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
