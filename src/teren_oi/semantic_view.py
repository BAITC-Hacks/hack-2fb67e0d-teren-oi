"""Presentation adapters for the validated semantic core; exact diff stays intact."""

from collections import Counter

from .evidence import resolve_citation
from .models import Comparison
from .report import escape_markdown


STATUS_LABELS = {
    "created": "Создано", "retained": "Сохранено", "reorganized": "Преобразовано",
    "removed": "Удалено", "changed": "Изменено", "reassigned": "Передано",
    "lost": "Возможная потеря",
}


def evidence_payload(item, comparison: Comparison) -> dict:
    payload = item.model_dump(mode="json")
    for citation, original in zip(payload["citations"], item.citations):
        clause = resolve_citation(comparison, original)
        if clause is not None:
            citation.update(source=clause.source, location=clause.location)
    return payload


def semantic_units(units: list[dict], departments: list, comparison: Comparison) -> list[dict]:
    """Override only unambiguous named assessments; retain provenance and filter IDs."""
    def key(name: str) -> str:
        return " ".join(name.split()).casefold()

    names = [{key(name) for name in (item.name_before, item.name_after) if name}
             for item in departments]
    counts = Counter(name for group in names for name in group)
    result = [{**unit, "origin": "local", "citations": []} for unit in units]
    changes = (*comparison.removed, *comparison.modified, *comparison.added, *comparison.unchanged)
    for item, group in zip(departments, names):
        if any(counts[name] > 1 for name in group):
            continue  # Contradictory/overlapping model assessments cannot replace a unit.
        matched = [unit for unit in result if key(unit["name"]) in group]
        cited = {resolve_citation(comparison, citation) for citation in item.citations}
        change_ids = {change_id for unit in matched for change_id in unit["change_ids"]}
        change_ids.update(f"change-{index}" for index, change in enumerate(changes, 1)
                          if any(clause is not None and clause in cited for clause in (change.before, change.after)))
        result = [unit for unit in result if key(unit["name"]) not in group]
        result.append({
            "name": item.name_after or item.name_before,
            "name_before": item.name_before, "name_after": item.name_after,
            "status": "transformed" if item.status == "reorganized" else item.status,
            "origin": "ai", "citations": evidence_payload(item, comparison)["citations"],
            "clause_ids": sorted({citation.clause_id for citation in item.citations}),
            "change_ids": sorted(change_ids),
        })
    return sorted(result, key=lambda unit: key(unit["name"]))


def semantic_report(departments: list[dict], mappings: list[dict]) -> list[str]:
    """Use the same semantic payload in both downloadable formats."""
    lines: list[str] = []
    for title, items, before, after in (
        ("Изменения подразделений — оценка ИИ", departments, "name_before", "name_after"),
        ("Смысловое сопоставление функций — оценка ИИ", mappings, "old_function", "new_function"),
    ):
        if not items:
            continue
        lines.extend([f"## {title}", "", "Цитаты проверены. Смысловые оценки требуют проверки экспертом.", ""])
        for item in items:
            lines.extend([
                f"### {STATUS_LABELS[item['status']]}", "",
                f"До: {escape_markdown(item.get(before) or '—')}", "",
                f"После: {escape_markdown(item.get(after) or '—')}", "",
            ])
            if "old_department" in item:
                lines.extend(["Подразделения: " + escape_markdown(item.get("old_department") or "—", inline=True)
                              + " → " + escape_markdown(item.get("new_department") or "—", inline=True), ""])
            for citation in item["citations"]:
                label = f"{citation['document_label']} · {citation['clause_id']} · {citation.get('source', '')} · {citation.get('location', '')}"
                lines.extend([f"Источник: {escape_markdown(label, inline=True)}", "",
                              escape_markdown(citation["quote"]), ""])
    return lines
