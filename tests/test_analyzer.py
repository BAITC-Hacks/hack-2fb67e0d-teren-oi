from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from teren_oi.analyzer import analyze_changes, analyze_structure
from teren_oi.diff import compare_documents
from teren_oi.models import (
    AnalysisResponse,
    Citation,
    Clause,
    DepartmentChange,
    DocumentLabel,
    Finding,
    FunctionMapping,
    SourceDocument,
)


def _comparison():
    old = SourceDocument(
        "old.txt",
        (
            Clause(
                "2.1",
                "Подразделение Альфа поддерживает внутренние сервисы и обрабатывает эскалации.",
                "old.txt",
                "2.1",
            ),
            Clause(
                "2.2",
                "Подразделение Бета проверяет права доступа и сообщает об исключениях.",
                "old.txt",
                "2.2",
            ),
        ),
    )
    new = SourceDocument(
        "new.txt",
        (
            Clause("2.1", "Подразделение Гамма управляет архитектурой сети.", "new.txt", "2.1"),
            Clause("2.2", "Подразделение Дельта планирует внутренние проверки.", "new.txt", "2.2"),
            Clause(
                "2.3",
                "Подразделение Альфа поддерживает внутренние сервисы и обрабатывает эскалации.",
                "new.txt",
                "2.3",
            ),
            Clause("2.4", "Подразделение Эпсилон отслеживает качество услуг.", "new.txt", "2.4"),
        ),
    )
    return compare_documents(old, new)


def _citation(label: DocumentLabel, clause_id: str, quote: str) -> Citation:
    return Citation(document_label=label, clause_id=clause_id, quote=quote)


def _ai_response() -> AnalysisResponse:
    return AnalysisResponse(
        summary="This model-written summary is replaced with counts from validated output.",
        department_changes=[
            DepartmentChange(
                name_before=None,
                name_after="Подразделение Гамма",
                status="created",
                citations=[
                    _citation(
                        "после", "2.1", "Подразделение Гамма управляет архитектурой сети"
                    )
                ],
            ),
            DepartmentChange(
                name_before="Подразделение Альфа",
                name_after="Подразделение Альфа",
                status="retained",
                citations=[
                    _citation("до", "2.1", "Подразделение Альфа поддерживает внутренние сервисы"),
                    _citation(
                        "после", "2.3", "Подразделение Альфа поддерживает внутренние сервисы"
                    ),
                ],
            ),
            DepartmentChange(
                name_before=None,
                name_after="Несуществующее подразделение",
                status="created",
                citations=[_citation("после", "9.9", "Не существует")],
            ),
        ],
        function_mappings=[
            FunctionMapping(
                old_function="Проверять права доступа",
                new_function=None,
                old_department="Подразделение Бета",
                new_department=None,
                status="lost",
                confidence="medium",
                citations=[_citation("до", "2.2", "проверяет права доступа")],
            ),
            FunctionMapping(
                old_function="Поддерживать внутренние сервисы",
                new_function="Поддерживать внутренние сервисы",
                old_department="Подразделение Альфа",
                new_department="Подразделение Альфа",
                status="retained",
                confidence="high",
                citations=[
                    _citation("до", "2.1", "Подразделение Альфа поддерживает внутренние сервисы"),
                    _citation(
                        "после", "2.3", "Подразделение Альфа поддерживает внутренние сервисы"
                    ),
                ],
            ),
            FunctionMapping(
                old_function="Функция без источника",
                new_function=None,
                old_department=None,
                new_department=None,
                status="lost",
                confidence="high",
                citations=[_citation("до", "2.2", "выдуманный фрагмент")],
            ),
        ],
        findings=[
            Finding(
                kind="possible_loss",
                title="Possible loss",
                explanation="Review whether the responsibility was transferred.",
                confidence="medium",
                citations=[_citation("до", "2.2", "проверяет права доступа")],
            ),
            Finding(
                kind="possible_duplication",
                title="Possible duplication",
                explanation="Two new clauses need manual comparison.",
                confidence="low",
                citations=[
                    _citation("после", "2.1", "Подразделение Гамма управляет архитектурой сети"),
                    _citation("после", "2.4", "Подразделение Эпсилон отслеживает качество услуг"),
                ],
            ),
            Finding(
                kind="possible_conflict",
                title="Possible conflict",
                explanation="Clarify the division of decision-making responsibilities.",
                confidence="low",
                citations=[
                    _citation("после", "2.1", "Подразделение Гамма управляет архитектурой сети"),
                    _citation("после", "2.2", "Подразделение Дельта планирует внутренние проверки"),
                ],
            ),
        ],
    )


class AnalyzeStructureTests(unittest.TestCase):
    def _mock_openai(self):
        parsed = _ai_response()
        mock_client = SimpleNamespace(
            responses=SimpleNamespace(
                parse=lambda **_kwargs: SimpleNamespace(output_parsed=parsed)
            )
        )
        return mock_client

    def test_returns_evidence_validated_structures(self) -> None:
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"}),
            patch("teren_oi.analyzer.OpenAI", return_value=self._mock_openai()),
        ):
            result = analyze_structure(_comparison(), "gpt-5.6-terra")

        self.assertEqual(
            [item.status for item in result.department_changes], ["created", "retained"]
        )
        self.assertEqual([item.status for item in result.function_mappings], ["lost", "retained"])
        self.assertEqual(
            [item.kind for item in result.findings],
            ["possible_loss", "possible_duplication", "possible_conflict"],
        )
        self.assertIn("2 изменений подразделений", result.summary)
        self.assertIn("2 сопоставлений функций", result.summary)
        self.assertNotIn("This model-written summary", result.summary)

    def test_legacy_analyze_changes_adapter_keeps_web_finding_kinds(self) -> None:
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"}),
            patch("teren_oi.analyzer.OpenAI", return_value=self._mock_openai()),
        ):
            findings = analyze_changes(_comparison(), "gpt-5.6-terra")

        self.assertEqual(
            [item.kind for item in findings],
            [
                "потенциальная потеря функции",
                "потенциальное дублирование",
                "потенциальный конфликт интересов",
            ],
        )


if __name__ == "__main__":
    unittest.main()
