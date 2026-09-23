from __future__ import annotations

import json
from collections.abc import Iterable

from .models import Change, Citation, Clause, Comparison, Finding, to_dict

LIMITATIONS = (
    "AI-выводы являются рекомендациями и требуют проверки человеком.",
    "Детерминированное сравнение сопоставляет пункты по clause_id; перенумерация "
    "может выглядеть как удаление и добавление.",
    "OCR сканированных PDF не входит в MVP.",
)


def _change_dict(change: Change) -> dict[str, object]:
    return {
        "clause_id": change.clause_id,
        "before": to_dict(change.before) if change.before else None,
        "after": to_dict(change.after) if change.after else None,
    }


def _document_clauses(comparison: Comparison, document_label: str) -> tuple[Clause, ...]:
    if document_label == "до":
        return comparison.old_document.clauses
    return comparison.new_document.clauses


def _resolve_citation(comparison: Comparison, citation: Citation) -> Clause | None:
    quote = citation.quote.strip()
    return next(
        (
            clause
            for clause in _document_clauses(comparison, citation.document_label)
            if clause.clause_id == citation.clause_id and quote in clause.text
        ),
        None,
    )


def _validated_findings(
    comparison: Comparison, findings: Iterable[Finding]
) -> list[tuple[Finding, list[tuple[Citation, Clause]]]]:
    validated: list[tuple[Finding, list[tuple[Citation, Clause]]]] = []
    for finding in findings:
        evidence: list[tuple[Citation, Clause]] = []
        for citation in finding.citations:
            clause = _resolve_citation(comparison, citation)
            if clause is None:
                evidence = []
                break
            evidence.append((citation, clause))
        if evidence:
            validated.append((finding, evidence))
    return validated


def _finding_dict(finding: Finding, evidence: list[tuple[Citation, Clause]]) -> dict[str, object]:
    payload = finding.model_dump(mode="json")
    payload["evidence"] = [
        {
            "document_label": citation.document_label,
            "clause_id": citation.clause_id,
            "quote": citation.quote,
            "source": clause.source,
            "location": clause.location,
        }
        for citation, clause in evidence
    ]
    return payload


def _executive_summary(comparison: Comparison, finding_count: int) -> str:
    return (
        f"Сопоставлено {len(comparison.old_document.clauses)} пунктов версии «до» и "
        f"{len(comparison.new_document.clauses)} пунктов версии «после»: "
        f"добавлено {len(comparison.added)}, удалено {len(comparison.removed)}, "
        f"изменено {len(comparison.modified)}. Подтверждённых аналитических выводов: "
        f"{finding_count}."
    )


def report_as_json(
    comparison: Comparison,
    findings: list[Finding],
    old_name: str,
    new_name: str,
) -> str:
    validated = _validated_findings(comparison, findings)
    payload = {
        "documents": {"before": old_name, "after": new_name},
        "executive_summary": _executive_summary(comparison, len(validated)),
        "counts": {
            "added": len(comparison.added),
            "removed": len(comparison.removed),
            "modified": len(comparison.modified),
            "unchanged": len(comparison.unchanged),
        },
        "changes": {
            kind: [_change_dict(item) for item in items]
            for kind, items in (
                ("added", comparison.added),
                ("removed", comparison.removed),
                ("modified", comparison.modified),
                ("unchanged", comparison.unchanged),
            )
        },
        "findings": [_finding_dict(finding, evidence) for finding, evidence in validated],
        "limitations": list(LIMITATIONS),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _append_change(lines: list[str], change: Change) -> None:
    lines.extend([f"### Пункт {change.clause_id}", ""])
    if change.before:
        lines.extend(
            [
                f"- **До — {change.before.source}, {change.before.location}:** "
                f"{change.before.text}",
                "",
            ]
        )
    if change.after:
        lines.extend(
            [
                f"- **После — {change.after.source}, {change.after.location}:** "
                f"{change.after.text}",
                "",
            ]
        )


def _append_findings(
    lines: list[str],
    findings: Iterable[tuple[Finding, list[tuple[Citation, Clause]]]],
) -> None:
    rendered = False
    for finding, evidence in findings:
        rendered = True
        lines.extend(
            [
                f"### {finding.title}",
                "",
                finding.explanation,
                "",
                f"Уверенность: **{finding.confidence}**",
                "",
            ]
        )
        for citation, clause in evidence:
            lines.append(
                f"> {citation.document_label.capitalize()} — {clause.source}, "
                f"{clause.location}, пункт {citation.clause_id}: «{citation.quote}»"
            )
        lines.append("")
    if not rendered:
        lines.extend(["Нет подтверждённых выводов по доступным источникам.", ""])


def report_as_markdown(
    comparison: Comparison,
    findings: list[Finding],
    old_name: str,
    new_name: str,
) -> str:
    validated = _validated_findings(comparison, findings)
    losses = [item for item in validated if item[0].kind == "потенциальная потеря функции"]
    duplications = [item for item in validated if item[0].kind == "потенциальное дублирование"]
    mappings = [item for item in validated if item[0].kind == "перераспределение ответственности"]
    conflicts = [
        item
        for item in validated
        if "конфликт" in f"{item[0].title} {item[0].explanation}".casefold()
    ]

    lines = [
        "# Аналитическое заключение Teren Oi",
        "",
        f"- До: **{old_name}**",
        f"- После: **{new_name}**",
        "",
        "## Executive Summary / Итоговая сводка",
        "",
        _executive_summary(comparison, len(validated)),
        "",
        "## Structural Changes / Структурные изменения",
        "",
        "Ниже приведены детерминированные изменения пунктов; наименования подразделений "
        "не выводятся без подтверждённого анализа.",
        "",
    ]
    for title, changes in (
        ("Добавленные пункты", comparison.added),
        ("Удалённые пункты", comparison.removed),
        ("Изменённые пункты", comparison.modified),
    ):
        lines.extend([f"### {title}", ""])
        if not changes:
            lines.extend(["Нет.", ""])
        for change in changes:
            _append_change(lines, change)

    lines.extend(["## Function Mapping / Сопоставление функций", ""])
    _append_findings(lines, mappings)

    lines.extend(["## Potential Lost Functions / Потенциально потерянные функции", ""])
    _append_findings(lines, losses)

    lines.extend(["## Potential Duplications / Потенциальное дублирование", ""])
    _append_findings(lines, duplications)

    lines.extend(["## Potential Conflicts / Потенциальные конфликты", ""])
    _append_findings(lines, conflicts)

    lines.extend(["## Evidence / Доказательства", ""])
    if validated:
        for finding, evidence in validated:
            lines.extend([f"### {finding.title}", ""])
            for citation, clause in evidence:
                lines.extend(
                    [
                        f"- **{citation.document_label.capitalize()} — {clause.source}; "
                        f"{clause.location}; пункт {citation.clause_id}:** "
                        f"«{citation.quote}»",
                        "",
                    ]
                )
    else:
        lines.extend(["Нет подтверждённых аналитических выводов.", ""])

    lines.extend(["## Limitations / Ограничения", ""])
    lines.extend(f"- {limitation}" for limitation in LIMITATIONS)
    lines.append("")
    return "\n".join(lines)
