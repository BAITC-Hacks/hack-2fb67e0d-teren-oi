from __future__ import annotations

import json
import re
from collections.abc import Iterable

from .models import Change, Citation, Clause, Comparison, Finding, to_dict
from .evidence import validated_findings as _validated_findings

LIMITATIONS = (
    "AI-выводы являются рекомендациями и требуют проверки человеком.",
    "AI анализирует ограниченную выборку пунктов; длинные пункты могут быть усечены.",
    "Автоматический сигнал об удалённом пункте не доказывает потерю функции: она могла быть перенесена.",
    "Точное сравнение учитывает однозначно совпадающий текст и номера пунктов. "
    "Перенумерация с изменением формулировки может выглядеть как удаление и добавление.",
    "OCR сканированных PDF не входит в MVP.",
)


def escape_markdown(value: str, *, inline: bool = False) -> str:
    """Keep document/model text literal inside the authored Markdown report.

    Source quotes retain their words and line breaks. Metadata and finding titles
    use a single line so they cannot terminate an authored heading or bold label.
    Exporters decode these escapes without treating the decoded text as markup.
    """
    if inline:
        value = " ".join(value.splitlines())
    value = "".join("\\" + char if char in "\\`*_[]<>#|" else char for char in value)
    return re.sub(r"(?m)^(\s*)([-+])(?=\s)", r"\1\\\2", value)


def _change_dict(change: Change) -> dict[str, object]:
    return {
        "clause_id": change.clause_id,
        "before": to_dict(change.before) if change.before else None,
        "after": to_dict(change.after) if change.after else None,
    }


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
        f"изменено {len(comparison.modified)}. Сигналов для проверки по источникам: "
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
    lines.extend([f"### Пункт {escape_markdown(change.clause_id, inline=True)}", ""])
    if change.before:
        lines.extend(
            [
                f"- **До — пункт {escape_markdown(change.before.clause_id, inline=True)}; "
                f"{escape_markdown(change.before.source, inline=True)}, "
                f"{escape_markdown(change.before.location, inline=True)}:** "
                f"{escape_markdown(change.before.text)}",
                "",
            ]
        )
    if change.after:
        lines.extend(
            [
                f"- **После — пункт {escape_markdown(change.after.clause_id, inline=True)}; "
                f"{escape_markdown(change.after.source, inline=True)}, "
                f"{escape_markdown(change.after.location, inline=True)}:** "
                f"{escape_markdown(change.after.text)}",
                "",
            ]
        )


def _append_findings(
    lines: list[str],
    findings: Iterable[tuple[Finding, list[tuple[Citation, Clause]]]],
    origins: dict[int, str] | None = None,
) -> None:
    rendered = False
    for finding, evidence in findings:
        rendered = True
        lines.extend(
            [
                f"### {escape_markdown(finding.title, inline=True)}",
                "",
                escape_markdown(finding.explanation),
                "",
                ("Источник: локальное сопоставление. Требуется ручная проверка."
                 if origins and origins.get(id(finding)) == "local"
                 else f"Оценка модели: **{finding.confidence}** (не вероятность). Требуется проверка человеком."),
                "",
            ]
        )
        for citation, clause in evidence:
            lines.append(
                f"> {citation.document_label.capitalize()} — {escape_markdown(clause.source, inline=True)}, "
                f"{escape_markdown(clause.location, inline=True)}, "
                f"пункт {escape_markdown(citation.clause_id, inline=True)}: «{escape_markdown(citation.quote)}»"
            )
        lines.append("")
    if not rendered:
        lines.extend(["Нет сигналов для проверки по доступным источникам.", ""])


def report_as_markdown(
    comparison: Comparison,
    findings: list[Finding],
    old_name: str,
    new_name: str,
    *,
    finding_origins: list[str] | None = None,
    context: list[str] | None = None,
) -> str:
    origins = {id(item): origin for item, origin in zip(findings, finding_origins or [])}
    validated = _validated_findings(comparison, findings)
    local = [item for item in validated if origins.get(id(item[0])) == "local"]
    losses = [item for item in validated if item[0].kind == "потенциальная потеря функции"
              and origins.get(id(item[0])) != "local"]
    duplications = [item for item in validated if item[0].kind == "потенциальное дублирование"]
    mappings = [item for item in validated if item[0].kind == "перераспределение ответственности"]
    conflicts = [
        item
        for item in validated
        if "конфликт" in f"{item[0].kind} {item[0].title} {item[0].explanation}".casefold()
    ]

    lines = [
        "# Аналитическое заключение Tereñ oi",
        "",
        f"- До: **{escape_markdown(old_name, inline=True)}**",
        f"- После: **{escape_markdown(new_name, inline=True)}**",
        "",
        "## Executive Summary / Итоговая сводка",
        "",
        _executive_summary(comparison, len(validated)),
        "",
        *(context or []),
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
        ("Перенумерованные пункты с тем же текстом", tuple(
            item for item in comparison.unchanged
            if item.before and item.after and item.before.clause_id != item.after.clause_id
        )),
    ):
        lines.extend([f"### {title}", ""])
        if not changes:
            lines.extend(["Нет.", ""])
        for change in changes:
            _append_change(lines, change)

    lines.extend(["## Function Mapping / Дополнительные замечания о перераспределении ответственности", ""])
    _append_findings(lines, mappings, origins)

    lines.extend(["## Potential Lost Functions / Потенциально потерянные функции", ""])
    _append_findings(lines, losses, origins)

    lines.extend(["## Local Signals / Локальные сигналы точного сравнения", "",
                  "Удалённые пункты требуют проверки переноса; это не вывод ИИ о потере функции.", ""])
    _append_findings(lines, local, origins)

    lines.extend(["## Potential Duplications / Потенциальное дублирование", ""])
    _append_findings(lines, duplications, origins)

    lines.extend(["## Potential Conflicts / Потенциальные конфликты", ""])
    _append_findings(lines, conflicts, origins)

    lines.extend(["## Other Findings / Другие изменения", ""])
    _append_findings(lines, [item for item in validated if item[0].kind == "другое изменение"], origins)

    lines.extend(["## Evidence / Доказательства", ""])
    if validated:
        for finding, evidence in validated:
            lines.extend([f"### {escape_markdown(finding.title, inline=True)}", ""])
            for citation, clause in evidence:
                lines.extend(
                    [
                        f"- **{citation.document_label.capitalize()} — {escape_markdown(clause.source, inline=True)}; "
                        f"{escape_markdown(clause.location, inline=True)}; "
                        f"пункт {escape_markdown(citation.clause_id, inline=True)}:** "
                        f"«{escape_markdown(citation.quote)}»",
                        "",
                    ]
                )
    else:
        lines.extend(["Нет сигналов для проверки по доступным источникам.", ""])

    lines.extend(["## Limitations / Ограничения", ""])
    lines.extend(f"- {limitation}" for limitation in LIMITATIONS)
    lines.append("")
    return "\n".join(lines)
