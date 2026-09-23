from __future__ import annotations

import json
import unittest

from teren_oi.diff import compare_documents
from teren_oi.models import Citation, Clause, Comparison, Finding, SourceDocument
from teren_oi.report import report_as_json, report_as_markdown


def _comparison() -> Comparison:
    old = SourceDocument(
        name="old.docx",
        clauses=(Clause("5.1", "Проводит внутренний аудит", "old.docx", "block 2 / section 5.1"),),
    )
    new = SourceDocument(
        name="new.pdf",
        clauses=(Clause("5.1", "Проводит ИТ-аудит", "new.pdf", "page 3 / block 1 / section 5.1"),),
    )
    return compare_documents(old, new)


def _finding(quote: str, title: str = "Изменение функции") -> Finding:
    return Finding(
        kind="перераспределение ответственности",
        title=title,
        explanation="Функция была уточнена.",
        confidence="высокая",
        citations=[Citation(document_label="после", clause_id="5.1", quote=quote)],
    )


class ReportTests(unittest.TestCase):
    def test_json_resolves_source_and_location_for_valid_evidence(self) -> None:
        payload = json.loads(
            report_as_json(
                _comparison(),
                [_finding("ИТ-аудит")],
                "old.docx",
                "new.pdf",
            )
        )

        self.assertEqual(len(payload["findings"]), 1)
        evidence = payload["findings"][0]["evidence"][0]
        self.assertEqual(evidence["source"], "new.pdf")
        self.assertIn("page 3", evidence["location"])
        self.assertIn("limitations", payload)

    def test_report_omits_finding_when_quote_is_not_in_source(self) -> None:
        comparison = _comparison()
        markdown = report_as_markdown(
            comparison,
            [_finding("Несуществующая цитата", "Неподтверждённый вывод")],
            "old.docx",
            "new.pdf",
        )
        payload = json.loads(
            report_as_json(
                comparison,
                [_finding("Несуществующая цитата", "Неподтверждённый вывод")],
                "old.docx",
                "new.pdf",
            )
        )

        self.assertNotIn("Неподтверждённый вывод", markdown)
        self.assertEqual(payload["findings"], [])

    def test_markdown_contains_required_sections_and_traceability(self) -> None:
        markdown = report_as_markdown(
            _comparison(),
            [_finding("ИТ-аудит")],
            "old.docx",
            "new.pdf",
        )

        for heading in (
            "Executive Summary",
            "Structural Changes",
            "Function Mapping",
            "Potential Lost Functions",
            "Potential Duplications",
            "Potential Conflicts",
            "Evidence",
            "Limitations",
        ):
            self.assertIn(heading, markdown)
        self.assertIn("new.pdf", markdown)
        self.assertIn("page 3 / block 1 / section 5.1", markdown)


if __name__ == "__main__":
    unittest.main()
