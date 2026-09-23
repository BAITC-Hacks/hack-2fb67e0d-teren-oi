from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from teren_oi import analyzer
from teren_oi.diff import compare_documents
from teren_oi.models import AnalysisResponse, Clause, Finding, SourceDocument


def document(name: str, *bodies: tuple[str, str]) -> SourceDocument:
    return SourceDocument(name, tuple(
        Clause(clause_id, text, name, f"line {index}")
        for index, (clause_id, text) in enumerate(bodies, start=1)
    ))


def finding(quote: str, *, clause_id: str = "1", label: str = "после") -> Finding:
    return Finding.model_validate({
        "kind": "другое изменение", "title": "Изменена задача",
        "explanation": "Задача требует проверки.", "confidence": "низкая",
        "citations": [{"document_label": label, "clause_id": clause_id, "quote": quote}],
    })


class AiResultTests(unittest.TestCase):
    def test_success_has_real_call_and_never_exposes_unvalidated_summary(self) -> None:
        comparison = compare_documents(
            document("before", ("1", "Собирает данные"), ("2", "Проверяет отчёт")),
            document("after", ("1", "Анализирует данные"), ("2", "Проверяет отчёт")),
        )
        response = AnalysisResponse(summary="Неподтверждённое утверждение", findings=[
            finding("Анализирует данные"), finding("Выдуманная цитата"),
        ])
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unit-test-placeholder"}), \
                patch.object(analyzer, "OpenAI") as client:
            client.return_value.responses.parse.return_value = SimpleNamespace(output_parsed=response)
            result = analyzer.analyze_with_metadata(comparison, "test-model")
        self.assertTrue(result.called)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.rejected_findings, 1)
        self.assertEqual(result.coverage, {
            "total_clauses": 3, "included_clauses": 3,
            "omitted_clauses": 0, "truncated_clauses": 0,
        })
        self.assertFalse(hasattr(result, "summary"))
        client.assert_called_once_with(timeout=60.0, max_retries=0)

    def test_unchanged_documents_do_not_require_key_or_call_model(self) -> None:
        source = document("same", ("1", "Проверяет отчёт"))
        comparison = compare_documents(source, source)
        with patch.dict("os.environ", {}, clear=True), patch.object(analyzer, "OpenAI") as client:
            result = analyzer.analyze_with_metadata(comparison, "test-model")
            self.assertEqual(analyzer.analyze_changes(comparison, "test-model"), [])
        client.assert_not_called()
        self.assertFalse(result.called)
        self.assertEqual(result.coverage["included_clauses"], 0)
        self.assertEqual(result.coverage["omitted_clauses"], 1)

    def test_repeated_id_requires_unambiguous_full_source_occurrence(self) -> None:
        comparison = compare_documents(
            document("before"),
            document("after", ("1", "Общая функция отдела А"), ("1", "Общая функция отдела Б")),
        )
        response = AnalysisResponse(summary="", findings=[
            finding("Общая функция"), finding("Общая функция отдела Б"),
            finding("Общая функция отдела Б", label="до"),
        ])
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unit-test-placeholder"}), \
                patch.object(analyzer, "OpenAI") as client:
            client.return_value.responses.parse.return_value = SimpleNamespace(output_parsed=response)
            result = analyzer.analyze_with_metadata(comparison, "test-model")
        self.assertEqual(result.rejected_findings, 2)
        self.assertEqual(result.findings[0].citations[0].quote, "Общая функция отдела Б")

    def test_coverage_counts_truncation_and_budget_omissions(self) -> None:
        comparison = compare_documents(document("before"), document(
            "after", *((str(index), "Я" * 2_000) for index in range(40)),
        ))
        coverage = analyzer.evidence_coverage(comparison, sent=True)
        self.assertEqual(coverage["total_clauses"], 40)
        self.assertGreater(coverage["omitted_clauses"], 0)
        self.assertEqual(coverage["included_clauses"] + coverage["omitted_clauses"], 40)
        self.assertEqual(coverage["truncated_clauses"], coverage["included_clauses"])
        self.assertLessEqual(sum(len(item[3]) for item in analyzer._evidence(comparison)), 32_000)
        self.assertEqual(analyzer.evidence_coverage(comparison)["included_clauses"], 0)

    def test_quote_outside_sent_fragment_is_rejected(self) -> None:
        comparison = compare_documents(
            document("before"), document("after", ("1", "Я" * 1_600 + "Скрытая задача")),
        )
        response = AnalysisResponse(summary="", findings=[finding("Скрытая задача")])
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unit-test-placeholder"}), \
                patch.object(analyzer, "OpenAI") as client:
            client.return_value.responses.parse.return_value = SimpleNamespace(output_parsed=response)
            result = analyzer.analyze_with_metadata(comparison, "test-model")
        self.assertEqual(result.findings, [])
        self.assertEqual(result.rejected_findings, 1)

    def test_provider_error_does_not_echo_sensitive_error_body(self) -> None:
        comparison = compare_documents(document("before"), document("after", ("1", "Задача")))
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unit-test-placeholder"}), \
                patch.object(analyzer, "OpenAI") as client:
            client.return_value.responses.parse.side_effect = RuntimeError("sensitive-provider-body")
            with self.assertRaises(analyzer.AnalysisError) as error:
                analyzer.analyze_with_metadata(comparison, "test-model")
        self.assertNotIn("sensitive-provider-body", str(error.exception))


if __name__ == "__main__":
    unittest.main()
