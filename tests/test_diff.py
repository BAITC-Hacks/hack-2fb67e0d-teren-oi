from __future__ import annotations

import unittest

from teren_oi.diff import compare_documents, validate_analysis_response
from teren_oi.models import (
    AnalysisResponse,
    Citation,
    Clause,
    DepartmentChange,
    Finding,
    FunctionMapping,
    SourceDocument,
)


def _comparison():
    old = SourceDocument(
        "old.txt",
        (
            Clause("1.1", "Отдел А проверяет обращения клиентов.", "old.txt", "1.1"),
            Clause("1.2", "Отдел Б ведёт журнал обращений.", "old.txt", "1.2"),
        ),
    )
    new = SourceDocument(
        "new.txt",
        (
            Clause("1.1", "Отдел А обрабатывает обращения клиентов.", "new.txt", "1.1"),
            Clause("1.2", "Отдел Б ведёт журнал обращений.", "new.txt", "1.2"),
            Clause("1.3", "Отдел В проверяет качество услуг.", "new.txt", "1.3"),
        ),
    )
    return compare_documents(old, new)


class CitationValidationTests(unittest.TestCase):
    def test_fabricated_citation_is_rejected(self) -> None:
        comparison = _comparison()
        result = AnalysisResponse(
            summary="ignored",
            department_changes=[],
            function_mappings=[],
            findings=[Finding(
                kind="possible_loss",
                title="Проверка",
                explanation="Проверка",
                confidence="medium",
                citations=[
                    Citation(document_label="до", clause_id="9.9", quote="выдуманная цитата")
                ],
            )],
        )

        validated = validate_analysis_response(
            result, comparison, before_complete=True, after_complete=True
        )

        self.assertEqual(validated.findings, [])

    def test_valid_exact_citation_survives(self) -> None:
        comparison = _comparison()
        result = AnalysisResponse(
            summary="ignored",
            department_changes=[],
            function_mappings=[],
            findings=[Finding(
                kind="possible_loss",
                title="Проверка функции",
                explanation="Требуется проверить перенос обязанности.",
                confidence="low",
                citations=[Citation(
                    document_label="до",
                    clause_id="1.1",
                    quote="проверяет обращения клиентов",
                )],
            )],
        )

        validated = validate_analysis_response(
            result, comparison, before_complete=True, after_complete=True
        )

        self.assertEqual(len(validated.findings), 1)
        self.assertEqual(validated.findings[0].kind, "possible_loss")

    def test_source_valid_but_unsupplied_citation_is_rejected(self) -> None:
        comparison = _comparison()
        result = AnalysisResponse(
            summary="ignored",
            department_changes=[],
            function_mappings=[],
            findings=[Finding(
                kind="possible_loss",
                title="Проверка функции",
                explanation="Требуется проверить перенос обязанности.",
                confidence="low",
                citations=[Citation(
                    document_label="до",
                    clause_id="1.2",
                    quote="Отдел Б ведёт журнал обращений",
                )],
            )],
        )

        validated = validate_analysis_response(
            result,
            comparison,
            before_complete=True,
            after_complete=True,
            allowed_evidence=[("до", "1.1", "Отдел А проверяет обращения клиентов.")],
        )

        self.assertEqual(validated.findings, [])

    def test_created_and_retained_departments_are_representable(self) -> None:
        created = DepartmentChange(
            name_before=None,
            name_after="Департамент В",
            status="created",
            citations=[Citation(
                document_label="после", clause_id="1.3", quote="Отдел В проверяет качество услуг"
            )],
        )
        retained = DepartmentChange(
            name_before="Отдел Б",
            name_after="Отдел Б",
            status="retained",
            citations=[
                Citation(document_label="до", clause_id="1.2", quote="Отдел Б ведёт журнал"),
                Citation(document_label="после", clause_id="1.2", quote="Отдел Б ведёт журнал"),
            ],
        )

        self.assertEqual(created.status, "created")
        self.assertEqual(retained.status, "retained")

    def test_created_department_requires_complete_old_context(self) -> None:
        comparison = _comparison()
        result = AnalysisResponse(
            summary="ignored",
            department_changes=[DepartmentChange(
                name_before=None,
                name_after="Отдел В",
                status="created",
                citations=[Citation(
                    document_label="после",
                    clause_id="1.3",
                    quote="Отдел В проверяет качество услуг",
                )],
            )],
            function_mappings=[],
            findings=[],
        )

        incomplete = validate_analysis_response(result, comparison, after_complete=True)
        complete = validate_analysis_response(
            result, comparison, before_complete=True, after_complete=True
        )

        self.assertEqual(incomplete.department_changes, [])
        self.assertEqual(len(complete.department_changes), 1)

    def test_removed_department_requires_complete_after_context(self) -> None:
        comparison = _comparison()
        result = AnalysisResponse(
            summary="ignored",
            department_changes=[DepartmentChange(
                name_before="Отдел А",
                name_after=None,
                status="removed",
                citations=[Citation(
                    document_label="до", clause_id="1.1", quote="Отдел А проверяет обращения"
                )],
            )],
            function_mappings=[],
            findings=[],
        )

        incomplete = validate_analysis_response(result, comparison, before_complete=True)
        complete = validate_analysis_response(
            result, comparison, before_complete=True, after_complete=True
        )

        self.assertEqual(incomplete.department_changes, [])
        self.assertEqual(len(complete.department_changes), 1)

    def test_lost_function_mapping_is_representable_but_needs_complete_after(self) -> None:
        comparison = _comparison()
        mapping = FunctionMapping(
            old_function="Проверяет обращения клиентов",
            new_function=None,
            old_department="Отдел А",
            new_department=None,
            status="lost",
            confidence="medium",
            citations=[Citation(
                document_label="до", clause_id="1.1", quote="проверяет обращения клиентов"
            )],
        )
        result = AnalysisResponse(
            summary="ignored",
            department_changes=[],
            function_mappings=[mapping],
            findings=[],
        )

        incomplete = validate_analysis_response(result, comparison, before_complete=True)
        complete = validate_analysis_response(
            result, comparison, before_complete=True, after_complete=True
        )

        self.assertEqual(incomplete.function_mappings, [])
        self.assertEqual(complete.function_mappings[0].status, "lost")

    def test_possible_duplication_and_conflict_need_two_after_citations(self) -> None:
        comparison = _comparison()
        result = AnalysisResponse(
            summary="ignored",
            department_changes=[],
            function_mappings=[],
            findings=[
                Finding(
                    kind="possible_duplication",
                    title="Недостаточно источников",
                    explanation="Есть только один пункт.",
                    confidence="low",
                    citations=[Citation(
                        document_label="после",
                        clause_id="1.1",
                        quote="Отдел А обрабатывает обращения",
                    )],
                ),
                Finding(
                    kind="possible_conflict",
                    title="Пересечение обязанностей",
                    explanation="Оба отдела описаны в новой редакции.",
                    confidence="medium",
                    citations=[
                        Citation(
                            document_label="после",
                            clause_id="1.1",
                            quote="Отдел А обрабатывает обращения клиентов",
                        ),
                        Citation(
                            document_label="после",
                            clause_id="1.3",
                            quote="Отдел В проверяет качество услуг",
                        ),
                    ],
                ),
            ],
        )

        validated = validate_analysis_response(result, comparison, after_complete=True)

        self.assertEqual([item.kind for item in validated.findings], ["possible_conflict"])

    def test_compare_documents_still_separates_added_modified_and_unchanged(self) -> None:
        comparison = _comparison()

        self.assertEqual([item.clause_id for item in comparison.unchanged], ["1.2"])
        self.assertEqual([item.clause_id for item in comparison.modified], ["1.1"])
        self.assertEqual([item.clause_id for item in comparison.added], ["1.3"])
        self.assertEqual(comparison.removed, ())


if __name__ == "__main__":
    unittest.main()
