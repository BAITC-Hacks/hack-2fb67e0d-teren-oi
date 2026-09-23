"""Resolve evidence once for UI and reports, including repeated clause numbers."""

from collections.abc import Iterable

from .models import Citation, Clause, Comparison, Finding


def resolve_citation(comparison: Comparison, citation: Citation) -> Clause | None:
    quote = citation.quote.strip()
    if not quote:
        return None
    document = comparison.old_document if citation.document_label == "до" else comparison.new_document
    matches = [
        clause for clause in document.clauses
        if clause.clause_id == citation.clause_id and quote in clause.text
    ]
    # The same number and quote may belong to different sections. Do not invent
    # a source position when the citation cannot distinguish those occurrences.
    return matches[0] if len(matches) == 1 else None


def validated_findings(
    comparison: Comparison, findings: Iterable[Finding]
) -> list[tuple[Finding, list[tuple[Citation, Clause]]]]:
    validated = []
    for finding in findings:
        evidence = []
        for citation in finding.citations:
            clause = resolve_citation(comparison, citation)
            if clause is None:
                break
            evidence.append((citation, clause))
        else:
            if evidence:
                validated.append((finding, evidence))
    return validated
