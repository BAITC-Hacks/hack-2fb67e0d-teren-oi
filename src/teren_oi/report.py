from __future__ import annotations

import json

from .models import Comparison, Finding, to_dict


def _change_dict(change):
    return {
        "clause_id": change.clause_id,
        "before": to_dict(change.before) if change.before else None,
        "after": to_dict(change.after) if change.after else None,
    }


def report_as_json(comparison: Comparison, findings: list[Finding], old_name: str, new_name: str) -> str:
    payload = {
        "documents": {"before": old_name, "after": new_name},
        "counts": {"added": len(comparison.added), "removed": len(comparison.removed),
                   "modified": len(comparison.modified), "unchanged": len(comparison.unchanged)},
        "changes": {kind: [_change_dict(item) for item in items] for kind, items in (
            ("added", comparison.added), ("removed", comparison.removed),
            ("modified", comparison.modified), ("unchanged", comparison.unchanged))},
        "findings": [finding.model_dump(mode="json") for finding in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def report_as_markdown(comparison: Comparison, findings: list[Finding], old_name: str, new_name: str) -> str:
    lines = ["# Сравнение редакций", "", f"- До: **{old_name}**", f"- После: **{new_name}**", "",
             "## Сводка", "", f"- Добавлено пунктов: {len(comparison.added)}",
             f"- Удалено пунктов: {len(comparison.removed)}", f"- Изменено пунктов: {len(comparison.modified)}",
             f"- Без изменений: {len(comparison.unchanged)}", ""]
    if findings:
        lines.extend(["## Аналитические выводы", ""])
        for finding in findings:
            lines.extend([f"### {finding.kind}: {finding.title}", "", finding.explanation,
                          f"Уверенность: **{finding.confidence}**", ""])
            for cite in finding.citations:
                lines.append(f"> {cite.document_label}, пункт {cite.clause_id}: «{cite.quote}»")
            lines.append("")
    for title, changes in (("Добавленные пункты", comparison.added), ("Удалённые пункты", comparison.removed),
                           ("Изменённые пункты", comparison.modified)):
        lines.extend([f"## {title}", ""])
        if not changes:
            lines.extend(["Нет.", ""])
        for change in changes:
            lines.extend([f"### Пункт {change.clause_id}", ""])
            if change.before:
                lines.extend([f"**До:** {change.before.text}", ""])
            if change.after:
                lines.extend([f"**После:** {change.after.text}", ""])
    return "\n".join(lines)
